"""HTTP contract for the internal tool-intent endpoint (``POST /api/jev/tool-intent``).

Every test uses the offline :class:`FakeTransport` (via ``make_jev_database``) so no
network is used, and none is claimed. The suite pins the endpoint's own guarantees:
auth (missing token -> 503, wrong token -> 401, constant-time), fail-safe shadow
semantics, the deterministic read-only/explicit short-circuits (zero Jev calls), the
code-first permission refusal, owner-scoped receipts, and bounded body validation.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from jev_fixtures import make_jev_database

from app.api.tool_intent import router as tool_intent_router
from app.errors import ApiError
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService

KEY = "tool.intent.v1"
TOKEN = "test-internal-token"


def make_service(database, responder, *, mode="on"):
    gateway = JevGateway(
        transport=FakeTransport(responder),
        modes={KEY: mode},
        receipt_store=SqlReceiptStore(database),
    )
    return SemanticDecisionService(gateway), gateway.transport


def _choice_responder(choice: str):
    def responder(call):
        return JevResult(answers={KEY: JevAnswer(choice=choice)})

    return responder


def _refuse_responder(call):
    raise AssertionError("this path must never spend a Jev intent call")


def make_app(database, service):
    app = FastAPI()
    app.state.database = database
    app.state.jev_service = service
    app.include_router(tool_intent_router)

    @app.exception_handler(ApiError)
    async def _api_error_handler(request, error):
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": error.details,
                }
            },
        )

    return app


def base_payload(**overrides):
    payload = {
        "user_message": "请删除这个任务",
        "proposed_tool": "deleteTask",
        "tool_arguments": {"taskId": "task-1"},
        "actor_scope": "owner",
        "actor_permissions": ["tasks:write"],
        "required_permissions": ["tasks:write"],
        "is_read_only": False,
        "explicit": False,
        "object_revision": None,
        "current_revision": None,
        "owner_user_id": "user-a",
        "authorization_scope": "tasks",
        "course_id": "c1",
        "workspace_id": None,
        "material_revision": None,
        "node_id": None,
        "spec_version": None,
    }
    payload.update(overrides)
    return payload


def _headers(token=TOKEN):
    return {"X-CourseMate-Internal-Token": token}


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


def test_missing_token_returns_503(tmp_path, monkeypatch) -> None:
    database = make_jev_database(tmp_path)
    service, _ = make_service(database, _choice_responder("CONSISTENT"))
    app = make_app(database, service)
    monkeypatch.delenv("JEV_TOOL_INTENT_TOKEN", raising=False)

    response = TestClient(app).post("/api/jev/tool-intent", json=base_payload())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INTERNAL_ENDPOINT_DISABLED"


def test_wrong_token_returns_401(tmp_path, monkeypatch) -> None:
    database = make_jev_database(tmp_path)
    service, _ = make_service(database, _choice_responder("CONSISTENT"))
    app = make_app(database, service)
    monkeypatch.setenv("JEV_TOOL_INTENT_TOKEN", TOKEN)

    response = TestClient(app).post(
        "/api/jev/tool-intent", json=base_payload(), headers=_headers("wrong-token")
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_INTERNAL_TOKEN"


# --------------------------------------------------------------------------- #
# Deterministic short-circuits + shadow fail-safe
# --------------------------------------------------------------------------- #


def test_shadow_non_explicit_write_requires_confirmation(tmp_path, monkeypatch) -> None:
    database = make_jev_database(tmp_path)
    service, transport = make_service(database, _choice_responder("CONSISTENT"), mode="shadow")
    app = make_app(database, service)
    monkeypatch.setenv("JEV_TOOL_INTENT_TOKEN", TOKEN)

    response = TestClient(app).post(
        "/api/jev/tool-intent", json=base_payload(), headers=_headers()
    )

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "REQUIRE_CONFIRMATION"
    assert body["used_jev"] is False
    assert body["jev_label"] is None
    assert len(transport.calls) == 1  # shadow still records, but never uses the label


def test_read_only_allows_with_zero_jev_calls(tmp_path, monkeypatch) -> None:
    database = make_jev_database(tmp_path)
    service, transport = make_service(database, _refuse_responder)
    app = make_app(database, service)
    monkeypatch.setenv("JEV_TOOL_INTENT_TOKEN", TOKEN)

    response = TestClient(app).post(
        "/api/jev/tool-intent",
        json=base_payload(
            is_read_only=True,
            proposed_tool="searchTask",
            actor_permissions=[],
            required_permissions=[],
        ),
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "ALLOW"
    assert body["path"] == "deterministic:read_only"
    assert body["jev_calls"] == 0
    assert transport.calls == []


def test_explicit_allows_with_zero_jev_calls(tmp_path, monkeypatch) -> None:
    database = make_jev_database(tmp_path)
    service, transport = make_service(database, _refuse_responder)
    app = make_app(database, service)
    monkeypatch.setenv("JEV_TOOL_INTENT_TOKEN", TOKEN)

    response = TestClient(app).post(
        "/api/jev/tool-intent", json=base_payload(explicit=True), headers=_headers()
    )

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "ALLOW"
    assert body["path"] == "deterministic:explicit"
    assert body["jev_calls"] == 0
    assert transport.calls == []


def test_missing_required_permission_refused_in_code(tmp_path, monkeypatch) -> None:
    database = make_jev_database(tmp_path)
    service, transport = make_service(database, _choice_responder("CONSISTENT"))
    app = make_app(database, service)
    monkeypatch.setenv("JEV_TOOL_INTENT_TOKEN", TOKEN)

    response = TestClient(app).post(
        "/api/jev/tool-intent",
        json=base_payload(actor_permissions=[], required_permissions=["tasks:write"]),
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "REFUSE_UNAUTHORIZED"
    assert body["used_jev"] is False
    assert body["jev_calls"] == 0
    assert transport.calls == []


# --------------------------------------------------------------------------- #
# Receipt scope isolation
# --------------------------------------------------------------------------- #


def test_receipts_are_owner_scoped_and_distinct(tmp_path, monkeypatch) -> None:
    database = make_jev_database(tmp_path)
    service, _ = make_service(database, _choice_responder("CONSISTENT"), mode="on")
    app = make_app(database, service)
    monkeypatch.setenv("JEV_TOOL_INTENT_TOKEN", TOKEN)
    client = TestClient(app)

    for owner in ("user-a", "user-b"):
        response = client.post(
            "/api/jev/tool-intent",
            json=base_payload(owner_user_id=owner),
            headers=_headers(),
        )
        assert response.status_code == 200
        assert response.json()["verdict"] == "ALLOW"

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT owner_scope_hash FROM jev_decision_receipts ORDER BY rowid"
        ).fetchall()

    hashes = [row[0] for row in rows]
    assert len(hashes) == 2
    assert all(hash_value is not None for hash_value in hashes)
    assert hashes[0] != hashes[1]


# --------------------------------------------------------------------------- #
# Bounded body
# --------------------------------------------------------------------------- #


def test_oversized_body_rejected(tmp_path, monkeypatch) -> None:
    database = make_jev_database(tmp_path)
    service, _ = make_service(database, _choice_responder("CONSISTENT"))
    app = make_app(database, service)
    monkeypatch.setenv("JEV_TOOL_INTENT_TOKEN", TOKEN)

    response = TestClient(app).post(
        "/api/jev/tool-intent",
        json=base_payload(tool_arguments={"blob": "x" * 100_000}),
        headers=_headers(),
    )

    assert response.status_code == 422
