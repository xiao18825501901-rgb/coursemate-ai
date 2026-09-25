"""The mounted 做一题 action consumes the V3 Question Engine offline.

All data is synthetic.  DeepSeek calls are the labelled deterministic fixture;
TypeSafe decisions use an injected fake transport.  The test proves the real
mounted HTTP/database path without contacting a provider.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from app.jev.catalog import load_catalog
from app.jev.errors import JevNotConfiguredError
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService
from app.learning.workspaces import join_course
from fastapi import Request
from fastapi.testclient import TestClient

UI = "/ui-extension/api/ui/v1"
SUBJECT = "user-a"


class FakeAuthVerifier:
    def authenticate(self, request: Request) -> str | None:
        return SUBJECT if request.headers.get("authorization") == "Bearer token-a" else None


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class ForbiddenLegacyExerciseProvider:
    """The integrated action must not fall back to the old UI exercise author."""

    def __init__(self) -> None:
        self.exercise_calls = 0

    async def generate_exercise(self, *_args: Any, **_kwargs: Any):
        self.exercise_calls += 1
        raise AssertionError("legacy UI exercise generator was called")
        yield  # pragma: no cover - makes this an async generator


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        app_env="test",
        v3_enabled=True,
        ui_extension_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, ForbiddenLegacyExerciseProvider]]:
    monkeypatch.setenv("CMUI_PROVIDER_MODE", "test")
    monkeypatch.setenv("CMUI_AUTO_VERIFY_NEW_USERS", "false")

    def responder(call: Any) -> JevResult:
        key = next(iter(call.questions))
        verdict = {
            "exercise.prototype.v1": "worked_application",
            "question.ambiguity.v1": "CLEAR",
            "question.answer_agreement.v1": "AGREE",
        }[key]
        return JevResult(answers={key: JevAnswer(choice=verdict)})

    def fake_gateway(*, receipt_store: Any, modes: Any) -> JevGateway:
        del modes
        return JevGateway(
            transport=FakeTransport(responder),
            catalog=load_catalog(),
            modes={
                "exercise.prototype.v1": "on",
                "question.ambiguity.v1": "on",
                "question.answer_agreement.v1": "on",
            },
            receipt_store=receipt_store,
        )

    main_module = importlib.import_module("app.main")
    monkeypatch.setattr(main_module, "JevGateway", fake_gateway)
    legacy = ForbiddenLegacyExerciseProvider()
    application = main_module.create_app(
        settings=_settings(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
        ui_provider=legacy,
    )
    with TestClient(application) as test_client:
        yield test_client, legacy


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer token-a"}


def seed_objective(client: TestClient, course_id: str) -> str:
    database = client.app.state.database
    workspace = join_course(database, course_id, SUBJECT, 10)
    node_id = "node-density-practice"
    content = "A core point has at least MinPts points in its epsilon neighbourhood."
    item = {
        "item_id": "objective-density",
        "requirement": "REQUIRED",
        "objective": "计算每个点的 epsilon 邻域并判断核心点数量",
        "acceptance": "邻域计数和核心点结论均有课程规则支持",
        "evidence_ids": ["chunk-density-practice"],
    }
    spec_json = json.dumps([item], ensure_ascii=False, sort_keys=True)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO knowledge_nodes(id,course_id,owner_user_id,title,description,"
            "major,kind,status) VALUES(?,?,?,'Density clustering','Synthetic','CS',"
            "'ATOMIC','PRIVATE')",
            (node_id, course_id, SUBJECT),
        )
        connection.execute(
            "INSERT INTO documents(id,course_id,filename,stored_path,media_type,extension,"
            "sha256,byte_size,status,chunk_count) VALUES('doc-density-practice',?,"
            "'lecture.md','lecture.md','text/markdown','.md',?,?,'ready',1)",
            (course_id, "b" * 64, len(content.encode())),
        )
        connection.execute(
            "INSERT INTO chunks(id,document_id,course_id,ordinal,content,locator_type,"
            "locator_value,section,embedding) VALUES('chunk-density-practice',"
            "'doc-density-practice',?,0,?,'page','7','DBSCAN','[]')",
            (course_id, content),
        )
        connection.execute(
            "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) "
            "VALUES(?,1,?,?)",
            (node_id, spec_json, hashlib.sha256(spec_json.encode()).hexdigest()),
        )
    assert workspace["course_id"] == course_id
    return node_id


def wait_terminal(client: TestClient, run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(f"{UI}/runs/{run_id}", headers=auth())
        assert response.status_code == 200, response.text
        row = response.json()
        if row["status"] in {"completed", "failed", "cancelled"}:
            return row
        time.sleep(0.05)
    raise AssertionError("exercise run did not become terminal")


def test_mounted_do_one_question_uses_ready_revision_and_keeps_answer_private(
    client: tuple[TestClient, ForbiddenLegacyExerciseProvider],
) -> None:
    test_client, legacy = client
    created = test_client.post(
        f"{UI}/courses",
        headers=auth(),
        json={"name": "Synthetic question course", "description": "offline fixture"},
    )
    assert created.status_code == 201, created.text
    course_id = created.json()["id"]
    node_id = seed_objective(test_client, course_id)
    pair = test_client.post(
        f"{UI}/pairs", headers=auth(), json={"course": course_id}
    ).json()

    started = test_client.post(
        f"{UI}/courses/{course_id}/exercises",
        headers=auth(),
        json={
            "pair_id": pair["id"],
            "node": node_id,
            "request_id": "question-engine-http-0001",
        },
    )
    assert started.status_code == 202, started.text
    run = wait_terminal(test_client, started.json()["id"])
    assert run["status"] == "completed", run
    assert legacy.exercise_calls == 0

    ui_database = test_client.app.state.ui_extension_app.state.db
    exercise = ui_database.one(
        "SELECT * FROM cmui_exercises WHERE run=?", (started.json()["id"],)
    )
    assert exercise["question_revision_id"]
    assert exercise["verification_status"] == "AI_REVIEWED"
    assert exercise["generation_version"] == "exercise.v2+question-engine.v1"
    stored_steps = json.loads(exercise["answer_steps"])
    private_answer = stored_steps[0]["text"]
    assert private_answer

    events = ui_database.all(
        "SELECT type,data FROM cmui_run_events WHERE run=? ORDER BY seq",
        (started.json()["id"],),
    )
    public_event_text = json.dumps(events, ensure_ascii=False)
    assert private_answer not in public_event_text
    hidden = test_client.get(f"{UI}/exercises/{exercise['id']}", headers=auth())
    assert hidden.status_code == 200
    assert hidden.json()["steps"] == []
    assert private_answer not in hidden.text

    hint = test_client.post(
        f"{UI}/exercises/{exercise['id']}/hints",
        headers=auth(),
        json={"request_id": "question-engine-hint-0001"},
    )
    assert hint.status_code == 200, hint.text
    assert hint.json()["assistance"] == "HINT"
    assert hint.json()["independent"] is False
    assert private_answer not in hint.text

    attempted = test_client.post(
        f"{UI}/exercises/{exercise['id']}/attempts",
        headers=auth(),
        json={
            "request_id": "question-engine-attempt-0001",
            "answer": (
                "I would apply the bounded neighbourhood rule, "
                "but my conclusion is incomplete."
            ),
        },
    )
    assert attempted.status_code == 200, attempted.text
    assert attempted.json()["assistance"] == "HINT"
    assert attempted.json()["independent"] is False
    assert attempted.json()["feedback"]

    restored = test_client.get(f"{UI}/exercises/{exercise['id']}", headers=auth())
    assert restored.status_code == 200, restored.text
    assert restored.json()["hint_count"] == 1
    assert restored.json()["latest_hint"]["id"] == hint.json()["id"]
    assert restored.json()["latest_attempt"]["id"] == attempted.json()["id"]
    conversation_id = ui_database.one(
        "SELECT conversation FROM cmui_messages WHERE exercise=?", (exercise["id"],)
    )["conversation"]
    history = test_client.get(f"{UI}/conversations/{conversation_id}", headers=auth())
    assert history.status_code == 200, history.text
    historical = next(
        item["exercise_state"]
        for item in history.json()["messages"]
        if item.get("exercise") == exercise["id"]
    )
    assert historical["latest_attempt"]["id"] == attempted.json()["id"]

    with test_client.app.state.database.connect() as connection:
        provenance = connection.execute(
            "SELECT workspace_id,publication_status FROM question_engine_provenance "
            "WHERE question_revision_id=?",
            (exercise["question_revision_id"],),
        ).fetchone()
        practice_reservations = connection.execute(
            "SELECT operation_id,role,status FROM learning_model_call_reservations "
            "WHERE role IN ('PRACTICE_HINT','PRACTICE_FEEDBACK') ORDER BY operation_id"
        ).fetchall()
    assert provenance["publication_status"] == "READY"
    assert [tuple(row) for row in practice_reservations] == [
        ("question-engine-attempt-0001", "PRACTICE_FEEDBACK", "COMPLETED"),
        ("question-engine-hint-0001", "PRACTICE_HINT", "COMPLETED"),
    ]

    revealed = test_client.post(
        f"{UI}/exercises/{exercise['id']}/reveal",
        headers=auth(),
        json={"request_id": "question-engine-reveal-0001"},
    )
    assert revealed.status_code == 200, revealed.text
    assert revealed.json()["steps"] == stored_steps

    assisted_after_reveal = test_client.post(
        f"{UI}/exercises/{exercise['id']}/attempts",
        headers=auth(),
        json={
            "request_id": "question-engine-attempt-0002",
            "answer": "This response was written after the worked answer was shown.",
        },
    )
    assert assisted_after_reveal.status_code == 200, assisted_after_reveal.text
    assert assisted_after_reveal.json()["assistance"] == "ANSWER_REVEALED"
    assert assisted_after_reveal.json()["independent"] is False

    repeated = test_client.post(
        f"{UI}/courses/{course_id}/exercises",
        headers=auth(),
        json={
            "pair_id": pair["id"],
            "node": node_id,
            "request_id": "question-engine-http-0002",
        },
    )
    assert repeated.status_code == 202, repeated.text
    repeated_run = wait_terminal(test_client, repeated.json()["id"])
    assert repeated_run["status"] == "completed", repeated_run
    with test_client.app.state.database.connect() as connection:
        families = connection.execute(
            "SELECT question.family_id FROM question_engine_provenance AS provenance "
            "JOIN assessment_question_revisions AS question "
            "ON question.id=provenance.question_revision_id "
            "WHERE provenance.workspace_id=? ORDER BY question.rowid",
            (provenance["workspace_id"],),
        ).fetchall()
    assert len({item["family_id"] for item in families}) == 2


def test_mounted_do_one_question_fails_closed_when_semantic_review_is_unavailable(
    client: tuple[TestClient, ForbiddenLegacyExerciseProvider],
) -> None:
    test_client, legacy = client
    database = test_client.app.state.database
    unavailable = SemanticDecisionService(
        JevGateway(
            transport=FakeTransport(
                lambda _call: JevNotConfiguredError("synthetic unavailable review")
            ),
            catalog=load_catalog(),
            modes={
                "exercise.prototype.v1": "on",
                "question.ambiguity.v1": "on",
                "question.answer_agreement.v1": "on",
            },
            receipt_store=SqlReceiptStore(database),
        )
    )
    test_client.app.state.ui_extension_adapter.question_engine.semantic_decisions = unavailable

    created = test_client.post(
        f"{UI}/courses",
        headers=auth(),
        json={"name": "Unavailable review course", "description": "offline fixture"},
    )
    assert created.status_code == 201, created.text
    course_id = created.json()["id"]
    node_id = seed_objective(test_client, course_id)
    pair = test_client.post(
        f"{UI}/pairs", headers=auth(), json={"course": course_id}
    ).json()
    started = test_client.post(
        f"{UI}/courses/{course_id}/exercises",
        headers=auth(),
        json={
            "pair_id": pair["id"],
            "node": node_id,
            "request_id": "question-engine-review-unavailable",
        },
    )
    assert started.status_code == 202, started.text
    run = wait_terminal(test_client, started.json()["id"])
    assert run["status"] == "failed"
    assert run["error"] == "QUESTION_ENGINE_FAILED"
    assert legacy.exercise_calls == 0

    ui_database = test_client.app.state.ui_extension_app.state.db
    assert ui_database.one(
        "SELECT COUNT(*) AS n FROM cmui_exercises WHERE run=?",
        (started.json()["id"],),
    )["n"] == 0
    with database.connect() as connection:
        statuses = connection.execute(
            "SELECT publication_status FROM question_engine_provenance"
        ).fetchall()
    assert statuses
    assert {row["publication_status"] for row in statuses} == {"NEEDS_REVIEW"}
