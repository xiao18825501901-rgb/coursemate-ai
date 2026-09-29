"""Qualification metrics and label-provenance contracts.

A qualification is the only thing that lets the hybrid gate publish, so its
arithmetic and its honesty rules are pinned here: one-sided bounds are exact,
a case is never qualified on one-sided evidence, and a zero false-accept count
is reported with its sample size instead of being called zero risk.
"""
from __future__ import annotations

import json

import pytest
from test_hybrid_review_policy import _inputs  # noqa: E402 - shared fixture builder

from app.learning.hybrid_evaluation_set import (
    NEGATIVE_LABEL,
    POSITIVE_LABEL,
    EvaluationRow,
    build_rows,
    dataset_digest,
    disagreeing_solution,
    duplicate_correct_option,
    missing_condition,
)
from app.learning.hybrid_qualification import (
    RowOutcome,
    evaluate_row,
    qualify,
    summarise,
    zero_false_accept_upper_bound,
)
from app.learning.hybrid_review import (
    ADVERSARIAL_AUDIT_ROLE,
    CASE_AGREEMENT,
    CASE_AMBIGUITY,
    EVIDENCE_AUDIT_ROLE,
    JudgeDependency,
    SpecificationEnumeration,
)


def test_zero_false_accept_bound_is_the_exact_binomial_expression() -> None:
    assert zero_false_accept_upper_bound(10) == pytest.approx(1 - 0.05 ** (1 / 10))
    assert zero_false_accept_upper_bound(20) == pytest.approx(1 - 0.05 ** (1 / 20))
    # Monotone: more independent negatives can only tighten the bound.
    assert zero_false_accept_upper_bound(50) < zero_false_accept_upper_bound(10)
    with pytest.raises(ValueError):
        zero_false_accept_upper_bound(0)


def test_mutations_change_the_revision_and_the_declared_field() -> None:
    base = _inputs(
        question_text=(
            "Compute the neighbourhood size where MinPts is three, given that "
            "the point itself is excluded."
        )
    )
    condition = missing_condition(base)
    assert condition is not None
    assert condition.question_revision != base.question_revision
    assert condition.question_text != base.question_text

    disagreement = disagreeing_solution(base)
    assert disagreement is not None
    assert disagreement.question_revision != base.question_revision
    assert disagreement.solution_b != base.solution_b


def test_a_mutation_that_cannot_apply_yields_no_row_rather_than_a_fake_defect() -> None:
    # No correct_option_index in the solution: the mutation must not produce a
    # "defect" that is not there, because that would count a control as a negative.
    base = _inputs(question_text="Explain what makes a schedule recoverable.")
    assert duplicate_correct_option(base) is None
    rows = build_rows([("family-noop", base)])
    assert {row.target_case for row in rows if row.label == NEGATIVE_LABEL} == {
        CASE_AGREEMENT
    }


def test_the_disagreement_mutation_leaves_no_agreeing_content() -> None:
    """A summary sentence alone is not a disagreement.

    If the mutated second solution still shows the original answer in its steps,
    a reviewer may legitimately report agreement, and the resulting
    "false accept" measures the mutation rather than the reviewer.  So the
    mutation must rewrite the substantive fields too.
    """
    base = _inputs(
        solution_a={"candidate_answer": {"core_point": True, "count": 3}},
        solution_b={
            "schema_version": "blind-solve-output.v1",
            "solvability": "SOLVABLE",
            "conclusion": "The point is a core point; the count is 3.",
            "steps": [
                {"ordinal": 1, "operation": "count", "result": "3"},
                {"ordinal": 2, "operation": "compare", "result": "core point"},
            ],
            "assumptions": [],
        },
    )
    mutated = disagreeing_solution(base)
    assert mutated is not None
    payload = json.dumps(mutated.solution_b, ensure_ascii=False)
    # The contradicted result is present in both the conclusion and the steps...
    assert "false" in mutated.solution_b["conclusion"]
    assert "false" in mutated.solution_b["steps"][-1]["result"]
    assert mutated.solution_b["steps"][0]["result"] == "3"
    # ...and the old agreeing verdict no longer stands as the conclusion result.
    assert mutated.solution_b["steps"][-1]["result"] != "core point"
    assert "core point" not in mutated.solution_b["conclusion"]
    assert mutated.solution_b["solvability"] == "SOLVABLE"
    assert mutated.question_revision != base.question_revision
    assert payload  # the payload is well-formed JSON


