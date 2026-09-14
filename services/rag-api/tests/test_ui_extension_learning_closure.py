"""The refreshed shell must write to the authoritative V3 learning state - or, where
the semantics forbid it, stay visibly honest about what it does not write.

Two directions are covered with real database assertions:

1. A teach run that targets a knowledge node starts the caller's V3 learning
   journey (the same `learning_journeys` row V3 teach() creates) and records the
   cross-reference in the UI database. It NEVER claims REQUIRED-item coverage:
   coverage stays exclusively owned by V3 teach()/teaching_delivery_evidence, so
   the node's progress remains NOT_STARTED until real evidence exists.

2. The assessment entry point is no longer read-only: a real V3 session can be
   started, viewed (questions visible, answers hidden), submitted with five
   answers, graded into grade_snapshots, and abandoned - and it stays isolated
   from the learning progress and from other users.
"""

from __future__ import annotations

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


class FakeUiProvider:
    """Contract fixture with the same yield vocabulary as the real QwenProvider.

    Not a live model; it exists so the run pipeline can be exercised end to end.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate(self, course, text, profile, sources, history, lane, bridge=None, **kwargs):
        self.calls.append({"text": text, "lane": lane, "node": None, "bridge": bridge})
        yield {"kind": "status", "status": "planning", "label": "测试模型：生成 Prompt"}
        yield {"kind": "prompt", "text": "本地测试：用中文讲解，保留英文术语，逐步例题，最后互动检查。"}
        yield {"kind": "status", "status": "generating", "label": "测试模型：生成内容"}
        yield {"kind": "delta", "text": "## Step 1 理解问题\n先识别条件。"}
        yield {"kind": "delta", "text": "\n\n## Step 2 联系知识\n这是仅用于契约测试的教学输出。 [S1]"}
        yield {"kind": "usage", "stage": "answer", "value": {"input_tokens": 1, "output_tokens": 1}}


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
    provider = FakeUiProvider()
    settings = make_settings(tmp_path)
    application = create_app(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
        ui_provider=provider,
    )
    with TestClient(application) as test_client:
        test_client.app.state.ui_provider = provider  # type: ignore[attr-defined]
        yield test_client


def auth(token: str) -> dict[str, str]:
    return {"Authorization": token}


def create_course_and_seed(client: TestClient) -> str:
    """Create the official course and the synthetic assessment fixture, then return
    the fixture's atomic node id."""

    created = client.post(
        "/api/courses",
        headers=auth("Bearer admin-token"),
        json={"id": "cs3481", "name": "Fundamentals of Data Science", "description": "Notes"},
    )
    assert created.status_code == 201, created.text

    import sys
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).resolve().parents[3] / "scripts"))
    from prepare_v3_e2e import seed_assessment_fixture  # noqa: E402

    return seed_assessment_fixture(client.app.state.database, "user-a")


def wait_terminal(client: TestClient, run_id: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = client.get(f"{UI}/runs/{run_id}", headers=auth("Bearer token-a")).json()
        if row["status"] in {"completed", "failed", "cancelled"}:
            return row
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} did not reach a terminal state in {timeout}s")


def test_teach_run_starts_the_v3_journey_without_claiming_coverage(client: TestClient) -> None:
    node_id = create_course_and_seed(client)
    conversation = client.post(
        f"{UI}/conversations",
        headers=auth("Bearer token-a"),
        json={"course": "cs3481", "lane": "teach"},
    )
    assert conversation.status_code == 201, conversation.text
    conv_id = conversation.json()["id"]

    started = client.post(
        f"{UI}/conversations/{conv_id}/runs",
        headers=auth("Bearer token-a"),
        json={"text": "请从零教我理解这个节点", "request_id": "closure-teach-000001", "node_id": node_id},
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]

    database = client.app.state.database
    with database.connect() as connection:
        journeys = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM learning_journeys WHERE node_id=? ORDER BY rowid", (node_id,)
            )
        ]
    # The journey is the same durable row V3 teach() creates.
    assert len(journeys) == 1
    assert journeys[0]["status"] == "LEARNING"
    assert journeys[0]["spec_version"] == 1

    with client.app.state.ui_extension_app.state.db.connect() as connection:
        links = [
            dict(row)
            for row in connection.execute("SELECT * FROM cmui_run_v3 WHERE run=?", (run_id,))
        ]
    assert len(links) == 1
    assert links[0]["journey_id"] == journeys[0]["id"]
    assert links[0]["node_id"] == node_id

    # The run finishes, and no REQUIRED-item coverage appears: free-text teaching
    # must not fabricate delivery evidence.
    wait_terminal(client, run_id)
    with database.connect() as connection:
        coverage = connection.execute(
            "SELECT COUNT(*) AS n FROM teaching_delivery_evidence WHERE journey_id=?",
            (journeys[0]["id"],),
        ).fetchone()[0]
    assert coverage == 0

    tree = client.get(f"{UI}/courses/cs3481/knowledge", headers=auth("Bearer token-a")).json()
    node = next(row for row in tree if row["id"] == node_id)
    # Progress stays honest: NOT_STARTED until real V3 coverage exists.
    assert node["progress"] == "NOT_STARTED"

    # A second teach run on the same node reuses the same journey - idempotent.
    second = client.post(
        f"{UI}/conversations/{conv_id}/runs",
        headers=auth("Bearer token-a"),
        json={"text": "再讲一遍", "request_id": "closure-teach-000002", "node_id": node_id},
    )
    assert second.status_code == 202, second.text
    wait_terminal(client, second.json()["id"])
    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM learning_journeys WHERE node_id=?", (node_id,)
        ).fetchone()[0]
    assert count == 1


