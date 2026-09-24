"""Question Engine preflight prices both bounded DeepSeek calls."""

from decimal import Decimal
from types import SimpleNamespace

from app.cm_update.provider import QwenProvider


def test_question_engine_estimate_reserves_author_and_blind_solver() -> None:
    provider = QwenProvider(
        SimpleNamespace(
            operation_input_usd_per_million=Decimal("2"),
            operation_output_usd_per_million=Decimal("10"),
            image_max_pixels=1_048_576,
            answer_tokens=6_500,
        )
    )

    estimate = provider.estimate_question_engine()

    assert estimate.stage_count == 2
    assert [stage["name"] for stage in estimate.stages] == [
        "question_author",
        "question_blind_solver",
    ]
    assert estimate.output_tokens == 13_000
    assert all(
        stage["input_tokens_upper_bound"] >= 60_000
        for stage in estimate.stages
    )
    assert estimate.usd > Decimal("0")