def test_the_missing_condition_mutation_removes_the_operative_givens() -> None:
    base = _inputs(
        question_text=(
            "For epsilon = 1.0 and MinPts = 3, is the point (0,0) a core point? "
            "Count the point itself as one of its own neighbours."
        )
    )
    mutated = missing_condition(base)
    assert mutated is not None
    # The numeric givens are gone, so a unique answer is no longer determined.
    assert "1.0" not in mutated.question_text
    assert "MinPts = 3" not in mutated.question_text


def test_an_inline_numeric_given_is_replaced_rather_than_left_alone() -> None:
    """A one-clause stem cannot be trimmed, so the given is removed in place.

    Without this, an item like "Compute 2 + 3." produced no ambiguity negative at
    all, which is why the ambiguity case came out unmeasured rather than
    measured-and-clean.
    """
    base = _inputs(question_text="Compute 2 + 3 as base-ten integers.")
    mutated = missing_condition(base)
    assert mutated is not None
    assert "2" not in mutated.question_text.replace("unspecified", "")
    assert "unspecified" in mutated.question_text
    assert mutated.question_revision != base.question_revision


def test_a_prose_answer_disagreement_is_stated_not_hedged() -> None:
    """The authored corpus answers in prose, so the mutation must reject, not wrap.

    Wrapping the original text ("a different result from <the same words>") reads
    like the same answer, and a reviewer that then reports agreement is right.
    """
    base = _inputs(
        solution_a={"candidate_answer": "The proposed statement violates the rule."},
        solution_b={
            "schema_version": "blind-solve-output.v1",
            "solvability": "SOLVABLE",
            "conclusion": "The proposed statement violates the rule.",
            "steps": [
                {"ordinal": 1, "operation": "apply the rule", "result": "violates"}
            ],
            "assumptions": [],
        },
    )
    mutated = disagreeing_solution(base)
    assert mutated is not None
    conclusion = mutated.solution_b["conclusion"]
    assert "opposite" in conclusion
    assert "reject" in conclusion.lower()
    assert mutated.solution_b["steps"][-1]["result"] != "violates"


def test_the_constraint_clause_mutation_removes_a_stated_requirement() -> None:
    """Prose items state their requirement in words, not digits.

    The diagnosis of the authored corpus showed every NUMERIC item had zero
    digits in its stem, so the digit-based mutation could fire on 2 of 23 items.
    """
    base = _inputs(
        question_text=(
            "A schedule is recoverable when every transaction that reads a value "
            "written by an uncommitted transaction commits only after that writer "
            "commits. Decide whether the supplied schedule is recoverable."
        )
    )
    mutated = missing_condition(base)
    assert mutated is not None
    assert "only after" not in mutated.question_text
    assert "recoverable" in mutated.question_text
    assert len(mutated.question_text) >= 40


def test_a_stem_with_no_given_at_all_still_yields_no_negative() -> None:
    base = _inputs(question_text="Explain what makes a schedule recoverable.")
    assert missing_condition(base) is None


def test_a_prose_stem_with_no_removable_given_yields_no_ambiguity_negative() -> None:
    """Deleting scene-setting prose does not make an item under-specified.

    If it did, a reviewer that still answered CLEAR would be right while the row
    was scored as a missed defect -- the same measurement error that made the
    first disagreement mutation look like a reviewer flaw.  This stem states no
    requirement and carries no given, so nothing can be removed from it.
    """
    prose = (
        "The lecture introduced the idea of a recoverable schedule and contrasted "
        "it with several other schedule classes. Discuss what the term means and "
        "why the distinction matters in practice."
    )
    base = _inputs(question_text=prose)
    assert missing_condition(base) is None
    rows = build_rows([("family-prose", base)])
    assert CASE_AMBIGUITY not in {
        row.target_case for row in rows if row.label == NEGATIVE_LABEL
    }


