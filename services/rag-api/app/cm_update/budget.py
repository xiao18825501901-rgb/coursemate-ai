"""Server-side application USD policy for the two learning-pane composers.

Provider credit, token limits, timeouts, stop/cancel, and rate limits remain
separate controls.  `None` is the only representation of the product's
unlimited application-dollar cap.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class BudgetPolicyError(ValueError):
    code = "BUDGET_POLICY_INVALID"


class BudgetBaselineUnavailable(BudgetPolicyError):
    code = "BUDGET_BASELINE_UNCONFIGURED"


class BudgetEstimateUnavailable(BudgetPolicyError):
    code = "BUDGET_ESTIMATE_UNCONFIGURED"


class ApplicationBudgetExceeded(BudgetPolicyError):
    code = "APPLICATION_USD_BUDGET_EXCEEDED"


@dataclass(frozen=True)
class BudgetDecision:
    strength: str
    baseline_usd: Decimal | None
    estimated_usd: Decimal | None
    application_usd_cap: Decimal | None

    @property
    def unlimited(self) -> bool:
        return self.application_usd_cap is None


def parse_usd(
    value: str | Decimal | None,
    *,
    required: bool,
    field: str,
    missing_error: type[BudgetPolicyError],
) -> Decimal | None:
    if value is None or value == "":
        if required:
            raise missing_error(f"{field} is not configured")
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise BudgetPolicyError(f"{field} is invalid") from error
    if not parsed.is_finite() or parsed <= 0:
        raise BudgetPolicyError(f"{field} must be a positive finite USD value")
    return parsed


def evaluate_operation_budget(
    strength: str, baseline_usd: Decimal | str | None, estimated_usd: Decimal | str | None
) -> BudgetDecision:
    if strength not in {"medium", "high", "max"}:
        raise BudgetPolicyError("unknown reasoning strength")
    baseline = parse_usd(
        baseline_usd,
        required=strength != "max",
        field="operation baseline",
        missing_error=BudgetBaselineUnavailable,
    )
    estimate = parse_usd(
        estimated_usd,
        required=strength != "max",
        field="operation estimate",
        missing_error=BudgetEstimateUnavailable,
    )
    if strength == "max":
        # Do not turn this into a large number, zero, Infinity, or a default.
        return BudgetDecision(strength, baseline, estimate, None)
    assert baseline is not None and estimate is not None
    cap = baseline if strength == "medium" else baseline * Decimal("2")
    if estimate > cap:
        raise ApplicationBudgetExceeded("estimated operation cost exceeds selected application USD cap")
    return BudgetDecision(strength, baseline, estimate, cap)
