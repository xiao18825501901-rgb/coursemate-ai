from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.learning.practice_feedback import PracticeFeedbackOutput, PracticeProviderRun


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


def test_practice_feedback_accepts_the_verified_generic_qwen_route() -> None:
    run = PracticeProviderRun.model_validate(
        {
            "model": "qwen3.8-max",
            "provider": "ALIBABA_MODEL_STUDIO_COMPATIBLE",
            "protocol": "chat_completions",
            "region": "ENDPOINT_CN",
            "role": "PRACTICE_FEEDBACK",
            "template_version": "practice-feedback.v1",
            "schema_version": "practice-feedback-output.v1",
            "input_hash": "a" * 64,
            "started_at": "2026-10-18T00:00:00Z",
            "finished_at": "2026-10-18T00:00:01Z",
            "latency_ms": 1000,
            "input_tokens": 100,
            "output_tokens": 50,
            "status": "COMPLETED",
            "error_class": None,
        }
    )

    assert run.model == "qwen3.8-max"
