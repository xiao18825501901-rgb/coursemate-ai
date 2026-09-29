"""Constructive ambiguity: a counterexample, or an honest abstention.

The published review rule asks a reviewer to say whether an item is
under-specified.  Nine measured runs and five rule iterations later the answer was
still not separable: the reviewer over-reports a missing condition on sound items,
and detection and coverage move together, so no point on the frontier was both
safe and usable.  The failing judgement was never "is this item vague" -- it was
"would a different but admissible reading change the grade".

That second question has a shape a server can check.  A material objection is now
a *witness*: two readings, why each fits every public condition, the answer each
produces, and the difference between them under the declared equivalence.  The
server then does the three things a reviewer cannot do for itself:

* it refuses a witness that breaks the stated conditions -- adding data the item
  does not supply, changing the declared dialect, or imagining a different world;
* it refuses a witness whose two answers are equal *under the declared
  equivalence*, which is precisely the "different method, same result" case that
  must not block a sound item;
* where a registered profile can execute the difference, it executes it.

And the asymmetry that mattered most is kept: **not finding a witness is not a
pass.**  A confirmed witness is a defect; an unverified objection stays an
objection; approval requires positive completeness evidence from a registered
profile together with an active qualification.  Nothing here converts "nobody
proved it is ambiguous" into "it is clear".
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import Field, StringConstraints, model_validator

from app.learning.models import Contract, Identifier
from app.learning.sql_oracle import (
    OracleLimits,
    OracleResult,
    compare_results,
    run_statement,
)
from app.learning.task_spec import CompletenessEvidence, Equivalence

WITNESS_VERSION: Final = "ambiguity-witness.v1"

WitnessStatus = Literal[
    "CONFIRMED_MATERIAL",
    "REFUSED_INADMISSIBLE",
    "REFUSED_NOT_MATERIAL",
    "UNVERIFIABLE",
]
WitnessCheckedBy = Literal["PROFILE_CHECKER", "STRUCTURAL_RULES", "NONE"]

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)]


class Interpretation(Contract):
    """One reading of the item, and what it would score."""

    label: Literal["A", "B"]
    statement: ShortText
    admissible_because: ShortText
    answer: ShortText
    scored_conclusion: ShortText
    # Optional executable form.  A profile checker may run it; when it is absent
    # the witness can still be refused structurally, but it can never be
    # confirmed by execution.
    executable_statement: str | None = Field(default=None, max_length=8000)

    def scored_tokens(self) -> tuple[str, ...]:
        return tuple(sorted(self.scored_conclusion.split()))


class AmbiguityWitnessClaim(Contract):
    """What a reviewer must produce instead of the word "ambiguous"."""

    schema_version: Literal["ambiguity-witness.v1"] = WITNESS_VERSION
    problem_field_or_span: ShortText
    interpretations: list[Interpretation] = Field(min_length=2, max_length=2)
    material_difference: ShortText
    minimal_disambiguation: ShortText
    supporting_span_ids: list[Identifier] = Field(default_factory=list, max_length=16)
    # Declared, never inferred: a reading that needs data the item does not give
    # is not an alternative reading of *this* item.
    introduces_new_data: bool = False
    changes_stated_condition: bool = False

    @model_validator(mode="after")
    def the_two_labels_are_distinct(self) -> AmbiguityWitnessClaim:
        if {item.label for item in self.interpretations} != {"A", "B"}:
            raise ValueError("a witness states exactly one reading A and one reading B")
        return self


class WitnessVerdict(Contract):
    status: WitnessStatus
    checked_by: WitnessCheckedBy
    executed: bool = False
    reason: ShortText

    @property
    def blocks(self) -> bool:
        """A confirmed material defect blocks; an unverified objection holds."""
        return self.status in {"CONFIRMED_MATERIAL", "UNVERIFIABLE"}

    @property
    def unresolved(self) -> bool:
        return self.status == "UNVERIFIABLE"


def _structural_verdicts(
    claim: AmbiguityWitnessClaim,
    *,
    declared_equivalence: Equivalence,
    span_ids: set[str],
) -> WitnessVerdict | None:
    """The refusals that need no execution.  None means "not decided here"."""
    if claim.introduces_new_data:
        return WitnessVerdict(
            status="REFUSED_INADMISSIBLE",
            checked_by="STRUCTURAL_RULES",
            reason=(
                "the reading needs data the item does not supply, so it is a "
                "different exercise rather than another reading of this one"
            ),
        )
    if claim.changes_stated_condition:
        return WitnessVerdict(
            status="REFUSED_INADMISSIBLE",
            checked_by="STRUCTURAL_RULES",
            reason="the reading contradicts a condition the item states",
        )
    unknown = sorted(set(claim.supporting_span_ids) - span_ids)
    if unknown:
        return WitnessVerdict(
            status="REFUSED_INADMISSIBLE",
            checked_by="STRUCTURAL_RULES",
            reason=f"the witness cites spans the item was not given: {unknown}",
        )
    left, right = claim.interpretations
    if declared_equivalence != "SEMANTIC_RUBRIC":
        if left.scored_conclusion.strip() == right.scored_conclusion.strip():
            return WitnessVerdict(
                status="REFUSED_NOT_MATERIAL",
                checked_by="STRUCTURAL_RULES",
                reason="both readings produce the same scored conclusion",
            )
        if declared_equivalence in {"SET_UNORDERED", "BAG_UNORDERED"} and (
            left.scored_tokens() == right.scored_tokens()
        ):
            return WitnessVerdict(
                status="REFUSED_NOT_MATERIAL",
                checked_by="STRUCTURAL_RULES",
                reason=(
                    "the two readings differ only in the order of an unordered "
                    "result, which the declared equivalence accepts"
                ),
            )
    return None


class SqlWitnessChecker:
    """Execute a witness against the frozen instance the item declares.

    It answers exactly one question: do the two readings produce different results
    on the rows the item itself gives.  That is a bounded claim about one instance.
    It is not, and is never reported as, a proof of general query equivalence.
    """

    def __init__(self, *, schema: str, data: str, limits: OracleLimits | None = None) -> None:
        self.schema = schema
        self.data = data
        self.limits = limits or OracleLimits()

    def _run(self, statement: str) -> OracleResult:
        return run_statement(
            statement=statement,
            schema=self.schema,
            data=self.data,
            limits=self.limits,
        )

    def check(
        self,
        claim: AmbiguityWitnessClaim,
        *,
        declared_equivalence: Equivalence,
        span_ids: set[str],
        comparison: Literal["ORDERED", "BAG", "SET"] = "SET",
    ) -> WitnessVerdict:
        structural = _structural_verdicts(
            claim, declared_equivalence=declared_equivalence, span_ids=span_ids
        )
        if structural is not None:
            return structural
        statements = [item.executable_statement for item in claim.interpretations]
        if any(statement is None for statement in statements):
            return WitnessVerdict(
                status="UNVERIFIABLE",
                checked_by="NONE",
                reason=(
                    "the witness declares a difference but supplies no executable "
                    "form, so the server cannot check it against the given rows"
                ),
            )
        outcomes = [self._run(str(statement)) for statement in statements]
        if any(not outcome.ok for outcome in outcomes):
            return WitnessVerdict(
                status="UNVERIFIABLE",
                checked_by="NONE",
                reason=(
                    "at least one reading could not be executed on the given rows: "
                    + "; ".join(str(outcome.reason) for outcome in outcomes if not outcome.ok)
                ),
            )
        same, detail = compare_results(outcomes[0], outcomes[1], comparison=comparison)
        if same:
            return WitnessVerdict(
                status="REFUSED_NOT_MATERIAL",
                checked_by="PROFILE_CHECKER",
                executed=True,
                reason=(
                    "the two readings produce the same result on the rows the item "
                    f"gives, under the declared {comparison} comparison ({detail})"
                ),
            )
        return WitnessVerdict(
            status="CONFIRMED_MATERIAL",
            checked_by="PROFILE_CHECKER",
            executed=True,
            reason=(
                "the two admissible readings produce different results on the rows "
                f"the item itself gives ({detail})"
            ),
        )


def structural_check(
    claim: AmbiguityWitnessClaim,
    *,
    declared_equivalence: Equivalence,
    span_ids: set[str],
) -> WitnessVerdict:
    """The no-execution path: refuse what is refutable, abstain otherwise."""
    structural = _structural_verdicts(
        claim, declared_equivalence=declared_equivalence, span_ids=span_ids
    )
    if structural is not None:
        return structural
    return WitnessVerdict(
        status="UNVERIFIABLE",
        checked_by="NONE",
        reason=(
            "the witness is not refuted by the stated conditions, but no registered "
            "checker has verified the difference, so the objection stays open"
        ),
    )


def ambiguity_gate_verdict(
    *,
    witness_verdicts: list[WitnessVerdict],
    blocking_enumeration_entries: int = 0,
    completeness: CompletenessEvidence | None = None,
    qualification_active: bool = False,
) -> tuple[str, list[str]]:
    """Derive the ambiguity case verdict from evidence, never from a bare opinion.

    The order matters and is deliberately conservative:

    1. a confirmed material witness is a defect, whatever else is true;
    2. an unresolved witness is an open objection -- it cannot pass, but it also
       is not converted into a failure the server cannot substantiate;
    3. a blocking enumeration entry is a concrete missing dependency;
    4. a pass requires positive completeness evidence for a registered profile
       **and** an active qualification for this scope.  Without both, the answer
       is UNCERTAIN, which is the honest reading of "nobody has shown this is
       answerable" and never a silent approval.
    """
    reasons: list[str] = []
    if any(verdict.status == "CONFIRMED_MATERIAL" for verdict in witness_verdicts):
        return "FAIL", ["HYBRID_WITNESS_CONFIRMED_MATERIAL"]
    if any(verdict.unresolved for verdict in witness_verdicts):
        return "UNCERTAIN", ["HYBRID_WITNESS_UNVERIFIED"]
    if blocking_enumeration_entries:
        return "FAIL", ["HYBRID_UNSTATED_DEPENDENCY:question.ambiguity.v1"]
    if completeness is None or not completeness.certifies:
        reasons.append("HYBRID_COMPLETENESS_CERTIFICATE_MISSING")
    if not qualification_active:
        reasons.append("HYBRID_QUALIFICATION_MISSING")
    if reasons:
        return "UNCERTAIN", reasons
    return "PASS", []
