"""Server-configured, full-model-only generic route; no client route selection."""

from typing import Any
from urllib.parse import urlsplit

from app.config import Settings
from app.errors import ApiError
from app.evaluation.provider_safety import validate_model_studio_base_url
from app.learning.provider import LearningProvider
from app.learning.qwen_profile import qwen_quality_profile


def generic_model_settings(settings: Settings) -> Settings:
    if (
        not settings.generic_llm_enabled
        or not settings.cj_qwen_api_key
        or not settings.cj_qwen_api_key.get_secret_value()
        or settings.cj_qwen_model != "qwen3.8-max"
        or not settings.cj_qwen_capability_receipt_id
        or not settings.cj_qwen_secret_generation_id
        or settings.cj_qwen_native_reasoning is not True
        or settings.cj_qwen_reasoning_effort != "xhigh"
    ):
        raise ApiError(503, "GENERIC_MODEL_NOT_READY", "The learning service is not ready.")
    try:
        endpoint = validate_model_studio_base_url(settings.cj_qwen_base_url)
    except ValueError:
        raise ApiError(
            503,
            "GENERIC_MODEL_ENDPOINT_INVALID",
            "The service configuration is invalid.",
        ) from None
    host = urlsplit(endpoint).hostname or ""
    if host != "dashscope.aliyuncs.com" and not host.endswith(
        ".cn-beijing.maas.aliyuncs.com"
    ):
        raise ApiError(
            503,
            "GENERIC_MODEL_REGION_NOT_VERIFIED",
            "The service region is not verified.",
        )
    return settings.model_copy(
        update={
            "rag_provider_mode": "openai",
            "v3_model": "qwen3.8-max",
            "v3_qwen_protocol": "chat_completions",
            "v3_qwen_native_reasoning": True,
            "v3_qwen_reasoning_effort": "xhigh",
            "v3_model_api_key": settings.cj_qwen_api_key,
            "v3_model_base_url": endpoint,
        }
    )


def build_generic_provider(settings: Settings) -> LearningProvider:
    return LearningProvider(generic_model_settings(settings))


def generic_provider_route(
    settings: Settings, provider: LearningProvider
) -> dict[str, Any]:
    """Validate the actual sole client, not merely configured reference names."""
    expected = generic_model_settings(settings)
    actual = provider.settings
    if (
        provider.cache_model != "qwen3.8-max"
        or provider.cache_protocol != "chat_completions"
        or (actual.v3_model_base_url or "").rstrip("/")
        != (expected.v3_model_base_url or "").rstrip("/")
        or actual.cj_qwen_capability_receipt_id != expected.cj_qwen_capability_receipt_id
        or actual.cj_qwen_secret_generation_id != expected.cj_qwen_secret_generation_id
        or qwen_quality_profile(actual) != qwen_quality_profile(expected)
    ):
        raise ApiError(503, "GENERIC_MODEL_NOT_READY", "The learning service is not ready.")
    return {
        "endpoint": (expected.v3_model_base_url or "").rstrip("/"),
        "model": provider.cache_model,
        "protocol": provider.cache_protocol,
        "quality_profile": qwen_quality_profile(expected),
    }
