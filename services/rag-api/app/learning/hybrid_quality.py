"""The hybrid strict quality service: orchestration, receipts and qualification.

This is the single place that turns

    deterministic report + advisory local observation + two strong reviews +
    a scoped qualification

into a durable :class:`HybridReviewResult` the Question Engine can act on.

Design rules enforced here, not by convention:

* the deterministic hard gates are inputs, never outputs -- this service cannot
  turn a deterministic ``FAIL`` into acceptance, and the final validator
  re-checks them anyway;
* the local (OpenJev) observation is advisory: a missing, unavailable, skipped
  or disagreeing local observation never blocks a complete, qualified strong
  review and never deletes evidence;
* an unqualified or out-of-scope reviewer may not publish.  A qualification row
  is re-checked for method identity, policy revision, language, domain, case set,
  role set, expiry and ``active`` at publication time;
* every reviewer call and its full response are persisted before the content is
  used, so a paid call is never silently retried.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Final
from uuid import uuid4

from pydantic import Field, StringConstraints, model_validator

from app.db import Database
from app.learning.blind_solve import BlindSolveReceipt
from app.learning.deepseek_reviewer import (
    DeepSeekStrongReviewer,
    LocalObservation,
    ReviewerInputs,
    StrongReviewError,
    StrongReviewOutcome,
)
from app.learning.human_review_card import HumanReviewStore
from app.learning.hybrid_review import (
    CASE_ACCEPT_LABEL,
    CASE_AMBIGUITY,
    CASE_DIMENSION,
    POLICY_REVISION,
    SPECIFICATION_AUDIT_ROLE,
    STRONG_REVIEW_ROLES,
    combine_case_verdicts,
    project_case_verdicts,
)
from app.learning.models import Contract, Identifier
from app.learning.question_author import AuthoredQuestionCandidate
from app.learning.question_blueprint import QuestionBlueprint
from app.learning.question_evidence import QuestionEvidencePack
from app.learning.question_validator import (
    QuestionSemanticSignals,
    QuestionValidationReport,
    SemanticSignal,
    required_specialized_semantic_dimension,
)

Hex64 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

# How long a qualification stays valid before it must be re-derived from a
# fresh held-out evaluation.  An expired qualification blocks publication and
# produces an explicit reason rather than silently passing.
QUALIFICATION_TTL_DAYS: Final = 45


class HybridReviewUnavailable(RuntimeError):
    """The hybrid gate could not produce a qualified receipt for this revision."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class HybridQualification(Contract):
    """A versioned, scoped quality qualification for one reviewed method."""

    id: Identifier
    policy_revision: str
    method_identity: Hex64
    status: str
    reviewer_label: str
    languages: list[str]
    domains: list[str]
    cases: list[str]
    roles: list[str]
    sample_counts: dict[str, int]
    metrics: dict[str, Any]
    evidence_manifest_digest: Hex64
    observed_model_facts: dict[str, Any] = Field(default_factory=dict)
    expires_at: str
    active: bool = True
    created_at: str | None = None

    @model_validator(mode="after")
    def label_matches_status(self) -> HybridQualification:
        if self.status == "SCOPED_QUALITY_ACCEPTED" and self.reviewer_label != (
            "SCOPED_QUALITY_ACCEPTED"
        ):
            raise ValueError("an accepted qualification must carry the scoped label")
        return self

    def covers(
        self,
        *,
        policy_revision: str,
        method_identity: str,
        language: str,
        domain: str,
        cases: tuple[str, ...],
        now: datetime,
    ) -> tuple[bool, str]:
        """Full scope and freshness re-check.  Returns ``(ok, reason)``."""
        if not self.active:
            return False, "QUALIFICATION_INACTIVE"
        if self.status != "SCOPED_QUALITY_ACCEPTED":
            return False, "QUALIFICATION_NOT_ACCEPTED"
        if self.policy_revision != policy_revision:
            return False, "QUALIFICATION_POLICY_MISMATCH"
        if self.method_identity != method_identity:
            return False, "QUALIFICATION_METHOD_MISMATCH"
        try:
            expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False, "QUALIFICATION_EXPIRY_INVALID"
        if expires.tzinfo is None:
            return False, "QUALIFICATION_EXPIRY_INVALID"
        if expires <= now:
            return False, "QUALIFICATION_EXPIRED"
        if language not in self.languages:
            return False, "QUALIFICATION_LANGUAGE_OUT_OF_SCOPE"
        if domain not in self.domains:
            return False, "QUALIFICATION_DOMAIN_OUT_OF_SCOPE"
        if not set(cases).issubset(set(self.cases)):
            return False, "QUALIFICATION_CASE_OUT_OF_SCOPE"
        if not set(STRONG_REVIEW_ROLES).issubset(set(self.roles)):
            return False, "QUALIFICATION_ROLE_OUT_OF_SCOPE"
        return True, ""


