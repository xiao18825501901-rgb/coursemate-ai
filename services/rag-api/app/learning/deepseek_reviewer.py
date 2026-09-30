"""Two independently requested DeepSeek semantic reviewers for the hybrid gate.

Roles (``hybrid-strict-v1``):

``evidence_audit``
    Reviews the frozen item, its exact sources, the anonymised author and blind
    solutions in a server-frozen order, the rubric and the trusted deterministic
    results, and answers every server-selected case.

``adversarial_audit``
    A second, stateless request that tries to falsify the item: a second
    defensible interpretation, a shared mistake, a second correct option, a
    missing prerequisite.  It receives the *same* frozen material with the
    anonymised solution order reversed and receives no verdict, explanation or
    local label from the first reviewer.

Isolation is a property of this module's construction, not of a prompt:

* the two roles are separate provider calls with distinct ``role`` strings,
  distinct instruction documents and distinct input digests;
* neither call is ever given the other's output, the OpenJev observation, or the
  author's chat history -- :class:`ReviewerInputs` has no such field, so the
  material cannot leak by accident;
* both calls are made before either result is read into the gate, so a reviewer
  cannot be "re-asked until satisfied".

Two requests to the same model are process separation, not statistical
independence.  Nothing here multiplies probabilities or claims two experts; the
qualification registry records measured behaviour instead.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Protocol

from pydantic import Field, StringConstraints, model_validator

from app.learning.hybrid_review import (
    ADVERSARIAL_AUDIT_ROLE,
    CASE_ACCEPT_LABEL,
    EVIDENCE_AUDIT_ROLE,
    POLICY_REVISION,
    SPECIFICATION_AUDIT_ROLE,
    STRONG_REVIEW_ROLES,
    JudgeFindings,
    ReferenceVerification,
    SpecificationEnumeration,
    balanced_solution_order,
    verify_references,
)
from app.learning.models import Contract
from app.learning.provider import ProviderCallFailure

# Prompt revisions are part of `method_identity`, so a change to the reviewer
# instructions must bump the version: a qualification obtained with v1 must never
# be readable as a qualification of a later revision.
EVIDENCE_AUDIT_PROMPT_VERSION: Final = "judge-evidence-audit.v4"
ADVERSARIAL_AUDIT_PROMPT_VERSION: Final = "judge-adversarial-audit.v4"
SPECIFICATION_AUDIT_PROMPT_VERSION: Final = "judge-specification-audit.v1"
STRONG_REVIEW_SCHEMA_VERSION: Final = "coursejesus-judge-findings.v3"
SPECIFICATION_SCHEMA_VERSION: Final = "coursejesus-specification-audit.v1"
PROMPT_DIR: Final = Path(__file__).with_name("prompts")
EVIDENCE_AUDIT_PROMPT_PATH: Final = PROMPT_DIR / "judge_evidence_audit_v1.md"
ADVERSARIAL_AUDIT_PROMPT_PATH: Final = PROMPT_DIR / "judge_adversarial_audit_v1.md"
SPECIFICATION_AUDIT_PROMPT_PATH: Final = PROMPT_DIR / "judge_specification_audit_v1.md"

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Hex64 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class StrongReviewError(RuntimeError):
    """A strong review could not reach a complete, verifiable terminal."""

    def __init__(
        self, code: str, message: str, *, provider_run: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.provider_run = provider_run


class StrongReviewRun(Contract):
    """The recorded provider facts of one reviewer call (DeepSeek or a fixture)."""

    model: ShortText
    provider: ShortText
    protocol: ShortText
    region: ShortText
    role: ShortText
    template_version: ShortText
    schema_version: ShortText
    input_hash: Hex64
    started_at: ShortText
    finished_at: ShortText
    latency_ms: int = Field(ge=0)
    # Additive: the phase budgets this call was allowed to use.  Absent on
    # records written before the policy existed, so a stored run still
    # validates; present, it says what connect, read, write and pool were.
    timeouts: dict[str, float] | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    provider_response_id: ShortText | None = None
    status: Literal["COMPLETED"]
    error_class: None = None

    @model_validator(mode="after")
    def deepseek_or_labelled_fixture_only(self) -> StrongReviewRun:
        fixture = (
            self.model == "FAKE_TEST_ONLY"
            and self.provider == "deterministic"
            and self.protocol == "fixture"
            and self.region == "LOCAL_TEST"
        )
        deepseek = (
            self.model == "deepseek-flash"
            and self.provider == "DEEPSEEK_API"
            and self.protocol == "responses"
            and self.region == "ENDPOINT_DEEPSEEK"
        )
        if not (fixture or deepseek):
            raise ValueError("strong-review receipts must be DeepSeek or labelled test fixtures")
        return self


@dataclass(frozen=True)
class ReviewerInputs:
    """Everything both strong reviewers are allowed to see.  Nothing else.

    There is deliberately no field for another reviewer's verdict, for a local
    model's label, for the author's chat history, or for a pre-computed
    "acceptable" flag.
    """

    question_revision: str
    blueprint_hash: str
    evidence_pack_hash: str
    course_id: str
    node_id: str
    spec_version: int
    objective_id: str
    language: str
    domain: str
    required_cases: tuple[str, ...]
    question_text: str
    question_type: str
    options: tuple[str, ...]
    solution_a: dict[str, Any]
    solution_b: dict[str, Any]
    rubric: tuple[str, ...]
    evidence: tuple[dict[str, str], ...]
    deterministic: dict[str, str]
    output_language: str = "en"


@dataclass(frozen=True)
class SpecificationOutcome:
    """The dedicated under-specification pass's recorded result."""

    call_id: str
    input_hash: str
    response_digest: str
    response_text: str
    enumeration: SpecificationEnumeration
    run: StrongReviewRun
    terminal: str = "completed"

    def as_receipt(self) -> dict[str, Any]:
        return {
            "role": SPECIFICATION_AUDIT_ROLE,
            "call_id": self.call_id,
            "input_hash": self.input_hash,
            "response_digest": self.response_digest,
            "terminal": self.terminal,
            "dependencies": [
                item.model_dump(mode="json") for item in self.enumeration.dependencies
            ],
        }

    @property
    def blocks(self) -> bool:
        return bool(self.enumeration.blocking_entries)


