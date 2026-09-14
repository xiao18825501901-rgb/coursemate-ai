"""The UI's study tasks must use the existing Node agent, not a second store.

These tests run a stub with the same contract as `services/agent-api`
(`GET/POST/PATCH/DELETE /api/tasks`, `POST /api/agent/chat`) and assert that the
domain adapter forwards the caller's bearer credential, translates between the
UI's canonical task DTO and the agent's DTO, and refuses an edit that would
overwrite a task changed elsewhere.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.ui_extension.domain import V3DomainAdapter

UI = "/ui-extension/api/ui/v1"
SUBJECTS = {
    "Bearer token-a": "user-a",
    "Bearer token-b": "user-b",
    "Bearer admin-token": "user-admin",
}


class FakeAuthVerifier:
    def authenticate(self, request: Request) -> str | None:
        return SUBJECTS.get(request.headers.get("authorization", ""))


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class _TaskStore:
    """Minimal stand-in for the agent's SQLite task repository."""

    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, object]] = {}
        self.owners: dict[str, str] = {}
        self.counter = 0
        self.seen_credentials: list[str] = []
        self.chat_calls: list[dict[str, object]] = []

    def create(self, owner: str, body: dict[str, object]) -> dict[str, object]:
        self.counter += 1
        task_id = f"task_{self.counter:04d}"
        task = {
            "id": task_id,
            "title": body.get("title"),
            "notes": body.get("notes"),
            "courseId": body.get("courseId"),
            "status": "todo",
            "priority": body.get("priority"),
            "dueDate": body.get("dueDate"),
            "sourceCitation": body.get("sourceCitation"),
            "createdAt": f"2026-09-14T00:00:{self.counter:02d}.000Z",
            "updatedAt": f"2026-09-14T00:00:{self.counter:02d}.000Z",
            "completedAt": None,
        }
        self.tasks[task_id] = task
        self.owners[task_id] = owner
        return task

    def owned(self, owner: str) -> list[dict[str, object]]:
        return [task for task in self.tasks.values() if self.owners[task["id"]] == owner]


def _handler(store: _TaskStore):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args: object) -> None:  # pragma: no cover - quiet stub
            return

        def _credential(self) -> str:
            value = self.headers.get("authorization", "")
            store.seen_credentials.append(value)
            return value

        def _owner(self) -> str | None:
            return SUBJECTS.get(self._credential())

        def _body(self) -> dict[str, object]:
            length = int(self.headers.get("content-length") or 0)
            if length == 0:
                return {}
            return json.loads(self.rfile.read(length))

        def _send(self, status: int, payload: object) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _require_owner(self) -> str | None:
            owner = self._owner()
            if owner is None:
                self._send(
                    401,
                    {"error": {"code": "UNAUTHENTICATED", "message": "sign in", "details": {}}},
                )
            return owner

        def do_GET(self) -> None:  # noqa: N802 - http.server contract
            if not self._require_owner():
                return
            if self.path.startswith("/api/tasks"):
                owner = self._owner() or ""
                items = store.owned(owner)
                self._send(200, {"items": items, "page": 1, "pageSize": 100, "total": len(items)})
                return
            self._send(404, {"error": {"code": "ROUTE_NOT_FOUND", "message": "no", "details": {}}})

        def do_POST(self) -> None:  # noqa: N802 - http.server contract
            owner = self._require_owner()
            if owner is None:
                return
            body = self._body()
            if self.path == "/api/tasks":
                self._send(201, store.create(owner, body))
                return
            if self.path == "/api/agent/chat":
                store.chat_calls.append({"owner": owner, "message": body.get("message")})
                self._send(
                    200,
                    {
                        "message": "已为你创建「复习聚类」任务。",
                        "toolResults": [{"ok": True, "data": {"id": "task_0001"}, "error": None}],
                    },
                )
                return
            self._send(404, {"error": {"code": "ROUTE_NOT_FOUND", "message": "no", "details": {}}})

        def do_PATCH(self) -> None:  # noqa: N802 - http.server contract
            owner = self._require_owner()
            if owner is None:
                return
            task_id = self.path.rsplit("/", 1)[-1]
            task = store.tasks.get(task_id)
            if task is None or store.owners[task_id] != owner:
                self._send(
                    404, {"error": {"code": "TASK_NOT_FOUND", "message": "gone", "details": {}}}
                )
                return
            body = self._body()
            for key, value in body.items():
                task[key] = value
            task["updatedAt"] = "2026-09-15T00:00:00.000Z"
            if task["status"] == "completed":
                task["completedAt"] = "2026-09-15T00:00:00.000Z"
            self._send(200, task)

        def do_DELETE(self) -> None:  # noqa: N802 - http.server contract
            owner = self._require_owner()
            if owner is None:
                return
            task_id = self.path.rsplit("/", 1)[-1]
            if task_id not in store.tasks or store.owners[task_id] != owner:
                self._send(
                    404, {"error": {"code": "TASK_NOT_FOUND", "message": "gone", "details": {}}}
                )
                return
            del store.tasks[task_id]
            self.send_response(204)
            self.send_header("content-length", "0")
            self.end_headers()

    return Handler


@pytest.fixture
def agent() -> Iterator[tuple[str, _TaskStore]]:
    store = _TaskStore()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(store))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}", store
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def client(tmp_path: Path, agent: tuple[str, _TaskStore], monkeypatch) -> Iterator[TestClient]:
    url, _store = agent
    monkeypatch.setenv("UI_TASK_AGENT_URL", url)
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        admin_user_ids="user-admin",
        app_env="test",
        v3_enabled=True,
        ui_extension_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
        ui_task_agent_url=url,
    )
    application = create_app(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )
    with TestClient(application) as test_client:
        yield test_client


