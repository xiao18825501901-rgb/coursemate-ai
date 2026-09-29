"""Server-side hybrid strict quality policy (``hybrid-strict-v1``).

This module owns the *policy* half of the hybrid Question Engine gate:

* which decision cases a question kind requires;
* the strict JSON contract each strong reviewer must satisfy;
* the server-side verification of a reviewer's references (span ids, verbatim
  quotations, solution step ids) that no model self-report can replace;
* the combination rule -- every required case must be supported by **both**
  independently requested reviewer roles, and a verified deterministic failure
  is never overridable by a favourable model vote;
* the projection of that combination back onto the pre-existing CourseJesus
  semantic verdicts, so the downstream Question Engine keeps its original four
  quality requirements instead of gaining a weaker parallel one.

It deliberately contains no provider code, no database access and no
qualification registry: those live in :mod:`app.learning.deepseek_reviewer`,
:mod:`app.learning.hybrid_qualification` and the additive receipts migration.
Nothing here is a hard-gate bypass: a local (OpenJev) observation can never
produce or veto one of these case verdicts.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from pydantic import Field, StringConstraints, model_validator

from app.learning.models import Contract

POLICY_REVISION: Final = "hybrid-strict-v1"
CASE_MAPPING_VERSION: Final = "hybrid-case-mapping.v1"

CASE_AMBIGUITY: Final = "question.ambiguity.v1"
CASE_AGREEMENT: Final = "question.answer_agreement.v1"
CASE_DISTRACTORS: Final = "question.mcq_distractor_quality.v1"
CASE_RULE: Final = "question.rule_violation_quality.v1"

ALL_CASES: Final[tuple[str, ...]] = (
    CASE_AMBIGUITY,
    CASE_AGREEMENT,
    CASE_DISTRACTORS,
    CASE_RULE,
)

# Which cases each question kind must satisfy.  The server decides this from the
# blueprint; a model may never omit a case by declaring it "not applicable".
CASE_SETS_BY_KIND: Final[dict[str, tuple[str, ...]]] = {
    "ordinary": (CASE_AMBIGUITY, CASE_AGREEMENT),
    "mcq": (CASE_AMBIGUITY, CASE_AGREEMENT, CASE_DISTRACTORS),
    "rule": (CASE_AMBIGUITY, CASE_AGREEMENT, CASE_RULE),
    "mcq_rule": (CASE_AMBIGUITY, CASE_AGREEMENT, CASE_DISTRACTORS, CASE_RULE),
}

# The label each case uses when a reviewer finds the item acceptable.
CASE_ACCEPT_LABEL: Final[dict[str, str]] = {
    CASE_AMBIGUITY: "CLEAR",
    CASE_AGREEMENT: "AGREE",
    CASE_DISTRACTORS: "ACCEPTABLE",
    CASE_RULE: "SUPPORTED",
}

# The label the pre-existing validator uses when a case is refused.
CASE_REFUSE_LABEL: Final[dict[str, str]] = {
    CASE_AMBIGUITY: "AMBIGUOUS",
    CASE_AGREEMENT: "DISAGREE",
    CASE_DISTRACTORS: "WEAK",
    CASE_RULE: "UNSUPPORTED",
}

# Which CourseJesus semantic dimension each case feeds.
CASE_DIMENSION: Final[dict[str, str]] = {
    CASE_AMBIGUITY: "AMBIGUITY",
    CASE_AGREEMENT: "AUTHOR_BLIND_AGREEMENT",
    CASE_DISTRACTORS: "MCQ_DISTRACTOR_QUALITY",
    CASE_RULE: "RULE_VIOLATION_QUALITY",
}

EVIDENCE_AUDIT_ROLE: Final = "evidence_audit"
ADVERSARIAL_AUDIT_ROLE: Final = "adversarial_audit"
STRONG_REVIEW_ROLES: Final[tuple[str, ...]] = (
    EVIDENCE_AUDIT_ROLE,
    ADVERSARIAL_AUDIT_ROLE,
)

ReviewRole = Literal["evidence_audit", "adversarial_audit"]
CaseVerdict = Literal["PASS", "FAIL", "UNCERTAIN"]

CaseKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
ShortQuote = Annotated[str, StringConstraints(min_length=1, max_length=800)]
Assertion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
StepId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
MissingCondition = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)
]
Counterexample = Annotated[str, StringConstraints(strip_whitespace=True, max_length=3000)]


class JudgeSourceRef(Contract):
    """One short verbatim quotation tied to a server-supplied evidence span id."""

    source_span_id: CaseKey
    quote: ShortQuote


class JudgeFinding(Contract):
    case: CaseKey
    verdict: CaseVerdict
    assertion: Assertion
    evidence_refs: list[JudgeSourceRef] = Field(default_factory=list, max_length=16)
    solution_step_ids: list[StepId] = Field(default_factory=list, max_length=32)
    counterexample: Counterexample | None = None
    missing_conditions: list[MissingCondition] = Field(default_factory=list, max_length=20)


class JudgeFindings(Contract):
    """The strict top-level object a strong reviewer must return."""

    findings: list[JudgeFinding] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def cases_are_unique(self) -> JudgeFindings:
        seen = [finding.case for finding in self.findings]
        if len(set(seen)) != len(seen):
            raise ValueError("a reviewer may report each required case exactly once")
        return self


class ReferenceVerificationError(RuntimeError):
    """A reviewer reference could not be traced to the frozen server material."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "HYBRID_REVIEW_REFERENCE_INVALID"


