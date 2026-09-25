"""P5 recovery contract through real orchestration and fake HTTP upstreams.

This is deliberately not the deterministic ``LearningProvider`` fixture path.
The real OpenAI Responses adapter serializes both structured requests, the real
SDK parses both HTTP responses, the real orchestrator reserves/finalizes each
call, and the real Jev gateway persists its required receipts.  Only the two
remote servers are replaced with labelled ``httpx.MockTransport`` handlers, so
the test is offline and non-billable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI
from pydantic import SecretStr
from test_question_persistence import (
    COURSE,
    NODE,
    OWNER,
    PRIVATE_COURSE,
    WORKSPACE,
    database_with_objective,
)

from app.jev.catalog import load_catalog
from app.jev.gateway import JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService
from app.learning.orchestrator import LearningOrchestrator
from app.learning.provider import LearningProvider
from app.learning.testing import fixture_output
from app.rag.retrieval import HybridRetriever
from app.repositories.chunks import ChunkRepository


class FixedEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


def _responses_payload(output: dict[str, Any], ordinal: int) -> dict[str, Any]:
    text = json.dumps(output, ensure_ascii=False)
    return {
        "id": f"resp_fake_http_{ordinal}",
        "object": "response",
        "created_at": ordinal,
        "status": "completed",
        "background": False,
        "billing": {"payer": "developer"},
        "error": None,
        "incomplete_details": None,
        "instructions": "versioned instruction",
        "max_output_tokens": 4000,
        "max_tool_calls": None,
        "model": "deepseek-flash",
        "output": [
            {
                "id": f"msg_fake_http_{ordinal}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "annotations": [],
                        "logprobs": [],
                        "text": text,
                    }
                ],
            }
        ],
        "parallel_tool_calls": False,
        "previous_response_id": None,
        "prompt_cache_key": None,
        "prompt_cache_retention": None,
        "reasoning": {"effort": "none", "summary": None},
        "safety_identifier": None,
        "service_tier": "default",
        "store": False,
        "temperature": 1.0,
        "text": {"format": {"type": "text"}, "verbosity": "medium"},
        "tool_choice": "auto",
        "tools": [],
        "top_logprobs": 0,
        "top_p": 1.0,
        "truncation": "disabled",
        "usage": {
            "input_tokens": 30 + ordinal,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 20 + ordinal,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 50 + (2 * ordinal),
        },
        "user": None,
        "metadata": {},
    }


class FakeHttpJevTransport:
    """HTTP-backed test adapter beneath the production Jev gateway."""

    model_version = "jev-fake-http-v1"

    def __init__(self) -> None:
        self.calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            key = str(payload["definition"])
            verdict = {
                "question.ambiguity.v1": "CLEAR",
                "question.answer_agreement.v1": "AGREE",
            }[key]
            return httpx.Response(
                200,
                json={
                    "request_id": f"jev-fake-http-{len(self.calls)}",
                    "model_version": self.model_version,
                    "choice": verdict,
                },
            )

        self.client = httpx.Client(transport=httpx.MockTransport(handler))

    def call(self, call: Any, *, timeout_seconds: float) -> JevResult:
        key = str(next(iter(call.questions)))
        self.calls.append(key)
        response = self.client.post(
            "https://jev.fake.invalid/system-one",
            json={"definition": key, "state": call.state},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return JevResult(
            answers={key: JevAnswer(choice=payload["choice"])},
            request_id=payload["request_id"],
            model_version=payload["model_version"],
        )


def test_real_question_orchestrator_completes_over_fake_http_upstreams(
    tmp_path: Path,
) -> None:
    database, base_config = database_with_objective(tmp_path)
    live_config = base_config.model_copy(
        update={
            "app_env": "development",
            "rag_provider_mode": "openai",
            "v3_model": "deepseek-flash",
            "v3_model_api_key": SecretStr("fake-http-only"),
            "v3_model_base_url": "https://api.deepseek.com",
            "v3_max_output_tokens": 4000,
            "v3_model_timeout_seconds": 60,
            "v3_daily_model_calls_per_user": 10,
            "v3_daily_model_calls_per_user_course": 10,
        }
    )
    deepseek_requests: list[dict[str, Any]] = []

    def deepseek_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert str(request.url) == "https://api.deepseek.com/responses"
        assert body["model"] == "deepseek-flash"
        assert body["reasoning"] == {"effort": "none"}
        assert body["store"] is False and body["tools"] == []
        serialized = body["input"]
        assert isinstance(serialized, str)
        envelope = json.loads(serialized)
        schema_name = str(body["text"]["format"]["name"])
        output = fixture_output(schema_name, envelope["authorized_context"])
        deepseek_requests.append(body)
        return httpx.Response(
            200,
            json=_responses_payload(output, len(deepseek_requests)),
        )

    provider = LearningProvider(live_config)
    transport_events: list[dict[str, Any]] = []
    provider.transport_event_sink = transport_events.append
    provider.client = OpenAI(
        api_key="fake-http-only",
        base_url="https://api.deepseek.com",
        max_retries=0,
        timeout=60,
        http_client=httpx.Client(transport=httpx.MockTransport(deepseek_handler)),
    )
    jev_transport = FakeHttpJevTransport()
    decisions = SemanticDecisionService(
        JevGateway(
            transport=jev_transport,
            catalog=load_catalog(),
            modes={
                "exercise.prototype.v1": "off",
                "question.ambiguity.v1": "on",
                "question.answer_agreement.v1": "on",
            },
            receipt_store=SqlReceiptStore(database),
        )
    )
    orchestrator = LearningOrchestrator(
        database,
        live_config,
        HybridRetriever(ChunkRepository(database), FixedEmbeddingProvider()),
        jev=decisions,
    )
    orchestrator.provider = provider
    orchestrator.question_engine.provider = provider

    result = orchestrator.question_engine.generate_one(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        operation_id="p5-fake-http-question-0001",
    )

    assert result["status"] == "READY"
    assert len(deepseek_requests) == 2
    assert [event["phase"] for event in transport_events] == [
        "SEND_INTENT",
        "RESPONSE_COMPLETE",
        "CONTRACT_VALID",
        "SEND_INTENT",
        "RESPONSE_COMPLETE",
        "CONTRACT_VALID",
    ]
    assert [
        event["role"]
        for event in transport_events
        if event["phase"] == "RESPONSE_COMPLETE"
    ] == ["QUESTION_AUTHOR", "QUESTION_BLIND_SOLVER"]
    assert all(
        event.get("output_text")
        for event in transport_events
        if event["phase"] == "RESPONSE_COMPLETE"
    )
    assert jev_transport.calls == [
        "question.ambiguity.v1",
        "question.answer_agreement.v1",
    ]
    with database.connect() as connection:
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT role,status FROM learning_model_call_reservations "
                "WHERE operation_id=? ORDER BY rowid",
                ("p5-fake-http-question-0001",),
            ).fetchall()
        ] == [
            ("QUESTION_AUTHOR", "COMPLETED"),
            ("QUESTION_BLIND_SOLVER", "COMPLETED"),
        ]
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT role,status,provider_response_id,input_tokens,output_tokens "
                "FROM learning_model_run_evidence WHERE operation_id=? ORDER BY rowid",
                ("p5-fake-http-question-0001",),
            ).fetchall()
        ] == [
            ("QUESTION_AUTHOR", "COMPLETED", "resp_fake_http_1", 31, 21),
            ("QUESTION_BLIND_SOLVER", "COMPLETED", "resp_fake_http_2", 32, 22),
        ]
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT definition_key,mode,outcome FROM jev_decision_receipts "
                "ORDER BY created_at,rowid"
            ).fetchall()
        ] == [
            ("question.ambiguity.v1", "on", "ok"),
            ("question.answer_agreement.v1", "on", "ok"),
        ]
        question_hash = connection.execute(
            "SELECT question_revision_hash FROM question_engine_provenance "
            "WHERE question_revision_id=?",
            (result["question_revision_id"],),
        ).fetchone()[0]
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT definition_key,mode,outcome FROM jev_decision_receipts "
                "WHERE question_hash=? ORDER BY created_at,rowid",
                (question_hash,),
            ).fetchall()
        ] == [
            ("question.ambiguity.v1", "on", "ok"),
            ("question.answer_agreement.v1", "on", "ok"),
        ]
