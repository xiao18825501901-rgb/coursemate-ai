from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from app.config import Settings
from app.learning.provider import LearningProvider


class ExampleOutput(BaseModel):
    value: str


def test_learning_provider_uses_safe_deepseek_runtime_settings(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.responses = SimpleNamespace(create=self.create)

        @staticmethod
        def create(**kwargs: Any) -> SimpleNamespace:
            captured["request"] = kwargs
            return SimpleNamespace(
                id="response-fixture",
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                status="completed",
                output_text='{"value":"ok"}',
            )

    # The client is built by the shared policy module, so that is where the
    # stand-in has to be installed.
    monkeypatch.setattr("app.provider_client.OpenAI", FakeOpenAI)
    provider = LearningProvider(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            app_env="development",
            rag_provider_mode="openai",
            v3_enabled=True,
            v3_model="deepseek-flash",
            v3_model_api_key=SecretStr("test-only-key"),
            v3_model_base_url="https://api.deepseek.com",
            v3_model_timeout_seconds=180,
        )
    )

    result, run = provider.generate(
        ExampleOutput,
        instructions="Return the fixture.",
        context={},
        role="test",
    )

    assert result == ExampleOutput(value="ok")
    assert run["status"] == "COMPLETED"
    assert run["provider"] == "DEEPSEEK_API"
    # Explicit and per-phase: the SDK defaults were max_retries=2 with a 5 s
    # connect against a 600 s read, and neither number was recorded anywhere.
    import httpx

    timeout = captured["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 10.0
    assert timeout.read == 180
    assert timeout.write == 180
    assert timeout.pool == 30.0
    assert captured["max_retries"] == 0
    assert captured["base_url"] == "https://api.deepseek.com"
    assert run["timeouts"] == {
        "connectSeconds": 10.0,
        "readSeconds": 180.0,
        "writeSeconds": 180.0,
        "poolSeconds": 30.0,
        "operationDeadlineSeconds": 370.0,
    }
    # DeepSeek contract: native thinking off, json_schema structured output, and
    # NO Qwen-only enable_thinking field anywhere in the request body.
    assert captured["request"]["extra_body"]["reasoning"] == {"effort": "none"}
    assert captured["request"]["extra_body"]["text"]["format"]["type"] == "json_schema"
    assert "enable_thinking" not in str(captured["request"])


def test_learning_provider_historical_model_studio_path_still_validates(
    monkeypatch: Any,
) -> None:
    """The historical qwen3.8-max path remains for reading old records only."""
    captured: dict[str, Any] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.responses = SimpleNamespace(create=self.create)

        @staticmethod
        def create(**kwargs: Any) -> SimpleNamespace:
            captured["request"] = kwargs
            return SimpleNamespace(
                id="response-fixture",
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                status="completed",
                output_text='{"value":"ok"}',
            )

    monkeypatch.setattr("app.provider_client.OpenAI", FakeOpenAI)
    provider = LearningProvider(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            app_env="development",
            rag_provider_mode="openai",
            v3_enabled=True,
            v3_model="qwen3.8-max",
            v3_model_api_key=SecretStr("test-only-key"),
            v3_model_base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            v3_model_timeout_seconds=180,
        )
    )

    result, run = provider.generate(
        ExampleOutput, instructions="Return the fixture.", context={}, role="test"
    )
    assert result == ExampleOutput(value="ok")
    assert run["provider"] == "ALIBABA_MODEL_STUDIO_COMPATIBLE"
    assert captured["base_url"] == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    assert captured["request"]["extra_body"] == {"enable_thinking": False}

def test_a_live_shaped_run_carries_only_keys_the_receipt_accepts(monkeypatch: Any) -> None:
    """The regression the staging probe found.

    The complete response and its rejection reason are diagnostic evidence, not
    receipt fields.  Writing them into the run made every live call fail
    AuthorProviderRun validation with extra_forbidden -- the fixture path never
    showed it, because the fixture branch returns before the response is read.
    This test drives the live branch and asserts the run stays receipt-shaped.
    """
    from app.learning.question_author import AuthorProviderRun

    class FakeOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            self.responses = SimpleNamespace(create=self.create)

        @staticmethod
        def create(**kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(
                id="response-live-shaped",
                usage=SimpleNamespace(input_tokens=11, output_tokens=22),
                status="completed",
                output_text='{"value":"ok"}',
            )

    monkeypatch.setattr("app.provider_client.OpenAI", FakeOpenAI)
    provider = LearningProvider(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            app_env="development",
            rag_provider_mode="openai",
            v3_enabled=True,
            v3_model="deepseek-flash",
            v3_model_api_key=SecretStr("test-only-key"),
            v3_model_base_url="https://api.deepseek.com",
        )
    )
    _, run = provider.generate(
        ExampleOutput, instructions="Return the fixture.", context={}, role="test"
    )
    extra = set(run) - set(AuthorProviderRun.model_fields)
    assert extra == set(), f"the run carried keys the receipt refuses: {sorted(extra)}"
    assert "response_text" not in run
    assert "response_received" not in run
    assert run["status"] == "COMPLETED"


def test_a_failed_live_call_keeps_the_complete_response_for_offline_parsing(
    monkeypatch: Any,
) -> None:
    """A schema rejection must carry the paid response, and stay attributable."""
    from app.learning.provider import ProviderCallFailure, schema_error_summary

    class FakeOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            self.responses = SimpleNamespace(create=self.create)

        @staticmethod
        def create(**kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(
                id="response-bad-json",
                usage=SimpleNamespace(input_tokens=11, output_tokens=22),
                status="completed",
                output_text="not json at all",
            )

    monkeypatch.setattr("app.provider_client.OpenAI", FakeOpenAI)
    provider = LearningProvider(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            app_env="development",
            rag_provider_mode="openai",
            v3_enabled=True,
            v3_model="deepseek-flash",
            v3_model_api_key=SecretStr("test-only-key"),
            v3_model_base_url="https://api.deepseek.com",
        )
    )
    with pytest.raises(ProviderCallFailure) as caught:
        provider.generate(
            ExampleOutput, instructions="Return the fixture.", context={}, role="test"
        )
    run = caught.value.run
    assert run["status"] == "FAILED"
    assert run["error_class"] == "SCHEMA_INVALID"
    assert run["failure_layer"] == "RESPONSE_SCHEMA"
    assert run["response_received"] is True
    assert run["response_text"] == "not json at all"
    assert run["schema_error_summary"] == ["<root>: json_invalid"]
    # The helper is available for a caller to record a summary of its own.
    assert callable(schema_error_summary)