@dataclass(frozen=True)
class StrongReviewOutcome:
    """One completed, reference-verified reviewer result."""

    role: str
    call_id: str
    input_hash: str
    response_digest: str
    response_text: str
    findings: JudgeFindings
    verification: ReferenceVerification
    run: StrongReviewRun
    terminal: str = "completed"

    def case_verdicts(self) -> dict[str, str]:
        """The reviewer's per-case verdicts after the substantiation pass.

        A verdict the reviewer did not support with its own reported evidence is
        not a decision; it is downgraded to ``UNCERTAIN`` before the two roles
        are combined.  This can never turn anything into a ``PASS``.
        """
        from app.learning.hybrid_review import substantiated_case_verdicts

        verdicts, _ = substantiated_case_verdicts(self.findings)
        return verdicts

    def substantiation_reasons(self) -> list[str]:
        from app.learning.hybrid_review import substantiated_case_verdicts

        _, reasons = substantiated_case_verdicts(self.findings)
        return reasons

    def blocking_substantiation_reasons(self) -> list[str]:
        """Substantiation reasons for the cases the roles actually decide.

        The ambiguity case is decided by the server completeness certificate, so
        a downgrade of a role ambiguity verdict explains the record without
        blocking the item.  Every other case still blocks on an unsubstantiated
        verdict, and the full list is still recorded on the receipt.
        """
        from app.learning.hybrid_review import CASE_AMBIGUITY

        return [
            reason
            for reason in self.substantiation_reasons()
            if not reason.endswith(":" + CASE_AMBIGUITY)
        ]

    def as_receipt(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "call_id": self.call_id,
            "input_hash": self.input_hash,
            "response_digest": self.response_digest,
            "terminal": self.terminal,
            "findings": self.findings.model_dump(mode="json"),
            "verification": self.verification.model_dump(mode="json"),
        }


