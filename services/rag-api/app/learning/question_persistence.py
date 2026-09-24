"""Question Engine stage 7: atomically persist one scoped revision and its provenance.

The existing Assessment question/rubric/reference tables remain the only question pool.  This
module adds the missing provenance edge and promotes a revision to READY only when the candidate,
current evidence, blind solve and all applicable durable Jev receipts describe the same revision.
Jev remains a signal: READY is labelled ``AI_REVIEWED``, never deterministic or institutional.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from app.db import Database
from app.errors import ApiError
from app.jev.models import owner_scope_hash
from app.jev.service import SemanticDecisionService
from app.learning.blind_solve import BlindSolveReceipt, BlindSolveRequest
from app.learning.models import Contract
from app.learning.provider import structured_input_hash
from app.learning.question_author import AuthoredQuestionCandidate, QuestionAuthorOutput
from app.learning.question_blueprint import QuestionBlueprint, TeachingObjective, resolve_objective
from app.learning.question_evidence import (
    EvidencePackAccess,
    EvidencePackError,
    QuestionEvidencePack,
    build_evidence_pack,
)
from app.learning.question_validator import (
    QuestionSemanticSignals,
    QuestionValidationReport,
    question_semantic_input_fields,
    question_specialized_semantic_input_fields,
    required_specialized_semantic_dimension,
    validate_question_candidate,
)
from app.learning.workspaces import workspace_for


class QuestionPersistenceError(RuntimeError):
    """Stable Stage-7 refusal without private answers or provider bodies."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class QuestionPersistenceResult(Contract):
    question_revision_id: str
    status: Literal["READY", "NEEDS_REVIEW", "REJECTED"]
    readiness_reason: str
    verification_method: Literal["AI_REVIEWED", "MODEL_ONLY"]
    idempotent: bool


@dataclass(frozen=True)
class _Readiness:
    publication_status: Literal["READY", "NEEDS_REVIEW", "REJECTED"]
    validation_status: Literal["VALIDATED", "NEEDS_REVIEW", "REJECTED"]
    verification_method: Literal["AI_REVIEWED", "MODEL_ONLY"]
    reason: str


def _encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_encode(value).encode()).hexdigest()


def _current_evidence(
    database: Database,
    *,
    workspace: sqlite3.Row,
    blueprint: QuestionBlueprint,
    evidence: QuestionEvidencePack,
) -> QuestionEvidencePack:
    try:
        with database.connect() as connection:
            objective = resolve_objective(
                connection,
                node_id=blueprint.node_id,
                spec_version=blueprint.spec_version,
                item_id=blueprint.objective_id,
            )
        expected = TeachingObjective(
            node_id=blueprint.node_id,
            spec_version=blueprint.spec_version,
            spec_content_hash=blueprint.spec_content_hash,
            item_id=blueprint.objective_id,
            requirement=objective.requirement,
            objective=blueprint.objective_text,
            acceptance=evidence.acceptance,
            evidence_ids=tuple(evidence.evidence_ids),
        )
        if objective != expected:
            raise QuestionPersistenceError(
                "QUESTION_SOURCE_CHANGED",
                "The teaching objective changed before the question was persisted.",
            )
        rebuilt = build_evidence_pack(
            database,
            objective=objective,
            access=EvidencePackAccess(
                owner_user_id=str(workspace["owner_user_id"]),
                course_id=str(workspace["course_id"]),
                private_course_id=str(workspace["private_course_id"]),
            ),
        )
    except EvidencePackError as error:
        raise QuestionPersistenceError(
            "QUESTION_SOURCE_CHANGED",
            "The cited material is no longer available for this learner.",
        ) from error
    if rebuilt.identity() != evidence.identity():
        raise QuestionPersistenceError(
            "QUESTION_SOURCE_CHANGED",
            "The evidence snapshot changed before the question was persisted.",
        )
    return rebuilt


