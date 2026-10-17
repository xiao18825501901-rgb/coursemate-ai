"""Non-secret quality identity; no account capability claim or model dispatch."""

from typing import Any

from app.config import Settings
from app.errors import ApiError

PROFILE_VERSION = "cj.qwen.native-quality.v1"


def qwen_quality_profile(settings: Settings) -> dict[str, Any]:
    native = settings.v3_qwen_native_reasoning
    effort = settings.v3_qwen_reasoning_effort
    if type(native) is not bool or (
        native and (effort != "xhigh" or settings.v3_qwen_protocol != "chat_completions")
    ) or (not native and effort != ""):
        raise ApiError(
            503,
            "MODEL_QUALITY_PROFILE_INVALID",
            "The service quality profile is invalid.",
        )
    return {
        "version": PROFILE_VERSION,
        "native_reasoning": native,
        "reasoning_effort": effort,
        "stream": native,
        "usage_requested": native,
        "output_limit_parameter": "max_tokens",
    }
