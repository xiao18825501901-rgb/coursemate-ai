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

from hashlib import sha256
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
# The under-specification judgement is the one case that moves the whole gate and
# the one case that never settled while it was asked of the two general passes.
# It is asked separately because it is the only case whose answer depends on a
# judgement about *the reader* rather than about the item: "would someone holding
# only this stem and these sources be able to produce a unique answer?"  A pass
# whose only output is the enumeration, with no verdict of its own to defend,
# removes the incentive to rationalise a conclusion already reached.
SPECIFICATION_AUDIT_ROLE: Final = "specification_audit"
STRONG_REVIEW_ROLES: Final[tuple[str, ...]] = (
    EVIDENCE_AUDIT_ROLE,
    ADVERSARIAL_AUDIT_ROLE,
)
ALL_REVIEW_ROLES: Final[tuple[str, ...]] = (
    EVIDENCE_AUDIT_ROLE,
    ADVERSARIAL_AUDIT_ROLE,
    SPECIFICATION_AUDIT_ROLE,
)

ReviewRole = Literal["evidence_audit", "adversarial_audit"]
CaseVerdict = Literal["PASS", "FAIL", "UNCERTAIN"]

CaseKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
ShortQuote = Annotated[str, StringConstraints(min_length=1, max_length=800)]
Assertion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Hex64 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
StepId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
MissingCondition = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)
]
Counterexample = Annotated[str, StringConstraints(strip_whitespace=True, max_length=3000)]


EvidenceKind = Literal[
    "DIRECT_QUOTE",
    "SOURCE_RULE",
    "PROBLEM_DATA",
    "EXERCISE_ASSUMPTION",
    "CLAIM_TO_CRITIQUE",
    "CHECKER_RESULT",
]
Claim = Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=400)]


class JudgeSourceRef(Contract):
    """A reference to a server-supplied evidence span id, and what it is cited for.

    The quotation used to be mandatory, and that made the protocol fail for a
    reason that had nothing to do with whether the source supported the claim: a
    reviewer that had correctly selected a span still failed when it did not
    re-transcribe a long sentence character for character.  The reviewer now
    selects the id and states the claim; the **server** restores the frozen text,
    its digest and its locator, so the final citation is server-owned rather than
    model-transcribed.

    This removes transcription, not verification.  An unknown id is still
    refused, and a quotation that *is* supplied must still match the frozen text
    exactly -- no folding of case, negation or mathematical symbols.  A derived
    numeric result is declared as CHECKER_RESULT and carries rule, data and
    checker references instead of a literal quotation.
    """

    source_span_id: CaseKey
    claim: Claim | None = None
    evidence_kind: EvidenceKind = "DIRECT_QUOTE"
    quote: ShortQuote | None = None
    checker_ref: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None

    @model_validator(mode="after")
    def a_derived_result_names_its_checker(self) -> JudgeSourceRef:
        if self.evidence_kind == "CHECKER_RESULT" and not self.checker_ref:
            raise ValueError("a derived result must name the checker that produced it")
        return self


class ResolvedSpan(Contract):
    """The server's own citation: the frozen text a reviewer pointed at.

    A reader of the receipt can recompute the digest from the frozen source and
    see exactly which characters were cited, without trusting anything the model
    transcribed.
    """

    source_span_id: CaseKey
    truncated: bool = False
    text_digest: Hex64
    char_count: int = Field(ge=0)
    locator: str = Field(min_length=1, max_length=200)


