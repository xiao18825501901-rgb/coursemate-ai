"""Role-by-role fake-HTTP contract tests for the DeepSeek generation migration.

Every test here uses a fake upstream (``httpx.MockTransport`` or a recorded
OpenAI SDK double) - there are NO live or paid calls.  Each test asserts the
configured DeepSeek model + host and that the request body carries no Qwen-only
field.  The final host-spy test proves the official configuration sends ZERO
requests to any Qwen/dashscope host across all migrated roles.
"""

from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.cm_update.config import Settings as UiSettings
from app.cm_update.provider import DeepSeekProvider
from app.config import Settings
from app.learning.coverage_review import deepseek_review_invoke, resolve_coverage_reviewer
from app.learning.provider import LearningProvider
from app.rag.answers import DeepSeekAnswerProvider

DEEPSEEK_HOST = "api.deepseek.com"
QWEN_ONLY_FIELDS = ("enable_thinking", "max_pixels")
QWEN_HOST_MARKERS = ("aliyuncs", "dashscope", "qwen")


def _keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys |= _keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _keys(item)
    return keys


def ui_cfg(**kwargs: Any) -> UiSettings:
    params: dict[str, Any] = dict(
        provider_mode="deepseek",
        deepseek_base_url="https://api.deepseek.com",
        deepseek_key="test-not-real",
        deepseek_model="deepseek-flash",
        deepseek_protocol="responses",
        allow_billable=True,
    )
    params.update(kwargs)
    return UiSettings(**params)


def chat_sse(text: str, finish: str = "stop") -> str:
    return (
        "\n\n".join(
            "data: " + json.dumps(x, ensure_ascii=False)
            for x in [
                {"choices": [{"delta": {"content": text}, "finish_reason": None}]},
                {"choices": [{"delta": {}, "finish_reason": finish}], "usage": {"prompt_tokens": 3, "completion_tokens": 4}},
            ]
        )
        + "\n\ndata: [DONE]\n\n"
    )


def responses_sse(text: str, *, usage: dict | None = None) -> str:
    usage = usage or {"input_tokens": 5, "output_tokens": 6}
    return (
        "data: "
        + json.dumps({"type": "response.output_text.delta", "delta": text})
        + "\n\ndata: "
        + json.dumps({"type": "response.completed", "response": {"status": "completed", "usage": usage}})
        + "\n\n"
    )


# --------------------------------------------------------------------------
# Role 1: cm_update UI provider (teach / exercise / explanation / classification)
# --------------------------------------------------------------------------


async def _teach_args(provider: DeepSeekProvider, mode: str = "normal") -> list[dict]:
    items = [
        item
        async for item in provider.generate(
            {"name": "Data Science", "code": "CS3481"},
            "教我 DBSCAN",
            {"language": "zh-CN"},
            [{"id": "S1", "text": "density clustering"}],
            [],
            "teach",
            teaching_mode=mode,
        )
    ]
    return items


@pytest.mark.asyncio
async def test_ui_responses_stream_has_deepseek_model_and_no_qwen_fields() -> None:
    calls: list[tuple[str, dict]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, text=responses_sse("直接回答 [S1]"), headers={"content-type": "text/event-stream"})

    provider = DeepSeekProvider(ui_cfg(), httpx.MockTransport(transport))
    items = await _teach_args(provider)
    assert any(item["kind"] == "delta" and item["text"] == "直接回答 [S1]" for item in items)

    url, body = calls[0]
    assert url == "https://api.deepseek.com/responses"
    assert body["model"] == "deepseek-flash"
    assert body["stream"] is True
    assert body["reasoning"] == {"effort": "none"}
    assert "input" in body and "max_output_tokens" in body
    assert not (_keys(body) & set(QWEN_ONLY_FIELDS))


@pytest.mark.asyncio
async def test_ui_chat_completions_stream_has_no_enable_thinking() -> None:
    calls: list[tuple[str, dict]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, text=chat_sse("回答 [S1]"), headers={"content-type": "text/event-stream"})

    provider = DeepSeekProvider(ui_cfg(deepseek_protocol="chat_completions"), httpx.MockTransport(transport))
    await _teach_args(provider)

    url, body = calls[0]
    assert url == "https://api.deepseek.com/chat/completions"
    assert body["model"] == "deepseek-flash"
    assert body["thinking"] == {"type": "disabled"}
    assert body["max_tokens"] > 0
    assert not (_keys(body) & set(QWEN_ONLY_FIELDS))


