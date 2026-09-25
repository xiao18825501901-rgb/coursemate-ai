from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.learning.practice_feedback import PracticeFeedbackOutput


def _payload(criterion_feedback: str) -> dict[str, object]:
    return {
        "verdict": "PARTIAL",
        "feedback": "The learner reached the conclusion but omitted one required justification.",
        "strengths": ["The conclusion is correct."],
        "gaps": ["The comparison is not explicit."],
        "next_step": "State the comparison explicitly.",
        "criteria": [
            {
                "criterion_id": "criterion_1",
                "met": False,
                "feedback": criterion_feedback,
            }
        ],
    }


def test_rubric_feedback_accepts_a_complete_512_character_live_explanation() -> None:
    live_length_explanation = "x" * 512

    output = PracticeFeedbackOutput.model_validate(_payload(live_length_explanation))

    assert output.criteria[0].feedback == live_length_explanation


def test_rubric_feedback_remains_bounded() -> None:
    with pytest.raises(ValidationError, match="at most 1000 characters"):
        PracticeFeedbackOutput.model_validate(_payload("x" * 1_001))
