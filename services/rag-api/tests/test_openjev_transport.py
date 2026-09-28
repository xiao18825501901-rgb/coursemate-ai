from __future__ import annotations

import json

import httpx
import pytest

from app.jev.errors import JevInvalidResponseError, JevUnavailableError
from app.jev.gateway import DisabledTransport, OpenJevTransport
from app.jev.models import JevCall, JevQuestion


def call() -> JevCall:
    return JevCall(
        state={"question_text": "Which result is supported?", "allowed_rules": ["R1"]},
        questions={
            "question.ambiguity.v1": JevQuestion(
                key="question.ambiguity.v1",
                primitive="Choice",
                instructions="Is the question unambiguous?",
                criteria={"CLEAR": "clear", "AMBIGUOUS": "ambiguous"},
            )
        },
    )


def response(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "status": "COMPLETED",
        "provider": "open-jev-selfhost",
        "request_id": "openjev-request-1",
        "model": {
            "id": "onnx-community/open-jev-deberta-v3-large-ONNX",
            "revision": "model-revision-1",
            "dtype": "q4",
            "library_commit": "52667199e8a55553e1865a41f43fcb7d4dd92779",
            "tokenizer_hash": "a" * 64,
            "weights_hash": "b" * 64,
        },
        "input": {
            "truncated": False,
            "source_language": "en",
            "served_language": "en",
            "transform_version": "coursejesus-openjev-input.v1",
        },
        "answers": {
            "question.ambiguity.v1": {
                "type": "choice",
                "choice": "CLEAR",
                "confidence": 0.91,
                "probabilities": {"CLEAR": 0.91, "AMBIGUOUS": 0.09},
            }
        },
        "timing": {"queue_ms": 1.5, "inference_ms": 20.0},
    }
    value.update(overrides)
    return value


def transport(handler) -> OpenJevTransport:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenJevTransport(
        endpoint="http://127.0.0.1:8765",
        bearer_token="secret",
        expected_model_revision="model-revision-1",
        client=client,
    )


def test_openjev_transport_sends_one_authenticated_request_and_keeps_distribution() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer secret"
        payload = json.loads(request.content)
        assert payload["questions"]["question.ambiguity.v1"]["options"] == [
            "CLEAR",
            "AMBIGUOUS",
        ]
        assert payload["truncation"] == "error"
        return httpx.Response(200, json=response())

    result = transport(handler).call(call(), timeout_seconds=2)

    assert len(requests) == 1
    assert result.answers["question.ambiguity.v1"].choice == "CLEAR"
    assert result.answers["question.ambiguity.v1"].raw["probabilities"] == {
        "CLEAR": 0.91,
        "AMBIGUOUS": 0.09,
    }
    assert result.metadata["provider"] == "open-jev-selfhost"


def test_source_language_is_computed_from_content_not_schema_keys() -> None:
    assert OpenJevTransport._language(
        {"question_text": "这是一个条件完整的问题。", "question_type": "short_answer"}
    ) == "zh"
    assert OpenJevTransport._language({"question_text": "这是 SQL 问题。"}) == "mixed"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda body: body.update(provider="typesafe"),
        lambda body: body["model"].update(revision="other"),
        lambda body: body["input"].update(truncated=True),
        lambda body: body["answers"]["question.ambiguity.v1"].update(
            probabilities={"CLEAR": 0.9, "AMBIGUOUS": 0.9}
        ),
    ],
)
def test_openjev_transport_rejects_untrusted_or_invalid_response(mutator) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        body = response()
        mutator(body)
        return httpx.Response(200, json=body)

    with pytest.raises(JevInvalidResponseError):
        transport(handler).call(call(), timeout_seconds=2)


def test_openjev_transport_has_no_implicit_retry() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("offline")

    with pytest.raises(JevUnavailableError):
        transport(handler).call(call(), timeout_seconds=2)
    assert attempts == 1


def test_disabled_transport_never_attempts_typesafe() -> None:
    with pytest.raises(JevUnavailableError, match="disabled"):
        DisabledTransport().call(call(), timeout_seconds=2)