@pytest.mark.asyncio
async def test_ui_exercise_uses_responses_text_format_json_schema() -> None:
    payload = {
        "question": "Which points are core points under DBSCAN?",
        "answer_steps": [{"title": "Count neighbours", "text": "Compare each eps-neighbourhood with MinPts."}],
        "references": ["S1"],
    }
    calls: list[tuple[str, dict]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, text=responses_sse(json.dumps(payload)), headers={"content-type": "text/event-stream"})

    provider = DeepSeekProvider(ui_cfg(), httpx.MockTransport(transport))
    items = [
        item
        async for item in provider.generate_exercise(
            {"name": "Data Science", "code": "CS3481"},
            {"title": "DBSCAN"},
            {"language": "zh-CN"},
            [{"id": "S1", "text": "density clustering"}],
        )
    ]
    url, body = calls[0]
    assert url == "https://api.deepseek.com/responses"
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["name"] == "coursemate_exercise_v2"
    assert "strict" not in body["text"]["format"]
    assert not (_keys(body) & set(QWEN_ONLY_FIELDS))
    assert not any(item["kind"] == "delta" for item in items)
    assert next(item["text"] for item in items if item["kind"] == "complete") == json.dumps(payload)


@pytest.mark.asyncio
async def test_ui_images_use_detail_and_never_max_pixels() -> None:
    captured: dict = {}

    def transport(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, text=responses_sse("看图回答"), headers={"content-type": "text/event-stream"})

    provider = DeepSeekProvider(ui_cfg(), httpx.MockTransport(transport))
    data_url = "data:image/png;base64," + base64.b64encode(b"fake").decode()
    # Build a message list the way generate() does, then attach images directly.
    messages = provider.direct_messages({"name": "x", "code": "x"}, "看图", {}, [], [], "teach")
    provider.attach_images(messages, [{"data_url": data_url}])
    content = messages[-1]["content"]
    parts = content if isinstance(content, list) else [content]
    image_parts = [p for p in parts if isinstance(p, dict) and p.get("type") == "input_image"]
    assert image_parts, parts
    assert image_parts[0]["image_url"] == data_url
    assert "max_pixels" not in _keys(image_parts[0])


# --------------------------------------------------------------------------
# Role 2: V3 LearningProvider (structured outputs + images)
# --------------------------------------------------------------------------


def _learning_provider_with_capture(monkeypatch: pytest.MonkeyPatch) -> tuple[LearningProvider, dict]:
    captured: dict = {}

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
        Settings(
            _env_file=None,
            app_env="development",
            rag_provider_mode="openai",
            v3_enabled=True,
            v3_model="deepseek-flash",
            v3_model_api_key="test-only-key",
            v3_model_base_url="https://api.deepseek.com",
            v3_model_timeout_seconds=180,
        )
    )
    return provider, captured


def test_learning_provider_uses_deepseek_payload_without_qwen_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import BaseModel

    class ExampleOutput(BaseModel):
        value: str

    provider, captured = _learning_provider_with_capture(monkeypatch)
    result, run = provider.generate(
        ExampleOutput, instructions="Return the fixture.", context={}, role="test"
    )

    assert result == ExampleOutput(value="ok")
    assert run["status"] == "COMPLETED"
    assert run["provider"] == "DEEPSEEK_API"
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["max_retries"] == 0
    request = captured["request"]
    assert request["model"] == "deepseek-flash"
    assert "enable_thinking" not in _keys(request)
    assert request["extra_body"]["reasoning"] == {"effort": "none"}
    assert request["extra_body"]["text"]["format"]["type"] == "json_schema"