class ReferenceVerification(Contract):
    """The server-owned result of checking one reviewer output against frozen input."""

    case_set_exact: bool
    quotes_traceable: bool
    steps_exist: bool
    unknown_span_ids: list[CaseKey] = Field(default_factory=list, max_length=32)
    unknown_step_ids: list[StepId] = Field(default_factory=list, max_length=32)
    untraceable_quotes: list[CaseKey] = Field(default_factory=list, max_length=32)

    @property
    def complete(self) -> bool:
        return self.case_set_exact and self.quotes_traceable and self.steps_exist


def case_set_for(kind: str) -> tuple[str, ...]:
    """Return the exact required case tuple for one question kind."""
    try:
        return CASE_SETS_BY_KIND[kind]
    except KeyError as error:  # pragma: no cover - guarded by the caller
        raise ValueError(f"unsupported hybrid question kind: {kind!r}") from error


def case_set_for_blueprint(*, question_type: str, rule_policy: bool) -> tuple[str, ...]:
    """Derive the required cases from the blueprint's own question contract."""
    if question_type == "MCQ_SINGLE" and rule_policy:
        return CASE_SETS_BY_KIND["mcq_rule"]
    if question_type == "MCQ_SINGLE":
        return CASE_SETS_BY_KIND["mcq"]
    if rule_policy:
        return CASE_SETS_BY_KIND["rule"]
    return CASE_SETS_BY_KIND["ordinary"]


def project_case_verdicts(case_outcomes: dict[str, str]) -> dict[str, str]:
    """Project combined per-case PASS/FAIL/UNCERTAIN onto the original verdicts.

    A case is projected into the pre-existing CourseJesus vocabulary so the
    unchanged validator keeps its four original requirements.  Only an
    unambiguous PASS becomes the accept label; anything else is a refusal or an
    explicit ``UNCERTAIN``.
    """
    projected: dict[str, str] = {}
    for case, outcome in case_outcomes.items():
        if case not in CASE_ACCEPT_LABEL:
            raise ValueError(f"unknown hybrid case: {case!r}")
        if outcome == "PASS":
            projected[CASE_DIMENSION[case]] = CASE_ACCEPT_LABEL[case]
        elif outcome == "FAIL":
            projected[CASE_DIMENSION[case]] = CASE_REFUSE_LABEL[case]
        elif outcome == "UNCERTAIN":
            projected[CASE_DIMENSION[case]] = "UNCERTAIN"
        else:  # pragma: no cover - guarded by CaseVerdict
            raise ValueError(f"invalid hybrid case verdict: {outcome!r}")
    return projected


def combine_case_verdicts(
    *,
    required_cases: tuple[str, ...],
    by_role: dict[str, dict[str, str]],
) -> tuple[dict[str, str], list[str]]:
    """Combine both reviewer roles into one verdict per required case.

    The rule is deliberately conjunctive and never majoritarian:

    * both roles PASS -> PASS;
    * either role FAIL -> FAIL (a concrete defect is not outvoted);
    * otherwise -> UNCERTAIN.

    Returns the combined verdicts plus a list of stable refusal reasons.  A
    missing role, a missing case, or an unknown verdict is itself a refusal.
    """
    reasons: list[str] = []
    if set(by_role) != set(STRONG_REVIEW_ROLES):
        reasons.append("HYBRID_REQUIRES_TWO_DISTINCT_ROLES")
    combined: dict[str, str] = {}
    for case in required_cases:
        verdicts: list[str] = []
        for role in STRONG_REVIEW_ROLES:
            outcomes = by_role.get(role)
            if outcomes is None:
                continue
            verdict = outcomes.get(case)
            if verdict not in {"PASS", "FAIL", "UNCERTAIN"}:
                reasons.append(f"HYBRID_CASE_MISSING:{role}:{case}")
                continue
            verdicts.append(verdict)
        if len(verdicts) != len(STRONG_REVIEW_ROLES):
            combined[case] = "UNCERTAIN"
            continue
        if "FAIL" in verdicts:
            combined[case] = "FAIL"
            reasons.append(f"HYBRID_CASE_FAIL:{case}")
        elif all(verdict == "PASS" for verdict in verdicts):
            combined[case] = "PASS"
        else:
            combined[case] = "UNCERTAIN"
            reasons.append(f"HYBRID_CASE_UNCERTAIN:{case}")
    extra = {
        case
        for outcomes in by_role.values()
        for case in outcomes
        if case not in required_cases
    }
    for case in sorted(extra):
        reasons.append(f"HYBRID_CASE_NOT_REQUIRED:{case}")
    return combined, list(dict.fromkeys(reasons))