class JudgeDependency(Contract):
    """One datum, convention or prerequisite the answer depends on.

    The ambiguity case is the one the reviewer configuration could not decide
    from a bare verdict, so it is not asked for one: the reviewer enumerates what
    the answer depends on and the server derives the verdict from that
    enumeration.  A claim that an item is "fully specified" is only as good as
    the list behind it.

    The first version of this rule failed an item whenever *any* entry was
    unstated, and it refused more than half of the sound controls: reviewers
    listed conventions a competent reader supplies (a rounding convention, an
    implicit ordering) alongside genuinely absent data.  The second field is what
    separates the two.  An entry only blocks the item when its absence **changes
    the answer**, and the reviewer has to say what the different answer would be
    -- so blanket marking is not a shortcut, it requires producing the
    consequence for each entry.
    """

    datum: Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=400)]
    stated_in_stem: bool
    answer_changes_if_absent: bool = False
    consequence: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=600)]
        | None
    ) = None

    @model_validator(mode="before")
    @classmethod
    def drop_a_consequence_that_cannot_matter(cls, value: Any) -> Any:
        """Discard a consequence on an entry that does not change the answer.

        The field is only read when an entry blocks the item, so an unused one
        cannot change any decision.  Rejecting the whole response over it did real
        damage: a bounded frozen evaluation lost five review calls to exactly this,
        all of them `findings.0.dependencies.N: value_error`, which threw away a
        complete paid response for a field nothing reads.  The rule that matters --
        a blocking entry must state the different answer that would result -- is
        still enforced below.
        """
        if isinstance(value, dict) and not value.get("answer_changes_if_absent"):
            value = {key: item for key, item in value.items() if key != "consequence"}
        return value

    @model_validator(mode="after")
    def a_consequence_is_required_when_the_answer_changes(self) -> JudgeDependency:
        if self.answer_changes_if_absent and not self.consequence:
            raise ValueError(
                "a dependency whose absence changes the answer must state the "
                "different answer that would result"
            )
        return self

    @property
    def blocks_the_item(self) -> bool:
        """True when this entry is missing and its absence changes the answer."""
        return (
            not self.stated_in_stem
            and self.answer_changes_if_absent
            and bool(self.consequence and self.consequence.strip())
        )


class JudgeFinding(Contract):
    case: CaseKey
    verdict: CaseVerdict
    assertion: Assertion
    evidence_refs: list[JudgeSourceRef] = Field(default_factory=list, max_length=16)
    # A claimed material ambiguity must arrive as a checkable witness.  The
    # server verifies it: it refuses a reading that breaks the stated conditions
    # and one whose two answers are equal under the declared equivalence, and it
    # never treats the absence of a witness as an approval.  Imported lazily to
    # keep this module free of a task-contract dependency at import time.
    ambiguity_witness: Any | None = None
    solution_step_ids: list[StepId] = Field(default_factory=list, max_length=32)
    counterexample: Counterexample | None = None
    missing_conditions: list[MissingCondition] = Field(default_factory=list, max_length=20)
    dependencies: list[JudgeDependency] = Field(default_factory=list, max_length=24)


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
    # The server's own record of every span a reviewer cited: the frozen digest,
    # the character count and the locator.  This is the citation of record; a
    # model-transcribed quotation is at most a cross-check against it.
    resolved_spans: list[ResolvedSpan] = Field(default_factory=list, max_length=64)

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


def substantiated_case_verdicts(findings: JudgeFindings) -> tuple[dict[str, str], list[str]]:
    """Enforce that a verdict is supported by what the reviewer itself reported.

    A bare verdict is not evidence.  Three things are therefore resolved
    deterministically, in the reviewer's own terms, before the two roles are
    combined:

    * **a missing dependency that changes the answer is a concrete defect.**  For
      the ambiguity case the reviewer must enumerate what the answer depends on
      and, for each entry, say whether it is stated in the stem and whether its
      absence changes the answer.  An entry that is unstated **and** changes the
      answer is a defect whoever noticed it, so the case is ``FAIL`` whatever
      verdict was claimed.  An unstated entry that does not change the answer is
      recorded and ignored: reviewers list conventions a competent reader
      supplies, and failing an item for those refused more than half of the sound
      controls.
    * **``CLEAR`` must be backed by an enumeration.**  A ``PASS`` on ambiguity
      with no dependency list at all is a claim without a check, and is
      downgraded to ``UNCERTAIN``.  This is the rule that turns "the reviewers
      never noticed the removed requirement" into an abstention rather than a
      release.
    * **a ``FAIL`` with nothing behind it** -- no counterexample, no missing
      condition, no blocking dependency -- is not a defect finding.  Treating it
      as one would let a reviewer block a sound question arbitrarily.  It is
      downgraded to ``UNCERTAIN``.

    Everything else is passed through unchanged.  This never turns anything into
    a ``PASS``; it can only remove an unsupported decision and leave the item
    under review.
    """
    verdicts: dict[str, str] = {}
    reasons: list[str] = []
    for finding in findings.findings:
        verdict = finding.verdict
        if any(item.blocks_the_item for item in finding.dependencies):
            verdicts[finding.case] = "FAIL"
            reasons.append("HYBRID_UNSTATED_DEPENDENCY:" + finding.case)
            continue
        if verdict == "FAIL":
            has_counterexample = bool(
                finding.counterexample and finding.counterexample.strip()
            )
            has_missing = bool(finding.missing_conditions)
            if not (has_counterexample or has_missing):
                verdict = "UNCERTAIN"
                reasons.append("HYBRID_UNSUBSTANTIATED_FAIL:" + finding.case)
        elif verdict == "PASS" and finding.case == CASE_AMBIGUITY:
            if finding.missing_conditions:
                verdict = "UNCERTAIN"
                reasons.append("HYBRID_SELF_CONTRADICTED_PASS:" + finding.case)
            elif not finding.dependencies:
                verdict = "UNCERTAIN"
                reasons.append("HYBRID_AMBIGUITY_NOT_ENUMERATED:" + finding.case)
        verdicts[finding.case] = verdict
    return verdicts, reasons