class StrongReviewProvider(Protocol):
    def generate(
        self,
        schema: type[Any],
        *,
        instructions: str,
        context: dict[str, Any],
        role: str,
        template_version: str = ...,
        schema_version: str | None = ...,
        max_output_tokens: int | None = ...,
    ) -> tuple[Any, dict[str, Any]]: ...


def _read_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def detector_language(text: str) -> str:
    """Deterministic language scope of the reviewed material (never a model claim)."""
    has_zh = bool(re.search(r"[\u3400-\u9fff]", text))
    has_latin = bool(re.search(r"[A-Za-z]", text))
    if has_zh and has_latin:
        return "mixed"
    return "zh" if has_zh else "en"


def reviewer_context(
    inputs: ReviewerInputs,
    *,
    role: str,
) -> dict[str, Any]:
    """Build one reviewer's authorized context.

    The anonymised solution order is frozen from the question revision hash and
    reversed between the two roles, so neither role sees a different fact set
    and neither order was chosen after observing an answer.
    """
    order = balanced_solution_order(revision_hash=inputs.question_revision)
    if role == ADVERSARIAL_AUDIT_ROLE:
        order = (order[1], order[0])
    solutions = []
    for position, label in zip("XY", order, strict=True):
        payload = inputs.solution_a if label == "AUTHOR" else inputs.solution_b
        solutions.append({"label": position, "content": payload})
    return {
        "policy_revision": POLICY_REVISION,
        "review_role": role,
        "target": {
            "course_id": inputs.course_id,
            "node_id": inputs.node_id,
            "spec_version": inputs.spec_version,
            "objective_id": inputs.objective_id,
            "language": inputs.language,
            "domain": inputs.domain,
        },
        "frozen_item": {
            "question_text": inputs.question_text,
            "question_type": inputs.question_type,
            "options": list(inputs.options),
        },
        "rubric": list(inputs.rubric),
        "source_spans": [
            {
                "source_span_id": fragment["evidence_id"],
                "content": fragment["content"],
            }
            for fragment in inputs.evidence
        ],
        "anonymized_solutions": solutions,
        "trusted_deterministic_results": dict(inputs.deterministic),
        "required_cases": list(inputs.required_cases),
        "accepted_labels": {
            case: CASE_ACCEPT_LABEL[case] for case in inputs.required_cases
        },
        "output_language": inputs.output_language,
    }


