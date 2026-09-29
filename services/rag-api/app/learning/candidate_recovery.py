"""Review an already-authored candidate without re-authoring it.

The brief is explicit: when a candidate's author, blind-solve and deterministic
results are already complete and only the semantic review is missing, add the
review and do not call the author again.  The nine `NEEDS_REVIEW` revisions left
by the previous round are exactly that case, and this module rebuilds them from
their stored provenance so the hybrid chain can review them.

Nothing here invents content.  Every field is read back from what the pipeline
already persisted, and the rebuild is *verified* rather than assumed:

* the blueprint comes from `question_engine_provenance.blueprint_json` and is
  re-hashed to its recorded `blueprint_hash`;
* the evidence pack is rebuilt from the objective and must reproduce the
  recorded `evidence_pack_hash`;
* the candidate's revision hash is recomputed from the split public/private
  fields and must equal the recorded `question_revision_hash`;
* the blind receipt's input hash is recomputed from the recorded question,
  options and rules and must equal the recorded `blind_input_hash`.

A mismatch is a refusal, not a repair: a rebuilt candidate that does not hash to
what was stored is a different candidate, and reviewing it would produce a
receipt for an item nobody authored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.db import Database
from app.learning.blind_solve import BlindSolveReceipt, BlindSolveRequest
from app.learning.question_author import (
    AuthoredQuestionCandidate,
    AuthorProviderRun,
    PrivateCandidateSolution,
    PublicAuthoredQuestion,
)
from app.learning.question_blueprint import (
    QuestionBlueprint,
    blueprint_identity_match,
    resolve_objective,
)

# Re-exported for callers that already import the rendering from here; the
# implementation lives beside QuestionBlueprint.identity() so the recovery stage
# and the deterministic validator cannot accept different renderings.
from app.learning.question_blueprint import (
    render_integral_floats_as_ints as _integral_floats_as_ints,  # noqa: F401
)
from app.learning.question_evidence import EvidencePackAccess, build_evidence_pack
from app.learning.workspaces import workspace_for


class CandidateRecoveryError(RuntimeError):
    """A stored candidate could not be rebuilt exactly as it was authored."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RecoveredCandidate:
    """One stored revision, rebuilt and verified against its own hashes."""

    question_revision_id: str
    workspace_id: str
    owner_user_id: str
    course_id: str
    node_id: str
    spec_version: int
    publication_status: str
    readiness_reason: str
    blueprint: QuestionBlueprint
    evidence: Any
    candidate: AuthoredQuestionCandidate
    blind_receipt: BlindSolveReceipt
    validation_report: dict[str, Any]
    # "CANONICAL" means the rebuild is byte-identical to what was stored;
    # "INTEGRAL_FLOAT_AS_INT" means it is numerically identical under the
    # historical rendering.  A reader can tell the two apart.
    identity_rendering: str = "CANONICAL"

    @property
    def question_revision(self) -> str:
        return self.candidate.question_revision


def _loads(value: Any, *, field: str) -> Any:
    if value is None:
        raise CandidateRecoveryError("CANDIDATE_FIELD_MISSING", f"{field} is absent")
    try:
        return json.loads(str(value))
    except (TypeError, ValueError) as error:
        raise CandidateRecoveryError(
            "CANDIDATE_FIELD_INVALID", f"{field} is not valid JSON"
        ) from error


# The identity rendering used to live here.  It now lives beside
# QuestionBlueprint.identity() so the recovery stage and the deterministic
# validator cannot drift apart on which renderings they accept -- that drift is
# exactly what made one stored candidate pass recovery and fail INPUT_IDENTITY.


