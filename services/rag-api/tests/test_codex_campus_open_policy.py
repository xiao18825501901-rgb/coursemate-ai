"""Current campus access policy and the dormant future verification gate.

These tests deliberately leave student-verification records untouched.  Access
comes from the policy, never from pretending every registered user is verified.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_assessment_runtime import seed_assessment_pool
from test_current_change_features import (
    UI,
    FakeAuthVerifier,
    FakeEmbeddingProvider,
    auth,
    disable_local_identity,
    make_course,
    make_settings,
    seed_question_objective,
)

from app.cm_update import social
from app.cm_update.campus_access import (
    NEW_USERS_REQUIRE_VERIFICATION,
    OPEN_TO_REGISTERED,
    can_access_campus,
)
from app.cm_update.config import Settings as UiSettings
from app.cm_update.db import Database
from app.main import create_app


def wait_terminal_as(client: TestClient, run_id: str, token: str) -> dict:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(f"{UI}/runs/{run_id}", headers=auth(token))
        assert response.status_code == 200, response.text
        row = response.json()
        if row["status"] in {"completed", "failed", "cancelled"}:
            return row
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not finish")


@pytest.fixture
def open_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("CMUI_PROVIDER_MODE", "test")
    monkeypatch.setenv("CMUI_AUTO_VERIFY_NEW_USERS", "false")
    monkeypatch.setenv("CMUI_CAMPUS_ACCESS_MODE", OPEN_TO_REGISTERED)
    monkeypatch.delenv("CMUI_VERIFICATION_EFFECTIVE_AT", raising=False)
    application = create_app(
        settings=make_settings(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )
    with TestClient(application) as test_client:
        yield test_client


def test_open_policy_allows_active_unverified_users_on_both_route_families(
    open_client: TestClient,
) -> None:
    make_course(open_client)

    status = open_client.get(f"{UI}/me/verification", headers=auth("token-c"))
    assert status.status_code == 200
    assert status.json() == {"verified": False, "method": None, "verified_at": None}

    responses = {
        "catalog": open_client.get(f"{UI}/courses", headers=auth("token-c")),
        "course": open_client.get(f"{UI}/courses/cs3481", headers=auth("token-c")),
        "pin": open_client.put(f"{UI}/courses/cs3481/pin", headers=auth("token-c")),
        "files": open_client.get(f"{UI}/courses/cs3481/files", headers=auth("token-c")),
        "knowledge": open_client.get(
            f"{UI}/courses/cs3481/knowledge", headers=auth("token-c")
        ),
        "comments": open_client.get(
            f"{UI}/courses/cs3481/comments", headers=auth("token-c")
        ),
        "legacy_documents": open_client.get(
            "/api/courses/cs3481/documents", headers=auth("token-c")
        ),
        "learning": open_client.post(
            "/api/learning/workspaces",
            headers=auth("token-c"),
            json={"course_id": "cs3481"},
        ),
    }
    assert {name: response.status_code for name, response in responses.items()} == {
        "catalog": 200,
        "course": 200,
        "pin": 200,
        "files": 200,
        "knowledge": 200,
        "comments": 200,
        "legacy_documents": 200,
        "learning": 200,
    }, {name: response.text for name, response in responses.items()}

    # Opening campus access changes no verification fact.
    assert open_client.app.state.ui_extension_app.state.db.one(
        "SELECT * FROM cmui_verification WHERE owner='user-c'"
    ) is None


def test_open_policy_still_denies_anonymous_disabled_and_other_users_private_data(
    open_client: TestClient,
) -> None:
    make_course(open_client)
    assert open_client.get(f"{UI}/courses").status_code == 401

    created = open_client.post(
        f"{UI}/courses",
        headers=auth("token-c"),
        json={"name": "Private Canvas Course", "code": "PRIVATE-C"},
    )
    assert created.status_code == 201, created.text
    private_id = created.json()["id"]
    denied = open_client.get(
        f"{UI}/courses/{private_id}/files", headers=auth("token-d")
    )
    assert denied.status_code in {403, 404}

    disable_local_identity(open_client, "user-c")
    assert open_client.get(
        f"{UI}/courses", headers=auth("token-c")
    ).status_code == 403
    assert open_client.get(
        "/api/courses", headers=auth("token-c")
    ).status_code == 403
    assert open_client.get(
        f"{UI}/courses/cs3481/files", headers=auth("token-c")
    ).status_code == 403
    assert open_client.get(
        "/api/courses/cs3481/documents", headers=auth("token-c")
    ).status_code == 403


def test_open_policy_allows_unverified_recipient_to_join_a_campus_snapshot(
    open_client: TestClient,
) -> None:
    make_course(open_client)
    assert open_client.get(f"{UI}/me", headers=auth("token-c")).status_code == 200
    sent = open_client.post(
        f"{UI}/shares",
        headers=auth("token-a"),
        json={
            "course": "cs3481",
            "recipients": ["user-c"],
            "history_scope": "none",
            "request_id": "open-campus-snapshot",
        },
    )
    assert sent.status_code == 201, sent.text
    joined = open_client.post(
        f"{UI}/shares/{sent.json()['id']}/join",
        headers=auth("token-c"),
    )
    assert joined.status_code == 200, joined.text
    assert social.verification_status(
        open_client.app.state.ui_extension_app.state.db,
        "user-c",
    )["verified"] is False


def test_open_policy_covers_files_rag_learning_exercise_assessment_and_sse(
    open_client: TestClient,
) -> None:
    """An active unverified account crosses every campus-content gate."""

    make_course(open_client)
    with open_client.app.state.database.connect() as connection:
        connection.execute(
            "INSERT INTO knowledge_nodes(id,course_id,owner_user_id,title,description,"
            "major,kind,status) VALUES('node-c','cs3481','user-c','Node C',"
            "'Synthetic definition','CS','ATOMIC','PRIVATE')"
        )
    seed_question_objective(open_client, "node-c", "node c")

    uploaded = open_client.post(
        f"{UI}/courses/cs3481/files",
        headers=auth("token-c"),
        files={
            "file": (
                "private-notes.md",
                b"# Private notes\n\nA transaction preserves consistency.",
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    file_id = uploaded.json()["id"]
    for path in (
        f"{UI}/courses/cs3481/files/{file_id}/content",
        f"{UI}/courses/cs3481/files/{file_id}/content?download=true",
        f"{UI}/courses/cs3481/files/{file_id}/text",
    ):
        response = open_client.get(path, headers=auth("token-c"))
        assert response.status_code == 200, (path, response.text)

    workspace = open_client.post(
        "/api/learning/workspaces",
        headers=auth("token-c"),
        json={"course_id": "cs3481"},
    )
    assert workspace.status_code == 200, workspace.text
    rag = open_client.post(
        "/api/qa/chat",
        headers=auth("token-c"),
        json={"course_id": "cs3481", "question": "What does the course say?"},
    )
    assert rag.status_code == 200, rag.text

    conversation = open_client.post(
        f"{UI}/conversations",
        headers=auth("token-c"),
        json={"course": "cs3481", "lane": "teach"},
    )
    assert conversation.status_code == 201, conversation.text
    teaching_run = open_client.post(
        f"{UI}/conversations/{conversation.json()['id']}/runs",
        headers=auth("token-c"),
        json={"text": "Explain node x", "request_id": "open-campus-teaching"},
    )
    assert teaching_run.status_code == 202, teaching_run.text
    wait_terminal_as(open_client, teaching_run.json()["id"], "token-c")
    events = open_client.get(
        f"{UI}/runs/{teaching_run.json()['id']}/events?after=0",
        headers=auth("token-c"),
    )
    assert events.status_code == 200, events.text
    assert "event:" in events.text

    pair = open_client.post(
        f"{UI}/pairs",
        headers=auth("token-c"),
        json={"course": "cs3481"},
    )
    assert pair.status_code == 201, pair.text
    exercise = open_client.post(
        f"{UI}/courses/cs3481/exercises",
        headers=auth("token-c"),
        json={"pair_id": pair.json()["id"], "request_id": "open-campus-exercise"},
    )
    assert exercise.status_code == 202, exercise.text
    wait_terminal_as(open_client, exercise.json()["id"], "token-c")

    seed_assessment_pool(
        open_client,
        {"id": "node-c"},
        prefix="open-campus-",
        item_id="objective-node-c",
        private_owner="user-c",
    )
    assessment = open_client.post(
        f"{UI}/courses/cs3481/knowledge/node-c/assessment/session",
        headers=auth("token-c"),
        json={"request_id": "open-campus-assessment"},
    )
    assert assessment.status_code == 201, assessment.text
    assert len(assessment.json()["questions"]) == 5

    assert social.verification_status(
        open_client.app.state.ui_extension_app.state.db,
        "user-c",
    )["verified"] is False


def test_future_gate_grandfathers_existing_accounts_and_verifies_only_new_ones(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "policy.sqlite3")
    db.initialize()
    for owner, created_at in (
        ("old-unverified", "2026-01-01T00:00:00+00:00"),
        ("new-unverified", "2026-07-01T00:00:00+00:00"),
        ("new-verified", "2026-07-02T00:00:00+00:00"),
        ("disabled-old", "2026-01-02T00:00:00+00:00"),
    ):
        db.execute(
            "INSERT INTO cmui_users(id,name,handle,created_at) VALUES(?,?,?,?)",
            (owner, owner, f"handle-{owner}", created_at),
        )
    db.execute(
        "INSERT INTO cmui_directory(subject,public_id,active,updated_ms,created_ms) "
        "VALUES('disabled-old','person-disabled',0,1,1)"
    )
    social.set_verified(db, "new-verified", "code", "synthetic valid verification")

    kwargs = {
        "mode": NEW_USERS_REQUIRE_VERIFICATION,
        "verification_effective_at": "2026-06-01T00:00:00Z",
    }
    assert can_access_campus(db, "old-unverified", **kwargs) is True
    assert can_access_campus(db, "new-unverified", **kwargs) is False
    assert can_access_campus(db, "new-verified", **kwargs) is True
    assert can_access_campus(db, "disabled-old", **kwargs) is False

    # The currently deployed mode admits active users while preserving the same
    # verification rows for a future explicit owner switch.
    assert can_access_campus(
        db,
        "new-unverified",
        mode=OPEN_TO_REGISTERED,
        verification_effective_at=None,
    ) is True
    assert social.verification_status(db, "new-unverified")["verified"] is False


def test_policy_configuration_requires_an_explicit_future_boundary(tmp_path: Path) -> None:
    open_settings = UiSettings(
        data_dir=tmp_path / "open",
        campus_access_mode=OPEN_TO_REGISTERED,
        verification_effective_at="",
    )
    open_settings.validate()

    missing_boundary = UiSettings(
        data_dir=tmp_path / "missing",
        campus_access_mode=NEW_USERS_REQUIRE_VERIFICATION,
        verification_effective_at="",
    )
    with pytest.raises(ValueError, match="CMUI_VERIFICATION_EFFECTIVE_AT is required"):
        missing_boundary.validate()

    future_settings = UiSettings(
        data_dir=tmp_path / "future",
        campus_access_mode=NEW_USERS_REQUIRE_VERIFICATION,
        verification_effective_at="2026-06-01T00:00:00Z",
    )
    future_settings.validate()
