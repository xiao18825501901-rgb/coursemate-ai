"""The deterministic half of `question.answer_agreement.v1`.

The 2026-09-30 qualification run recorded four injected `DISAGREEING_SOLUTION`
rows that both reviewer roles accepted.  Every one of them was a pair whose
answer the server could have compared itself, so these tests pin the two halves
of that repair: the comparison refuses on a conflict, and the mutation actually
puts the conflict in the channel the answer is stored in.

The asymmetry is the point.  A deterministic checker that can only take a PASS
away is a safety net; one that can also grant a PASS is a second reviewer with
no evidence, and it would be able to manufacture a false accept on its own.
"""
from __future__ import annotations

import json
from decimal import Decimal

from test_hybrid_review_policy import _inputs  # noqa: E402 - shared fixture builder

from app.learning.answer_agreement import (
    CHANNEL_NUMBER,
    CHANNEL_OPTION_INDEX,
    VERDICT_AGREE,
    VERDICT_DISAGREE,
    VERDICT_UNREADABLE,
    compare_answers,
    read_number,
)
from app.learning import hybrid_review
from app.learning.hybrid_evaluation_set import disagreeing_solution
from app.learning.hybrid_review import (
    ADVERSARIAL_AUDIT_ROLE,
    CASE_AGREEMENT,
    COMBINATION_VERSION,
    EVIDENCE_AUDIT_ROLE,
    combine_case_verdicts,
    method_identity,
)

ROLES = (EVIDENCE_AUDIT_ROLE, ADVERSARIAL_AUDIT_ROLE)


# --------------------------------------------------------------- the comparison


def test_a_conflicting_option_index_is_a_disagreement() -> None:
    check = compare_answers({"correct_option_index": 1}, {"correct_option_index": 2})
    assert check.verdict == VERDICT_DISAGREE
    assert check.channel == CHANNEL_OPTION_INDEX
    assert check.disagrees
    assert "option 1" in check.detail and "option 2" in check.detail


def test_the_same_option_index_is_left_to_the_roles() -> None:
    check = compare_answers({"correct_option_index": 3}, {"correct_option_index": 3})
    assert check.verdict == VERDICT_AGREE
    # `AGREE` is deliberately not a grant: it is the absence of a deterministic
    # refusal, and only the two roles can pass the case.
    assert not check.disagrees


def test_a_boolean_is_never_read_as_an_option_index() -> None:
    # `True == 1` would otherwise compare equal to option 1 and invent agreement.
    check = compare_answers({"correct_option_index": True}, {"correct_option_index": 1})
    assert check.verdict == VERDICT_UNREADABLE


def test_conflicting_declared_numbers_are_a_disagreement() -> None:
    check = compare_answers({"candidate_answer": "42"}, {"answer": "43"})
    assert check.verdict == VERDICT_DISAGREE
    assert check.channel == CHANNEL_NUMBER


def test_equal_numbers_written_differently_are_not_a_disagreement() -> None:
    check = compare_answers({"candidate_answer": "1,250"}, {"answer": "1250.0"})
    assert check.verdict == VERDICT_AGREE


def test_prose_answers_take_no_position() -> None:
    """Normalising prose would eventually call two different answers equal."""
    check = compare_answers(
        {"candidate_answer": "about 42"}, {"answer": "roughly forty-three"}
    )
    assert check.verdict == VERDICT_UNREADABLE
    assert not check.disagrees


def test_one_unreadable_side_takes_no_position() -> None:
    check = compare_answers({"candidate_answer": "42"}, {"conclusion": "forty-two"})
    assert check.verdict == VERDICT_UNREADABLE
    assert not check.disagrees


def test_read_number_rejects_anything_that_is_not_only_a_number() -> None:
    assert read_number("42") == 42
    assert read_number("-3.5") == Decimal("-3.5")
    assert read_number("1,250") == 1250
    assert read_number(7) == 7
    assert read_number("42 marks") is None
    assert read_number("$42") is None
    assert read_number("") is None
    assert read_number(None) is None
    assert read_number(True) is None


# ------------------------------------------------------- the combination rule


def _both_roles(case: str, verdict: str) -> dict[str, dict[str, str]]:
    return {role: {case: verdict} for role in ROLES}


def test_a_deterministic_disagreement_fails_the_case_despite_two_passes() -> None:
    combined, reasons = combine_case_verdicts(
        required_cases=(CASE_AGREEMENT,),
        by_role=_both_roles(CASE_AGREEMENT, "PASS"),
        solution_a={"correct_option_index": 1},
        solution_b={"correct_option_index": 2},
    )
    assert combined[CASE_AGREEMENT] == "FAIL"
    assert any("ANSWER_DISAGREEMENT" in reason for reason in reasons)


def test_the_deterministic_refusal_replaces_a_stale_uncertain_reason() -> None:
    by_role = {
        EVIDENCE_AUDIT_ROLE: {CASE_AGREEMENT: "PASS"},
        ADVERSARIAL_AUDIT_ROLE: {CASE_AGREEMENT: "UNCERTAIN"},
    }
    combined, reasons = combine_case_verdicts(
        required_cases=(CASE_AGREEMENT,),
        by_role=by_role,
        solution_a={"candidate_answer": "42"},
        solution_b={"answer": "43"},
    )
    assert combined[CASE_AGREEMENT] == "FAIL"
    agreement_reasons = [r for r in reasons if CASE_AGREEMENT in r]
    assert agreement_reasons == [f"HYBRID_DETERMINISTIC_ANSWER_DISAGREEMENT:{CASE_AGREEMENT}"]