def _recomputed_report(
    *,
    blueprint: QuestionBlueprint,
    evidence: QuestionEvidencePack,
    candidate: AuthoredQuestionCandidate,
    blind_receipt: BlindSolveReceipt,
    supplied: QuestionValidationReport,
) -> QuestionValidationReport:
    signals = {signal.dimension: signal for signal in supplied.semantic_signals}
    expected_dimensions = {"AMBIGUITY", "AUTHOR_BLIND_AGREEMENT"}
    specialized_dimension = required_specialized_semantic_dimension(blueprint)
    if specialized_dimension is not None:
        expected_dimensions.add(specialized_dimension)
    if len(signals) != len(supplied.semantic_signals) or set(signals) != expected_dimensions:
        raise QuestionPersistenceError(
            "QUESTION_VALIDATION_MISMATCH",
            "The validation report does not contain the exact semantic dimensions.",
        )
    semantic = QuestionSemanticSignals(
        ambiguity=signals["AMBIGUITY"],
        answer_agreement=signals["AUTHOR_BLIND_AGREEMENT"],
        specialized_quality=(
            signals[specialized_dimension] if specialized_dimension is not None else None
        ),
    )
    recomputed = validate_question_candidate(
        candidate=candidate,
        blueprint=blueprint,
        evidence=evidence,
        blind_receipt=blind_receipt,
        semantic_signals=semantic,
    )
    if recomputed.model_dump(mode="json") != supplied.model_dump(mode="json"):
        raise QuestionPersistenceError(
            "QUESTION_VALIDATION_MISMATCH",
            "The supplied validation report does not match the exact candidate inputs.",
        )
    return recomputed


def _evidence_current_in_transaction(
    connection: sqlite3.Connection,
    *,
    workspace: sqlite3.Row,
    evidence: QuestionEvidencePack,
) -> bool:
    """Repeat the immutable binding checks under the same write lock as publication."""
    for fragment in evidence.fragments:
        row = connection.execute(
            "SELECT version.*,chunk.ordinal AS chunk_ordinal,chunk.content AS chunk_content,"
            "chunk.locator_type AS chunk_locator_type,"
            "chunk.locator_value AS chunk_locator_value,chunk.section AS chunk_section "
            "FROM chunks AS chunk JOIN chunk_source_versions AS source "
            "ON source.chunk_id=chunk.id JOIN document_versions AS version "
            "ON version.id=source.document_version_id WHERE chunk.id=?",
            (fragment.evidence_id,),
        ).fetchone()
        if row is None:
            return False
        course_scope = (
            str(row["course_id"]) == str(workspace["course_id"])
            and str(row["source_scope"]) in {"OFFICIAL", "OWNER_COURSE"}
        ) or (
            str(row["course_id"]) == str(workspace["private_course_id"])
            and str(row["source_scope"]) == "WORKSPACE_PRIVATE"
            and str(row["owner_user_id"]) == str(workspace["owner_user_id"])
        )
        content = str(row["chunk_content"])
        exact = (
            course_scope
            and str(row["id"]) == fragment.document_version_id
            and str(row["document_id"]) == fragment.document_id
            and int(row["version"]) == fragment.document_version
            and str(row["sha256"]) == fragment.document_sha256
            and str(row["filename"]) == fragment.filename
            and str(row["source_scope"]) == fragment.source_scope
            and int(row["chunk_ordinal"]) == fragment.ordinal
            and str(row["chunk_locator_type"]) == fragment.locator_type
            and str(row["chunk_locator_value"]) == fragment.locator_value
            and row["chunk_section"] == fragment.section
            and hashlib.sha256(content.encode()).hexdigest()
            == fragment.source_content_sha256
            and content[: len(fragment.content)] == fragment.content
            and hashlib.sha256(fragment.content.encode()).hexdigest()
            == fragment.excerpt_sha256
            and fragment.truncated == (len(fragment.content) < len(content))
        )
        if not exact:
            return False
        statuses = {
            str(status["status"])
            for status in connection.execute(
                "SELECT status FROM material_evidence WHERE node_id=? AND chunk_id=? "
                "AND document_version_id=?",
                (evidence.node_id, fragment.evidence_id, fragment.document_version_id),
            ).fetchall()
        }
        if "REVOKED" in statuses and "ACTIVE" not in statuses:
            return False
    return True