def test_learning_provider_durably_reports_complete_response_before_schema_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import BaseModel

    from app.learning.provider import ProviderCallFailure

    class ExampleOutput(BaseModel):
        value: str

    class FakeOpenAI:
        def __init__(self, **_kwargs: Any) -> None:
            self.responses = SimpleNamespace(create=self.create)

        @staticmethod
        def create(**_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(
                id="response-invalid-contract",
                usage=SimpleNamespace(input_tokens=17, output_tokens=9),
                status="completed",
                output_text="not valid json",
            )

    monkeypatch.setattr("app.learning.provider.OpenAI", FakeOpenAI)
    provider = LearningProvider(
        Settings(
            _env_file=None,
            app_env="development",
            rag_provider_mode="openai",
            v3_enabled=True,
            v3_model="deepseek-flash",
            v3_model_api_key="test-only-key",
            v3_model_base_url="https://api.deepseek.com",
        )
    )
    events: list[dict[str, Any]] = []
    provider.transport_event_sink = events.append

    with pytest.raises(ProviderCallFailure) as raised:
        provider.generate(
            ExampleOutput,
            instructions="Return the fixture.",
            context={},
            role="test-invalid-contract",
        )

    assert [event["phase"] for event in events] == [
        "SEND_INTENT",
        "RESPONSE_COMPLETE",
        "CONTRACT_REJECTED",
    ]
    assert events[1] == {
        "phase": "RESPONSE_COMPLETE",
        "provider": "DEEPSEEK_API",
        "model": "deepseek-flash",
        "protocol": "responses",
        "role": "test-invalid-contract",
        "input_hash": events[0]["input_hash"],
        "provider_response_id": "response-invalid-contract",
        "provider_status": "completed",
        "input_tokens": 17,
        "output_tokens": 9,
        "output_text": "not valid json",
    }
    assert raised.value.run["status"] == "FAILED"
    assert raised.value.run["error_class"] == "SCHEMA_INVALID"


def test_learning_provider_does_not_send_when_transport_intent_cannot_be_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import BaseModel

    from app.learning.provider import ProviderCallFailure

    class ExampleOutput(BaseModel):
        value: str

    called = False

    class FakeOpenAI:
        def __init__(self, **_kwargs: Any) -> None:
            self.responses = SimpleNamespace(create=self.create)

        @staticmethod
        def create(**_kwargs: Any) -> SimpleNamespace:
            nonlocal called
            called = True
            raise AssertionError("the provider send must remain unreachable")

    monkeypatch.setattr("app.learning.provider.OpenAI", FakeOpenAI)
    provider = LearningProvider(
        Settings(
            _env_file=None,
            app_env="development",
            rag_provider_mode="openai",
            v3_enabled=True,
            v3_model="deepseek-flash",
            v3_model_api_key="test-only-key",
            v3_model_base_url="https://api.deepseek.com",
        )
    )

    def fail_closed(_event: dict[str, Any]) -> None:
        raise OSError("synthetic durable ledger failure")

    provider.transport_event_sink = fail_closed
    with pytest.raises(ProviderCallFailure) as raised:
        provider.generate(
            ExampleOutput,
            instructions="Return the fixture.",
            context={},
            role="test-ledger-failure",
        )

    assert called is False
    assert raised.value.run["status"] == "UNKNOWN"
    assert raised.value.run["error_class"] == "OSError"


def test_learning_provider_rejects_non_deepseek_host_for_deepseek_model() -> None:
    from pydantic import BaseModel

    from app.learning.provider import ProviderCallFailure

    provider = LearningProvider(
        Settings(
            _env_file=None,
            app_env="development",
            rag_provider_mode="openai",
            v3_enabled=True,
            v3_model="deepseek-flash",
            v3_model_api_key="test-only-key",
            v3_model_base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        )
    )

    class ExampleOutput(BaseModel):
        value: str

    with pytest.raises(ProviderCallFailure) as error:
        provider.generate(ExampleOutput, instructions="x", context={}, role="test")
    assert error.value.run["error_class"] == "MODEL_ENDPOINT_INVALID"


# --------------------------------------------------------------------------
# Role 3: coverage reviewer transport
# --------------------------------------------------------------------------


def test_coverage_review_uses_deepseek_chat_completions_without_enable_thinking() -> None:
    captured: dict = {}

    def transport(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"verdicts":[]}'}, "finish_reason": "stop"}]})

    invoke = deepseek_review_invoke(
        base_url="https://api.deepseek.com",
        api_key="redacted",
        model="deepseek-flash",
        timeout=30,
        allow_billable=True,
        transport=httpx.MockTransport(transport),
    )
    result = asyncio.run(invoke([{"role": "user", "content": "x"}], 100))
    assert result == '{"verdicts":[]}'
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["body"]["model"] == "deepseek-flash"
    assert captured["body"]["thinking"] == {"type": "disabled"}
    assert "enable_thinking" not in _keys(captured["body"])


def test_coverage_review_resolver_defaults_to_deepseek() -> None:
    reviewer = resolve_coverage_reviewer(
        "production",
        "model",
        allow_billable=True,
        base_url="https://api.deepseek.com",
        api_key="redacted",
        model="deepseek-flash",
    )
    assert reviewer.model == "deepseek-flash"


# --------------------------------------------------------------------------
# Role 4: grounded QA answer provider
# --------------------------------------------------------------------------


def test_qa_answer_provider_streams_from_deepseek() -> None:
    captured: dict = {}

    class FakeResponses:
        def create(self, **kwargs: Any) -> list[Any]:
            captured["request"] = kwargs
            return [SimpleNamespace(type="response.output_text.delta", delta="grounded")]

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()

    provider = DeepSeekAnswerProvider(api_key="redacted", client=FakeClient())  # type: ignore[arg-type]
    text = list(provider.stream_answer(question="q", context="c", instructions="i"))
    assert text == ["grounded"]
    assert captured["request"]["model"] == "deepseek-flash"
    assert captured["request"]["extra_body"]["reasoning"] == {"effort": "none"}
    assert not (_keys(captured["request"]) & set(QWEN_ONLY_FIELDS))


def test_qa_answer_provider_rejects_random_base_url() -> None:
    with pytest.raises(ValueError):
        DeepSeekAnswerProvider(api_key="redacted", base_url="https://random.example.com")


# --------------------------------------------------------------------------
# Host spy: ZERO Qwen/dashscope egress across the migrated roles
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_host_spy_zero_qwen_egress_across_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    egress: dict[str, list[str]] = {}

    # Role 1 - UI provider (teach + exercise + explanation + classification).
    ui_urls: list[str] = []
    exercise_output = json.dumps(
        {
            "question": "Which points are core points under DBSCAN?",
            "answer_steps": [{"title": "Count neighbours", "text": "Compare each eps-neighbourhood."}],
            "references": [],
        }
    )

    def ui_transport(request: httpx.Request) -> httpx.Response:
        ui_urls.append(str(request.url))
        return httpx.Response(200, text=responses_sse(exercise_output), headers={"content-type": "text/event-stream"})

    ui = DeepSeekProvider(ui_cfg(), httpx.MockTransport(ui_transport))
    async for _ in ui.generate({"name": "x", "code": "x"}, "teach", {}, [], [], "teach"):
        pass
    async for _ in ui.generate_exercise({"name": "x", "code": "x"}, {"title": "n"}, {}, []):
        pass
    async for _ in ui.generate_explanation({"name": "x", "code": "x"}, "q", "a", "s", {}, []):
        pass
    await ui.classify_course_with_usage({"course": {}})
    egress["ui"] = list(ui_urls)

    # Role 2 - V3 LearningProvider (base URL is the SDK egress host).
    learning_capture: dict = {}

    class LearningFakeOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            learning_capture.update(kwargs)
            self.responses = SimpleNamespace(create=self.create)

        @staticmethod
        def create(**kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(
                id="r", usage=SimpleNamespace(input_tokens=0, output_tokens=0),
                status="completed", output_text='{"value":"ok"}',
            )

    monkeypatch.setattr("app.learning.provider.OpenAI", LearningFakeOpenAI)
    from pydantic import BaseModel

    class _Out(BaseModel):
        value: str

    learning = LearningProvider(
        Settings(
            _env_file=None, app_env="development", rag_provider_mode="openai",
            v3_enabled=True, v3_model="deepseek-flash", v3_model_api_key="k",
            v3_model_base_url="https://api.deepseek.com",
        )
    )
    learning.generate(_Out, instructions="i", context={}, role="test")
    egress["learning"] = [str(learning_capture.get("base_url", ""))]

    # Role 3 - coverage reviewer.
    review_urls: list[str] = []

    def review_transport(request: httpx.Request) -> httpx.Response:
        review_urls.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})

    invoke = deepseek_review_invoke(
        base_url="https://api.deepseek.com",
        api_key="redacted",
        model="deepseek-flash",
        timeout=30,
        allow_billable=True,
        transport=httpx.MockTransport(review_transport),
    )
    await invoke([{"role": "user", "content": "x"}], 100)
    egress["coverage_review"] = list(review_urls)

    # Role 4 - grounded QA (base URL is the SDK egress host).
    qa_capture: dict = {}

    class QaFakeOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            qa_capture.update(kwargs)
            self.responses = SimpleNamespace(create=lambda **kw: iter([]))

    monkeypatch.setattr("app.rag.answers.OpenAI", QaFakeOpenAI)
    qa = DeepSeekAnswerProvider(api_key="redacted")
    list(qa.stream_answer(question="q", context="c", instructions="i"))
    egress["rag_qa"] = [str(qa_capture.get("base_url", ""))]

    for role, urls in egress.items():
        assert urls and all(urls), f"{role} made no egress to inspect: {urls}"
        for url in urls:
            host = url.split("/")[2] if "://" in url else url
            assert DEEPSEEK_HOST in host, f"{role} egressed to non-DeepSeek host: {url}"
            assert not any(marker in host.lower() for marker in QWEN_HOST_MARKERS), (
                f"{role} egressed to a Qwen/dashscope host: {url}"
            )


# --------------------------------------------------------------------------
# Production settings: no silent Qwen fallback
# --------------------------------------------------------------------------


def test_ui_settings_deepseek_mode_requires_deepseek_credential() -> None:
    settings = ui_cfg()
    settings.validate()  # valid deepseek configuration passes

    missing_key = ui_cfg(deepseek_key="")
    with pytest.raises(ValueError, match="DeepSeek credential"):
        missing_key.validate()

    wrong_model = ui_cfg(deepseek_model="qwen3.8-max")
    with pytest.raises(ValueError, match="deepseek-flash"):
        wrong_model.validate()


def test_v3_default_model_is_deepseek_not_qwen() -> None:
    settings = Settings(_env_file=None)
    assert settings.v3_model == "deepseek-flash"
    assert settings.deepseek_chat_model == "deepseek-flash"
    assert settings.deepseek_chat_base_url == "https://api.deepseek.com"