def test_matching_answers_do_not_pass_the_case_on_their_own() -> None:
    """Equality of two numbers is not agreement of reasoning."""
    combined, _ = combine_case_verdicts(
        required_cases=(CASE_AGREEMENT,),
        by_role=_both_roles(CASE_AGREEMENT, "UNCERTAIN"),
        solution_a={"correct_option_index": 1},
        solution_b={"correct_option_index": 1},
    )
    assert combined[CASE_AGREEMENT] == "UNCERTAIN"


def test_an_unreadable_pair_leaves_the_role_verdicts_untouched() -> None:
    combined, reasons = combine_case_verdicts(
        required_cases=(CASE_AGREEMENT,),
        by_role=_both_roles(CASE_AGREEMENT, "PASS"),
        solution_a={"candidate_answer": "about 42"},
        solution_b={"conclusion": "roughly forty-three"},
    )
    assert combined[CASE_AGREEMENT] == "PASS"
    assert not any("ANSWER_DISAGREEMENT" in reason for reason in reasons)


def test_the_check_is_skipped_when_no_solutions_were_supplied() -> None:
    combined, _ = combine_case_verdicts(
        required_cases=(CASE_AGREEMENT,), by_role=_both_roles(CASE_AGREEMENT, "PASS")
    )
    assert combined[CASE_AGREEMENT] == "PASS"


# ---------------------------------------------------------- the mutation itself


def test_the_disagreement_mutation_contradicts_the_stored_answer() -> None:
    """An MCQ negative whose second solution picks the author's option is not a defect.

    This is the regression for the four false accepts of the 2026-09-30 run: the
    mutation rewrote the surrounding prose and left the selected option agreeing,
    so the recorded "false accept" measured the mutation rather than the
    reviewers.
    """
    base = _inputs(
        question_type="MCQ_SINGLE",
        options=("alpha", "beta", "gamma"),
        solution_a={"candidate_answer": "beta", "correct_option_index": 1},
        solution_b={"correct_option_index": 1, "steps": [{"ordinal": 1, "result": "beta"}]},
    )
    mutated = disagreeing_solution(base)
    assert mutated is not None
    assert mutated.solution_b["correct_option_index"] == 2
    check = compare_answers(mutated.solution_a, mutated.solution_b)
    assert check.verdict == VERDICT_DISAGREE
    assert check.channel == CHANNEL_OPTION_INDEX


def test_the_disagreement_mutation_wraps_around_the_last_option() -> None:
    base = _inputs(
        question_type="MCQ_SINGLE",
        options=("alpha", "beta"),
        solution_a={"candidate_answer": "beta", "correct_option_index": 1},
        solution_b={"correct_option_index": 1, "steps": [{"ordinal": 1, "result": "beta"}]},
    )
    mutated = disagreeing_solution(base)
    assert mutated is not None
    assert mutated.solution_b["correct_option_index"] == 0


def test_a_numeric_answer_is_contradicted_in_its_own_channel() -> None:
    base = _inputs(
        solution_a={"candidate_answer": "42"},
        solution_b={"raw": "42"},
    )
    mutated = disagreeing_solution(base)
    assert mutated is not None
    assert mutated.solution_b["answer"] == "43"
    assert compare_answers(mutated.solution_a, mutated.solution_b).verdict == VERDICT_DISAGREE


def test_a_free_text_answer_is_still_contradicted_explicitly() -> None:
    base = _inputs(
        solution_a={"candidate_answer": "The point is a core point."},
        solution_b={"raw": "The point is a core point."},
    )
    mutated = disagreeing_solution(base)
    assert mutated is not None
    assert "REJECTED" in str(mutated.solution_b["answer"])
    # Not machine-readable, so the deterministic check abstains and the roles
    # keep the case: the mutation is honest about what it cannot compare.
    assert compare_answers(mutated.solution_a, mutated.solution_b).verdict == VERDICT_UNREADABLE


_IDENTITY_INPUTS = {
    "model_alias": "deepseek-flash",
    "provider": "DEEPSEEK_API",
    "protocol": "responses",
    "evidence_prompt_version": "judge-evidence-audit.v1",
    "adversarial_prompt_version": "judge-adversarial-audit.v1",
    "schema_version": "coursejesus-judge-findings.v1",
}


def test_the_combination_rule_is_part_of_the_measured_method(monkeypatch) -> None:
    """A qualification must be bound to the procedure, not only to the questions.

    The method identity used to be built from the prompt and schema revisions
    alone, so adding a deterministic input to one of the four cases would have
    left every existing qualification valid for a procedure it never measured.
    """
    before = method_identity(**_IDENTITY_INPUTS)
    assert COMBINATION_VERSION == "hybrid-combination.v2"
    monkeypatch.setattr(hybrid_review, "COMBINATION_VERSION", "hybrid-combination.v3")
    assert method_identity(**_IDENTITY_INPUTS) != before


def test_the_identity_is_stable_when_nothing_changed() -> None:
    assert method_identity(**_IDENTITY_INPUTS) == method_identity(**_IDENTITY_INPUTS)
    assert len(method_identity(**_IDENTITY_INPUTS)) == 64


def test_the_mutated_row_is_still_well_formed_json() -> None:
    base = _inputs(
        question_type="MCQ_SINGLE",
        options=("alpha", "beta"),
        solution_a={"correct_option_index": 0, "candidate_answer": "alpha"},
        solution_b={"correct_option_index": 0, "steps": [{"ordinal": 1, "result": "alpha"}]},
    )
    mutated = disagreeing_solution(base)
    assert mutated is not None
    payload = json.loads(json.dumps(mutated.solution_b, ensure_ascii=False))
    assert isinstance(payload, dict)
    assert mutated.question_revision != base.question_revision