def test_an_explicit_condition_marker_still_produces_a_negative() -> None:
    base = _inputs(
        question_text=(
            "Decide whether the schedule is conflict-serializable, assuming that "
            "the transaction order listed is the only one considered."
        )
    )
    mutated = missing_condition(base)
    assert mutated is not None
    assert "assuming" not in mutated.question_text


def test_a_stem_without_a_removable_condition_yields_no_ambiguity_negative() -> None:
    base = _inputs(question_text="State the value.")
    assert missing_condition(base) is None
    rows = build_rows([("family-short", base)])
    assert CASE_AMBIGUITY not in {
        row.target_case for row in rows if row.label == NEGATIVE_LABEL
    }


def test_the_evaluation_set_has_one_control_and_one_negative_per_case() -> None:
    base_inputs = _inputs(
        question_text=(
            "Compute the neighbourhood size where MinPts is three, given that "
            "the point itself is excluded."
        ),
        required_cases=(CASE_AMBIGUITY, CASE_AGREEMENT),
    )
    rows = build_rows([("family-1", base_inputs)])
    labels = [row.label for row in rows]
    assert labels.count(POSITIVE_LABEL) == 1
    assert labels.count(NEGATIVE_LABEL) == 2
    targets = {row.target_case for row in rows if row.label == NEGATIVE_LABEL}
    assert targets == {CASE_AMBIGUITY, CASE_AGREEMENT}
    assert all(row.provenance for row in rows)
    assert dataset_digest(rows) == dataset_digest(build_rows([("family-1", base_inputs)]))


def _outcome(
    *,
    label: str,
    family: str,
    verdicts: dict[str, str],
    language: str = "en",
    domain: str = "OFFICIAL",
    target_case: str | None = None,
) -> RowOutcome:
    return RowOutcome(
        row_id=f"{family}:{label}",
        family_id=family,
        label=label,
        language=language,
        domain=domain,
        question_type="NUMERIC",
        released=False,
        case_outcomes=dict(verdicts),
        target_case=target_case,
        defect=None,
        provenance="test fixture",
    )


def test_a_zero_false_accept_run_reports_its_sample_size() -> None:
    outcomes = []
    for index in range(12):
        family = f"family-{index}"
        outcomes.append(
            _outcome(
                label=NEGATIVE_LABEL,
                family=family,
                verdicts={CASE_AMBIGUITY: "FAIL", CASE_AGREEMENT: "FAIL"},
            )
        )
    summary = summarise(outcomes)
    assert summary["overall"]["false_accept"] == 0
    assert summary["negative_rows"] == 12
    assert summary["independent_negative_families"] == 12
    assert summary["zero_false_accept_upper_bound_95"] == pytest.approx(
        1 - 0.05 ** (1 / 12)
    )
    # Not "zero risk": the bound is reported, not hidden.
    assert summary["zero_false_accept_upper_bound_95"] > 0.2


def test_a_case_without_negatives_is_not_qualified() -> None:
    outcomes = [
        _outcome(
            label=POSITIVE_LABEL,
            family=f"p-{index}",
            verdicts={CASE_AMBIGUITY: "PASS", CASE_AGREEMENT: "PASS"},
        )
        for index in range(6)
    ]
    decision = qualify(
        outcomes,
        method_identity="a" * 64,
        observed_model_facts={},
        min_positives_per_case=3,
        min_negatives_per_case=3,
        min_independent_negatives=0,
        min_release_recall=0.0,
    )
    assert decision["status"] == "DRAFT"
    assert decision["cases"] == []
    assert CASE_AMBIGUITY in decision["unmeasured_cases"]


