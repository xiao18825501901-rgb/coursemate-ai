from types import SimpleNamespace
from typing import Any

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

    monkeypatch.setattr("app.learning.provider.OpenAI", FakeOpenAI)
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
    assert captured["timeout"] == 180
    assert captured["max_retries"] == 0
    assert captured["base_url"] == "https://api.deepseek.com"
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

    monkeypatch.setattr("app.learning.provider.OpenAI", FakeOpenAI)
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
