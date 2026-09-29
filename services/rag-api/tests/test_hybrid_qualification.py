"""Qualification metrics and label-provenance contracts.

A qualification is the only thing that lets the hybrid gate publish, so its
arithmetic and its honesty rules are pinned here: one-sided bounds are exact,
a case is never qualified on one-sided evidence, and a zero false-accept count
is reported with its sample size instead of being called zero risk.
"""
from __future__ import annotations

import math

import pytest

from app.learning.hybrid_evaluation_set import (
    NEGATIVE_LABEL,
    POSITIVE_LABEL,
    EvaluationRow,
    build_rows,
    dataset_digest,
    duplicate_correct_option,
    disagreeing_solution,
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
    CASE_DISTRACTORS,
    CASE_RULE,
    EVIDENCE_AUDIT_ROLE,
)

from test_hybrid_review_policy import _inputs  # noqa: E402 - shared fixture builder


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
    base = _inputs()
    assert duplicate_correct_option(base) is None
    rows = build_rows([("family-noop", base)])
    assert {row.target_case for row in rows if row.label == NEGATIVE_LABEL} == {
        CASE_AGREEMENT
    }


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
        target_case=None,
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
    )
    assert decision["status"] == "DRAFT"
    assert decision["cases"] == []
    assert CASE_AMBIGUITY in decision["unmeasured_cases"]


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
        # Three negatives: two refused, one wrongly released.
        *[
            _outcome(
                label=NEGATIVE_LABEL,
                family=f"n{index}",
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
    assert overall["true_reject"] == 5
    assert overall["true_accept"] == 3
    assert overall["false_reject"] == 1
    assert overall["false_accept_rate"] == pytest.approx(1 / 6)
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
    # Two of the four (row, case) decisions abstained.
    assert overall["coverage"] == pytest.approx(0.5)


def test_evaluate_row_requires_the_conjunction_of_both_roles() -> None:
    from app.learning.deepseek_reviewer import ReferenceVerification
    from app.learning.hybrid_review import JudgeFinding, JudgeFindings

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

        @property
        def verification(self) -> ReferenceVerification:
            return ReferenceVerification(
                case_set_exact=True, quotes_traceable=True, steps_exist=True
            )

    first = _Outcome(EVIDENCE_AUDIT_ROLE, "PASS")
    second = _Outcome(ADVERSARIAL_AUDIT_ROLE, "FAIL")
    outcome = evaluate_row(row, first=first, second=second)  # type: ignore[arg-type]
    assert outcome.released is False
    assert outcome.case_outcomes[CASE_AMBIGUITY] == "FAIL"

    both_pass = evaluate_row(  # type: ignore[arg-type]
        row,
        first=_Outcome(EVIDENCE_AUDIT_ROLE, "PASS"),
        second=_Outcome(ADVERSARIAL_AUDIT_ROLE, "PASS"),
    )
    assert both_pass.released is True


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