def test_zero_false_accepts_by_refusing_everything_is_not_a_qualification() -> None:
    """An everything-blocked procedure is not a safe procedure.

    The first enumeration-based run reached zero false accepts out of 41
    negatives while refusing 13 of 24 sound controls.  Without a coverage floor
    that would have qualified a method that publishes almost nothing, which is
    the "all blocked, therefore zero risk" baseline the policy forbids.
    """
    outcomes = [
        _outcome(
            label=NEGATIVE_LABEL,
            family=f"n{index}",
            target_case=CASE_AMBIGUITY,
            verdicts={CASE_AMBIGUITY: "FAIL"},
        )
        for index in range(20)
    ]
    outcomes.extend(
        _outcome(
            label=POSITIVE_LABEL,
            family=f"p{index}",
            verdicts={CASE_AMBIGUITY: "FAIL"},
        )
        for index in range(20)
    )
    refused = qualify(
        outcomes,
        method_identity="a" * 64,
        observed_model_facts={},
        min_positives_per_case=8,
        min_negatives_per_case=8,
        min_independent_negatives=16,
        min_release_recall=0.5,
    )
    assert refused["summary"]["release"]["false_accept"] == 0
    assert refused["release_recall"] == 0.0
    assert refused["coverage_sufficient"] is False
    assert refused["status"] == "DRAFT"
    assert refused["cases"] == []


def test_a_safe_and_usable_procedure_qualifies() -> None:
    outcomes = [
        _outcome(
            label=NEGATIVE_LABEL,
            family=f"n{index}",
            target_case=CASE_AMBIGUITY,
            verdicts={CASE_AMBIGUITY: "FAIL"},
        )
        for index in range(20)
    ]
    outcomes.extend(
        _outcome(
            label=POSITIVE_LABEL,
            family=f"p{index}",
            verdicts={CASE_AMBIGUITY: "PASS"},
        )
        for index in range(20)
    )
    for outcome in outcomes:
        outcome.released = all(
            verdict == "PASS" for verdict in outcome.case_outcomes.values()
        )
    accepted = qualify(
        outcomes,
        method_identity="a" * 64,
        observed_model_facts={},
        min_positives_per_case=8,
        min_negatives_per_case=8,
        min_independent_negatives=16,
        min_release_recall=0.5,
    )
    assert accepted["release_recall"] == 1.0
    assert accepted["status"] == "SCOPED_QUALITY_ACCEPTED"
    assert accepted["cases"] == [CASE_AMBIGUITY]


def test_a_thin_but_clean_sample_cannot_qualify_a_method() -> None:
    """A small clean run is not evidence of a clean procedure.

    This round is the evidence: 18 negatives recorded a pass, and the same
    runner with 40 negatives recorded three false accepts.  The global floor is
    what stops a thin sample from granting a durable permission.
    """
    outcomes = [
        _outcome(
            label=NEGATIVE_LABEL,
            family=f"n{index}",
            target_case=CASE_AMBIGUITY,
            verdicts={CASE_AMBIGUITY: "FAIL"},
        )
        for index in range(4)
    ]
    outcomes.extend(
        _outcome(
            label=POSITIVE_LABEL,
            family=f"p{index}",
            verdicts={CASE_AMBIGUITY: "PASS"},
        )
        for index in range(4)
    )
    strict = qualify(
        outcomes,
        method_identity="a" * 64,
        observed_model_facts={},
        min_positives_per_case=3,
        min_negatives_per_case=3,
        min_independent_negatives=16,
        min_release_recall=0.0,
    )
    assert strict["sample_sufficient"] is False
    assert strict["status"] == "DRAFT"
    assert strict["cases"] == []
    # The same measurements would have qualified without the global floor, which
    # is exactly the failure this guard exists to prevent.
    lax = qualify(
        outcomes,
        method_identity="a" * 64,
        observed_model_facts={},
        min_positives_per_case=3,
        min_negatives_per_case=3,
        min_independent_negatives=0,
        min_release_recall=0.0,
    )
    assert lax["status"] == "SCOPED_QUALITY_ACCEPTED"


