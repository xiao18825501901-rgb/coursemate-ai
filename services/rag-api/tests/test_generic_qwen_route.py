import pytest
from pydantic import SecretStr

from app.config import Settings
from app.errors import ApiError
from app.learning.generic_provider import generic_model_settings

ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def qualified_settings(**updates):
    settings = Settings(
        _env_file=None,
        app_env="development",
        generic_llm_enabled=True,
        cj_qwen_api_key=SecretStr("TEST_ONLY-placeholder"),
        cj_qwen_base_url=ENDPOINT,
        cj_qwen_capability_receipt_id="TEST_ONLY-capability",
        cj_qwen_secret_generation_id="TEST_ONLY-generation",
    )
    return settings.model_copy(update=updates)


def test_generic_route_maps_verified_qwen_without_mutating_deepseek_baseline():
    original = qualified_settings()
    before = original.model_dump(mode="json")

    mapped = generic_model_settings(original)

    assert mapped.v3_model == "qwen3.8-max"
    assert mapped.v3_qwen_protocol == "chat_completions"
    assert mapped.v3_qwen_native_reasoning is True
    assert mapped.v3_qwen_reasoning_effort == "xhigh"
    assert mapped.v3_model_base_url == ENDPOINT
    assert original.model_dump(mode="json") == before
    assert original.v3_model == "deepseek-flash"


@pytest.mark.parametrize(
    "updates",
    [
        {"generic_llm_enabled": False},
        {"cj_qwen_api_key": None},
        {"cj_qwen_capability_receipt_id": ""},
        {"cj_qwen_secret_generation_id": ""},
        {"cj_qwen_native_reasoning": False},
        {"cj_qwen_reasoning_effort": ""},
    ],
)
def test_generic_route_fails_closed_without_exact_capability_and_quality(updates):
    with pytest.raises(ApiError) as caught:
        generic_model_settings(qualified_settings(**updates))
    assert caught.value.code == "GENERIC_MODEL_NOT_READY"


def test_generic_route_refuses_unverified_region():
    with pytest.raises(ApiError) as caught:
        generic_model_settings(
            qualified_settings(cj_qwen_base_url="https://example.com/compatible-mode/v1")
        )
    assert caught.value.code in {
        "GENERIC_MODEL_ENDPOINT_INVALID",
        "GENERIC_MODEL_REGION_NOT_VERIFIED",
    }


def test_profile_defaults_keep_historical_direct_qwen_off():
    settings = Settings(_env_file=None)
    assert settings.v3_qwen_native_reasoning is False
    assert settings.v3_qwen_reasoning_effort == ""
    assert settings.cj_qwen_native_reasoning is True
    assert settings.cj_qwen_reasoning_effort == "xhigh"
