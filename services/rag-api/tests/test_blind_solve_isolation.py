"""The blind solve must not be able to see the answer — proven with sentinels, not asserted.

The isolation in `app/learning/blind_solve.py` is only worth something if a regression fails a
test. Each test here puts a recognisable sentinel into one piece of the answer side (the author's
solution, the correct option, a student's answer, a critique's correction, a rubric key) and checks
that the serialized request cannot contain it.
"""

from __future__ import annotations

import json

import pytest

from app.learning.blind_solve import (
    BLIND_SOLVE_FIELDS,
    BlindSolveLeak,
    BlindSolveReceipt,
    BlindSolveRequest,
    assert_no_answer_leak,
)

# One sentinel per leak channel. They are deliberately distinctive so a match cannot be accidental.
AUTHOR_SOLUTION = "AUTHOR-SOLUTION-SENTINEL: the core point is D because it has 4 neighbours"
CORRECT_OPTION = "B"
STUDENT_ANSWER = "STUDENT-ANSWER-SENTINEL: I think the answer is A"
CRITIQUE_CORRECTION = "CRITIQUE-SENTINEL: the previous draft wrongly said minPts counts only others"
RUBRIC_KEY = "RUBRIC-SENTINEL: full marks require the answer D"

QUESTION = (
    "Given epsilon = 1.1 and minPts = 4 (counting the point itself), classify A, B, C, D and E "
    "as core, border or noise."
)
OPTIONS = ("A", "B", "C", "D", "E")
RULES = ("A point is a core point when its epsilon-neighbourhood, including itself, has at least "
         "minPts points.", "The boundary is closed: distance <= epsilon counts as inside.")


def request() -> BlindSolveRequest:
    return BlindSolveRequest(
        question_text=QUESTION,
        options=OPTIONS,
        allowed_rules=RULES,
    )


def test_the_payload_is_exactly_the_whitelist() -> None:
    payload = request().payload()
    assert tuple(payload) == BLIND_SOLVE_FIELDS
    assert set(payload) <= set(BLIND_SOLVE_FIELDS)


def test_no_answer_side_text_reaches_the_request() -> None:
    assert_no_answer_leak(
        request(),
        [AUTHOR_SOLUTION, STUDENT_ANSWER, CRITIQUE_CORRECTION, RUBRIC_KEY],
    )
    # The correct option sentinel ("B") is a single letter, so it is checked the way it actually
    # leaks: as a field, not as prose (see the field-name test below). This asserts the *value*
    # check still fires when the letter is used as an answer-shaped sentinel.
    with pytest.raises(BlindSolveLeak):
        assert_no_answer_leak(request(), [OPTIONS[1]])


def test_each_channel_is_actually_scanned() -> None:
    """A leak on any one channel fails, so the guard cannot be satisfied by scanning one field."""
    for sentinel in (AUTHOR_SOLUTION, STUDENT_ANSWER, CRITIQUE_CORRECTION, RUBRIC_KEY):
        smuggled = BlindSolveRequest(
            question_text=QUESTION,
            options=OPTIONS,
            allowed_rules=(*RULES, sentinel),
        )
        with pytest.raises(BlindSolveLeak) as failure:
            assert_no_answer_leak(smuggled, [sentinel])
        # The message names what was found without echoing the sentinel into a log.
        assert "sentinel" in str(failure.value)
        assert sentinel not in str(failure.value)


def test_an_extra_field_is_refused_rather_than_sent() -> None:
    # A field that names the answer side is reported as the leak it is, not as an unknown field.
    with pytest.raises(BlindSolveLeak) as failure:
        assert_no_answer_leak({**request().payload(), "author_solution": "D"})
    assert "forbidden fields" in str(failure.value)

    with pytest.raises(BlindSolveLeak) as failure:
        assert_no_answer_leak({**request().payload(), "correct_option": "D"})
    assert "forbidden fields" in str(failure.value)

    # And a merely unknown field is still refused: the whitelist is closed, so "one more helpful
    # field" cannot be added later without a deliberate change here.
    with pytest.raises(BlindSolveLeak) as failure:
        assert_no_answer_leak({**request().payload(), "helpful_context": "the answer is D"})
    assert "outside the whitelist" in str(failure.value)


def test_structured_options_are_refused_at_construction() -> None:
    """The projection from a structured option to text is where the correctness flag is dropped."""
    with pytest.raises(TypeError):
        BlindSolveRequest(
            question_text=QUESTION,
            options=({"text": "D", "correct": True},),  # type: ignore[arg-type]
        )


def test_an_empty_question_is_refused() -> None:
    with pytest.raises(ValueError):
        BlindSolveRequest(question_text="   ")


def test_the_input_hash_identifies_the_request_and_ignores_key_order() -> None:
    first = request()
    second = BlindSolveRequest(
        question_text=QUESTION,
        options=OPTIONS,
        allowed_rules=RULES,
    )
    assert first.input_hash() == second.input_hash()
    assert len(first.input_hash()) == 64

    different = BlindSolveRequest(question_text=QUESTION, options=OPTIONS, allowed_rules=RULES[:1])
    assert different.input_hash() != first.input_hash()
    # A changed question changes the hash, which is what ties a receipt to what was solved.
    reworded = BlindSolveRequest(question_text=QUESTION + " Show your working.", options=OPTIONS)
    assert reworded.input_hash() != first.input_hash()


def test_a_receipt_is_only_current_for_the_revision_it_solved() -> None:
    receipt = BlindSolveReceipt(
        input_hash=request().input_hash(),
        question_revision="rev-1",
        model_version="deepseek-flash",
        output="D is the only core point; A, B, C and E are border or noise.",
        status="completed",
    )
    assert receipt.is_current_for("rev-1") is True
    # Editing the question produces a new revision; the old solve is not evidence about it.
    assert receipt.is_current_for("rev-2") is False
    assert BlindSolveReceipt(
        input_hash="x",
        question_revision="rev-1",
        model_version="m",
        output="",
        status="completed",
    ).is_current_for("rev-1") is False
    assert BlindSolveReceipt(
        input_hash="x",
        question_revision="rev-1",
        model_version="m",
        output="answer",
        status="failed",
    ).is_current_for("rev-1") is False


def test_the_serialized_request_carries_no_answer_shaped_key() -> None:
    """The check that survives a careless caller: nothing in the JSON keys can name an answer."""
    payload = json.loads(json.dumps(request().payload(), ensure_ascii=False))
    assert_no_answer_leak(
        payload, [AUTHOR_SOLUTION, STUDENT_ANSWER, CRITIQUE_CORRECTION, RUBRIC_KEY]
    )
    assert "correct" not in json.dumps(payload).casefold()