def test_release_metrics_separate_false_accept_from_false_reject() -> None:
    outcomes = [
        # Two positives: one released, one wrongly refused.
        _outcome(
            label=POSITIVE_LABEL,
            family="p1",
            verdicts={CASE_AMBIGUITY: "PASS", CASE_AGREEMENT: "PASS"},
        ),
        _outcome(
            label=POSITIVE_LABEL,
            family="p2",
            verdicts={CASE_AMBIGUITY: "FAIL", CASE_AGREEMENT: "PASS"},
        ),
        # Three negatives, each targeting the ambiguity case: two refused, one
        # wrongly released.  The agreement verdict on these rows is evidence
        # about a case their defect does not touch, so it is not tallied.
        *[
            _outcome(
                label=NEGATIVE_LABEL,
                family=f"n{index}",
                target_case=CASE_AMBIGUITY,
                verdicts=(
                    {CASE_AMBIGUITY: "PASS", CASE_AGREEMENT: "FAIL"}
                    if index == 0
                    else {CASE_AMBIGUITY: "FAIL", CASE_AGREEMENT: "FAIL"}
                ),
            )
            for index in range(3)
        ],
    ]
    overall = summarise(outcomes)["overall"]
    assert overall["false_accept"] == 1
    assert overall["true_reject"] == 2
    assert overall["true_accept"] == 3
    assert overall["false_reject"] == 1
    assert overall["false_accept_rate"] == pytest.approx(1 / 3)
    assert overall["release_recall"] == pytest.approx(3 / 4)


def test_row_level_release_metrics_measure_the_actual_publication_rule() -> None:
    """A row is released only when every required case passes in both roles."""
    outcomes = [
        # Positive, all cases PASS -> released.
        _outcome(
            label=POSITIVE_LABEL,
            family="p1",
            verdicts={CASE_AMBIGUITY: "PASS", CASE_AGREEMENT: "PASS"},
        ),
        # Positive with one failing case -> not released (false reject).
        _outcome(
            label=POSITIVE_LABEL,
            family="p2",
            verdicts={CASE_AMBIGUITY: "FAIL", CASE_AGREEMENT: "PASS"},
        ),
        # Negative with one passing case -> correctly not released.
        _outcome(
            label=NEGATIVE_LABEL,
            family="n1",
            verdicts={CASE_AMBIGUITY: "PASS", CASE_AGREEMENT: "FAIL"},
        ),
        # Negative where both cases were waved through -> a true false accept.
        _outcome(
            label=NEGATIVE_LABEL,
            family="n2",
            verdicts={CASE_AMBIGUITY: "PASS", CASE_AGREEMENT: "PASS"},
        ),
    ]
    for outcome in outcomes:
        outcome.released = all(v == "PASS" for v in outcome.case_outcomes.values())
    release = summarise(outcomes)["release"]
    assert release["positive_rows"] == 2
    assert release["negative_rows"] == 2
    assert release["true_accept"] == 1
    assert release["false_reject"] == 1
    assert release["false_accept"] == 1
    assert release["true_reject"] == 1
    assert release["release_precision"] == pytest.approx(1 / 2)
    assert release["false_release_rate"] == pytest.approx(1 / 2)


def test_uncertain_is_counted_as_abstention_not_as_a_decision() -> None:
    outcomes = [
        _outcome(
            label=NEGATIVE_LABEL,
            family="n1",
            target_case=CASE_AMBIGUITY,
            verdicts={CASE_AMBIGUITY: "UNCERTAIN", CASE_AGREEMENT: "FAIL"},
        ),
        _outcome(
            label=POSITIVE_LABEL,
            family="p1",
            verdicts={CASE_AMBIGUITY: "UNCERTAIN", CASE_AGREEMENT: "PASS"},
        ),
    ]
    overall = summarise(outcomes)["overall"]
    assert overall["negative_abstain"] == 1
    assert overall["positive_abstain"] == 1
    assert overall["false_accept"] == 0
    assert overall["false_reject"] == 0
    # Three attributed decisions (one negative case, two positive cases); two
    # of them abstained, so coverage is one third.
    assert overall["coverage"] == pytest.approx(1 / 3)