def test_unknown_node_rejects_the_run_before_any_row_is_written(client: TestClient) -> None:
    create_course_and_seed(client)
    conversation = client.post(
        f"{UI}/conversations",
        headers=auth("Bearer token-a"),
        json={"course": "cs3481", "lane": "teach"},
    )
    conv_id = conversation.json()["id"]

    response = client.post(
        f"{UI}/conversations/{conv_id}/runs",
        headers=auth("Bearer token-a"),
        json={"text": "教我", "request_id": "closure-teach-000003", "node_id": "not-a-real-node"},
    )
    assert response.status_code == 404
    with client.app.state.ui_extension_app.state.db.connect() as connection:
        runs = connection.execute(
            "SELECT COUNT(*) FROM cmui_runs WHERE request_id='closure-teach-000003'"
        ).fetchone()[0]
    assert runs == 0


def test_assessment_lifecycle_from_start_to_grade(client: TestClient) -> None:
    node_id = create_course_and_seed(client)
    summary = client.get(
        f"{UI}/courses/cs3481/knowledge/{node_id}/assessment", headers=auth("Bearer token-a")
    )
    assert summary.status_code == 200
    assert summary.json()["status"] == "NOT_ASSESSED"
    assert summary.json()["grade"] is None

    started = client.post(
        f"{UI}/courses/cs3481/knowledge/{node_id}/assessment/session",
        headers=auth("Bearer token-a"),
        json={"request_id": "closure-assessment-000001"},
    )
    assert started.status_code == 201, started.text
    session_id = started.json()["id"]

    view = client.get(
        f"{UI}/courses/cs3481/knowledge/assessment/{session_id}", headers=auth("Bearer token-a")
    )
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["status"] == "IN_PROGRESS"
    assert len(body["questions"]) == 5
    for question in body["questions"]:
        assert question["prompt"].startswith("Synthetic assessment question")
        # The answer key must stay hidden before submission.
        assert "review" not in question

    submitted = client.post(
        f"{UI}/courses/cs3481/knowledge/assessment/{session_id}/submit",
        headers=auth("Bearer token-a"),
        json={
            "request_id": "closure-assessment-000002",
            "answers": [
                {"blueprint_item_id": question["id"], "answer": "correct"}
                for question in body["questions"]
            ],
        },
    )
    assert submitted.status_code == 200, submitted.text

    graded = client.get(
        f"{UI}/courses/cs3481/knowledge/assessment/{session_id}", headers=auth("Bearer token-a")
    ).json()
    assert graded["status"] == "GRADED"
    assert isinstance(graded["raw_score"], (int, float))
    for question in graded["questions"]:
        assert "review" in question
        assert question["review"]["submitted_answer"] == "correct"

    database = client.app.state.database
    with database.connect() as connection:
        snapshots = connection.execute(
            "SELECT COUNT(*) FROM grade_snapshots WHERE assessment_session_id=?", (session_id,)
        ).fetchone()[0]
        session_status = connection.execute(
            "SELECT status FROM assessment_sessions WHERE id=?", (session_id,)
        ).fetchone()[0]
    assert snapshots == 1
    assert session_status == "GRADED"

    # The graded result is what the node entry now reports, and it did NOT touch
    # the learning progress: the two states stay independent.
    after = client.get(
        f"{UI}/courses/cs3481/knowledge/{node_id}/assessment", headers=auth("Bearer token-a")
    ).json()
    assert after["status"] == "GRADED"
    tree = client.get(f"{UI}/courses/cs3481/knowledge", headers=auth("Bearer token-a")).json()
    node = next(row for row in tree if row["id"] == node_id)
    assert node["progress"] == "NOT_STARTED"


def test_assessment_can_be_abandoned_and_restarted(client: TestClient) -> None:
    node_id = create_course_and_seed(client)
    started = client.post(
        f"{UI}/courses/cs3481/knowledge/{node_id}/assessment/session",
        headers=auth("Bearer token-a"),
        json={"request_id": "closure-assessment-000011"},
    ).json()

    abandoned = client.post(
        f"{UI}/courses/cs3481/knowledge/assessment/{started['id']}/abandon",
        headers=auth("Bearer token-a"),
        json={"request_id": "closure-assessment-000012"},
    )
    assert abandoned.status_code == 200, abandoned.text

    restarted = client.post(
        f"{UI}/courses/cs3481/knowledge/{node_id}/assessment/session",
        headers=auth("Bearer token-a"),
        json={"request_id": "closure-assessment-000013"},
    )
    assert restarted.status_code == 201, restarted.text


def test_assessment_session_is_isolated_between_users(client: TestClient) -> None:
    node_id = create_course_and_seed(client)
    started = client.post(
        f"{UI}/courses/cs3481/knowledge/{node_id}/assessment/session",
        headers=auth("Bearer token-a"),
        json={"request_id": "closure-assessment-000021"},
    ).json()

    foreign = client.get(
        f"{UI}/courses/cs3481/knowledge/assessment/{started['id']}",
        headers=auth("Bearer token-b"),
    )
    assert foreign.status_code == 404