def list_recoverable(
    database: Database, *, limit: int = 50
) -> list[dict[str, Any]]:
    """The stored revisions whose author/blind results are complete."""
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT provenance.question_revision_id, provenance.workspace_id, "
            "provenance.node_id, provenance.publication_status, "
            "provenance.readiness_reason, provenance.created_at, "
            "question.question_type, workspace.course_id, workspace.owner_user_id "
            "FROM question_engine_provenance AS provenance "
            "JOIN assessment_question_revisions AS question "
            "ON question.id = provenance.question_revision_id "
            "JOIN learning_workspaces AS workspace "
            "ON workspace.id = provenance.workspace_id "
            "WHERE provenance.publication_status <> 'READY' "
            "AND provenance.author_run_json IS NOT NULL "
            "AND provenance.blind_output_json IS NOT NULL "
            "AND provenance.blind_run_json IS NOT NULL "
            "ORDER BY provenance.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def recover_candidate(
    database: Database, *, question_revision_id: str
) -> RecoveredCandidate:
    """Rebuild one stored candidate, verifying every hash on the way."""
    with database.connect() as connection:
        row = connection.execute(
            "SELECT provenance.*, question.prompt_text, question.options_json, "
            "question.answer_json, question.question_type, question.verification_method, "
            "workspace.owner_user_id, workspace.course_id, workspace.private_course_id "
            "FROM question_engine_provenance AS provenance "
            "JOIN assessment_question_revisions AS question "
            "ON question.id = provenance.question_revision_id "
            "JOIN learning_workspaces AS workspace "
            "ON workspace.id = provenance.workspace_id "
            "WHERE provenance.question_revision_id = ?",
            (question_revision_id,),
        ).fetchone()
    if row is None:
        raise CandidateRecoveryError("CANDIDATE_NOT_FOUND", "No such stored revision.")

    workspace_id = str(row["workspace_id"])
    owner_user_id = str(row["owner_user_id"])
    course_id = str(row["course_id"])
    private_course_id = str(row["private_course_id"])
    node_id = str(row["node_id"])
    spec_version = int(row["spec_version"])

    # The workspace helper authorises the read; a workspace the owner can no
    # longer reach is a refusal rather than a review.
    try:
        workspace_for(database, workspace_id, owner_user_id)
    except Exception as error:  # noqa: BLE001 - surfaced as a typed refusal
        raise CandidateRecoveryError(
            "CANDIDATE_WORKSPACE_UNAVAILABLE", "The stored workspace is not available."
        ) from error

    blueprint_payload = _loads(row["blueprint_json"], field="blueprint_json")
    blueprint = QuestionBlueprint.model_validate(blueprint_payload)
    identity_matches, identity_rendering = blueprint_identity_match(
        blueprint, str(row["blueprint_hash"])
    )
    if not identity_matches:
        raise CandidateRecoveryError(
            "CANDIDATE_HASH_MISMATCH", "The stored blueprint does not match its hash."
        )

    with database.connect() as connection:
        objective = resolve_objective(connection, node_id=node_id)
    evidence = build_evidence_pack(
        database,
        objective=objective,
        access=EvidencePackAccess(
            owner_user_id=owner_user_id,
            course_id=course_id,
            private_course_id=private_course_id,
        ),
    )
    if evidence.identity() != str(row["evidence_pack_hash"]):
        raise CandidateRecoveryError(
            "CANDIDATE_EVIDENCE_CHANGED",
            "The cited evidence no longer reproduces the stored pack.",
        )

    answer = _loads(row["answer_json"], field="answer_json")
    if not isinstance(answer, dict):
        raise CandidateRecoveryError("CANDIDATE_FIELD_INVALID", "answer_json is not an object.")
    solution = PrivateCandidateSolution.model_validate(
        {
            "candidate_answer": answer.get("reference_answer"),
            "correct_option_index": answer.get("model_candidate_correct_option_index"),
            "distractor_rationales": answer.get("distractor_rationales") or [],
            "rule_violation_analysis": answer.get("rule_violation_analysis"),
            "solution_steps": answer.get("solution_steps") or [],
            "source_refs": answer.get("source_refs") or [],
        }
    )
    public = PublicAuthoredQuestion.model_validate(
        {
            "question_text": str(row["prompt_text"]),
            "options": _loads(row["options_json"], field="options_json"),
            "source_refs": solution.source_refs,
            "answer_policy": blueprint.answer_policy,
        }
    )
    author_run = AuthorProviderRun.model_validate(
        _loads(row["author_run_json"], field="author_run_json")
    )
    candidate = AuthoredQuestionCandidate(
        blueprint_id=blueprint.blueprint_id,
        # The *stored* hash, not a recomputed one.  The revision identity was
        # computed against this exact value when the candidate was authored, and
        # for a row written under the historical integral-float rendering the
        # recomputed identity differs from it while the values are identical.
        blueprint_hash=str(row["blueprint_hash"]),
        evidence_pack_hash=evidence.identity(),
        question_revision=str(row["question_revision_hash"]),
        course_id=course_id,
        node_id=node_id,
        objective_id=blueprint.objective_id,
        question_type=blueprint.question_type,
        marks=blueprint.marks,
        public_question=public,
        private_solution=solution,
        provider_run=author_run,
    )
    if candidate.revision_identity() != candidate.question_revision:
        raise CandidateRecoveryError(
            "CANDIDATE_REVISION_MISMATCH",
            "The rebuilt candidate does not reproduce its stored revision hash.",
        )

    blind_run_payload = _loads(row["blind_run_json"], field="blind_run_json")
    blind_request = BlindSolveRequest(
        question_text=public.question_text,
        options=tuple(public.options),
        allowed_rules=tuple(fragment.content for fragment in evidence.fragments),
    )
    blind_receipt = BlindSolveReceipt(
        input_hash=str(row["blind_input_hash"]),
        question_revision=candidate.question_revision,
        model_version=str(blind_run_payload.get("model") or "UNKNOWN"),
        output=str(row["blind_output_json"]),
        # The receipt's own terminal is the lowercase form the solver writes;
        # `COMPLETED` appears only inside the provider run payload.
        status="completed",
        provider_run=None,
    )
    if not blind_receipt.is_current_for(
        candidate.question_revision, blind_request.input_hash()
    ):
        raise CandidateRecoveryError(
            "CANDIDATE_BLIND_MISMATCH",
            "The stored blind solve does not match this exact question revision.",
        )

    return RecoveredCandidate(
        question_revision_id=question_revision_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        course_id=course_id,
        node_id=node_id,
        spec_version=spec_version,
        publication_status=str(row["publication_status"]),
        readiness_reason=str(row["readiness_reason"]),
        blueprint=blueprint,
        evidence=evidence,
        candidate=candidate,
        blind_receipt=blind_receipt,
        validation_report=_loads(row["validation_report_json"], field="validation_report_json"),
        identity_rendering=identity_rendering,
    )


def deterministic_report_for(record: RecoveredCandidate):
    """Rebuild the six hard gates for a recovered candidate.

    Only the gates are recomputed here; the semantic signals are deliberately
    *not* reused from the stored report, because the whole point of this path is
    to replace an unqualified semantic decision with a reviewed one.  The
    recovered candidate is passed as a fallback-only report so the real hybrid
    review decides the semantic cases from scratch.
    """
    from app.learning.question_validator import QuestionSemanticSignals, validate_question_candidate

    fallback = QuestionSemanticSignals(
        ambiguity=_uncertain("AMBIGUITY"),
        answer_agreement=_uncertain("AUTHOR_BLIND_AGREEMENT"),
        specialized_quality=None,
    )
    return validate_question_candidate(
        candidate=record.candidate,
        blueprint=record.blueprint,
        evidence=record.evidence,
        blind_receipt=record.blind_receipt,
        semantic_signals=fallback,
    )


def _uncertain(dimension: str):
    from app.learning.question_validator import SemanticSignal

    return SemanticSignal(
        dimension=dimension,
        verdict="UNCERTAIN",
        used_jev=False,
        receipt_id=None,
        path="fallback:review_only_recovery",
    )
