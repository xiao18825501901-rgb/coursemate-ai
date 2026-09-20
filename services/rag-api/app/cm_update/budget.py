"""Server-side application USD policy for the two learning-pane composers.

Provider credit, token limits, timeouts, stop/cancel, and rate limits remain
separate controls.  `None` is the only representation of the product's
unlimited application-dollar cap.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_UP
from typing import Any


class BudgetPolicyError(ValueError):
    code = "BUDGET_POLICY_INVALID"


class BudgetBaselineUnavailable(BudgetPolicyError):
    code = "BUDGET_BASELINE_UNCONFIGURED"


class BudgetEstimateUnavailable(BudgetPolicyError):
    code = "BUDGET_ESTIMATE_UNCONFIGURED"


class BudgetPriceUnavailable(BudgetPolicyError):
    code = "BUDGET_PRICE_UNCONFIGURED"


class BudgetImagePriceUnavailable(BudgetPolicyError):
    code = "BUDGET_IMAGE_PRICE_UNCONFIGURED"


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


@dataclass(frozen=True)
class OperationEstimate:
    """A server-owned upper bound for one billable operation.

    Text is deliberately measured as UTF-8 bytes rather than a provider-specific
    tokenizer. A token cannot contain more source bytes than it consumes, so this
    is conservative across the OpenAI-compatible and Responses wire formats.
    ``extra_input_tokens`` is used for a planning stage whose generated result is
    later placed in a second request.
    """

    usd: Decimal
    input_tokens: int
    output_tokens: int
    stage_count: int
    image_inputs: int
    stages: tuple[dict[str, int | str], ...]

    def audit(self) -> dict[str, Any]:
        return {
            "kind": "server_operation_estimate",
            "usd": str(self.usd),
            "input_tokens_upper_bound": self.input_tokens,
            "output_tokens_upper_bound": self.output_tokens,
            "stage_count": self.stage_count,
            "image_inputs": self.image_inputs,
            "stages": [dict(stage) for stage in self.stages],
        }


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


def _content_metrics(value: Any) -> tuple[int, int]:
    """Return conservative text-token and image-input bounds for wire content."""

    if value is None:
        return 0, 0
    if isinstance(value, str):
        return len(value.encode("utf-8")), 0
    if isinstance(value, list):
        text = images = 0
        for item in value:
            item_text, item_images = _content_metrics(item)
            text += item_text
            images += item_images
        return text, images
    if isinstance(value, dict):
        content_type = value.get("type")
        if content_type in {"input_image", "image_url"}:
            # The URL/base64 bytes are transport data, not text prompt tokens.
            # Its monetary bound is configured explicitly per image input.
            return 0, 1
        text = images = 0
        for key, item in value.items():
            if key in {"image_url", "url"}:
                continue
            item_text, item_images = _content_metrics(item)
            text += item_text
            images += item_images
        return text, images
    return len(str(value).encode("utf-8")), 0


def _stage_metrics(messages: list[dict[str, Any]], extra_input_tokens: int) -> tuple[int, int]:
    if extra_input_tokens < 0:
        raise BudgetPolicyError("extra input token bound cannot be negative")
    text = extra_input_tokens
    images = 0
    # Fixed envelope allowance covers role labels and provider wire framing.
    for message in messages:
        content_tokens, content_images = _content_metrics(message.get("content"))
        text += content_tokens + 16
        images += content_images
    return text + 32, images


def estimate_operation_cost(
    *,
    stages: list[dict[str, Any]],
    input_usd_per_million: Decimal | str | None,
    output_usd_per_million: Decimal | str | None,
    image_tokens_per_input: int | None = None,
) -> OperationEstimate:
    """Price every bounded provider stage before the first outbound request.

    This function accepts only server-constructed messages and configured list
    prices. It never accepts a client-supplied amount. Unsupported image pricing
    fails closed instead of pretending the image input is free.
    """

    if not stages:
        raise BudgetPolicyError("at least one billable stage is required")
    input_rate = parse_usd(
        input_usd_per_million,
        required=True,
        field="input token price",
        missing_error=BudgetPriceUnavailable,
    )
    output_rate = parse_usd(
        output_usd_per_million,
        required=True,
        field="output token price",
        missing_error=BudgetPriceUnavailable,
    )
    assert input_rate is not None and output_rate is not None

    input_tokens = output_tokens = image_inputs = 0
    audit_stages: list[dict[str, int | str]] = []
    for stage in stages:
        name = stage.get("name")
        messages = stage.get("messages")
        max_output_tokens = stage.get("max_output_tokens")
        extra_input_tokens = stage.get("extra_input_tokens", 0)
        if not isinstance(name, str) or not name:
            raise BudgetPolicyError("billable stage name is required")
        if not isinstance(messages, list):
            raise BudgetPolicyError("billable stage messages are invalid")
        if not isinstance(max_output_tokens, int) or max_output_tokens <= 0:
            raise BudgetPolicyError("billable stage output bound is invalid")
        if not isinstance(extra_input_tokens, int):
            raise BudgetPolicyError("billable stage input bound is invalid")
        stage_tokens, stage_images = _stage_metrics(messages, extra_input_tokens)
        input_tokens += stage_tokens
        output_tokens += max_output_tokens
        image_inputs += stage_images
        audit_stages.append(
            {
                "name": name,
                "input_tokens_upper_bound": stage_tokens,
                "output_tokens_upper_bound": max_output_tokens,
                "image_inputs": stage_images,
            }
        )

    if image_inputs and (not isinstance(image_tokens_per_input, int) or image_tokens_per_input <= 0):
        raise BudgetImagePriceUnavailable("image input token bound is not configured")
    if image_inputs:
        assert image_tokens_per_input is not None
        input_tokens += image_inputs * image_tokens_per_input
        for stage in audit_stages:
            image_tokens = int(stage["image_inputs"]) * image_tokens_per_input
            stage["image_tokens_upper_bound"] = image_tokens
            stage["input_tokens_upper_bound"] = int(stage["input_tokens_upper_bound"]) + image_tokens
    amount = (
        Decimal(input_tokens) * input_rate / Decimal("1000000")
        + Decimal(output_tokens) * output_rate / Decimal("1000000")
    )
    # Never round a preflight estimate down below a provider billable amount.
    amount = amount.quantize(Decimal("0.000001"), rounding=ROUND_UP)
    return OperationEstimate(
        usd=amount,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stage_count=len(audit_stages),
        image_inputs=image_inputs,
        stages=tuple(audit_stages),
    )


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
