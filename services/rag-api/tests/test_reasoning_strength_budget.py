from decimal import Decimal

import pytest

from app.cm_update.budget import (
    ApplicationBudgetExceeded,
    BudgetBaselineUnavailable,
    BudgetImagePriceUnavailable,
    estimate_operation_cost,
    evaluate_operation_budget,
)


def test_reasoning_strength_uses_real_null_for_max_and_independent_caps() -> None:
    baseline = Decimal("0.10")

    with pytest.raises(ApplicationBudgetExceeded):
        evaluate_operation_budget("medium", baseline, Decimal("0.15"))

    high = evaluate_operation_budget("high", baseline, Decimal("0.15"))
    assert high.application_usd_cap == Decimal("0.20")
    assert high.estimated_usd == Decimal("0.15")

    with pytest.raises(ApplicationBudgetExceeded):
        evaluate_operation_budget("high", baseline, Decimal("0.21"))

    maximum = evaluate_operation_budget("max", baseline, Decimal("999.99"))
    assert maximum.application_usd_cap is None
    assert maximum.unlimited is True


def test_non_max_requires_a_configured_baseline_instead_of_a_silent_default() -> None:
    with pytest.raises(BudgetBaselineUnavailable):
        evaluate_operation_budget("medium", None, Decimal("0.01"))


def test_server_estimate_accumulates_actual_stage_input_and_bounded_output() -> None:
    estimate = estimate_operation_cost(
        stages=[
            {
                "name": "planner",
                "messages": [{"role": "system", "content": "课程模板"}],
                "max_output_tokens": 100,
            },
            {
                "name": "teacher",
                "messages": [{"role": "user", "content": "解释本题"}],
                "extra_input_tokens": 100,
                "max_output_tokens": 200,
            },
        ],
        input_usd_per_million="2",
        output_usd_per_million="10",
    )

    assert estimate.stage_count == 2
    assert estimate.input_tokens > 100
    assert estimate.output_tokens == 300
    assert estimate.usd > Decimal("0.003")


def test_server_estimate_fails_closed_when_an_image_has_no_token_bound() -> None:
    with pytest.raises(BudgetImagePriceUnavailable):
        estimate_operation_cost(
            stages=[
                {
                    "name": "problem",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "solve"},
                                {"type": "input_image", "image_url": "data:image/png;base64,xxx"},
                            ],
                        }
                    ],
                    "max_output_tokens": 100,
                }
            ],
            input_usd_per_million="2",
            output_usd_per_million="10",
        )
