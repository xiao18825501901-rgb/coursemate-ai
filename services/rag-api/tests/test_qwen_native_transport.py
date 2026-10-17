import json

import httpx
import pytest
from openai import OpenAI
from pydantic import BaseModel, SecretStr

from app.config import Settings
from app.learning.generic_provider import generic_model_settings
from app.learning.provider import LearningProvider, ProviderCallFailure

ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1"
PRIVATE_REASONING = "TEST_ONLY_PRIVATE_REASONING_MUST_NOT_SURVIVE"


class Result(BaseModel):
    answer: int


def generic_settings():
    return Settings(
        _env_file=None,
        app_env="development",
        generic_llm_enabled=True,
        cj_qwen_api_key=SecretStr("TEST_ONLY-placeholder"),
        cj_qwen_base_url=ENDPOINT,
        cj_qwen_capability_receipt_id="TEST_ONLY-capability",
        cj_qwen_secret_generation_id="TEST_ONLY-generation",
    )


class Boundary:
    def __init__(self, fault=None):
        self.fault = fault
        self.sent = []

    def __call__(self, request):
        body = json.loads(request.content)
        self.sent.append((request.url.path, body))
        if request.url.path.endswith("/responses"):
            return httpx.Response(
                200,
                json={
                    "id": "TEST_ONLY-tree-response",
                    "object": "response",
                    "created_at": 1,
                    "model": "deepseek-flash",
                    "status": "completed",
                    "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
                    "output": [
                        {
                            "id": "TEST_ONLY-message",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": '{"answer":43}',
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                },
            )

        def chunk(delta, finish=None):
            return {
                "id": "TEST_ONLY-stream-response",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "qwen3.8-plus" if self.fault == "wrong_model" else "qwen3.8-max",
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }

        chunks = [
            chunk({"role": "assistant", "reasoning_content": PRIVATE_REASONING}),
            chunk({"content": '{"answer":'}),
            chunk({"content": "43}"}),
        ]
        if self.fault != "early_eof":
            chunks.append(chunk({}, "stop"))
        if self.fault != "missing_usage":
            usage = chunk({})
            usage["choices"] = []
            usage["usage"] = {
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "total_tokens": 18,
            }
            chunks.append(usage)
        wire = "".join("data: " + json.dumps(value) + "\n\n" for value in chunks)
        if self.fault != "early_eof":
            wire += "data: [DONE]\n\n"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=wire.encode(),
        )


def adapter_for(settings, boundary):
    adapter = LearningProvider(settings)
    adapter.client = OpenAI(
        api_key="TEST_ONLY-placeholder",
        base_url=settings.v3_model_base_url,
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(boundary)),
    )
    return adapter


def generate(adapter, events):
    return adapter.generate(
        Result,
        instructions="Return one strict JSON object.",
        context={"TEST_ONLY": True},
        role="LLM_REVIEW",
        max_output_tokens=1700,
        transport_event_sink=events.append,
    )


def test_native_qwen_stream_returns_only_public_json_and_usage():
    boundary, events = Boundary(), []
    adapter = adapter_for(generic_model_settings(generic_settings()), boundary)
    try:
        output, run = generate(adapter, events)
        assert output.model_dump() == {"answer": 43}
        assert run["status"] == "COMPLETED"
        assert run["input_tokens"] == 11 and run["output_tokens"] == 7
        assert len(boundary.sent) == 1
        path, body = boundary.sent[0]
        assert path.endswith("/chat/completions")
        assert body["stream"] is True
        assert body["stream_options"] == {"include_usage": True}
        assert body["enable_thinking"] is True
        assert body["reasoning_effort"] == "xhigh"
        assert body["max_tokens"] == 1700
        assert PRIVATE_REASONING not in json.dumps([output.model_dump(), run, events])
    finally:
        adapter.client.close()


@pytest.mark.parametrize(
    "fault,code",
    [
        ("early_eof", "MODEL_INCOMPLETE"),
        ("missing_usage", "MODEL_USAGE_MISSING"),
        ("wrong_model", "MODEL_IDENTITY_MISMATCH"),
    ],
)
def test_native_qwen_stream_fails_without_fallback_or_private_trace(fault, code):
    boundary, events = Boundary(fault), []
    adapter = adapter_for(generic_model_settings(generic_settings()), boundary)
    try:
        with pytest.raises(ProviderCallFailure) as caught:
            generate(adapter, events)
        assert caught.value.run["error_class"] == code
        assert len(boundary.sent) == 1
        assert "CONTRACT_VALID" not in [event["phase"] for event in events]
        assert PRIVATE_REASONING not in json.dumps([caught.value.run, events])
    finally:
        adapter.client.close()


def test_deepseek_tree_transport_remains_responses_and_thinking_off():
    settings = generic_model_settings(generic_settings()).model_copy(
        update={
            "v3_model": "deepseek-flash",
            "v3_model_base_url": "https://api.deepseek.com",
        }
    )
    boundary, events = Boundary(), []
    adapter = adapter_for(settings, boundary)
    try:
        output, _ = generate(adapter, events)
        assert output.answer == 43
        path, body = boundary.sent[0]
        assert path.endswith("/responses")
        assert body["reasoning"] == {"effort": "none"}
        assert not {"enable_thinking", "reasoning_effort", "stream_options"}.intersection(body)
    finally:
        adapter.client.close()
