"""The rule-violation negative must survive the hard gate to test anything.

`question.rule_violation_quality.v1` is decided by the two reviewer roles, but an
item reaches them only after `INPUT_IDENTITY` has passed, and that gate checks
three things about a rule-violation item:

    rule_source_ref in public_question.source_refs
    rule_quote in rule_fragment.content
    proposed_statement in public_question.question_text

The previous `unsupported_rule` mutation broke the second and third of those: it
set a `rule_quote` that appears in no span, and replaced `proposed_statement` with
a canned sentence the question text does not contain.  Every row it produced was
therefore rejected by the hard gate before a reviewer was consulted, which makes
the recorded false-accept rate a property of the mutation rather than of the
case.  These tests pin the predicates that have to hold instead.
"""
from __future__ import annotations

from test_hybrid_review_policy import _inputs  # noqa: E402 - shared fixture builder

from app.learning.hybrid_evaluation_set import _WEAKENED_RULE, unsupported_rule

_PROPOSED = "The step reverses the order of assignment and recomputation."


def _rule_inputs(**overrides):
    payload = {
        "question_text": (
            "Judge the following claim about the algorithm and correct it if it is "
            f"wrong: {_PROPOSED}"
        ),
        "solution_a": {
            "candidate_answer": "The claim is wrong: assignment precedes recomputation.",
            "correct_option_index": None,
            "distractor_rationales": [],
            "solution_steps": [{"ordinal": 1}],
            "source_refs": ["ev-1", "ev-2"],
            "rule_violation_analysis": {
                "proposed_statement": _PROPOSED,
                "rule_source_ref": "ev-2",
                "rule_quote": "Assignment precedes recomputation.",
                "correction": "Reorder the step.",
                "explanation": "The course text orders assignment first.",
            },
        },
        "evidence": (
            {"evidence_id": "ev-1", "content": "K-means forms clusters, then recomputes."},
            {
                "evidence_id": "ev-2",
                "content": "Assignment precedes recomputation, and only for the stated K.",
            },
        ),
    }
    payload.update(overrides)
    return _inputs(**payload)


def test_the_weakened_quote_is_verbatim_in_the_cited_span() -> None:
    """`rule_quote in rule_fragment.content` is a hard gate, not a nicety."""
    mutated = unsupported_rule(_rule_inputs())
    assert mutated is not None
    analysis = mutated.solution_a["rule_violation_analysis"]
    cited = next(
        fragment
        for fragment in mutated.evidence
        if fragment["evidence_id"] == analysis["rule_source_ref"]
    )
    assert analysis["rule_quote"] == _WEAKENED_RULE
    assert analysis["rule_quote"] in cited["content"]


def test_the_proposed_statement_is_left_alone() -> None:
    """It is what the question asks about, and the gate looks for it in the stem."""
    mutated = unsupported_rule(_rule_inputs())
    assert mutated is not None
    analysis = mutated.solution_a["rule_violation_analysis"]
    assert analysis["proposed_statement"] == _PROPOSED
    assert analysis["proposed_statement"] in mutated.question_text


def test_only_the_cited_span_is_weakened() -> None:
    """Weakening the first span would leave the cited rule untouched."""
    mutated = unsupported_rule(_rule_inputs())
    assert mutated is not None
    contents = {f["evidence_id"]: f["content"] for f in mutated.evidence}
    assert contents["ev-1"] == "K-means forms clusters, then recomputes."
    assert contents["ev-2"] != "Assignment precedes recomputation, and only for the stated K."
    assert mutated.question_revision != _rule_inputs().question_revision


def test_an_item_without_a_cited_rule_yields_no_row() -> None:
    """A defect that cannot be applied must not be recorded as one."""
    assert unsupported_rule(_rule_inputs(solution_a={})) is None
    assert (
        unsupported_rule(
            _rule_inputs(
                solution_a={
                    "rule_violation_analysis": {
                        "proposed_statement": _PROPOSED,
                        "rule_source_ref": "ev-missing",
                        "correction": "c",
                        "explanation": "e",
                    }
                }
            )
        )
        is None
    )
