"""Server-route budget contracts for billable UI operations.

The provider below is a contract double: it never contacts Qwen. It proves the
route gate receives a server-side estimate, rejects medium before generation,
and persists the same estimate snapshot for an allowed high-strength run.
"""
from decimal import Decimal
import hashlib
import json
import time

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.cm_update.budget import OperationEstimate
from app.main import create_app
from test_current_change_features import (
    FakeAuthVerifier,
    FakeEmbeddingProvider,
    UI,
    auth,
    make_course,
    make_settings,
    wait_terminal,
)


class BudgetProbeProvider:
    def __init__(self) -> None:
        self.generate_calls = 0
        self.classification_calls = 0
        self.estimate_modes = []
        self.estimated_usd = Decimal("0.21")

    def estimate_generation(self, *_args, **_kwargs) -> OperationEstimate:
        self.estimate_modes.append(_kwargs.get("teaching_mode"))
        return OperationEstimate(
            usd=self.estimated_usd,
            input_tokens=100,
            output_tokens=200,
            stage_count=1,
            image_inputs=0,
            stages=(
                {
                    "name": "answer",
                    "input_tokens_upper_bound": 100,
                    "output_tokens_upper_bound": 200,
                    "image_inputs": 0,
                },
            ),
        )

    def estimate_classification(self, *_args, **_kwargs) -> OperationEstimate:
        return self.estimate_generation()

    async def generate(self, *_args, **_kwargs):
        self.generate_calls += 1
        yield {"kind": "status", "status": "generating", "label": "generating"}
        yield {"kind": "delta", "text": "预算合同测试输出"}
        yield {"kind": "usage", "stage": "answer", "value": {"input_tokens": 1, "output_tokens": 1}}

    async def classify_course(self, *_args, **_kwargs) -> str:
        self.classification_calls += 1
        return '{"template_id":"OTHER","decision":"other","degree_level":"unknown","confidence":0,"alternatives":[],"reason":"test","evidence_refs":[]}'

    async def classify_course_with_usage(self, *_args, **_kwargs) -> tuple[str, list[dict]]:
        result = await self.classify_course()
        return result, [{"input_tokens": 11, "output_tokens": 7}]