@dataclass(frozen=True)
class HybridReviewResult:
    """A qualified hybrid outcome for one question revision."""

    receipt_id: str
    signals: QuestionSemanticSignals
    case_outcomes: dict[str, str]
    projected: dict[str, str]
    qualification_id: str
    method_identity: str
    review_call_ids: tuple[str, ...]
    local_observation_ids: tuple[str, ...]
    local_status: str
    reasons: tuple[str, ...]
    human_card_id: str | None = None

    @property
    def accepted(self) -> bool:
        return not self.reasons and all(
            verdict == "PASS" for verdict in self.case_outcomes.values()
        )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _domain_of(evidence: QuestionEvidencePack) -> str:
    """The reviewed domain scope: the exact source kinds the item is built from."""
    kinds = sorted({fragment.source_scope for fragment in evidence.fragments})
    return "+".join(kinds) if kinds else "UNKNOWN"


def review_domain(evidence: QuestionEvidencePack) -> str:
    """Public alias used by the qualification harness and its tests."""
    return _domain_of(evidence)


def _language_of(blueprint: QuestionBlueprint, evidence: QuestionEvidencePack) -> str:
    from app.learning.deepseek_reviewer import detector_language

    text = " ".join(
        [
            evidence.objective_text,
            evidence.acceptance,
            *[fragment.content for fragment in evidence.fragments],
        ]
    )
    return detector_language(text)


def review_language(
    blueprint: QuestionBlueprint, evidence: QuestionEvidencePack
) -> str:
    """Public alias used by the qualification harness and its tests."""
    return _language_of(blueprint, evidence)


