"""A non-empty hierarchical knowledge tree and the complete dual-mode flow.

The closure prompt's P0-3: an empty tree returning [] is not the same as a
verified tree product. These tests seed a synthetic-but-valid official tree
(through the same integrity triggers V3 uses) and assert real database facts:

- hierarchy (composite root + two atomic children) and both status entries;
- a REAL LEARNING node (1 of 2 REQUIRED items covered by delivery evidence) and a
  REAL LEARNED node (its single REQUIRED item covered), both independent from the
  assessment state;
- the full Problem -> Step -> Bridge -> Teaching -> Return journey, with the
  bridge bound to the server-derived step, the teach run carrying the bridge
  context into the provider and linking the V3 journey, and the return closing
  the bridge without duplicating anything.
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


class LaneProvider:
    """Contract fixture that answers problems with numbered steps and teaching
    with a normal explanation, while recording every call for assertions."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate(self, course, text, profile, sources, history, lane, bridge=None, **kwargs):
        self.calls.append({"lane": lane, "text": text, "bridge": bridge})
        yield {"kind": "status", "status": "planning", "label": "测试模型"}
        yield {"kind": "prompt", "text": "本地测试 Prompt（不是千问实测）"}
        yield {"kind": "status", "status": "generating", "label": "测试模型"}
        answer = (
            "## Step 1 先审题\n识别题目给出的条件与目标。\n## Step 2 联系知识\n"
            "用聚类概念解释密度可达性。"
            if lane == "problem"
            else "这是带桥接上下文的教学输出。"
        )
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
    provider = LaneProvider()
    application = create_app(
        settings=make_settings(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
        ui_provider=provider,
    )
    with TestClient(application) as test_client:
        from campus_actor_fixture import authorize_synthetic_campus_users
        authorize_synthetic_campus_users(test_client, 'user-a')
        test_client.app.state.ui_provider = provider  # type: ignore[attr-defined]
        yield test_client


def auth(token: str) -> dict[str, str]:
    return {"Authorization": token}


def seed_course_and_tree(client: TestClient) -> dict:
    created = client.post(
        "/api/courses",
        headers=auth("Bearer admin-token"),
        json={"id": "cs3481", "name": "Fundamentals of Data Science", "description": "Notes"},
    )
    assert created.status_code == 201, created.text

    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
    from seed_tree_fixture import seed_tree_fixture

    return seed_tree_fixture(client.app.state.database, "user-a")


def wait_terminal(client: TestClient, run_id: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = client.get(f"{UI}/runs/{run_id}", headers=auth("Bearer token-a")).json()
        if row["status"] in {"completed", "failed", "cancelled"}:
            return row
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} did not finish in {timeout}s")


def new_conversation(client: TestClient, lane: str) -> str:
    response = client.post(
        f"{UI}/conversations", headers=auth("Bearer token-a"), json={"course": "cs3481", "lane": lane}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_knowledge_tree_reflects_real_hierarchy_and_both_states(client: TestClient) -> None:
    tree_ids = seed_course_and_tree(client)
    body = client.get(f"{UI}/courses/cs3481/knowledge", headers=auth("Bearer token-a")).json()

    by_id = {row["id"]: row for row in body}
    assert by_id[tree_ids["root"]]["parent"] is None
    assert by_id[tree_ids["root"]]["kind"] == "COMPOSITE"
    learning = by_id[tree_ids["learning"]]
    learned = by_id[tree_ids["learned"]]
    assert learning["parent"] == tree_ids["root"]
    assert learning["progress"] == "LEARNING", learning["learning"]
    assert learning["learning"]["required_total"] == 2
    assert learning["learning"]["covered_required"] == 1
    assert learned["parent"] == tree_ids["root"]
    assert learned["progress"] == "LEARNED", learned["learning"]
    assert learned["learning"]["required_total"] == 1
    assert learned["learning"]["covered_required"] == 1
    # Assessment is an independent state and stays NOT_ASSESSED.
    for node_id in (tree_ids["learning"], tree_ids["learned"]):
        assert by_id[node_id]["assessment"]["status"] == "NOT_ASSESSED"
        assert by_id[node_id]["grade"] is None


def test_dual_mode_problem_steps_stay_independent_of_teaching(client: TestClient) -> None:
    tree_ids = seed_course_and_tree(client)

    problem_conv = new_conversation(client, "problem")
    started = client.post(
        f"{UI}/conversations/{problem_conv}/runs",
        headers=auth("Bearer token-a"),
        json={"text": "怎么判断密度可达性？", "request_id": "dual-mode-problem-000001"},
    )
    assert started.status_code == 202, started.text
    assert wait_terminal(client, started.json()["id"])["status"] == "completed"
    assistant = next(message for message in client.get(
        f"{UI}/conversations/{problem_conv}", headers=auth("Bearer token-a")
    ).json()["messages"] if message["role"] == "assistant")
    assert [step["number"] for step in assistant["steps"]] == [1, 2]

    retired = client.post(
        f"{UI}/courses/cs3481/bridges",
        headers=auth("Bearer token-a"),
        json={"problem_message": assistant["id"], "step": 1,
              "question": "为什么先审题？", "node": tree_ids["learned"]},
    )
    assert retired.status_code == 410
    assert client.get(f"{UI}/courses/cs3481/layout", headers=auth("Bearer token-a")).json().get("bridge") is None

    # Teaching is still a normal independent run, including a selected node,
    # but it receives no problem-step bridge payload.
    teach_conv = new_conversation(client, "teach")
    taught = client.post(
        f"{UI}/conversations/{teach_conv}/runs",
        headers=auth("Bearer token-a"),
        json={"text": "请讲清楚聚类概念", "request_id": "dual-mode-teach-000001",
              "node_id": tree_ids["learned"]},
    )
    assert taught.status_code == 202, taught.text
    assert wait_terminal(client, taught.json()["id"])["status"] == "completed"
    provider: LaneProvider = client.app.state.ui_provider  # type: ignore[attr-defined]
    assert any(call["lane"] == "teach" and call["bridge"] is None for call in provider.calls)


def test_cross_pane_creation_returns_retired_for_any_step_number(client: TestClient) -> None:
    seed_course_and_tree(client)
    problem_conv = new_conversation(client, "problem")
    started = client.post(
        f"{UI}/conversations/{problem_conv}/runs",
        headers=auth("Bearer token-a"),
        json={"text": "讲讲聚类", "request_id": "dual-mode-problem-000099"},
    )
    assert wait_terminal(client, started.json()["id"])["status"] == "completed"
    assistant = next(message for message in client.get(
        f"{UI}/conversations/{problem_conv}", headers=auth("Bearer token-a")
    ).json()["messages"] if message["role"] == "assistant")
    retired = client.post(
        f"{UI}/courses/cs3481/bridges",
        headers=auth("Bearer token-a"),
        json={"problem_message": assistant["id"], "step": 99,
              "question": "第 99 步存在吗？", "node": None},
    )
    assert retired.status_code == 410


def test_retired_cross_pane_endpoint_does_not_validate_or_create_a_step(client: TestClient) -> None:
    seed_course_and_tree(client)
    problem_conv = new_conversation(client, "problem")
    started = client.post(
        f"{UI}/conversations/{problem_conv}/runs",
        headers=auth("Bearer token-a"),
        json={"text": "讲讲聚类", "request_id": "dual-mode-problem-000099"},
    )
    assert wait_terminal(client, started.json()["id"])["status"] == "completed"
    messages = client.get(
        f"{UI}/conversations/{problem_conv}", headers=auth("Bearer token-a")
    ).json()["messages"]
    assistant = next(message for message in messages if message["role"] == "assistant")

    retired = client.post(
        f"{UI}/courses/cs3481/bridges",
        headers=auth("Bearer token-a"),
        json={
            "problem_message": assistant["id"],
            "step": 99,
            "question": "第 99 步存在吗？",
            "node": None,
        },
    )
    assert retired.status_code == 410
