"""Trusted provider identities shared by Question Engine qualification stages."""

from __future__ import annotations

from typing import Any


def verified_run_identity(
    *, model: str, provider: str, protocol: str, region: str
) -> bool:
    """Accept only a server-owned production identity or the labelled test fixture."""

    fixture = (
        model == "FAKE_TEST_ONLY"
        and provider == "deterministic"
        and protocol == "fixture"
        and region == "LOCAL_TEST"
    )
    deepseek = (
        model == "deepseek-flash"
        and provider == "DEEPSEEK_API"
        and protocol == "responses"
        and region == "ENDPOINT_DEEPSEEK"
    )
    qwen = (
        model == "qwen3.8-max"
        and provider == "ALIBABA_MODEL_STUDIO_COMPATIBLE"
        and protocol == "chat_completions"
        and region in {"ENDPOINT_CN", "ENDPOINT_WORKSPACE"}
    )
    return fixture or deepseek or qwen


def verified_structured_provider(provider: Any) -> bool:
    """Verify the live adapter, including its protected Qwen capability lineage."""

    fixture = (
        getattr(provider, "cache_model", None) == "FAKE_TEST_ONLY"
        and getattr(provider, "cache_protocol", None) == "fixture"
        and getattr(provider, "cache_region", None) == "LOCAL_TEST"
    )
    deepseek = (
        getattr(provider, "cache_model", None) == "deepseek-flash"
        and getattr(provider, "is_deepseek", False) is True
        and getattr(provider, "cache_protocol", None) == "responses"
        and getattr(provider, "cache_region", None) == "ENDPOINT_DEEPSEEK"
    )
    qwen_shape = (
        getattr(provider, "cache_model", None) == "qwen3.8-max"
        and getattr(provider, "is_deepseek", True) is False
        and getattr(provider, "cache_protocol", None) == "chat_completions"
        and getattr(provider, "cache_region", None)
        in {"ENDPOINT_CN", "ENDPOINT_WORKSPACE"}
    )
    if not qwen_shape:
        return fixture or deepseek
    settings = getattr(provider, "settings", None)
    if settings is None:
        return False
    try:
        from app.learning.generic_provider import generic_provider_route

        generic_provider_route(settings, provider)
    except Exception:
        return False
    return True