class DeepSeekStrongReviewer:
    """Runs both strong-review roles as two separate, blinded provider calls."""

    def __init__(
        self,
        provider: StrongReviewProvider,
        *,
        model_alias: str,
        provider_label: str = "DEEPSEEK_API",
        protocol: str = "responses",
        evidence_prompt_version: str = EVIDENCE_AUDIT_PROMPT_VERSION,
        adversarial_prompt_version: str = ADVERSARIAL_AUDIT_PROMPT_VERSION,
        specification_prompt_version: str = SPECIFICATION_AUDIT_PROMPT_VERSION,
        schema_version: str = STRONG_REVIEW_SCHEMA_VERSION,
        specification_schema_version: str = SPECIFICATION_SCHEMA_VERSION,
        max_output_tokens: int | None = 4000,
    ) -> None:
        self.provider = provider
        self.model_alias = model_alias
        self.provider_label = provider_label
        self.protocol = protocol
        self.evidence_prompt_version = evidence_prompt_version
        self.adversarial_prompt_version = adversarial_prompt_version
        self.specification_prompt_version = specification_prompt_version
        self.schema_version = schema_version
        self.specification_schema_version = specification_schema_version
        self.max_output_tokens = max_output_tokens
        self._prompts: dict[str, str] = {}
        # The most recent specification pass, recorded by `review` so the caller
        # can persist it alongside the two case-deciding calls.
        self.last_specification: SpecificationOutcome | None = None

    @property
    def method_identity(self) -> str:
        from app.learning.hybrid_review import method_identity

        return method_identity(
            model_alias=self.model_alias,
            provider=self.provider_label,
            protocol=self.protocol,
            evidence_prompt_version=self.evidence_prompt_version,
            adversarial_prompt_version=self.adversarial_prompt_version,
            specification_prompt_version=self.specification_prompt_version,
            schema_version=self.schema_version,
            specification_schema_version=self.specification_schema_version,
        )

    def prompt_for(self, role: str) -> str:
        if role not in self._prompts:
            path = {
                EVIDENCE_AUDIT_ROLE: EVIDENCE_AUDIT_PROMPT_PATH,
                ADVERSARIAL_AUDIT_ROLE: ADVERSARIAL_AUDIT_PROMPT_PATH,
                SPECIFICATION_AUDIT_ROLE: SPECIFICATION_AUDIT_PROMPT_PATH,
            }[role]
            self._prompts[role] = _read_prompt(path)
        return self._prompts[role]

    def prompt_version_for(self, role: str) -> str:
        return {
            EVIDENCE_AUDIT_ROLE: self.evidence_prompt_version,
            ADVERSARIAL_AUDIT_ROLE: self.adversarial_prompt_version,
            SPECIFICATION_AUDIT_ROLE: self.specification_prompt_version,
        }[role]

    def review(
        self, inputs: ReviewerInputs
    ) -> tuple[StrongReviewOutcome, StrongReviewOutcome]:
        """Run both roles and the dedicated specification pass, then verify all.

        No early return on the first role.  The specification pass is a third
        call with a different schema and no verdict field; it is recorded like
        the others and governs only the ambiguity case.
        """
        span_text = {fragment["evidence_id"]: fragment["content"] for fragment in inputs.evidence}
        span_locator = {
            fragment["evidence_id"]: fragment.get("locator") or ""
            for fragment in inputs.evidence
        }
        span_ids = set(span_text)
        step_ids = _solution_step_ids(inputs)
        outcomes: list[StrongReviewOutcome] = []
        for role in STRONG_REVIEW_ROLES:
            context = reviewer_context(inputs, role=role)
            outcomes.append(self._one(role, context=context))
        specification = self._specification(inputs)
        if len(outcomes) != 2 or len({o.role for o in outcomes}) != 2:
            raise StrongReviewError(
                "HYBRID_REVIEW_ROLE_COLLISION",
                "The two strong reviews must be distinct roles.",
            )
        seen_calls = {outcomes[0].call_id, outcomes[1].call_id}
        if len(seen_calls) != 2 or specification.call_id in seen_calls:
            raise StrongReviewError(
                "HYBRID_REVIEW_CALL_COLLISION",
                "Every review must be a separate provider call.",
            )
        verified: list[StrongReviewOutcome] = []
        for outcome in outcomes:
            verification = verify_references(
                outcome.findings,
                required_cases=inputs.required_cases,
                span_ids=span_ids,
                span_text_by_id=span_text,
                solution_step_ids=step_ids,
                span_locator_by_id=span_locator,
            )
            verified.append(
                StrongReviewOutcome(
                    role=outcome.role,
                    call_id=outcome.call_id,
                    input_hash=outcome.input_hash,
                    response_digest=outcome.response_digest,
                    response_text=outcome.response_text,
                    findings=outcome.findings,
                    verification=verification,
                    run=outcome.run,
                )
            )
        self.last_specification = specification
        return verified[0], verified[1]

    def _specification(self, inputs: ReviewerInputs) -> SpecificationOutcome:
        """The dedicated under-specification pass: one call, no verdict field."""
        role = SPECIFICATION_AUDIT_ROLE
        context = reviewer_context(inputs, role=role)
        instructions = self.prompt_for(role)
        template_version = self.prompt_version_for(role)
        try:
            output, run = self.provider.generate(
                SpecificationEnumeration,
                instructions=instructions,
                context=context,
                role=role,
                template_version=template_version,
                schema_version=self.specification_schema_version,
                max_output_tokens=self.max_output_tokens,
            )
        except ProviderCallFailure as failure:
            raise StrongReviewError(
                "HYBRID_SPECIFICATION_PROVIDER_FAILED",
                "The specification pass did not reach a complete terminal.",
                provider_run=failure.run,
            ) from failure
        enumeration = SpecificationEnumeration.model_validate(output)
        record = StrongReviewRun.model_validate(run)
        response_text = json.dumps(
            enumeration.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
        )
        call_id = record.provider_response_id or f"{role}:{record.input_hash[:32]}"
        return SpecificationOutcome(
            call_id=str(call_id),
            input_hash=record.input_hash,
            response_digest=_digest(response_text),
            response_text=response_text,
            enumeration=enumeration,
            run=record,
        )

    def _one(self, role: str, *, context: dict[str, Any]) -> StrongReviewOutcome:
        instructions = self.prompt_for(role)
        template_version = self.prompt_version_for(role)
        try:
            output, run = self.provider.generate(
                JudgeFindings,
                instructions=instructions,
                context=context,
                role=role,
                template_version=template_version,
                schema_version=self.schema_version,
                max_output_tokens=self.max_output_tokens,
            )
        except ProviderCallFailure as failure:
            raise StrongReviewError(
                "HYBRID_REVIEW_PROVIDER_FAILED",
                "A strong semantic review did not reach a complete terminal.",
                provider_run=failure.run,
            ) from failure
        # The durable record must exist before the content is used.  The caller
        # persists the returned receipt; nothing here retries a paid call.
        record = StrongReviewRun.model_validate(run)
        try:
            findings = JudgeFindings.model_validate(output)
        except ValueError as error:
            # A response that does not satisfy the findings schema must become the
            # same typed failure as a transport problem, with its provider run
            # attached.  Left unhandled it propagates as a bare ValidationError, which
            # the durable worker turns into ASSESSMENT_WORKER_FAILED with nothing
            # recorded about the cause -- the least attributable of the review
            # failures, and one that cost a live campus preparation whole attempts.
            # The paid call is not retried here; this only makes the failure readable.
            raise StrongReviewError(
                "HYBRID_REVIEW_UNPARSEABLE",
                "The strong review response did not satisfy its schema: "
                f"{type(error).__name__}: {str(error)[:300]}",
                provider_run=record,
            ) from error
        response_text = json.dumps(
            findings.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
        )
        call_id = (
            record.provider_response_id
            or f"{role}:{record.input_hash[:32]}"
        )
        return StrongReviewOutcome(
            role=role,
            call_id=str(call_id),
            input_hash=record.input_hash,
            response_digest=_digest(response_text),
            response_text=response_text,
            findings=findings,
            verification=ReferenceVerification(
                case_set_exact=False,
                quotes_traceable=False,
                steps_exist=False,
            ),
            run=record,
        )