class SpecificationEnumeration(Contract):
    """The dedicated under-specification pass's entire output.

    It deliberately has **no verdict field**.  The pass cannot report "clear" or
    "ambiguous"; it can only list what the answer depends on and, for each entry,
    say whether the stem provides it and whether its absence changes the answer.
    The server turns that list into the case verdict.  Removing the verdict is
    the point: the two general passes were being asked to judge the item and to
    model the reader in one step, and that is what never converged.
    """

    dependencies: list[JudgeDependency] = Field(min_length=1, max_length=24)

    @property
    def blocking_entries(self) -> list[JudgeDependency]:
        return [item for item in self.dependencies if item.blocks_the_item]


def ambiguity_verdict_from_enumeration(
    enumeration: SpecificationEnumeration | None,
) -> tuple[str, str]:
    """Derive the ambiguity case verdict from the enumeration alone.

    * a blocking entry (unstated *and* answer-changing, with its consequence
      stated) -> ``FAIL``.  This is a concrete defect whoever found it.
    * otherwise -> ``PASS`` only when the pass produced an enumeration at all,
      because the pass is required to output one (``min_length=1``); a missing
      pass is an abstention, never an approval.
    """
    if enumeration is None:
        return "UNCERTAIN", "HYBRID_SPECIFICATION_PASS_MISSING"
    if enumeration.blocking_entries:
        return "FAIL", "HYBRID_UNSTATED_DEPENDENCY:" + CASE_AMBIGUITY
    return "PASS", ""


