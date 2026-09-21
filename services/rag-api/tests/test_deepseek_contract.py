"""Unit contract tests for the verified DeepSeek payload builders and validator.

These are OFFLINE_CONTRACT tests: they pin the exact wire shapes read from the
official DeepSeek API reference on 2026-09-21.  No live call is made, and every
assertion is against a documented field - nothing here is invented.
"""

from __future__ import annotations

import pytest

from app.evaluation.deepseek_contract import (
    API_BASE_URL,
    MODEL_ALIAS,
    DeepSeekCapabilityError,
    chat_completions_body,
    chat_completions_image_part,
    json_schema_text_format,
    responses_body,
    responses_image_part,
)
from app.evaluation.provider_safety import validate_deepseek_base_url

QWEN_ONLY_FIELDS = ("enable_thinking", "max_pixels")


def _flatten_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys |= _flatten_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _flatten_keys(item)
    return keys


def test_chat_completions_body_never_emits_qwen_only_fields() -> None:
    body = chat_completions_body(
        model=MODEL_ALIAS,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=512,
        stream=True,
    )
    assert body["model"] == MODEL_ALIAS
    assert body["stream"] is True
    assert body["max_tokens"] == 512
    assert body["thinking"] == {"type": "disabled"}
    assert not (_flatten_keys(body) & set(QWEN_ONLY_FIELDS))


def test_chat_completions_body_accepts_json_object_response_format() -> None:
    body = chat_completions_body(
        model=MODEL_ALIAS,
        messages=[],
        max_tokens=10,
        stream=False,
        response_format={"type": "json_object"},
    )
    assert body["response_format"] == {"type": "json_object"}


def test_chat_completions_body_rejects_json_schema_with_typed_error() -> None:
    with pytest.raises(DeepSeekCapabilityError) as error:
        chat_completions_body(
            model=MODEL_ALIAS,
            messages=[],
            max_tokens=10,
            stream=False,
            response_format={"type": "json_schema"},
        )
    assert "json_schema" in str(error.value)
    assert error.value.protocol == "chat_completions"


def test_responses_body_never_emits_qwen_only_fields() -> None:
    body = responses_body(
        model=MODEL_ALIAS,
        input=[{"role": "user", "content": "hi"}],
        max_output_tokens=512,
        stream=True,
    )
    assert body["model"] == MODEL_ALIAS
    assert body["max_output_tokens"] == 512
    assert body["reasoning"] == {"effort": "none"}
    assert not (_flatten_keys(body) & set(QWEN_ONLY_FIELDS))


def test_responses_body_carries_text_format_json_schema() -> None:
    schema = {"type": "object", "properties": {"question": {"type": "string"}}}
    fmt = json_schema_text_format("coursemate_exercise_v2", schema)
    body = responses_body(
        model=MODEL_ALIAS,
        input="question",
        max_output_tokens=512,
        stream=True,
        text_format=fmt,
    )
    assert body["text"] == {"format": fmt}
    assert fmt["type"] == "json_schema"
    assert "strict" not in fmt  # DeepSeek documents no strict flag


def test_image_parts_use_detail_and_never_max_pixels() -> None:
    chat = chat_completions_image_part("data:image/jpeg;base64,AAAA", detail="auto")
    responses = responses_image_part("data:image/png;base64,AAAA", detail="low")
    assert chat == {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,AAAA", "detail": "auto"},
    }
    assert responses == {
        "type": "input_image",
        "image_url": "data:image/png;base64,AAAA",
        "detail": "low",
    }
    assert not (_flatten_keys(chat) & set(QWEN_ONLY_FIELDS))
    assert not (_flatten_keys(responses) & set(QWEN_ONLY_FIELDS))


@pytest.mark.parametrize("ok", [API_BASE_URL, API_BASE_URL + "/"])
def test_deepseek_base_url_passes_validator(ok: str) -> None:
    assert validate_deepseek_base_url(ok) == ok


@pytest.mark.parametrize(
    "bad",
    [
        "https://random.example.com",
        "http://api.deepseek.com",
        "https://api.deepseek.com/v1",
        "https://user:pass@api.deepseek.com",
        "https://api.deepseek.com?x=1",
        "https://api.deepseek.com:8443",
    ],
)
def test_deepseek_base_url_rejects_random_or_malformed_hosts(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_deepseek_base_url(bad)


def test_capability_matrix_records_verification_date_and_model() -> None:
    from app.evaluation.deepseek_contract import (
        CAPABILITY_MATRIX,
        VERIFICATION_DATE,
    )

    assert VERIFICATION_DATE == "2026-09-21"
    assert CAPABILITY_MATRIX["responses"]["text_streaming"] == "OFFLINE_CONTRACT"
    assert CAPABILITY_MATRIX["live"]["text_streaming_live"] == "NOT_RUN"