def _durable_jev_receipts(
    connection: sqlite3.Connection,
    *,
    owner_user_id: str,
    workspace_id: str,
    blueprint: QuestionBlueprint,
    candidate: AuthoredQuestionCandidate,
    report: QuestionValidationReport,
    expected_input_hashes: dict[str, str] | None,
) -> bool:
    definitions = {
        "AMBIGUITY": "question.ambiguity.v1",
        "AUTHOR_BLIND_AGREEMENT": "question.answer_agreement.v1",
        "MCQ_DISTRACTOR_QUALITY": "question.mcq_distractor_quality.v1",
        "RULE_VIOLATION_QUALITY": "question.rule_violation_quality.v1",
    }
    if expected_input_hashes is None:
        return False
    expected_scope = owner_scope_hash(owner_user_id, "question_validation")
    for signal in report.semantic_signals:
        if not signal.used_jev or signal.receipt_id is None:
            return False
        row = connection.execute(
            "SELECT * FROM jev_decision_receipts WHERE id=?",
            (signal.receipt_id,),
        ).fetchone()
        if row is None:
            return False
        try:
            output = json.loads(str(row["output_json"]))
        except (TypeError, ValueError):
            return False
        expected = (
            str(row["definition_key"]) == definitions[signal.dimension]
            and str(row["primitive"]) == "Choice"
            and str(row["mode"]) == "on"
            and str(row["caller_role"]) == "question_validator"
            and str(row["owner_scope_hash"]) == expected_scope
            and str(row["course_id"]) == blueprint.course_id
            and str(row["workspace_id"]) == workspace_id
            and str(row["node_id"]) == blueprint.node_id
            and str(row["spec_version"]) == str(blueprint.spec_version)
            and str(row["question_hash"]) == candidate.question_revision
            and str(row["input_hash"]) == expected_input_hashes[signal.dimension]
            and str(row["outcome"]) == "ok"
            and isinstance(output, dict)
            and output.get("choice") == signal.verdict
        )
        if not expected:
            return False
    return True


def _readiness(
    report: QuestionValidationReport,
    *,
    author_current: bool,
    blind_current: bool,
    receipts_current: bool,
) -> _Readiness:
    if report.status == "REJECTED":
        return _Readiness("REJECTED", "REJECTED", "MODEL_ONLY", "HARD_GATE_REJECTED")
    if report.status != "VALIDATED":
        return _Readiness(
            "NEEDS_REVIEW", "NEEDS_REVIEW", "MODEL_ONLY", "VALIDATION_NEEDS_REVIEW"
        )
    if not author_current:
        return _Readiness(
            "NEEDS_REVIEW",
            "NEEDS_REVIEW",
            "MODEL_ONLY",
            "AUTHOR_PROVENANCE_INCOMPLETE",
        )
    if not blind_current:
        return _Readiness(
            "NEEDS_REVIEW",
            "NEEDS_REVIEW",
            "MODEL_ONLY",
            "BLIND_PROVENANCE_INCOMPLETE",
        )
    if not receipts_current:
        return _Readiness(
            "NEEDS_REVIEW",
            "NEEDS_REVIEW",
            "MODEL_ONLY",
            "JEV_RECEIPT_NOT_DURABLE_OR_SCOPED",
        )
    return _Readiness(
        "READY", "VALIDATED", "AI_REVIEWED", "VALIDATION_COMPLETE_AI_REVIEWED"
    )


