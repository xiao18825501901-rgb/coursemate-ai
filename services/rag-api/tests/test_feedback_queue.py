"""The feedback review queue is durable, private and inert.

The spec's P2 module is deliberately small: a user-initiated "报告问题" report is
triaged (one batched Jev call), recorded with identifiers only unless the user opted
in to attaching the body, and queued for a human. These tests hold it to exactly that:

* the queue survives a restart (it is read from the database, not process memory);
* a body exists **only** with the opt-in — enforced by the schema, so no future code
  path can store one without it;
* a repeated submission queues the report once;
* only an admin can list the queue, and a user only ever sees their own reports;
* nothing resolves, deletes or sanctions anything: every queued row stays `OPEN`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.services.feedback_store import FeedbackStore


class FakeAuthVerifier:
    SUBJECTS = {
        "Bearer token-a": "user-a",
        "Bearer token-b": "user-b",
        "Bearer admin-token": "user-admin",
    }

    def authenticate(self, request):  # noqa: ANN001, ANN201
        return self.SUBJECTS.get(request.headers.get("authorization", ""))


class FakeEmbeddingProvider:
    def embed_texts(self, texts):  # noqa: ANN001, ANN201
        return [[1.0, 0.0, 0.0] for _ in texts]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": token}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        database_path=tmp_path / "feedback.sqlite3",
        upload_dir=tmp_path / "uploads",
        admin_user_ids="user-admin",
        app_env="test",
        v3_enabled=True,
        ui_extension_enabled=False,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )
    application = create_app(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )
    with TestClient(application) as test_client:
        yield test_client


def submit(client: TestClient, **overrides) -> dict:
    payload = {
        "course_id": "cs3481",
        "message_id": "message_1",
        "run_id": "run_1",
        "model": "deepseek-flash",
        "template_version": "V2",
        "app_version": "local",
        "product_surface": "learn",
    }
    payload.update(overrides)
    response = client.post("/api/feedback", headers=auth("Bearer token-a"), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def database_of(client: TestClient) -> Database:
    return client.app.state.database


def test_submitted_report_is_queued_and_survives_a_restart(client: TestClient) -> None:
    body = submit(client)

    # A brand-new store over the same database is what a restart looks like: the queue
    # is read from the table, not from the triage object's memory.
    store = FeedbackStore(database_of(client))
    queued = store.by_report_key(str(body["report_key"]))
    assert queued is not None
    assert queued["owner_user_id"] == "user-a"
    assert queued["course_id"] == "cs3481"
    assert queued["status"] == "OPEN"  # a human moves it; nothing resolves it here
    assert queued["attach_body"] is False
    # Identifiers only: the report carried no body and none was stored.
    assert queued["report_text"] is None
    assert queued["question_text"] is None
    assert queued["answer_text"] is None
    assert queued["message_id"] == "message_1"
    assert queued["run_id"] == "run_1"
    assert queued["model"] == "deepseek-flash"
    assert queued["template_version"] == "V2"
    # The triage suggestion and its provenance are recorded, not invented.
    assert queued["category"] in {"ANSWER_WRONG", "CITATION_WRONG", "QUESTION_INCOMPLETE",
                                  "IMAGE_RECOGNITION", "GRADING_DISPUTE",
                                  "COURSE_CLASSIFICATION", "SERVICE_FAULT", "OTHER"}
    assert 0 <= int(queued["severity"]) <= 3
    assert queued["suggested_queue"] in {"priority", "service", "grading", "content", "triage"}
    assert queued["path"].startswith(("jev", "fallback:"))


def test_body_is_stored_only_with_the_opt_in(client: TestClient) -> None:
    submit(
        client,
        message_id="message_2",
        attach_body=True,
        report_text="答案里的公式错了",
        question="求导数",
        answer="x^2 的导数是 x",
    )
    store = FeedbackStore(database_of(client))
    rows = store.owned("user-a")
    opted_in = next(row for row in rows if row["message_id"] == "message_2")
    assert opted_in["attach_body"] is True
    assert opted_in["report_text"] == "答案里的公式错了"
    assert opted_in["question_text"] == "求导数"

    # And the rule is structural, not merely enforced by the endpoint: the schema
    # refuses a body that did not opt in, whoever writes it.
    with database_of(client).connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO feedback_reports("
            "id,report_key,owner_user_id,owner_scope_hash,course_id,category,"
            "severity,suggested_queue,path,attach_body,report_text) "
            "VALUES('sneaky','sneaky-key','user-a','hash','cs3481','OTHER',2,"
            "'CONTENT','jev',0,'a body that never opted in')"
        )


def test_repeated_submission_of_the_same_report_queues_it_once(client: TestClient) -> None:
    first = submit(client, message_id="message_3")
    second = submit(client, message_id="message_3")

    assert first["report_key"] == second["report_key"]  # same report, same key
    with database_of(client).connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM feedback_reports WHERE report_key=?",
            (first["report_key"],),
        ).fetchone()[0]
    assert count == 1


def test_queue_listing_requires_an_admin(client: TestClient) -> None:
    submit(client, message_id="message_4")

    forbidden = client.get("/api/feedback/queue", headers=auth("Bearer token-a"))
    assert forbidden.status_code == 403

    allowed = client.get("/api/feedback/queue", headers=auth("Bearer admin-token"))
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["count"] == 1
    assert body["reports"][0]["message_id"] == "message_4"


def test_queue_is_ordered_by_severity_and_a_user_sees_only_their_own(
    client: TestClient,
) -> None:
    # Two owners report; the queue is for the reviewer, "mine" is for the user.
    submit(client, message_id="message-a1")
    client.post(
        "/api/feedback",
        headers=auth("Bearer token-b"),
        json={"course_id": "cs3481", "message_id": "message-b1"},
    )

    queue = client.get("/api/feedback/queue", headers=auth("Bearer admin-token")).json()
    severities = [row["severity"] for row in queue["reports"]]
    assert severities == sorted(severities, reverse=True)  # most severe first
    assert {row["owner_user_id"] for row in queue["reports"]} == {"user-a", "user-b"}

    mine = client.get("/api/feedback/mine", headers=auth("Bearer token-a")).json()
    assert {row["owner_user_id"] for row in mine["reports"]} == {"user-a"}
    assert mine["count"] == 1


def test_nothing_in_the_store_can_resolve_or_delete_a_report(client: TestClient) -> None:
    """The module is a queue, not a CRM: no auto-resolution surface exists."""
    submit(client, message_id="message_5")
    store = FeedbackStore(database_of(client))

    public_methods = {
        name for name in dir(store) if not name.startswith("_") and callable(getattr(store, name))
    }
    # Deliberately read/append only. Adding a mutating method must be a conscious act
    # that fails this test and forces the reviewer workflow to be designed first.
    assert public_methods == {"record", "queue", "owned", "by_report_key"}

    for row in store.queue(status=None):
        assert row["status"] == "OPEN"