class HybridQualificationStore:
    """Read/write access to the ``hybrid_qualifications`` registry."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def active_for(
        self, *, policy_revision: str, method_identity: str
    ) -> list[HybridQualification]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM hybrid_qualifications "
                "WHERE policy_revision=? AND method_identity=? AND active=1 "
                "ORDER BY created_at DESC",
                (policy_revision, method_identity),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def get(self, qualification_id: str) -> HybridQualification | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM hybrid_qualifications WHERE id=?", (qualification_id,)
            ).fetchone()
        return self._decode(row) if row is not None else None

    @staticmethod
    def _decode(row: sqlite3.Row) -> HybridQualification:
        return HybridQualification(
            id=str(row["id"]),
            policy_revision=str(row["policy_revision"]),
            method_identity=str(row["method_identity"]),
            status=str(row["status"]),
            reviewer_label=str(row["reviewer_label"]),
            languages=json.loads(str(row["languages_json"])),
            domains=json.loads(str(row["domains_json"])),
            cases=json.loads(str(row["cases_json"])),
            roles=json.loads(str(row["roles_json"])),
            sample_counts=json.loads(str(row["sample_counts_json"])),
            metrics=json.loads(str(row["metrics_json"])),
            evidence_manifest_digest=str(row["evidence_manifest_digest"]),
            observed_model_facts=json.loads(str(row["observed_model_facts_json"] or "{}")),
            expires_at=str(row["expires_at"]),
            active=bool(row["active"]),
            created_at=str(row["created_at"]),
        )

    def record(
        self,
        *,
        qualification_id: str,
        policy_revision: str,
        method_identity: str,
        status: str,
        reviewer_label: str,
        languages: list[str],
        domains: list[str],
        cases: list[str],
        roles: list[str],
        sample_counts: dict[str, int],
        metrics: dict[str, Any],
        evidence_manifest_digest: str,
        observed_model_facts: dict[str, Any],
        expires_at: str,
    ) -> HybridQualification:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR REPLACE INTO hybrid_qualifications("
                "id,policy_revision,method_identity,status,reviewer_label,languages_json,"
                "domains_json,cases_json,roles_json,sample_counts_json,metrics_json,"
                "evidence_manifest_digest,observed_model_facts_json,expires_at,active) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                (
                    qualification_id,
                    policy_revision,
                    method_identity,
                    status,
                    reviewer_label,
                    _canonical(languages),
                    _canonical(domains),
                    _canonical(cases),
                    _canonical(roles),
                    _canonical(sample_counts),
                    _canonical(metrics),
                    evidence_manifest_digest,
                    _canonical(observed_model_facts),
                    expires_at,
                ),
            )
        recorded = self.get(qualification_id)
        assert recorded is not None  # written inside this call
        return recorded


class HybridQualityService:
    """Runs the strong reviews, records every call, and applies the policy."""

    def __init__(
        self,
        database: Database,
        reviewer: DeepSeekStrongReviewer,
        *,
        qualifications: HybridQualificationStore | None = None,
        local_observer: Any | None = None,
    ) -> None:
        self.database = database
        self.reviewer = reviewer
        self.qualifications = qualifications or HybridQualificationStore(database)
        self.local_observer = local_observer
        self.human_reviews = HumanReviewStore(database)

    @property
    def method_identity(self) -> str:
        return self.reviewer.method_identity

    def review(
        self,
        *,
        candidate: AuthoredQuestionCandidate,
        blueprint: QuestionBlueprint,
        evidence: QuestionEvidencePack,
        blind_receipt: BlindSolveReceipt,
        deterministic_report: QuestionValidationReport,
        owner_user_id: str,
        workspace_id: str,
        course_id: str,
        node_id: str,
        spec_version: int,
    ) -> HybridReviewResult | None:
        """Produce a durable hybrid receipt, or ``None`` when the item is not eligible."""
        if deterministic_report.status == "REJECTED":
            # A deterministic hard-gate failure can never be voted back to READY.
            return None
        from app.learning.hybrid_review import case_set_for_blueprint
        from app.learning.question_author import RULE_VIOLATION_POLICY_VERSION

        required_cases = case_set_for_blueprint(
            question_type=blueprint.question_type,
            rule_policy=(
                blueprint.generation_policy_version == RULE_VIOLATION_POLICY_VERSION
            ),
        )
        inputs = self._inputs(
            candidate=candidate,
            blueprint=blueprint,
            evidence=evidence,
            blind_receipt=blind_receipt,
            deterministic_report=deterministic_report,
            course_id=course_id,
            node_id=node_id,
            spec_version=spec_version,
            required_cases=required_cases,
        )
        # Advisory local observation first: it may point at something worth
        # checking, and it must never be able to block the strong path.
        observations = self._observe(inputs)
        try:
            first, second = self.reviewer.review(inputs)
        except StrongReviewError as failure:
            # Record the failure's own facts -- layer, error class, terminal
            # status, HTTP status, whether a response arrived, latency and usage
            # -- before re-raising.  Without this the only surviving trace is a
            # code string, and no later run can say where the call failed.
            self._record_provider_failure(
                candidate=candidate,
                blueprint=blueprint,
                evidence=evidence,
                failure=failure,
            )
            raise
        specification = getattr(self.reviewer, "last_specification", None)
        review_call_ids = self._record_calls(
            candidate=candidate,
            blueprint=blueprint,
            evidence=evidence,
            outcomes=(first, second),
            specification=specification,
        )
        observation_ids = self._record_observations(
            question_revision=candidate.question_revision, observations=observations
        )
        by_role = {
            first.role: first.case_verdicts(),
            second.role: second.case_verdicts(),
        }
        # A person may decide the one case the reviewers cannot: the card is
        # looked up by the exact question revision, re-validated on read, and
        # merged after the two-role rule so it can only move the case towards
        # refusal.  It can never touch the other three cases.
        card_id: str | None = None
        card: Any | None = None
        if CASE_AMBIGUITY in required_cases:
            found = self.human_reviews.current_for(
                question_revision_hash=candidate.question_revision
            )
            if found is not None:
                card_id, card = found
        # The qualification state is resolved before the cases are combined: the
        # ambiguity case now needs it as positive evidence, so it cannot be looked
        # up afterwards.
        language = inputs.language
        domain = inputs.domain
        qualification_id, qualification_reason = self._resolve_qualification(
            language=language, domain=domain, cases=required_cases
        )
        witness_verdicts = self._verify_witnesses(
            outcomes=(first, second),
            candidate=candidate,
            blueprint=blueprint,
            evidence=evidence,
        )
        completeness = self._completeness_certificate(
            candidate=candidate, blueprint=blueprint, evidence=evidence, inputs=inputs
        )
        combined, reasons = combine_case_verdicts(
            required_cases=required_cases,
            by_role=by_role,
            specification=(specification.enumeration if specification is not None else None),
            human_card=card,
            witness_verdicts=witness_verdicts,
            completeness=completeness,
            qualification_active=qualification_id is not None,
        )
        if specification is None:
            reasons.append("HYBRID_SPECIFICATION_PASS_MISSING")
        for outcome in (first, second):
            if not outcome.verification.complete:
                reasons.append(f"HYBRID_REVIEW_REFERENCES_UNVERIFIED:{outcome.role}")
            for reason in outcome.substantiation_reasons():
                reasons.append(f"{reason}:{outcome.role}")
        projected = project_case_verdicts(combined)
        if qualification_reason:
            reasons.append(qualification_reason)
        reasons = list(dict.fromkeys(reasons))

        status = "QUALITY_ACCEPTED" if not reasons else "QUALITY_NOT_ACCEPTED"
        receipt_id = f"hybrid-{uuid4().hex}"
        deterministic_digest = _digest(
            _canonical(deterministic_report.model_dump(mode="json"))
        )
        local_status = (
            "NOT_APPLICABLE"
            if not observations
            else (
                "OBSERVED"
                if all(item.status == "OBSERVED" for item in observations)
                else "PARTIAL"
            )
        )
        self._record_receipt(
            receipt_id=receipt_id,
            candidate=candidate,
            blueprint=blueprint,
            evidence=evidence,
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            course_id=course_id,
            node_id=node_id,
            spec_version=spec_version,
            language=language,
            domain=domain,
            required_cases=required_cases,
            combined=combined,
            projected=projected,
            review_call_ids=review_call_ids,
            observation_ids=observation_ids,
            local_status=local_status,
            deterministic_report=deterministic_report,
            deterministic_digest=deterministic_digest,
            reasons=reasons,
            status=status,
            qualification_id=qualification_id,
            human_card_id=card_id,
        )
        signals = self._signals(
            required_cases=required_cases,
            projected=projected,
            receipt_id=receipt_id,
        )
        return HybridReviewResult(
            receipt_id=receipt_id,
            signals=signals,
            case_outcomes=combined,
            projected=projected,
            qualification_id=qualification_id,
            method_identity=self.method_identity,
            review_call_ids=review_call_ids,
            local_observation_ids=tuple(observation_ids),
            local_status=local_status,
            reasons=tuple(reasons),
            human_card_id=card_id,
        )

    # ------------------------------------------------------------------ inputs

    def _inputs(
        self,
        *,
        candidate: AuthoredQuestionCandidate,
        blueprint: QuestionBlueprint,
        evidence: QuestionEvidencePack,
        blind_receipt: BlindSolveReceipt,
        deterministic_report: QuestionValidationReport,
        course_id: str,
        node_id: str,
        spec_version: int,
        required_cases: tuple[str, ...],
    ) -> ReviewerInputs:
        solution = candidate.private_solution.model_dump(mode="json")
        return ReviewerInputs(
            question_revision=candidate.question_revision,
            blueprint_hash=blueprint.identity(),
            evidence_pack_hash=evidence.identity(),
            course_id=course_id,
            node_id=node_id,
            spec_version=spec_version,
            objective_id=blueprint.objective_id,
            language=_language_of(blueprint, evidence),
            domain=_domain_of(evidence),
            required_cases=required_cases,
            question_text=candidate.public_question.question_text,
            question_type=blueprint.question_type,
            options=tuple(candidate.public_question.options),
            solution_a={
                "candidate_answer": solution.get("candidate_answer"),
                "correct_option_index": solution.get("correct_option_index"),
                "distractor_rationales": solution.get("distractor_rationales"),
                "rule_violation_analysis": solution.get("rule_violation_analysis"),
                "solution_steps": solution.get("solution_steps"),
                "source_refs": solution.get("source_refs"),
            },
            solution_b=_blind_solution_payload(blind_receipt),
            rubric=tuple(blueprint.scoring_criteria),
            evidence=tuple(
                {
                    "evidence_id": fragment.evidence_id,
                    "content": fragment.content,
                    # The locator travels with the span so the server can resolve a
                    # cited id back to a frozen, addressable place in the source.
                    "locator": fragment.locator,
                }
                for fragment in evidence.fragments
            ),
            deterministic={
                gate.gate: gate.status for gate in deterministic_report.hard_gates
            },
            output_language="en",
        )

    # --------------------------------------------------------------- local side

    def _observe(self, inputs: ReviewerInputs) -> list[LocalObservation]:
        if self.local_observer is None:
            return []
        try:
            return list(self.local_observer.observe(inputs))
        except Exception:  # noqa: BLE001 - a local observer may never block the gate
            return [
                LocalObservation(
                    case=case,
                    status="UNAVAILABLE",
                    reason="LOCAL_OBSERVER_FAILED",
                )
                for case in inputs.required_cases
            ]

    # ------------------------------------------------------- ambiguity evidence

    def _verify_witnesses(
        self,
        *,
        outcomes: tuple[StrongReviewOutcome, StrongReviewOutcome],
        candidate: AuthoredQuestionCandidate,
        blueprint: QuestionBlueprint,
        evidence: QuestionEvidencePack,
    ) -> list[Any]:
        """Check every witness the reviewers produced against the frozen material.

        Only the structural rules run here.  Executing a witness needs a declared,
        bounded instance to run it against, and an item that does not carry one
        cannot have its readings executed -- so such a witness stays an open
        objection rather than being confirmed or dismissed on the model's word.
        """
        from app.learning.ambiguity_witness import structural_check

        spec = candidate.task_spec(blueprint) if candidate.task_contract else None
        equivalence = spec.answer_equivalence if spec is not None else "EXACT"
        span_ids = set(evidence.evidence_ids)
        verdicts: list[Any] = []
        for outcome in outcomes:
            for finding in outcome.findings.findings:
                if finding.case != CASE_AMBIGUITY:
                    continue
                claim = finding.ambiguity_witness
                if claim is None:
                    continue
                verdicts.append(
                    structural_check(
                        claim,
                        declared_equivalence=equivalence,
                        span_ids=span_ids,
                    )
                )
        return verdicts

    def _completeness_certificate(
        self,
        *,
        candidate: AuthoredQuestionCandidate,
        blueprint: QuestionBlueprint,
        evidence: QuestionEvidencePack,
        inputs: ReviewerInputs,
    ) -> Any | None:
        """The server's own completeness evidence, or None when there is none.

        None is not a soft pass: the ambiguity case treats it as UNCERTAIN.  An
        item whose author produced no contract, or whose contract names no
        registered profile, has no positive evidence that it is answerable, and
        saying so is the honest outcome.
        """
        from app.learning.task_spec import certify_completeness, render_public_projection

        if not candidate.task_contract:
            return None
        spec = candidate.task_spec(blueprint)
        if spec is None:
            return None
        try:
            projection = render_public_projection(spec)
        except Exception:  # noqa: BLE001 - an unrenderable contract is no evidence
            return None
        return certify_completeness(
            spec,
            projection=projection,
            available_span_ids=evidence.evidence_ids,
            reviewable_language=inputs.language,
        )

    # ------------------------------------------------------------ persistence

    def _record_provider_failure(
        self,
        *,
        candidate: AuthoredQuestionCandidate,
        blueprint: QuestionBlueprint,
        evidence: QuestionEvidencePack,
        failure: StrongReviewError,
    ) -> str:
        """Persist one failed strong-review call, then let the caller re-raise."""
        from app.learning.provider_failure_ledger import record_provider_failure

        run = dict(getattr(failure, "provider_run", None) or {})
        return record_provider_failure(
            self.database,
            policy_revision=POLICY_REVISION,
            role=str(run.get("role") or "unknown"),
            run=run,
            question_revision_hash=candidate.question_revision,
            blueprint_hash=candidate.blueprint_hash,
            evidence_pack_hash=evidence.identity(),
            message=f"{failure.code}: {failure}",
        )

    def _record_calls(
        self,
        *,
        candidate: AuthoredQuestionCandidate,
        blueprint: QuestionBlueprint,
        evidence: QuestionEvidencePack,
        outcomes: tuple[StrongReviewOutcome, StrongReviewOutcome],
        specification: Any | None = None,
    ) -> tuple[str, ...]:
        call_ids: list[str] = []
        rows: list[tuple[str, str, str, str, Any]] = [
            (outcome.role, outcome.call_id, outcome.input_hash, outcome.response_digest, outcome)
            for outcome in outcomes
        ]
        if specification is not None:
            rows.append(
                (
                    SPECIFICATION_AUDIT_ROLE,
                    specification.call_id,
                    specification.input_hash,
                    specification.response_digest,
                    specification,
                )
            )
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for role, call_id_value, input_hash, response_digest, outcome in rows:
                call_id = f"hybridcall-{uuid4().hex}"
                call_ids.append(call_id)
                is_specification = role == SPECIFICATION_AUDIT_ROLE
                verification_payload = (
                    {"enumeration_only": True, "blocking": outcome.blocks}
                    if is_specification
                    else outcome.verification.model_dump(mode="json")
                )
                findings_payload = (
                    {"dependencies": [i.model_dump(mode="json") for i in outcome.enumeration.dependencies]}
                    if is_specification
                    else outcome.findings.model_dump(mode="json")
                )
                # A plain INSERT, not INSERT OR REPLACE.  SQLite fires a BEFORE
                # DELETE trigger from REPLACE only when recursive_triggers is on,
                # and it defaults to off, so REPLACE silently overwrote an
                # append-only row.  The unique key now includes the prompt and
                # schema versions, so a genuinely new method records a new call
                # and an exact duplicate refuses instead of erasing history.
                connection.execute(
                    "INSERT INTO hybrid_review_calls("
                    "id,question_revision_hash,blueprint_hash,evidence_pack_hash,policy_revision,"
                    "role,call_id,model,provider,protocol,region,template_version,schema_version,"
                    "input_hash,response_digest,response_json,findings_json,verification_json,"
                    "references_verified,terminal,input_tokens,output_tokens,latency_ms,"
                    "provider_response_id) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        call_id,
                        candidate.question_revision,
                        blueprint.identity(),
                        evidence.identity(),
                        POLICY_REVISION,
                        role,
                        call_id_value,
                        outcome.run.model,
                        outcome.run.provider,
                        outcome.run.protocol,
                        outcome.run.region,
                        outcome.run.template_version,
                        outcome.run.schema_version,
                        input_hash,
                        response_digest,
                        outcome.response_text,
                        _canonical(findings_payload),
                        _canonical(verification_payload),
                        # The specification pass has no references to verify; a
                        # blocking entry is verified by the required consequence.
                        1 if (is_specification or outcome.verification.complete) else 0,
                        outcome.terminal,
                        outcome.run.input_tokens,
                        outcome.run.output_tokens,
                        outcome.run.latency_ms,
                        outcome.run.provider_response_id,
                    ),
                )
        return tuple(call_ids)

    def _record_observations(
        self, *, question_revision: str, observations: list[LocalObservation]
    ) -> list[str]:
        if not observations:
            return []
        ids: list[str] = []
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for observation in observations:
                observation_id = f"hybridlocal-{uuid4().hex}"
                ids.append(observation_id)
                connection.execute(
                    "INSERT INTO hybrid_local_observations("
                    "id,question_revision_hash,case_key,status,verdict,probabilities_json,"
                    "model_revision,dtype,tokenizer_hash,transform_version,model_input_hash,"
                    "state_tokens,reason,latency_ms,qualification) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        observation_id,
                        question_revision,
                        observation.case,
                        observation.status,
                        observation.verdict,
                        _canonical(observation.probabilities),
                        observation.model_revision,
                        observation.dtype,
                        observation.tokenizer_hash,
                        observation.transform_version,
                        observation.input_hash,
                        observation.state_tokens,
                        observation.reason,
                        observation.latency_ms,
                        observation.qualification,
                    ),
                )
        return ids

    def _resolve_qualification(
        self, *, language: str, domain: str, cases: tuple[str, ...]
    ) -> tuple[str, str]:
        candidates = self.qualifications.active_for(
            policy_revision=POLICY_REVISION, method_identity=self.method_identity
        )
        if not candidates:
            return "UNQUALIFIED", "HYBRID_QUALIFICATION_MISSING"
        now = datetime.now(UTC)
        first_reason = "HYBRID_QUALIFICATION_OUT_OF_SCOPE"
        for qualification in candidates:
            ok, reason = qualification.covers(
                policy_revision=POLICY_REVISION,
                method_identity=self.method_identity,
                language=language,
                domain=domain,
                cases=cases,
                now=now,
            )
            if ok:
                return qualification.id, ""
            first_reason = f"HYBRID_{reason}" if reason else first_reason
        return "UNQUALIFIED", first_reason

    def _record_receipt(
        self,
        *,
        receipt_id: str,
        candidate: AuthoredQuestionCandidate,
        blueprint: QuestionBlueprint,
        evidence: QuestionEvidencePack,
        owner_user_id: str,
        workspace_id: str,
        course_id: str,
        node_id: str,
        spec_version: int,
        language: str,
        domain: str,
        required_cases: tuple[str, ...],
        combined: dict[str, str],
        projected: dict[str, str],
        review_call_ids: tuple[str, str],
        observation_ids: list[str],
        local_status: str,
        deterministic_report: QuestionValidationReport,
        deterministic_digest: str,
        reasons: list[str],
        status: str,
        qualification_id: str,
        human_card_id: str | None = None,
    ) -> None:
        from app.jev.models import owner_scope_hash

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO hybrid_quality_receipts("
                "id,question_revision_hash,blueprint_hash,evidence_pack_hash,policy_revision,"
                "method_identity,qualification_id,owner_scope_hash,course_id,workspace_id,node_id,"
                "spec_version,language,domain,required_cases_json,case_outcomes_json,"
                "projected_verdicts_json,review_call_ids_json,local_observation_ids_json,"
                "local_status,human_card_id,deterministic_report_json,deterministic_digest,"
                "reasons_json,status) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    receipt_id,
                    candidate.question_revision,
                    blueprint.identity(),
                    evidence.identity(),
                    POLICY_REVISION,
                    self.method_identity,
                    qualification_id,
                    owner_scope_hash(owner_user_id, "question_validation"),
                    course_id,
                    workspace_id,
                    node_id,
                    spec_version,
                    language,
                    domain,
                    _canonical(list(required_cases)),
                    _canonical(combined),
                    _canonical(projected),
                    _canonical(list(review_call_ids)),
                    _canonical(list(observation_ids)),
                    local_status,
                    human_card_id,
                    _canonical(deterministic_report.model_dump(mode="json")),
                    deterministic_digest,
                    _canonical(reasons),
                    status,
                ),
            )

    # ---------------------------------------------------------------- signals

    def _signals(
        self,
        *,
        required_cases: tuple[str, ...],
        projected: dict[str, str],
        receipt_id: str,
    ) -> QuestionSemanticSignals:
        def signal(dimension: str) -> SemanticSignal:
            return SemanticSignal(
                dimension=dimension,  # type: ignore[arg-type]
                verdict=projected.get(dimension, "UNCERTAIN"),  # type: ignore[arg-type]
                used_jev=True,
                receipt_id=receipt_id,
                path="hybrid",
            )

        specialized: SemanticSignal | None = None
        if required_cases and CASE_DIMENSION[required_cases[-1]] in {
            "MCQ_DISTRACTOR_QUALITY",
            "RULE_VIOLATION_QUALITY",
        }:
            specialized = signal(CASE_DIMENSION[required_cases[-1]])
        return QuestionSemanticSignals(
            ambiguity=signal("AMBIGUITY"),
            answer_agreement=signal("AUTHOR_BLIND_AGREEMENT"),
            specialized_quality=specialized,
        )


def _blind_solution_payload(blind_receipt: BlindSolveReceipt) -> dict[str, Any]:
    try:
        payload = json.loads(blind_receipt.output)
    except (TypeError, ValueError):
        return {"raw": blind_receipt.output}
    if isinstance(payload, dict):
        return payload
    return {"raw": blind_receipt.output}


def expected_specialized_dimension(blueprint: QuestionBlueprint) -> str | None:
    return required_specialized_semantic_dimension(blueprint)


def acceptance_label(case: str) -> str:
    return CASE_ACCEPT_LABEL[case]