def test_per_case_metrics_are_attributed_to_the_case_the_defect_targets() -> None:
    """A negative row is evidence about one case, not about every case it reports.

    An under-specified stem does not make the two solutions disagree, so a `PASS`
    on `answer_agreement` for that row is the correct answer, not a false accept.
    Counting it would inflate the agreement case with another case's rows.
    """
    rows = [
        # Targets ambiguity only; agreement is correctly PASS.
        _outcome(
            label=NEGATIVE_LABEL,
            family="n1",
            verdicts={CASE_AMBIGUITY: "FAIL", CASE_AGREEMENT: "PASS"},
        ),
        # Targets agreement only; ambiguity is correctly PASS.
        _outcome(
            label=NEGATIVE_LABEL,
            family="n2",
            verdicts={CASE_AMBIGUITY: "PASS", CASE_AGREEMENT: "FAIL"},
        ),
    ]
    rows[0].target_case = CASE_AMBIGUITY
    rows[1].target_case = CASE_AGREEMENT
    summary = summarise(rows)
    by_case = {}
    for key, tally in summary["scopes"].items():
        case = key.split("|", 1)[0]
        by_case[case] = tally
    assert by_case[CASE_AMBIGUITY]["negatives"] == 1
    assert by_case[CASE_AMBIGUITY]["false_accept"] == 0
    assert by_case[CASE_AMBIGUITY]["true_reject"] == 1
    assert by_case[CASE_AGREEMENT]["negatives"] == 1
    assert by_case[CASE_AGREEMENT]["false_accept"] == 0
    assert by_case[CASE_AGREEMENT]["true_reject"] == 1
    # The row-level rule still requires the whole row to be refused.
    assert summary["release"]["false_accept"] == 0


def test_a_missed_target_case_is_the_one_that_shows_up_as_a_false_accept() -> None:
    row = _outcome(
        label=NEGATIVE_LABEL,
        family="n1",
        verdicts={CASE_AMBIGUITY: "PASS", CASE_AGREEMENT: "PASS"},
    )
    row.target_case = CASE_AMBIGUITY
    row.released = True
    summary = summarise([row])
    ambiguity = next(
        tally for key, tally in summary["scopes"].items() if key.startswith(CASE_AMBIGUITY)
    )
    assert ambiguity["false_accept"] == 1
    # The agreement case has no attributed rows at all for this row.
    assert not [
        tally for key, tally in summary["scopes"].items() if key.startswith(CASE_AGREEMENT)
    ]


def test_the_zero_false_accept_bound_is_withheld_when_a_false_accept_occurred() -> None:
    row = _outcome(
        label=NEGATIVE_LABEL,
        family="n1",
        verdicts={CASE_AMBIGUITY: "PASS"},
    )
    row.target_case = CASE_AMBIGUITY
    row.released = True
    summary = summarise([row])
    assert summary["release"]["false_accept"] == 1
    assert summary["zero_false_accept_upper_bound_95"] is None
    assert summary["zero_false_accept_bound_applicable"] is False


def test_a_clean_run_still_reports_its_bound_and_sample_size() -> None:
    rows = []
    for index in range(7):
        row = _outcome(
            label=NEGATIVE_LABEL,
            family=f"n{index}",
            verdicts={CASE_AMBIGUITY: "FAIL"},
        )
        row.target_case = CASE_AMBIGUITY
        rows.append(row)
    summary = summarise(rows)
    assert summary["zero_false_accept_bound_applicable"] is True
    assert summary["zero_false_accept_upper_bound_95"] == pytest.approx(
        1 - 0.05 ** (1 / 7)
    )


