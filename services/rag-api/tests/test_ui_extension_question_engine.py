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
from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.jev.catalog import load_catalog
from app.jev.errors import JevNotConfiguredError
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService
from app.learning.workspaces import join_course

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

    def fake_gateway(
        *,
        receipt_store: Any,
        modes: Any,
        transport: Any = None,
        default_mode: Any = None,
    ) -> JevGateway:
        del modes, transport, default_mode
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


def activate_learning_loop_pack(client: TestClient, course_id: str, node_id: str) -> None:
    database = client.app.state.database
    manifest_hash = hashlib.sha256(b"synthetic-pack-source").hexdigest()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO learning_loop_pack_revisions("
            "id,course_id,offering_id,revision,source_manifest_hash,source_refs_json,"
            "rights_status,review_status,status,created_by_user_id) "
            "VALUES(?,?,?,1,?,'[]','OWNER_PRIVATE','AI_ORGANIZED','ACTIVE',?)",
            ("pack-mounted-r1", course_id, course_id, manifest_hash, SUBJECT),
        )
        connection.execute(
            "INSERT INTO learning_loop_pack_targets("
            "pack_revision_id,node_id,spec_version,objective_id) VALUES(?, ?, 1, ?)",
            ("pack-mounted-r1", node_id, "objective-density"),
        )
        connection.execute(
            "INSERT INTO learning_loop_course_flags("
            "course_id,enabled,enabled_by_user_id,enabled_at,history_complete_from) "
            "VALUES(?,1,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'),"
            "'1970-01-01T00:00:00.000Z')",
            (course_id, SUBJECT),
        )


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