def auth(token: str) -> dict[str, str]:
    return {"Authorization": token}


def _create(client: TestClient, token: str, **overrides: object) -> dict:
    body = {
        "title": "复习聚类",
        "due_at": "2026-09-16T14:00:00+08:00",
        "timezone": "Asia/Hong_Kong",
        "course": None,
        "request_id": "task-request-000001",
    }
    body.update(overrides)
    response = client.post(f"{UI}/tasks", headers=auth(token), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_tasks_are_created_in_the_real_agent_store(
    client: TestClient, agent: tuple[str, _TaskStore]
) -> None:
    _url, store = agent
    task = _create(client, "Bearer token-a")
    assert task["title"] == "复习聚类"
    assert task["status"] == "todo"
    assert task["timezone"] == "Asia/Hong_Kong"
    assert task["due_at"] == "2026-09-16T09:00:00.000Z"
    assert isinstance(task["version"], int) and task["version"] > 0
    # The agent received a date-only value, which is all its schema accepts.
    assert next(iter(store.tasks.values()))["dueDate"] == "2026-09-16"


def test_task_list_is_scoped_to_the_callers_own_credential(
    client: TestClient, agent: tuple[str, _TaskStore]
) -> None:
    _url, store = agent
    _create(client, "Bearer token-a")
    assert len(client.get(f"{UI}/tasks", headers=auth("Bearer token-a")).json()) == 1
    assert client.get(f"{UI}/tasks", headers=auth("Bearer token-b")).json() == []
    assert "Bearer token-a" in store.seen_credentials
    assert all(value != "" for value in store.seen_credentials)


def test_task_update_and_complete_use_the_agent_version(
    client: TestClient, agent: tuple[str, _TaskStore]
) -> None:
    _url, store = agent
    task = _create(client, "Bearer token-a")
    renamed = client.patch(
        f"{UI}/tasks/{task['id']}",
        headers=auth("Bearer token-a"),
        json={"title": "复习 DBSCAN", "version": task["version"]},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "复习 DBSCAN"
    assert renamed.json()["version"] != task["version"]
    assert store.tasks[task["id"]]["title"] == "复习 DBSCAN"

    done = client.patch(
        f"{UI}/tasks/{task['id']}",
        headers=auth("Bearer token-a"),
        json={"status": "done", "version": renamed.json()["version"]},
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done"
    assert store.tasks[task["id"]]["status"] == "completed"
    assert store.tasks[task["id"]]["completedAt"] is not None


def test_stale_task_version_is_rejected_without_writing(client: TestClient) -> None:
    task = _create(client, "Bearer token-a")
    response = client.patch(
        f"{UI}/tasks/{task['id']}",
        headers=auth("Bearer token-a"),
        json={"title": "stale", "version": task["version"] - 1},
    )
    assert response.status_code == 409
    listed = client.get(f"{UI}/tasks", headers=auth("Bearer token-a")).json()
    assert listed[0]["title"] == "复习聚类"


def test_another_user_cannot_touch_a_task(client: TestClient) -> None:
    task = _create(client, "Bearer token-a")
    assert (
        client.patch(
            f"{UI}/tasks/{task['id']}",
            headers=auth("Bearer token-b"),
            json={"title": "hijack", "version": task["version"]},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"{UI}/tasks/{task['id']}?version={task['version']}", headers=auth("Bearer token-b")
        ).status_code
        == 404
    )


def test_task_delete_removes_the_agent_row(client: TestClient, agent: tuple[str, _TaskStore]) -> None:
    _url, store = agent
    task = _create(client, "Bearer token-a")
    response = client.delete(
        f"{UI}/tasks/{task['id']}?version={task['version']}", headers=auth("Bearer token-a")
    )
    assert response.status_code == 200, response.text
    assert store.tasks == {}


def test_natural_language_planning_uses_the_tool_calling_agent(
    client: TestClient, agent: tuple[str, _TaskStore]
) -> None:
    _url, store = agent
    response = client.post(
        f"{UI}/tasks/plan",
        headers=auth("Bearer token-a"),
        json={"text": "帮我把下周的聚类复习排进计划", "request_id": "plan-request-000001"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["text"] == "已为你创建「复习聚类」任务。"
    assert body["tool_results"][0]["ok"] is True
    assert store.chat_calls == [
        {"owner": "user-a", "message": "帮我把下周的聚类复习排进计划"}
    ]


def test_agent_unavailable_is_a_clear_error_not_a_fake_success(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("UI_TASK_AGENT_URL", "http://127.0.0.1:9")
    adapter: V3DomainAdapter = client.app.state.ui_extension_adapter  # type: ignore[attr-defined]
    adapter.task_agent_url = "http://127.0.0.1:9"
    with pytest.raises(HTTPException) as error:
        import anyio

        anyio.run(adapter.call, "task.list", "user-a", {}, "Bearer token-a")
    assert error.value.status_code == 502


def test_missing_agent_configuration_is_reported(client: TestClient) -> None:
    adapter: V3DomainAdapter = client.app.state.ui_extension_adapter  # type: ignore[attr-defined]
    adapter.task_agent_url = ""
    import anyio

    with pytest.raises(HTTPException) as error:
        anyio.run(adapter.call, "task.list", "user-a", {}, "Bearer token-a")
    assert error.value.status_code == 503
