"""Regression coverage for retired cross-pane bridge creation.

The V3 domain's original bridge/coverage tests remain in the domain suite.
This integrated-shell suite proves the product change: historical evidence is
read-only, while problem panes can no longer launch a teaching run.
"""
from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.cm_update.db import now

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


class ScriptedProvider:
    async def generate(self, course, text, profile, sources, history, lane, bridge=None, **kwargs):
        assert bridge is None
        answer = "## Step 1 审题\n识别题目给出的条件。\n\n## Step 2 联系知识\n解释聚类概念。"
        yield {"kind": "delta", "text": answer}
        yield {"kind": "usage", "stage": "answer", "value": {"output_tokens": 2}}


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        admin_user_ids="user-admin",
        app_env="test",
        v3_enabled=True,
        ui_extension_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        settings=make_settings(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
        ui_provider=ScriptedProvider(),
    )
    with TestClient(app) as test_client:
        from campus_actor_fixture import authorize_synthetic_campus_users
        authorize_synthetic_campus_users(test_client, "user-a", "user-b")
        created = test_client.post(
            "/api/courses", headers=auth("Bearer admin-token"),
            json={"id": "cs3481", "name": "Fundamentals of Data Science", "description": "Notes"},
        )
        assert created.status_code == 201, created.text
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
        from seed_tree_fixture import seed_tree_fixture
        test_client.app.state.tree_ids = seed_tree_fixture(test_client.app.state.database, "user-a")
        yield test_client


def auth(token: str) -> dict[str, str]:
    return {"Authorization": token}


def wait_terminal(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        row = client.get(f"{UI}/runs/{run_id}", headers=auth("Bearer token-a")).json()
        if row["status"] in {"completed", "failed", "cancelled"}:
            return row
        time.sleep(0.05)
    raise AssertionError("run did not reach terminal state")


def completed_problem(client: TestClient) -> tuple[str, dict]:
    conversation = client.post(
        f"{UI}/conversations", headers=auth("Bearer token-a"),
        json={"course": "cs3481", "lane": "problem"},
    ).json()
    started = client.post(
        f"{UI}/conversations/{conversation['id']}/runs", headers=auth("Bearer token-a"),
        json={"text": "怎么判断密度可达性？", "request_id": "retired-bridge-problem"},
    )
    assert started.status_code == 202, started.text
    assert wait_terminal(client, started.json()["id"])["status"] == "completed"
    assistant = next(
        message for message in client.get(
            f"{UI}/conversations/{conversation['id']}", headers=auth("Bearer token-a")
        ).json()["messages"] if message["role"] == "assistant"
    )
    return conversation["id"], assistant


def test_historic_bridge_is_read_only_and_not_exposed_through_layout(client: TestClient) -> None:
    _, assistant = completed_problem(client)
    ui_db = client.app.state.ui_extension_app.state.db
    ui_db.execute(
        "INSERT INTO cmui_bridges(id,owner,course,problem_message,step,question,node,status,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        ("bridge_historic", "user-a", "cs3481", assistant["id"], 1,
         "历史记录为何先审题？", None, "open", now()),
    )

    history = client.get(f"{UI}/courses/cs3481/bridges", headers=auth("Bearer token-a"))
    assert history.status_code == 200
    assert [row["id"] for row in history.json()] == ["bridge_historic"]
    assert "bridge" not in client.get(
        f"{UI}/courses/cs3481/layout", headers=auth("Bearer token-a")
    ).json()
    retired = client.patch(f"{UI}/bridges/bridge_historic/return", headers=auth("Bearer token-a"))
    assert retired.status_code == 410
    assert ui_db.one("SELECT status FROM cmui_bridges WHERE id='bridge_historic'")["status"] == "open"


def test_new_cross_pane_creation_and_bridge_run_are_both_rejected(client: TestClient) -> None:
    _, assistant = completed_problem(client)
    created = client.post(
        f"{UI}/courses/cs3481/bridges", headers=auth("Bearer token-a"),
        json={"problem_message": assistant["id"], "step": 1, "question": "为什么？"},
    )
    assert created.status_code == 410
    teach = client.post(
        f"{UI}/conversations", headers=auth("Bearer token-a"),
        json={"course": "cs3481", "lane": "teach"},
    ).json()
    run = client.post(
        f"{UI}/conversations/{teach['id']}/runs", headers=auth("Bearer token-a"),
        json={"text": "讲解概念", "request_id": "retired-bridge-run", "bridge_id": "bridge_historic"},
    )
    assert run.status_code == 410