def test_evaluate_row_requires_the_conjunction_of_both_roles() -> None:
    from app.learning.deepseek_reviewer import ReferenceVerification

    row = EvaluationRow(
        row_id="r1",
        inputs=_inputs(required_cases=(CASE_AMBIGUITY,)),
        label=POSITIVE_LABEL,
        provenance="fixture",
        target_case=None,
        defect=None,
        family_id="f1",
    )

    class _Outcome:
        def __init__(self, role: str, verdict: str) -> None:
            self.role = role
            self._verdict = verdict

        def case_verdicts(self) -> dict[str, str]:
            return {CASE_AMBIGUITY: self._verdict}

        def substantiation_reasons(self) -> list[str]:
            return []

        @property
        def verification(self) -> ReferenceVerification:
            return ReferenceVerification(
                case_set_exact=True, quotes_traceable=True, steps_exist=True
            )

    class _Specification:
        enumeration = SpecificationEnumeration(
            dependencies=[
                JudgeDependency(
                    datum="the values stated in the stem", stated_in_stem=True
                )
            ]
        )

    # The ambiguity case is evidence-decided now: a bare FAIL without a witness is
    # not a defect and not an approval either, so it withholds release rather than
    # failing on an impression the measured frontier could not substantiate.
    first = _Outcome(EVIDENCE_AUDIT_ROLE, "PASS")
    second = _Outcome(ADVERSARIAL_AUDIT_ROLE, "FAIL")
    outcome = evaluate_row(  # type: ignore[arg-type]
        row, first=first, second=second, specification=_Specification()
    )
    assert outcome.released is False
    assert outcome.case_outcomes[CASE_AMBIGUITY] == "UNCERTAIN"

    # Two favourable verdicts are no longer sufficient to release an item: the
    # ambiguity case additionally needs the server's completeness certificate for
    # a registered profile and an active qualification.  This is the change the
    # measured frontier forced, and the harness now reports it instead of
    # attributing a release to the reviewer chain alone.
    both_pass = evaluate_row(  # type: ignore[arg-type]
        row,
        first=_Outcome(EVIDENCE_AUDIT_ROLE, "PASS"),
        second=_Outcome(ADVERSARIAL_AUDIT_ROLE, "PASS"),
        specification=_Specification(),
    )
    assert both_pass.released is False
    assert both_pass.reasons == [
        "HYBRID_COMPLETENESS_CERTIFICATE_MISSING",
        "HYBRID_QUALIFICATION_MISSING",
    ]
    assert both_pass.case_outcomes[CASE_AMBIGUITY] == "UNCERTAIN"


def test_an_unverifiable_reference_makes_a_row_unreleasable() -> None:
    from app.learning.deepseek_reviewer import ReferenceVerification

    row = EvaluationRow(
        row_id="r2",
        inputs=_inputs(required_cases=(CASE_AMBIGUITY,)),
        label=POSITIVE_LABEL,
        provenance="fixture",
        target_case=None,
        defect=None,
        family_id="f1",
    )

    class _Outcome:
        def __init__(self, role: str) -> None:
            self.role = role

        def case_verdicts(self) -> dict[str, str]:
            return {CASE_AMBIGUITY: "PASS"}

        def substantiation_reasons(self) -> list[str]:
            return []

        @property
        def verification(self) -> ReferenceVerification:
            return ReferenceVerification(
                case_set_exact=True,
                quotes_traceable=False,
                steps_exist=True,
                untraceable_quotes=["ev-1"],
            )

    outcome = evaluate_row(  # type: ignore[arg-type]
        row,
        first=_Outcome(EVIDENCE_AUDIT_ROLE),
        second=_Outcome(ADVERSARIAL_AUDIT_ROLE),
    )
    assert outcome.released is False
    assert any(
        reason.startswith("HYBRID_REVIEW_REFERENCES_UNVERIFIED")
        for reason in outcome.reasons
    )