def _criterion_fractions(count: int) -> list[int]:
    if count < 1 or count > 20:
        raise QuestionPersistenceError(
            "QUESTION_RUBRIC_INVALID", "A question needs between one and twenty criteria."
        )
    base, remainder = divmod(100, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def _criterion_dimension(question_type: str) -> str:
    return {
        "MCQ_SINGLE": "CONCEPT",
        "NUMERIC": "CALCULATION",
        "SHORT_TEXT": "CONCEPT",
        "EXPLANATION": "METHOD_REASONING",
        "CODE": "CODE_APPLICATION",
    }[question_type]


def _blind_json(receipt: BlindSolveReceipt) -> tuple[str, bool]:
    try:
        payload = json.loads(receipt.output)
    except (TypeError, ValueError):
        return _encode(receipt.output), False
    return _encode(payload), isinstance(payload, dict) and payload.get("schema_version") == (
        "blind-solve-output.v1"
    )


def _existing_result(
    connection: sqlite3.Connection,
    *,
    question_revision_hash: str,
    workspace_id: str,
    blueprint_hash: str,
    evidence_pack_hash: str,
) -> QuestionPersistenceResult | None:
    row = connection.execute(
        "SELECT provenance.*,question.verification_method "
        "FROM question_engine_provenance AS provenance "
        "JOIN assessment_question_revisions AS question "
        "ON question.id=provenance.question_revision_id "
        "WHERE provenance.workspace_id=? AND provenance.question_revision_hash=?",
        (workspace_id, question_revision_hash),
    ).fetchone()
    if row is None:
        return None
    if (
        str(row["blueprint_hash"]) != blueprint_hash
        or str(row["evidence_pack_hash"]) != evidence_pack_hash
    ):
        raise QuestionPersistenceError(
            "QUESTION_IDEMPOTENCY_CONFLICT",
            "The question revision hash is already bound to different inputs.",
        )
    return QuestionPersistenceResult(
        question_revision_id=str(row["question_revision_id"]),
        status=str(row["publication_status"]),
        readiness_reason=str(row["readiness_reason"]),
        verification_method=str(row["verification_method"]),
        idempotent=True,
    )


def persist_question_candidate(
    *,
    database: Database,
    owner_user_id: str,
    workspace_id: str,
    blueprint: QuestionBlueprint,
    evidence: QuestionEvidencePack,
    candidate: AuthoredQuestionCandidate,
    blind_receipt: BlindSolveReceipt,
    validation_report: QuestionValidationReport,
    semantic_decisions: SemanticDecisionService,
) -> QuestionPersistenceResult:
    """Persist one immutable revision; READY is owner-scoped and never exposes the answer."""
    try:
        computed_revision = candidate.revision_identity()
    except ValueError as error:
        raise QuestionPersistenceError(
            "QUESTION_REVISION_MISMATCH",
            "The public and private candidate fields do not form one revision.",
        ) from error
    if computed_revision != candidate.question_revision:
        raise QuestionPersistenceError(
            "QUESTION_REVISION_MISMATCH",
            "The candidate content no longer matches its immutable revision hash.",
        )
    try:
        workspace = workspace_for(database, workspace_id, owner_user_id)
    except ApiError as error:
        raise QuestionPersistenceError(
            "QUESTION_WORKSPACE_NOT_FOUND", "The learning workspace was not found."
        ) from error
    fresh_evidence = _current_evidence(
        database,
        workspace=workspace,
        blueprint=blueprint,
        evidence=evidence,
    )
    report = _recomputed_report(
        blueprint=blueprint,
        evidence=fresh_evidence,
        candidate=candidate,
        blind_receipt=blind_receipt,
        supplied=validation_report,
    )
    ambiguity_fields, agreement_fields = question_semantic_input_fields(
        candidate=candidate,
        blueprint=blueprint,
        evidence=fresh_evidence,
        blind_receipt=blind_receipt,
    )
    ambiguity_hash = semantic_decisions.bounded_choice_input_hash(
        "question.ambiguity.v1",
        fields=ambiguity_fields,
        candidate_ids=(
            "CLEAR",
            "AMBIGUOUS",
            "UNDER_SPECIFIED",
            "CONTRADICTORY",
            "UNCERTAIN",
        ),
    )
    agreement_hash = semantic_decisions.bounded_choice_input_hash(
        "question.answer_agreement.v1",
        fields=agreement_fields,
        candidate_ids=("AGREE", "DISAGREE", "AMBIGUOUS", "UNCERTAIN"),
    )
    input_hashes = {
        "AMBIGUITY": ambiguity_hash,
        "AUTHOR_BLIND_AGREEMENT": agreement_hash,
    }
    specialized_fields = question_specialized_semantic_input_fields(
        candidate=candidate,
        blueprint=blueprint,
        evidence=fresh_evidence,
    )
    if specialized_fields is not None:
        dimension, definition_key, fields, candidates = specialized_fields
        input_hashes[dimension] = semantic_decisions.bounded_choice_input_hash(
            definition_key,
            fields=fields,
            candidate_ids=candidates,
        )
    expected_input_hashes = (
        {dimension: value for dimension, value in input_hashes.items() if value is not None}
        if all(value is not None for value in input_hashes.values())
        else None
    )
    author_current = candidate.provider_run.input_hash == structured_input_hash(
        QuestionAuthorOutput,
        context={
            "blueprint": blueprint.model_dump(mode="json"),
            "evidence_pack": fresh_evidence.model_dump(mode="json"),
        },
    )
    request = BlindSolveRequest(
        question_text=candidate.public_question.question_text,
        options=tuple(candidate.public_question.options),
        allowed_rules=tuple(fragment.content for fragment in fresh_evidence.fragments),
    )
    blind_output_json, structured_blind_output = _blind_json(blind_receipt)
    blind_current = (
        blind_receipt.provider_run is not None
        and structured_blind_output
        and blind_receipt.is_current_for(candidate.question_revision, request.input_hash())
    )
    blueprint_hash = blueprint.identity()
    evidence_hash = fresh_evidence.identity()
    if any(len(criterion) > 2000 for criterion in blueprint.scoring_criteria):
        raise QuestionPersistenceError(
            "QUESTION_RUBRIC_INVALID", "A rubric criterion exceeds the persistence limit."
        )
    fractions = _criterion_fractions(len(blueprint.scoring_criteria))

    try:
        with database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = _existing_result(
                connection,
                question_revision_hash=candidate.question_revision,
                workspace_id=workspace_id,
                blueprint_hash=blueprint_hash,
                evidence_pack_hash=evidence_hash,
            )
            if existing is not None:
                return existing

            current_workspace = connection.execute(
                "SELECT * FROM learning_workspaces WHERE id=? AND owner_user_id=?",
                (workspace_id, owner_user_id),
            ).fetchone()
            item = connection.execute(
                "SELECT 1 FROM teaching_items WHERE node_id=? AND spec_version=? AND item_id=?",
                (blueprint.node_id, blueprint.spec_version, blueprint.objective_id),
            ).fetchone()
            if (
                current_workspace is None
                or str(current_workspace["course_id"]) != blueprint.course_id
                or item is None
            ):
                raise QuestionPersistenceError(
                    "QUESTION_INPUT_MISMATCH",
                    "The blueprint no longer matches the scoped workspace objective.",
                )
            if not _evidence_current_in_transaction(
                connection,
                workspace=current_workspace,
                evidence=fresh_evidence,
            ):
                raise QuestionPersistenceError(
                    "QUESTION_SOURCE_CHANGED",
                    "The evidence binding changed before the revision could commit.",
                )

            receipts_current = _durable_jev_receipts(
                connection,
                owner_user_id=owner_user_id,
                workspace_id=workspace_id,
                blueprint=blueprint,
                candidate=candidate,
                report=report,
                expected_input_hashes=expected_input_hashes,
            )
            ready = _readiness(
                report,
                author_current=author_current,
                blind_current=blind_current,
                receipts_current=receipts_current,
            )
            question_id = f"qe_{uuid4().hex}"
            revision = int(
                connection.execute(
                    "SELECT COALESCE(MAX(revision),0)+1 FROM assessment_question_revisions "
                    "WHERE course_id=? AND owner_user_id=? AND family_id=?",
                    (blueprint.course_id, owner_user_id, blueprint.question_family_id),
                ).fetchone()[0]
            )
            private_solution = candidate.private_solution.model_dump(mode="json")
            answer = {
                "reference_answer": candidate.private_solution.candidate_answer,
                "model_candidate_correct_option_index": (
                    candidate.private_solution.correct_option_index
                ),
                "distractor_rationales": private_solution["distractor_rationales"],
                "rule_violation_analysis": private_solution["rule_violation_analysis"],
                "solution_steps": private_solution["solution_steps"],
                "source_refs": private_solution["source_refs"],
                "verification_notice": "AI_REVIEWED_NOT_DETERMINISTIC_PROOF",
            }
            content = {
                "prompt": candidate.public_question.question_text,
                "options": candidate.public_question.options,
                "answer": answer,
                "blueprint_hash": blueprint_hash,
                "evidence_pack_hash": evidence_hash,
                "question_revision": candidate.question_revision,
            }
            connection.execute(
                "INSERT INTO assessment_question_revisions("
                "id,course_id,owner_user_id,family_id,revision,source_kind,question_type,"
                "difficulty,prompt_text,options_json,answer_json,validation_status,"
                "verification_method,content_hash,created_by_user_id) "
                "VALUES(?,?,?,?,?,'MODEL_GENERATED',?,?,?,?,?,?,?,?,?)",
                (
                    question_id,
                    blueprint.course_id,
                    owner_user_id,
                    blueprint.question_family_id,
                    revision,
                    blueprint.question_type,
                    blueprint.target_difficulty,
                    candidate.public_question.question_text,
                    _encode(candidate.public_question.options),
                    _encode(answer),
                    ready.validation_status,
                    ready.verification_method,
                    _digest(content),
                    owner_user_id,
                ),
            )
            dimension = _criterion_dimension(blueprint.question_type)
            for index, (description, fraction) in enumerate(
                zip(blueprint.scoring_criteria, fractions, strict=True), start=1
            ):
                connection.execute(
                    "INSERT INTO assessment_rubric_criteria("
                    "question_revision_id,criterion_id,node_id,spec_version,item_id,"
                    "dimension,max_fraction,description,deterministic_rule_json) "
                    "VALUES(?,?,?,?,?,?,?,?, '{}')",
                    (
                        question_id,
                        f"criterion_{index}",
                        blueprint.node_id,
                        blueprint.spec_version,
                        blueprint.objective_id,
                        dimension,
                        fraction,
                        description,
                    ),
                )
            steps = [
                {
                    "step_id": f"step_{step.ordinal}",
                    **step.model_dump(mode="json"),
                }
                for step in candidate.private_solution.solution_steps
            ]
            source_refs = sorted(
                {
                    ref
                    for step in candidate.private_solution.solution_steps
                    for ref in step.source_refs
                }
            )
            solution = {
                "answer": candidate.private_solution.candidate_answer,
                "steps": steps,
                "source_refs": source_refs,
            }
            connection.execute(
                "INSERT INTO assessment_reference_solutions("
                "id,question_revision_id,blueprint_item_id,solution_revision,steps_json,"
                "answer_json,source_refs_json,prompt_version,content_hash) "
                "VALUES(?,?,NULL,1,?,?,?,?,?)",
                (
                    f"qes_{uuid4().hex}",
                    question_id,
                    _encode(steps),
                    _encode(candidate.private_solution.candidate_answer),
                    _encode(source_refs),
                    candidate.provider_run.template_version,
                    _digest(solution),
                ),
            )
            connection.execute(
                "INSERT INTO question_engine_provenance("
                "question_revision_id,workspace_id,blueprint_id,blueprint_hash,"
                "evidence_pack_hash,question_revision_hash,node_id,spec_version,objective_id,"
                "blueprint_json,evidence_ids_json,author_run_json,blind_input_hash,"
                "blind_output_json,blind_run_json,validation_report_json,publication_status,"
                "readiness_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    question_id,
                    workspace_id,
                    blueprint.blueprint_id,
                    blueprint_hash,
                    evidence_hash,
                    candidate.question_revision,
                    blueprint.node_id,
                    blueprint.spec_version,
                    blueprint.objective_id,
                    _encode(blueprint.model_dump(mode="json")),
                    _encode(fresh_evidence.evidence_ids),
                    _encode(candidate.provider_run.model_dump(mode="json")),
                    blind_receipt.input_hash,
                    blind_output_json,
                    _encode(
                        blind_receipt.provider_run.model_dump(mode="json")
                        if blind_receipt.provider_run is not None
                        else None
                    ),
                    _encode(report.model_dump(mode="json")),
                    ready.publication_status,
                    ready.reason,
                ),
            )
            return QuestionPersistenceResult(
                question_revision_id=question_id,
                status=ready.publication_status,
                readiness_reason=ready.reason,
                verification_method=ready.verification_method,
                idempotent=False,
            )
    except sqlite3.IntegrityError as error:
        raise QuestionPersistenceError(
            "QUESTION_PERSISTENCE_CONFLICT",
            "The immutable question revision could not be stored atomically.",
        ) from error
