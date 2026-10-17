import json

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.db import Database
from app.errors import ApiError
from app.learning.generic_provider import generic_model_settings
from app.learning.models import Contract
from app.learning.provider import ProviderCallFailure
from app.learning.structured_calls import GenericStructuredCalls, ModelCallClaim


class Result(Contract):
    answer: int


class ControlledProvider:
    def __init__(self, settings, outcome="success"):
        self.settings = generic_model_settings(settings)
        self.cache_model = "qwen3.8-max"
        self.cache_protocol = "chat_completions"
        self.cache_region = "ENDPOINT_CN"
        self.outcome = outcome
        self.calls = 0

    def generate(self, _schema, **kwargs):
        self.calls += 1
        sink = kwargs["transport_event_sink"]
        sink({"phase": "SEND_INTENT"})
        if self.outcome == "unknown":
            raise ProviderCallFailure(
                TimeoutError("TEST_ONLY timeout"),
                {
                    "status": "UNKNOWN",
                    "error_class": "TimeoutError",
                    "failure_layer": "PROVIDER_TRANSPORT",
                    "response_received": False,
                    "max_output_tokens": kwargs["max_output_tokens"],
                },
            )
        sink(
            {
                "phase": "RESPONSE_COMPLETE",
                "returned_model": "qwen3.8-max",
                "reasoning_effort_requested": "xhigh",
                "native_reasoning_observed": True,
                "usage_reported": True,
                "input_tokens": 10,
                "output_tokens": 4,
                "provider_response_id": "TEST_ONLY-response",
            }
        )
        return Result(answer=43), {"provider_response_id": "TEST_ONLY-response"}


def prepared(tmp_path, outcome="success"):
    settings = Settings(
        _env_file=None,
        app_env="test",
        v3_enabled=True,
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        generic_llm_enabled=True,
        cj_qwen_api_key=SecretStr("TEST_ONLY-placeholder"),
        cj_qwen_capability_receipt_id="TEST_ONLY-capability",
        cj_qwen_secret_generation_id="TEST_ONLY-generation",
    )
    database = Database(settings)
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO courses(id,name) VALUES('course','Course')")
    provider = ControlledProvider(settings, outcome)
    calls = GenericStructuredCalls(database, settings, provider)
    claim = ModelCallClaim("TEST_ONLY-call", "owner", "course", "en", lambda: None)
    arguments = {
        "instructions": "Return strict JSON.",
        "payload": {"TEST_ONLY": True},
        "role": "LLM_REVIEW",
        "operation_family": "TEST_ONLY_FAMILY",
        "template_version": "TEST_ONLY-v1",
        "schema_version": "TEST_ONLY-result-v1",
        "max_output_tokens": 1700,
    }
    return database, provider, calls, claim, arguments


def row_for(database, request_id):
    with database.connect() as connection:
        return dict(
            connection.execute(
                "SELECT * FROM generic_llm_calls WHERE id=?", (request_id,)
            ).fetchone()
        )


def test_completed_call_is_durable_and_idempotently_reused(tmp_path):
    database, provider, calls, claim, arguments = prepared(tmp_path)
    first = calls.generate_for(claim, Result, **arguments)
    second = calls.generate_for(claim, Result, **arguments)

    assert first == second == Result(answer=43)
    assert provider.calls == 1
    row = row_for(database, claim.request_id)
    assert row["status"] == "COMPLETED"
    assert (row["input_tokens"], row["output_tokens"]) == (10, 4)
    assert json.loads(row["output_json"]) == {"answer": 43}
    assert "TEST_ONLY-placeholder" not in row["audit_json"]


def test_unknown_call_is_never_replayed(tmp_path):
    database, provider, calls, claim, arguments = prepared(tmp_path, "unknown")
    with pytest.raises(TimeoutError):
        calls.generate_for(claim, Result, **arguments)
    original = row_for(database, claim.request_id)
    assert original["status"] == "UNKNOWN"

    with pytest.raises(ApiError) as replay:
        calls.generate_for(claim, Result, **arguments)
    assert replay.value.code == "MODEL_REQUEST_UNCERTAIN"
    assert provider.calls == 1
    assert row_for(database, claim.request_id) == original


def test_same_request_id_cannot_change_input_identity(tmp_path):
    _database, provider, calls, claim, arguments = prepared(tmp_path)
    calls.generate_for(claim, Result, **arguments)
    changed = dict(arguments)
    changed["payload"] = {"TEST_ONLY": "changed"}

    with pytest.raises(ApiError) as conflict:
        calls.generate_for(claim, Result, **changed)
    assert conflict.value.code == "MODEL_ANSWER_IDENTITY_CONFLICT"
    assert provider.calls == 1