def combine_case_verdicts(
    *,
    required_cases: tuple[str, ...],
    by_role: dict[str, dict[str, str]],
    specification: SpecificationEnumeration | None = None,
    human_card: Any | None = None,
    witness_verdicts: list[Any] | None = None,
    completeness: Any | None = None,
    qualification_active: bool = False,
) -> tuple[dict[str, str], list[str]]:
    """Combine both reviewer roles into one verdict per required case.

    The rule is deliberately conjunctive and never majoritarian:

    * both roles PASS -> PASS;
    * either role FAIL -> FAIL (a concrete defect is not outvoted);
    * otherwise -> UNCERTAIN.

    The ambiguity case additionally consults, in order, the dedicated
    specification pass and then a human review card.  Each of those can only ever
    *refuse* an item or abstain; neither can approve one the roles refused, and
    neither can touch the other three cases.  When both are present the stricter
    answer wins, so an abstaining specification pass cannot be upgraded to a pass
    by a card and a refusing card cannot be overridden by a passing pass.

    Returns the combined verdicts plus a list of stable refusal reasons.
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
    # The ambiguity case is governed by the dedicated specification pass and by a
    # human review card, and the two have deliberately **different** authority:
    #
    #  * the automatic specification pass may only ever refuse or abstain.  It is
    #    a safety net over the two-role rule, so a passing pass can never upgrade
    #    a case the roles refused;
    #  * a valid human card is authoritative for this one case, in both
    #    directions.  That is the whole point of the card: the measurements show
    #    the reviewers cannot make this judgement safely *or* usefully, so a
    #    person replaces them here rather than merely advising them.
    #
    # Neither source can touch the other three cases.
    if CASE_AMBIGUITY in required_cases:
        # A verdict that has been superseded must not leave its reason behind:
        # `reasons` is what decides acceptance, so a stale CASE_FAIL would silently
        # cancel the authority the card was just given.
        def _drop_ambiguity_reasons() -> None:
            reasons[:] = [
                reason
                for reason in reasons
                if CASE_AMBIGUITY not in reason
            ]

        if human_card is not None:
            from app.learning.human_review_card import card_ambiguity_verdict

            derived, reason = card_ambiguity_verdict(human_card)
            _drop_ambiguity_reasons()
            combined[CASE_AMBIGUITY] = derived
            if derived != "PASS":
                reasons.append(reason or "HYBRID_HUMAN_CARD_FAILED")
        else:
            # The evidence path.  The two general roles' own ambiguity verdicts do
            # not decide this case: nine measured runs established that they
            # over-report an absent condition on sound items, so what counts is
            # what they can substantiate.  A substantiated objection is a witness
            # the server checked; an approved item needs a positive completeness
            # certificate for a registered profile plus an active qualification.
            from app.learning.ambiguity_witness import ambiguity_gate_verdict

            blocking = (
                len(specification.blocking_entries)
                if specification is not None
                else 0
            )
            derived, extra = ambiguity_gate_verdict(
                witness_verdicts=list(witness_verdicts or []),
                blocking_enumeration_entries=blocking,
                completeness=completeness,
                qualification_active=qualification_active,
            )
            if specification is None and derived == "UNCERTAIN" and not extra:
                extra = ["HYBRID_SPECIFICATION_PASS_MISSING"]
            _drop_ambiguity_reasons()
            combined[CASE_AMBIGUITY] = derived
            reasons.extend(extra)
    return combined, list(dict.fromkeys(reasons))


def verify_references(
    findings: JudgeFindings,
    *,
    required_cases: tuple[str, ...],
    span_ids: set[str],
    span_text_by_id: dict[str, str],
    solution_step_ids: set[str],
    span_locator_by_id: dict[str, str] | None = None,
) -> ReferenceVerification:
    """Resolve a reviewer's references against the frozen server material.

    The server owns the citation:

    * an unknown span id is refused, whether or not a quotation happens to match
      something -- the reviewer is citing material it was not given;
    * a known id is resolved to the frozen text, its digest and its locator, and
      that resolution is what the receipt records;
    * a quotation, when the reviewer supplies one, must still match the frozen
      text exactly apart from line wrapping.  Matching stays case-sensitive and
      symbol-sensitive: folding case, negation or a mathematical sign would let a
      paraphrase authorize a claim the source does not make.

    An exact resolution only proves the reference is traceable; it never proves
    the inference is sound.  That judgement stays with the reviewers and with the
    deterministic gate.
    """
    cases = [finding.case for finding in findings.findings]
    case_set_exact = len(cases) == len(set(cases)) and set(cases) == set(required_cases)
    locators = span_locator_by_id or {}
    unknown_spans: list[str] = []
    unknown_steps: list[str] = []
    untraceable: list[str] = []
    resolved: dict[str, ResolvedSpan] = {}
    for finding in findings.findings:
        for reference in finding.evidence_refs:
            if reference.source_span_id not in span_ids:
                unknown_spans.append(reference.source_span_id)
                continue
            text = span_text_by_id.get(reference.source_span_id, "")
            if reference.quote is not None and (
                _collapse(reference.quote) not in _collapse(text)
            ):
                untraceable.append(reference.source_span_id)
                continue
            resolved.setdefault(
                reference.source_span_id,
                ResolvedSpan(
                    source_span_id=reference.source_span_id,
                    truncated=False,
                    text_digest=sha256(text.encode()).hexdigest(),
                    char_count=len(text),
                    locator=locators.get(reference.source_span_id)
                    or f"span:{reference.source_span_id}",
                ),
            )
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
        resolved_spans=[resolved[key] for key in sorted(resolved)],
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
    specification_prompt_version: str = "",
    specification_schema_version: str = "",
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
        "specification_prompt_version": specification_prompt_version,
        "schema_version": schema_version,
        "specification_schema_version": specification_schema_version,
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
