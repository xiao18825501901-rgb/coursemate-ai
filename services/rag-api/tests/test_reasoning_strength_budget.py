from decimal import Decimal

import pytest

from app.cm_update.budget import (
    ApplicationBudgetExceeded,
    BudgetBaselineUnavailable,
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
