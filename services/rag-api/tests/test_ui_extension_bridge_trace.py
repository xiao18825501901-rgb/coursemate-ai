"""The bridge trace chain: shell problem -> V3 ledger -> teaching -> coverage.

Closure prompt section 3: the UI keeps its navigation table while V3 keeps the
teaching facts; every hop must be traceable through verifiable, versioned,
owner/course-controlled ids:

    cmui_bridges(problem_message, step)
      -> problem_revision_id (V3 learning_problems + problem_revisions)
      -> solution_id / step_ids (V3 learning_solutions + learning_steps)
      -> teach_run -> cmui_run_v3 (workspace/journey/node/spec)
      -> delivery_unit_id (V3 teaching_units)
      -> teaching_delivery_evidence (REVIEWED) -> learning_journeys
      -> return to the same problem and step (cmui bridge status)
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.learning.coverage_review import DeterministicCoverageReviewer
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


class ScriptedProvider:
    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def generate(self, course, text, profile, sources, history, lane, bridge=None, **kwargs):
        self.calls.append({"lane": lane, "text": text, "bridge": bridge})
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        yield {"kind": "status", "status": "planning", "label": "测试模型"}
        yield {"kind": "prompt", "text": "本地测试 Prompt（非千问实测）"}
        yield {"kind": "status", "status": "generating", "label": "测试模型"}
        yield {"kind": "delta", "text": answer}
        yield {"kind": "usage", "stage": "answer", "value": {"output_tokens": 2}}


PROBLEM_ANSWER = "## Step 1 审题\n识别题目给出的条件与目标。\n\n## Step 2 联系知识\n用聚类概念解释密度可达性。"


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
    provider = ScriptedProvider([])
    application = create_app(
        settings=make_settings(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
        ui_provider=provider,
        ui_coverage_reviewer=DeterministicCoverageReviewer(),
    )
    with TestClient(application) as test_client:
        test_client.app.state.ui_provider = provider  # type: ignore[attr-defined]
        test_client.app.state.tree_ids = seed_tree(test_client)  # type: ignore[attr-defined]
        yield test_client


def auth(token: str) -> dict[str, str]:
    return {"Authorization": token}


def seed_tree(client: TestClient) -> dict:
    created = client.post(
        "/api/courses",
        headers=auth("Bearer admin-token"),
        json={"id": "cs3481", "name": "Fundamentals of Data Science", "description": "Notes"},
    )
    assert created.status_code == 201, created.text
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
    from seed_tree_fixture import seed_tree_fixture

    return seed_tree_fixture(client.app.state.database, "user-a")


def wait_terminal(client: TestClient, run_id: str, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = client.get(f"{UI}/runs/{run_id}", headers=auth("Bearer token-a")).json()
        if row["status"] in {"completed", "failed", "cancelled"}:
            return row
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} did not finish in {timeout}s")


def wait_receipt(client: TestClient, run_id: str, timeout: float = 20.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = client.get(f"{UI}/runs/{run_id}", headers=auth("Bearer token-a")).json()
        receipt = row.get("coverage")
        if receipt is not None:
            return receipt
        if row["status"] in {"completed", "failed", "cancelled"}:
            time.sleep(0.5)
            return client.get(f"{UI}/runs/{run_id}", headers=auth("Bearer token-a")).json().get("coverage")
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} has no coverage receipt after {timeout}s")


def problem_run(client: TestClient, request_id: str = "bridge-problem-000001") -> dict:
    conversation = client.post(
        f"{UI}/conversations",
        headers=auth("Bearer token-a"),
        json={"course": "cs3481", "lane": "problem"},
    )
    assert conversation.status_code == 201, conversation.text
    started = client.post(
        f"{UI}/conversations/{conversation.json()['id']}/runs",
        headers=auth("Bearer token-a"),
        json={"text": "怎么判断密度可达性？", "request_id": request_id},
    )
    assert started.status_code == 202, started.text
    run_row = wait_terminal(client, started.json()["id"])
    assert run_row["status"] == "completed"
    messages = client.get(
        f"{UI}/conversations/{conversation.json()['id']}", headers=auth("Bearer token-a")
    ).json()["messages"]
    assistant = next(m for m in messages if m["role"] == "assistant")
    return {"run_id": started.json()["id"], "assistant": assistant}


def test_bridge_carries_full_v3_trace_chain(client: TestClient) -> None:
    provider: ScriptedProvider = client.app.state.ui_provider
    provider.responses.append(PROBLEM_ANSWER)
    problem = problem_run(client)
    tree = client.app.state.tree_ids

    bridge = client.post(
        f"{UI}/courses/cs3481/bridges",
        headers=auth("Bearer token-a"),
        json={
            "problem_message": problem["assistant"]["id"],
            "step": 1,
            "question": "为什么先审题？",
            "node": tree["learning"],
        },
    )
    assert bridge.status_code == 201, bridge.text
    row = bridge.json()
    assert row["status"] == "open"
    assert row["step"] == 1

    # The problem run is mapped into the V3 versioned problem ledger.
    assert row["problem_revision_id"]
    assert row["solution_id"]
    assert len(json.loads(row["step_ids_json"])) == 2
    with client.app.state.database.connect() as connection:
        v3_problem = connection.execute(
            "SELECT * FROM learning_problems WHERE id=?", (f"shell-{problem['run_id']}",)
        ).fetchone()
        assert v3_problem is not None
        revision = connection.execute(
            "SELECT * FROM problem_revisions WHERE id=?", (row["problem_revision_id"],)
        ).fetchone()
        assert revision["validation_status"] == "VALIDATED"
        assert len(revision["content_hash"]) == 64
        assert revision["revision"] == 1
        solution = connection.execute(
            "SELECT * FROM learning_solutions WHERE id=?", (row["solution_id"],)
        ).fetchone()
        assert solution is not None
        steps = connection.execute(
            "SELECT * FROM learning_steps WHERE solution_id=? ORDER BY ordinal",
            (row["solution_id"],),
        ).fetchall()
        assert [s["ordinal"] for s in steps] == [1, 2]

    # Teaching through the bridge links run -> journey -> delivery unit.
    provider.responses.append("这是围绕原题第 1 步的教学。State one metric：例如轮廓系数。")
    conversation = client.post(
        f"{UI}/conversations",
        headers=auth("Bearer token-a"),
        json={"course": "cs3481", "lane": "teach"},
    )
    taught = client.post(
        f"{UI}/conversations/{conversation.json()['id']}/runs",
        headers=auth("Bearer token-a"),
        json={
            "text": "请讲清楚这一步背后的聚类概念",
            "request_id": "bridge-teach-000001",
            "bridge_id": row["id"],
            "node_id": tree["learning"],
        },
    )
    assert taught.status_code == 202, taught.text
    run_row = wait_terminal(client, taught.json()["id"])
    assert run_row["status"] == "completed"
    receipt = wait_receipt(client, taught.json()["id"])
    assert receipt["status"] == "submitted"

    bridge_after = client.get(
        f"{UI}/courses/cs3481/bridges", headers=auth("Bearer token-a")
    ).json()
    assert len(bridge_after) == 1
    linked = bridge_after[0]
    assert linked["teach_run"] == taught.json()["id"]
    assert linked["journey_id"]
    assert int(linked["spec_version"]) == 1
    assert linked["delivery_unit_id"] == receipt["unit_id"]

    # The end-to-end chain resolves: problem revision -> step -> journey -> unit
    # -> REVIEWED evidence -> journey status.
    ui_db = client.app.state.ui_extension_app.state.db
    link = ui_db.one("SELECT * FROM cmui_run_v3 WHERE run=?", (taught.json()["id"],))
    assert link is not None
    with client.app.state.database.connect() as connection:
        unit = connection.execute(
            "SELECT * FROM teaching_units WHERE id=?", (receipt["unit_id"],)
        ).fetchone()
        assert unit["operation_id"] == taught.json()["id"]
        assert unit["journey_id"] == linked["journey_id"]
        evidence = connection.execute(
            "SELECT * FROM teaching_delivery_evidence WHERE teaching_unit_id=?",
            (receipt["unit_id"],),
        ).fetchall()
        assert len(evidence) == 1
        assert evidence[0]["validation_status"] == "REVIEWED"
        journey = connection.execute(
            "SELECT status FROM learning_journeys WHERE id=?", (linked["journey_id"],)
        ).fetchone()
        # 1 pre-seeded LEGACY item + this REVIEWED one = 2/2 on the learning node.
        assert journey["status"] == "LEARNED"

    # Return closes the bridge and the layout stops exposing it.
    returned = client.patch(
        f"{UI}/bridges/{row['id']}/return", headers=auth("Bearer token-a")
    )
    assert returned.status_code == 200
    assert returned.json()["status"] == "returned"
    layout = client.get(f"{UI}/courses/cs3481/layout", headers=auth("Bearer token-a")).json()
    assert layout["bridge"] is None


def test_duplicate_bridge_click_reuses_v3_records(client: TestClient) -> None:
    provider: ScriptedProvider = client.app.state.ui_provider
    provider.responses.append(PROBLEM_ANSWER)
    problem = problem_run(client)
    tree = client.app.state.tree_ids
    payload = {
        "problem_message": problem["assistant"]["id"],
        "step": 2,
        "question": "为什么联系聚类知识？",
        "node": tree["learning"],
    }
    first = client.post(
        f"{UI}/courses/cs3481/bridges", headers=auth("Bearer token-a"), json=payload
    )
    second = client.post(
        f"{UI}/courses/cs3481/bridges", headers=auth("Bearer token-a"), json=payload
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    with client.app.state.database.connect() as connection:
        revisions = connection.execute(
            "SELECT COUNT(*) FROM problem_revisions WHERE problem_id=?",
            (f"shell-{problem['run_id']}",),
        ).fetchone()[0]
        assert revisions == 1
    assert len(
        client.get(f"{UI}/courses/cs3481/bridges", headers=auth("Bearer token-a")).json()
    ) == 1


def test_cross_user_rejection_and_scoped_listing(client: TestClient) -> None:
    provider: ScriptedProvider = client.app.state.ui_provider
    provider.responses.append(PROBLEM_ANSWER)
    problem = problem_run(client)
    tree = client.app.state.tree_ids
    created = client.post(
        f"{UI}/courses/cs3481/bridges",
        headers=auth("Bearer token-a"),
        json={
            "problem_message": problem["assistant"]["id"],
            "step": 1,
            "question": "为什么先审题？",
            "node": tree["learning"],
        },
    ).json()

    # Another user sees no bridges, cannot create one over the owner's message,
    # and cannot return it.
    listed = client.get(
        f"{UI}/courses/cs3481/bridges", headers=auth("Bearer token-b")
    )
    assert listed.status_code == 200
    assert listed.json() == []
    forged = client.post(
        f"{UI}/courses/cs3481/bridges",
        headers=auth("Bearer token-b"),
        json={
            "problem_message": problem["assistant"]["id"],
            "step": 1,
            "question": "为什么先审题？",
            "node": tree["learning"],
        },
    )
    assert forged.status_code == 404
    returned = client.patch(
        f"{UI}/bridges/{created['id']}/return", headers=auth("Bearer token-b")
    )
    assert returned.status_code == 404
    # Owner still owns the open bridge.
    assert len(
        client.get(f"{UI}/courses/cs3481/bridges", headers=auth("Bearer token-a")).json()
    ) == 1


def test_fake_step_rejected_and_cancel_leaves_no_delivery_link(client: TestClient) -> None:
    import asyncio

    provider: ScriptedProvider = client.app.state.ui_provider
    provider.responses.append(PROBLEM_ANSWER)
    problem = problem_run(client)
    tree = client.app.state.tree_ids

    fake = client.post(
        f"{UI}/courses/cs3481/bridges",
        headers=auth("Bearer token-a"),
        json={
            "problem_message": problem["assistant"]["id"],
            "step": 99,
            "question": "第 99 步存在吗？",
            "node": tree["learning"],
        },
    )
    assert fake.status_code == 422

    bridge = client.post(
        f"{UI}/courses/cs3481/bridges",
        headers=auth("Bearer token-a"),
        json={
            "problem_message": problem["assistant"]["id"],
            "step": 1,
            "question": "为什么先审题？",
            "node": tree["learning"],
        },
    ).json()

    original = provider.generate

    async def blocked(course, text, profile, sources, history, lane, bridge=None, **kwargs):
        provider.calls.append({"lane": lane, "text": text})
        for _ in range(400):
            yield {"kind": "status", "status": "generating", "label": "阻塞中"}
            await asyncio.sleep(0.05)

    provider.generate = blocked
    try:
        conversation = client.post(
            f"{UI}/conversations",
            headers=auth("Bearer token-a"),
            json={"course": "cs3481", "lane": "teach"},
        ).json()
        started = client.post(
            f"{UI}/conversations/{conversation['id']}/runs",
            headers=auth("Bearer token-a"),
            json={
                "text": "会被取消的教学",
                "request_id": "bridge-cancel-000001",
                "bridge_id": bridge["id"],
                "node_id": tree["learning"],
            },
        )
        time.sleep(0.4)
        client.post(
            f"{UI}/runs/{started.json()['id']}/cancel", headers=auth("Bearer token-a")
        )
        row = wait_terminal(client, started.json()["id"])
        assert row["status"] == "cancelled"
        assert row.get("coverage") is None
    finally:
        provider.generate = original

    listed = client.get(
        f"{UI}/courses/cs3481/bridges", headers=auth("Bearer token-a")
    ).json()[0]
    assert listed["teach_run"] == started.json()["id"]  # the run started...
    assert listed["delivery_unit_id"] is None  # ...but never delivered
    with client.app.state.database.connect() as connection:
        units = connection.execute(
            "SELECT COUNT(*) FROM teaching_units WHERE operation_id=?",
            (started.json()["id"],),
        ).fetchone()[0]
        assert units == 0


def test_unbound_node_bridge_stays_navigable_without_coverage(client: TestClient) -> None:
    provider: ScriptedProvider = client.app.state.ui_provider
    provider.responses.append(PROBLEM_ANSWER)
    provider.responses.append("普通讲解，不绑定知识点。")
    problem = problem_run(client)

    bridge = client.post(
        f"{UI}/courses/cs3481/bridges",
        headers=auth("Bearer token-a"),
        json={
            "problem_message": problem["assistant"]["id"],
            "step": 1,
            "question": "这一步用什么知识？",
            "node": None,
        },
    )
    assert bridge.status_code == 201, bridge.text
    assert bridge.json()["problem_revision_id"]  # the problem is still versioned

    conversation = client.post(
        f"{UI}/conversations",
        headers=auth("Bearer token-a"),
        json={"course": "cs3481", "lane": "teach"},
    ).json()
    taught = client.post(
        f"{UI}/conversations/{conversation['id']}/runs",
        headers=auth("Bearer token-a"),
        json={
            "text": "请讲解这一步背后的知识",
            "request_id": "bridge-unbound-000001",
            "bridge_id": bridge.json()["id"],
        },
    )
    row = wait_terminal(client, taught.json()["id"])
    assert row["status"] == "completed"
    assert row.get("coverage") is None  # no node -> no journey -> no bookkeeping

    listed = client.get(
        f"{UI}/courses/cs3481/bridges", headers=auth("Bearer token-a")
    ).json()[0]
    assert listed["teach_run"] is None
    assert listed["journey_id"] is None
    assert listed["delivery_unit_id"] is None
    with client.app.state.database.connect() as connection:
        journeys = connection.execute(
            "SELECT COUNT(*) FROM learning_journeys"
        ).fetchone()[0]
        # Only the fixture's own two journeys exist; this flow added none.
        assert journeys == 2