def wait_practice_evaluation(client: TestClient, exercise_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(f"{UI}/exercises/{exercise_id}", headers=auth())
        assert response.status_code == 200, response.text
        attempt = response.json().get("latest_attempt")
        if attempt and attempt.get("status") not in {"PENDING", "RUNNING"}:
            return attempt
        time.sleep(0.05)
    raise AssertionError("saved practice submission did not finish evaluation")


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

    with test_client.app.state.database.connect() as connection:
        operation = connection.execute(
            "SELECT status FROM learning_operations WHERE id=?",
            (started.json()["id"],),
        ).fetchone()
        reservations = connection.execute(
            "SELECT role,status FROM learning_model_call_reservations "
            "WHERE operation_id=? ORDER BY rowid",
            (started.json()["id"],),
        ).fetchall()
        model_runs = connection.execute(
            "SELECT role,status FROM learning_model_run_evidence "
            "WHERE operation_id=? ORDER BY rowid",
            (started.json()["id"],),
        ).fetchall()
    assert operation["status"] == "COMPLETED"
    assert [tuple(row) for row in reservations] == [
        ("QUESTION_AUTHOR", "COMPLETED"),
        ("QUESTION_BLIND_SOLVER", "COMPLETED"),
    ]
    assert [tuple(row) for row in model_runs] == [
        ("QUESTION_AUTHOR", "COMPLETED"),
        ("QUESTION_BLIND_SOLVER", "COMPLETED"),
    ]

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
    assert attempted.status_code == 202, attempted.text
    assert attempted.json()["status"] == "PENDING"
    assert attempted.json()["assistance"] == "HINT"
    assert attempted.json()["independent"] is False
    assert attempted.json()["feedback"] is None
    evaluated = wait_practice_evaluation(test_client, exercise["id"])
    assert evaluated["assistance"] == "HINT"
    assert evaluated["independent"] is False
    assert evaluated["feedback"]

    restored = test_client.get(f"{UI}/exercises/{exercise['id']}", headers=auth())
    assert restored.status_code == 200, restored.text
    assert restored.json()["hint_count"] == 1
    assert restored.json()["latest_hint"]["id"] == hint.json()["id"]
    assert restored.json()["latest_attempt"]["id"] == evaluated["id"]
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
    assert historical["latest_attempt"]["id"] == evaluated["id"]

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
    assert assisted_after_reveal.status_code == 202, assisted_after_reveal.text
    assert assisted_after_reveal.json()["assistance"] == "ANSWER_REVEALED"
    assert assisted_after_reveal.json()["independent"] is False
    assisted_evaluated = wait_practice_evaluation(test_client, exercise["id"])
    assert assisted_evaluated["assistance"] == "ANSWER_REVEALED"
    assert assisted_evaluated["independent"] is False

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
    second_exercise = ui_database.one(
        "SELECT * FROM cmui_exercises WHERE run=?", (repeated.json()["id"],)
    )
    submitted_before_reveal = test_client.post(
        f"{UI}/exercises/{second_exercise['id']}/attempts",
        headers=auth(),
        json={
            "request_id": "question-engine-attempt-before-reveal",
            "answer": "A substantive independent answer saved before opening the solution.",
        },
    )
    assert submitted_before_reveal.status_code == 202
    assert submitted_before_reveal.json()["independent"] is True
    assert test_client.post(
        f"{UI}/exercises/{second_exercise['id']}/reveal",
        headers=auth(),
        json={"request_id": "question-engine-reveal-after-submit"},
    ).status_code == 200
    frozen = wait_practice_evaluation(test_client, second_exercise["id"])
    assert frozen["independent"] is True
    assert frozen["assistance"] == "NONE"
    with test_client.app.state.database.connect() as connection:
        families = connection.execute(
            "SELECT question.family_id FROM question_engine_provenance AS provenance "
            "JOIN assessment_question_revisions AS question "
            "ON question.id=provenance.question_revision_id "
            "WHERE provenance.workspace_id=? ORDER BY question.rowid",
            (provenance["workspace_id"],),
        ).fetchall()
    assert len({item["family_id"] for item in families}) == 2


def test_unbound_pair_selects_an_owner_scoped_atomic_node_with_active_spec(
    client: tuple[TestClient, ForbiddenLegacyExerciseProvider],
) -> None:
    test_client, legacy = client
    created = test_client.post(
        f"{UI}/courses",
        headers=auth(),
        json={"name": "Unbound private course", "description": "offline fixture"},
    )
    assert created.status_code == 201, created.text
    course_id = created.json()["id"]
    valid_node_id = seed_objective(test_client, course_id)
    database = test_client.app.state.database
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO knowledge_nodes(id,course_id,owner_user_id,title,description,"
            "major,kind,status) VALUES('node-without-active-spec',?,?,'No spec',"
            "'Must be skipped','CS','ATOMIC','PRIVATE')",
            (course_id, SUBJECT),
        )
    pair = test_client.post(
        f"{UI}/pairs", headers=auth(), json={"course": course_id}
    ).json()

    started = test_client.post(
        f"{UI}/courses/{course_id}/exercises",
        headers=auth(),
        json={"pair_id": pair["id"], "request_id": "unbound-valid-spec-0001"},
    )
    assert started.status_code == 202, started.text
    run = wait_terminal(test_client, started.json()["id"])
    assert run["status"] == "completed", run
    assert legacy.exercise_calls == 0
    ui_database = test_client.app.state.ui_extension_app.state.db
    exercise = ui_database.one(
        "SELECT node,target_node FROM cmui_exercises WHERE run=?",
        (started.json()["id"],),
    )
    assert exercise["node"] == valid_node_id
    assert exercise["target_node"] == "Density clustering"


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


def test_mounted_learning_loop_closes_on_unseen_valid_transfer_and_projects_card(
    client: tuple[TestClient, ForbiddenLegacyExerciseProvider],
) -> None:
    test_client, _legacy = client
    course = test_client.post(
        f"{UI}/courses", headers=auth(),
        json={"name": "Synthetic loop course", "description": "offline fixture"},
    ).json()
    node_id = seed_objective(test_client, course["id"])
    activate_learning_loop_pack(test_client, course["id"], node_id)
    pair = test_client.post(
        f"{UI}/pairs", headers=auth(), json={"course": course["id"]}
    ).json()

    initial_run = test_client.post(
        f"{UI}/courses/{course['id']}/exercises", headers=auth(),
        json={"pair_id": pair["id"], "node": node_id,
              "request_id": "mounted-loop-initial-question"},
    ).json()["id"]
    assert wait_terminal(test_client, initial_run)["status"] == "completed"
    ui_database = test_client.app.state.ui_extension_app.state.db
    initial = ui_database.one("SELECT * FROM cmui_exercises WHERE run=?", (initial_run,))
    assert initial["learning_cycle_id"]
    assert initial["learning_assignment_id"]

    submitted = test_client.post(
        f"{UI}/exercises/{initial['id']}/attempts", headers=auth(),
        json={"request_id": "mounted-loop-initial-attempt",
              "answer": "A substantive initial answer that may still be incorrect."},
    )
    assert submitted.status_code == 202
    wait_practice_evaluation(test_client, initial["id"])
    projected = test_client.get(f"{UI}/exercises/{initial['id']}", headers=auth()).json()
    assert projected["evidence_card"]["state"] == "INTERVENTION_DELIVERED"

    transfer_run = test_client.post(
        f"{UI}/courses/{course['id']}/exercises", headers=auth(),
        json={"pair_id": pair["id"], "node": node_id,
              "cycle_id": initial["learning_cycle_id"], "purpose": "TRANSFER",
              "request_id": "mounted-loop-transfer-question"},
    ).json()["id"]
    assert wait_terminal(test_client, transfer_run)["status"] == "completed"
    transfer = ui_database.one("SELECT * FROM cmui_exercises WHERE run=?", (transfer_run,))
    assert transfer["learning_cycle_id"] == initial["learning_cycle_id"]
    assert transfer["learning_assignment_id"] != initial["learning_assignment_id"]

    saved = test_client.post(
        f"{UI}/exercises/{transfer['id']}/attempts", headers=auth(),
        json={"request_id": "mounted-loop-transfer-attempt",
              "answer": "A real transfer attempt saved before any help was opened."},
    )
    assert saved.status_code == 202
    assert saved.json()["independent"] is True
    test_client.post(
        f"{UI}/exercises/{transfer['id']}/reveal", headers=auth(),
        json={"request_id": "mounted-loop-transfer-reveal"},
    )
    wait_practice_evaluation(test_client, transfer["id"])
    final = test_client.get(f"{UI}/exercises/{transfer['id']}", headers=auth()).json()
    assert final["evidence_card"]["historical_closure_exists"] is True
    assert final["evidence_card"]["currently_valid_closure"] is True
    assert final["evidence_card"]["attempts"][-1]["original_within_platform_unassisted"] is True