def test_qwen_route_uses_server_estimate_before_generation_and_snapshots_it(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("CMUI_PROVIDER_MODE", "qwen")
    monkeypatch.setenv("CMUI_ALLOW_BILLABLE", "true")
    monkeypatch.setenv("CMUI_OPERATION_USD_BASELINE", "0.20")
    monkeypatch.setenv("CMUI_OPERATION_INPUT_USD_PER_MILLION", "2")
    monkeypatch.setenv("CMUI_OPERATION_OUTPUT_USD_PER_MILLION", "10")

    settings = make_settings(tmp_path)
    settings.v3_model_api_key = SecretStr("test-not-real")
    settings.v3_model_base_url = "https://qwen.example.test/v1"
    provider = BudgetProbeProvider()
    application = create_app(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
        ui_provider=provider,
    )
    with TestClient(application) as client:
        make_course(client)
        conversation = client.post(
            f"{UI}/conversations", headers=auth("token-a"),
            json={"course": "cs3481", "lane": "problem"},
        ).json()

        rejected = client.post(
            f"{UI}/conversations/{conversation['id']}/runs", headers=auth("token-a"),
            json={
                "text": "medium must stop before model generation",
                "request_id": "server-budget-medium-001",
                "reasoning_strength": "medium",
            },
        )
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["detail"]["code"] == "APPLICATION_USD_BUDGET_EXCEEDED"
        assert provider.generate_calls == 0

        accepted = client.post(
            f"{UI}/conversations/{conversation['id']}/runs", headers=auth("token-a"),
            json={
                "text": "high may use two times the same B",
                "request_id": "server-budget-high-001",
                "reasoning_strength": "high",
            },
        )
        assert accepted.status_code == 202, accepted.text
        completed = wait_terminal(client, accepted.json()["id"])
        assert completed["status"] == "completed"
        assert completed["usage"][0]["kind"] == "server_operation_estimate"
        assert completed["usage"][0]["usd"] == "0.21"
        assert provider.generate_calls == 1

        unlimited = client.post(
            f"{UI}/conversations/{conversation['id']}/runs", headers=auth("token-a"),
            json={
                "text": "max is unlimited only at the application dollar gate",
                "request_id": "server-budget-max-001",
                "reasoning_strength": "max",
            },
        )
        assert unlimited.status_code == 202, unlimited.text
        assert unlimited.json()["application_budget_usd"] is None
        assert wait_terminal(client, unlimited.json()["id"])["status"] == "completed"
        assert provider.generate_calls == 2


def test_qwen_automatic_classification_fails_closed_before_a_billable_call(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("CMUI_PROVIDER_MODE", "qwen")
    monkeypatch.setenv("CMUI_ALLOW_BILLABLE", "true")
    monkeypatch.setenv("CMUI_OPERATION_USD_BASELINE", "0.20")
    monkeypatch.setenv("CMUI_OPERATION_INPUT_USD_PER_MILLION", "2")
    monkeypatch.setenv("CMUI_OPERATION_OUTPUT_USD_PER_MILLION", "10")

    settings = make_settings(tmp_path)
    settings.v3_model_api_key = SecretStr("test-not-real")
    settings.v3_model_base_url = "https://qwen.example.test/v1"
    provider = BudgetProbeProvider()
    application = create_app(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
        ui_provider=provider,
    )
    with TestClient(application) as client:
        make_course(client)
        uploaded = client.post(
            f"{UI}/courses/cs3481/files", headers=auth("token-a"),
            files={"file": ("classification.txt", b"CS3481 classification input", "text/plain")},
        )
        assert uploaded.status_code == 201, uploaded.text
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = client.get(
                f"{UI}/courses/cs3481/classification", headers=auth("token-a")
            ).json()
            if state["status"] == "FAILED_RETRYABLE":
                break
            time.sleep(0.02)
        assert state["status"] == "FAILED_RETRYABLE", state
        assert provider.classification_calls == 0


def test_qwen_classification_persists_a_non_content_billing_audit(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("CMUI_PROVIDER_MODE", "qwen")
    monkeypatch.setenv("CMUI_ALLOW_BILLABLE", "true")
    monkeypatch.setenv("CMUI_OPERATION_USD_BASELINE", "0.20")
    monkeypatch.setenv("CMUI_OPERATION_INPUT_USD_PER_MILLION", "2")
    monkeypatch.setenv("CMUI_OPERATION_OUTPUT_USD_PER_MILLION", "10")

    settings = make_settings(tmp_path)
    settings.v3_model_api_key = SecretStr("test-not-real")
    settings.v3_model_base_url = "https://qwen.example.test/v1"
    provider = BudgetProbeProvider()
    provider.estimated_usd = Decimal("0.01")
    application = create_app(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
        ui_provider=provider,
    )
    with TestClient(application) as client:
        make_course(client)
        uploaded = client.post(
            f"{UI}/courses/cs3481/files", headers=auth("token-a"),
            files={"file": ("classification.txt", b"CS3481 classification input", "text/plain")},
        )
        assert uploaded.status_code == 201, uploaded.text
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = client.get(
                f"{UI}/courses/cs3481/classification", headers=auth("token-a")
            ).json()
            if state["status"] == "OTHER":
                break
            time.sleep(0.02)
        assert state["status"] == "OTHER", state
        db = client.app.state.ui_extension_app.state.db
        rows = db.all(
            "SELECT value FROM cmui_meta WHERE key LIKE 'classification_billing_attempt:%'"
        )
        assert len(rows) == 1
        audit = json.loads(rows[0]["value"])
        assert audit["outcome"] == "completed"
        assert audit["billing"]["estimated_usd"] == "0.01"
        assert audit["billing"]["provider_usage"] == [{"input_tokens": 11, "output_tokens": 7}]
        assert "CS3481 classification input" not in rows[0]["value"]


def test_first_teaching_node_is_preflighted_as_two_stage_thinking(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("CMUI_PROVIDER_MODE", "qwen")
    monkeypatch.setenv("CMUI_ALLOW_BILLABLE", "true")
    monkeypatch.setenv("CMUI_OPERATION_USD_BASELINE", "0.20")
    monkeypatch.setenv("CMUI_OPERATION_INPUT_USD_PER_MILLION", "2")
    monkeypatch.setenv("CMUI_OPERATION_OUTPUT_USD_PER_MILLION", "10")

    settings = make_settings(tmp_path)
    settings.v3_model_api_key = SecretStr("test-not-real")
    settings.v3_model_base_url = "https://qwen.example.test/v1"
    provider = BudgetProbeProvider()
    provider.estimated_usd = Decimal("0.01")
    application = create_app(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
        ui_provider=provider,
    )
    with TestClient(application) as client:
        make_course(client)
        spec = json.dumps([
            {
                'item_id': 'required-a',
                'requirement': 'REQUIRED',
                'objective': 'Explain the synthetic node',
                'acceptance': 'Use the definition accurately',
                'evidence_ids': [],
            }
        ])
        with client.app.state.database.connect() as db:
            db.execute(
                'INSERT INTO teaching_specs(node_id,version,content_json,content_hash) VALUES(?,1,?,?)',
                ('node-x', spec, hashlib.sha256(spec.encode()).hexdigest()),
            )
        conversation = client.post(
            f"{UI}/conversations", headers=auth("token-a"),
            json={"course": "cs3481", "lane": "teach"},
        ).json()
        started = client.post(
            f"{UI}/conversations/{conversation['id']}/runs", headers=auth("token-a"),
            json={
                "text": "first node teaching needs plan then work",
                "request_id": "server-budget-first-node-001",
                "node_id": "node-x",
                "teaching_mode": "normal",
                "reasoning_strength": "medium",
            },
        )
        assert started.status_code == 202, started.text
        assert started.json()["teaching_mode"] == "thinking"
        assert provider.estimate_modes == ["thinking"]
