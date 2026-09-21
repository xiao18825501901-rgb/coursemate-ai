"""End-to-end endpoint behaviour with the fake model (no torch, no network)."""

from __future__ import annotations

import threading
import time

from app.definitions import DefinitionsRegistry
from app.main import create_app
from app.model import FakeModel
from app.settings import Settings
from fastapi.testclient import TestClient

from tests.fake_agent import make_fake, noul_result

TRIAGE = {
    "department": {
        "type": "choice",
        "instructions": "Which department?",
        "criteria": {"billing": "payments, refunds", "technical": "bugs, outages"},
    },
    "churn": {"type": "noul", "instructions": "Does the user threaten to cancel?"},
}


def _registry() -> DefinitionsRegistry:
    return DefinitionsRegistry.from_dict(
        {
            "definitions": [
                {
                    "decision_definition_id": "course-triage",
                    "definition_version": "1",
                    "compiler_versions": ["1.0.0"],
                    "max_questions": 10,
                    "max_options_per_question": 20,
                    "questions": TRIAGE,
                }
            ]
        }
    )


def _client(settings=None, model=None, registry=None) -> TestClient:
    settings = settings or Settings(model_backend="fake", app_env="test")
    return TestClient(
        create_app(settings=settings, model=model, registry=registry or _registry())
    )


def _decision_body(**overrides) -> dict:
    body = {
        "request_id": "req-0001",
        "decision_definition_id": "course-triage",
        "definition_version": "1",
        "compiled_state": {"body": "billed twice, please refund"},
        "questions": TRIAGE,
        "deadline_ms": 5000,
        "model_revision": "1c5edc17a7acd8701df6fc341c0d179f1c62c982",
        "compiler_version": "1.0.0",
    }
    body.update(overrides)
    return body


def _wait_ready(client: TestClient, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if client.get("/health/ready").status_code == 200:
            return
        time.sleep(0.01)
    raise AssertionError("service did not become ready")


def test_live_is_true_before_model_ready() -> None:
    entered = threading.Event()
    release = threading.Event()

    def load_fn() -> None:
        entered.set()
        release.wait(timeout=10)

    model = FakeModel(load_fn=load_fn)
    with _client(model=model) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/live").json()["status"] == "alive"
        assert client.get("/health/ready").status_code == 503
        release.set()
        _wait_ready(client)
        assert client.get("/health/ready").json()["status"] == "ready"


def test_model_info_reports_fake_backend() -> None:
    with _client() as client:
        _wait_ready(client)
        res = client.get("/internal/v1/model-info")
        assert res.status_code == 200
        data = res.json()
        assert data["real_inference"] is False
        assert data["model"]["backend"] == "fake"


def test_decision_ok() -> None:
    with _client() as client:
        _wait_ready(client)
        res = client.post("/internal/v1/decisions", json=_decision_body())
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "OK"
        assert data["answers"] is not None
        assert data["answers"]["department"]["type"] == "choice"
        assert data["answers"]["churn"]["type"] == "noul"
        assert data["receipt_id"]
        assert data["calibration_version"] == "none"


def test_unsupported_definition_rejected() -> None:
    with _client() as client:
        _wait_ready(client)
        res = client.post(
            "/internal/v1/decisions",
            json=_decision_body(decision_definition_id="does-not-exist"),
        )
        assert res.status_code == 422
        assert res.json()["status"] == "UNSUPPORTED_DEFINITION"


def test_unknown_compiler_version_rejected() -> None:
    with _client() as client:
        _wait_ready(client)
        res = client.post(
            "/internal/v1/decisions",
            json=_decision_body(compiler_version="99.0.0"),
        )
        assert res.status_code == 422
        assert res.json()["status"] == "UNSUPPORTED_DEFINITION"


def test_schema_mismatch_rejected() -> None:
    with _client() as client:
        _wait_ready(client)
        bad = _decision_body()
        bad["questions"] = {
            "department": {
                "type": "choice",
                "instructions": "A DIFFERENT PROMPT",
                "criteria": {"billing": "payments, refunds", "technical": "bugs, outages"},
            },
            "churn": {"type": "noul", "instructions": "Does the user threaten to cancel?"},
        }
        res = client.post("/internal/v1/decisions", json=bad)
        assert res.status_code == 422
        assert res.json()["status"] == "INVALID_REQUEST"


def test_input_too_long_rejected() -> None:
    def token_fn(state, questions):
        from app.model import TokenDiagnostics

        return TokenDiagnostics(
            total_tokens=999_999,
            per_question_tokens={"department": 999_999, "churn": 999_999},
            state_tokens=999_999,
            max_len=1024,
            head_max_len=256,
            options_not_fit=(),
            truncated=True,
        )

    model = make_fake(token_fn=token_fn)
    with _client(model=model) as client:
        _wait_ready(client)
        res = client.post("/internal/v1/decisions", json=_decision_body())
        assert res.status_code == 422
        assert res.json()["status"] == "INPUT_TOO_LONG"


def test_deadline_exceeded() -> None:
    def slow(state, questions):
        time.sleep(0.3)
        return noul_result()

    model = make_fake(predict_fn=slow)
    with _client(model=model) as client:
        _wait_ready(client)
        res = client.post("/internal/v1/decisions", json=_decision_body(deadline_ms=50))
        assert res.status_code == 408
        data = res.json()
        assert data["status"] == "DEADLINE_EXCEEDED"
        assert data["answers"] is None


def test_model_not_ready_rejected() -> None:
    entered = threading.Event()
    release = threading.Event()

    def load_fn() -> None:
        entered.set()
        release.wait(timeout=10)

    model = FakeModel(load_fn=load_fn)
    with _client(model=model) as client:
        assert client.get("/health/live").status_code == 200
        res = client.post("/internal/v1/decisions", json=_decision_body())
        assert res.status_code == 503
        assert res.json()["status"] == "MODEL_NOT_READY"
        release.set()
        _wait_ready(client)


def test_oversized_body_rejected() -> None:
    settings = Settings(model_backend="fake", app_env="test", max_body_bytes=1024)
    with _client(settings=settings) as client:
        _wait_ready(client)
        big = _decision_body()
        big["compiled_state"] = "x" * 5000
        res = client.post("/internal/v1/decisions", json=big)
        assert res.status_code == 413


def test_auth_required_for_internal() -> None:
    settings = Settings(
        model_backend="fake", app_env="test", service_token="test-secret-token"
    )
    with _client(settings=settings) as client:
        _wait_ready(client)
        assert client.get("/internal/v1/model-info").status_code == 401
        res = client.get(
            "/internal/v1/model-info",
            headers={"Authorization": "Bearer test-secret-token"},
        )
        assert res.status_code == 200


def test_health_is_unauthenticated() -> None:
    settings = Settings(
        model_backend="fake", app_env="test", service_token="test-secret-token"
    )
    with _client(settings=settings) as client:
        assert client.get("/health/live").status_code == 200