def verify_references(
    findings: JudgeFindings,
    *,
    required_cases: tuple[str, ...],
    span_ids: set[str],
    span_text_by_id: dict[str, str],
    solution_step_ids: set[str],
) -> ReferenceVerification:
    """Check a reviewer's references against the frozen server material.

    An exact quotation only proves the reference is traceable; it never proves
    the inference is sound.  That judgement stays with the reviewers and with
    the deterministic gate.

    Quotation matching is whitespace-insensitive (reviewers legitimately
    re-wrap lines) but otherwise exact and case-sensitive, so a fabricated or
    paraphrased "quote" is not accepted as traceable.
    """
    cases = [finding.case for finding in findings.findings]
    case_set_exact = len(cases) == len(set(cases)) and set(cases) == set(required_cases)
    unknown_spans: list[str] = []
    unknown_steps: list[str] = []
    untraceable: list[str] = []
    for finding in findings.findings:
        for reference in finding.evidence_refs:
            if reference.source_span_id not in span_ids:
                # A span id the server never supplied is not a traceable
                # reference, whether or not the quotation happens to match
                # something: the reviewer is citing material it was not given.
                unknown_spans.append(reference.source_span_id)
                continue
            haystack = _collapse(span_text_by_id.get(reference.source_span_id, ""))
            needle = _collapse(reference.quote)
            if not needle or needle not in haystack:
                untraceable.append(reference.source_span_id)
        for step_id in finding.solution_step_ids:
            if step_id not in solution_step_ids:
                unknown_steps.append(step_id)
    return ReferenceVerification(
        case_set_exact=case_set_exact,
        quotes_traceable=not untraceable and not unknown_spans,
        steps_exist=not unknown_steps,
        unknown_span_ids=sorted(set(unknown_spans))[:32],
        unknown_step_ids=sorted(set(unknown_steps))[:32],
        untraceable_quotes=sorted(set(untraceable))[:32],
    )


def _collapse(value: str) -> str:
    return " ".join(value.split())


def balanced_solution_order(*, revision_hash: str) -> tuple[str, str]:
    """Freeze the anonymised X/Y order before any reviewer sees an answer.

    The order is derived only from the immutable question revision hash, so it
    is reproducible, decided before the reviewer's answer is known, and
    balanced across questions instead of chosen after observing a result.
    """
    try:
        parity = int(revision_hash[:2], 16) % 2
    except (TypeError, ValueError):
        parity = 0
    return ("AUTHOR", "BLIND") if parity == 0 else ("BLIND", "AUTHOR")


def method_identity(
    *,
    model_alias: str,
    provider: str,
    protocol: str,
    evidence_prompt_version: str,
    adversarial_prompt_version: str,
    schema_version: str,
) -> str:
    """The exact reviewed method a qualification is bound to.

    The provider's served model revision is recorded separately as an
    observation because a hosted alias cannot be pinned; a qualification is
    bound to the alias plus every server-owned template and schema revision, and
    the deployment samples the served revision periodically rather than
    inventing a stable one.
    """
    import hashlib
    import json

    payload = {
        "policy_revision": POLICY_REVISION,
        "case_mapping_version": CASE_MAPPING_VERSION,
        "model_alias": model_alias,
        "provider": provider,
        "protocol": protocol,
        "evidence_prompt_version": evidence_prompt_version,
        "adversarial_prompt_version": adversarial_prompt_version,
        "schema_version": schema_version,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def review_input_hash(*, role: str, context: dict[str, Any], schema_name: str) -> str:
    """Stable digest of one reviewer call's exact authorized input."""
    import hashlib
    import json

    payload = {
        "role": role,
        "schema": schema_name,
        "policy_revision": POLICY_REVISION,
        "context": context,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