def _solution_step_ids(inputs: ReviewerInputs) -> set[str]:
    """The exact step ids either anonymised solution exposes to the reviewers."""
    ids: set[str] = set()
    for solution in (inputs.solution_a, inputs.solution_b):
        steps = solution.get("solution_steps") or solution.get("steps") or []
        if not isinstance(steps, list):
            continue
        for index, step in enumerate(steps, start=1):
            if isinstance(step, dict):
                ordinal = step.get("ordinal", index)
                ids.add(f"step_{ordinal}")
    return ids


def required_cases_for_inputs(inputs: ReviewerInputs) -> tuple[str, ...]:
    return inputs.required_cases


@dataclass
class LocalObservation:
    """An advisory-only local (OpenJev) observation.

    There is deliberately no field that grants or vetoes a hard-gate decision:
    an unqualified local signal may point at something worth checking, and the
    check -- not the probability -- is what can block publication.
    """

    case: str
    status: str  # "OBSERVED" | "SKIPPED" | "UNAVAILABLE"
    verdict: str | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    model_revision: str | None = None
    dtype: str | None = None
    tokenizer_hash: str | None = None
    transform_version: str | None = None
    input_hash: str | None = None
    state_tokens: int | None = None
    reason: str | None = None
    latency_ms: float | None = None
    qualification: str = "UNQUALIFIED_ADVISORY"

    def as_receipt(self) -> dict[str, Any]:
        return {
            "case": self.case,
            "status": self.status,
            "verdict": self.verdict,
            "probabilities": dict(self.probabilities),
            "model_revision": self.model_revision,
            "dtype": self.dtype,
            "tokenizer_hash": self.tokenizer_hash,
            "transform_version": self.transform_version,
            "input_hash": self.input_hash,
            "state_tokens": self.state_tokens,
            "reason": self.reason,
            "latency_ms": self.latency_ms,
            "qualification": self.qualification,
        }
