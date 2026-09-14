"""Legacy V3 conversation history must stay readable from the refreshed shell.

The refreshed shell keeps its own history in `cmui_conversations`/`cmui_messages`.
The pre-existing V3 conversations live in `conversations`/`messages` and are not
copied anywhere: copying would create two drifting histories. Instead the mounted
UI exposes them read-only, so no user record becomes unreachable when the new
navigation replaces the old one.

These tests drive the real V3 tables through a mounted host application.
"""

from __future__ import annotations

import json
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


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        admin_user_ids="user-admin",
        app_env="test",
        v3_enabled=True,
        ui_extension_enabled=True,
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


def auth(token: str) -> dict[str, str]:
    return {"Authorization": token}


def create_course(client: TestClient, course_id: str = "cs3481") -> None:
    response = client.post(
        "/api/courses",
        headers=auth("Bearer admin-token"),
        json={"id": course_id, "name": "Fundamentals of Data Science", "description": "Notes"},
    )
    assert response.status_code == 201, response.text


def seed_legacy_conversation(
    client: TestClient,
    *,
    owner: str,
    course_id: str = "cs3481",
    title: str = "Cluster analysis questions",
) -> str:
    """Insert a V3 conversation exactly as the existing Q&A surface would."""

    database = client.app.state.database
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO conversations (id, owner_user_id, course_id, title) VALUES (?,?,?,?)",
            ("conv_legacy_1", owner, course_id, title),
        )
        connection.execute(
            "INSERT INTO messages (id, conversation_id, role, content, citations_json) "
            "VALUES (?,?,?,?,?)",
            (
                "msg_legacy_1",
                "conv_legacy_1",
                "user",
                "How does DBSCAN identify a core point?",
                "[]",
            ),
        )
        connection.execute(
            "INSERT INTO messages (id, conversation_id, role, content, citations_json) "
            "VALUES (?,?,?,?,?)",
            (
                "msg_legacy_2",
                "conv_legacy_1",
                "assistant",
                "A core point has at least MinPts neighbours within epsilon.",
                json.dumps([{"document_id": "doc_1", "filename": "lecture.md"}]),
            ),
        )
    return "conv_legacy_1"


def test_legacy_history_is_listed_with_real_metadata(client: TestClient) -> None:
    create_course(client)
    seed_legacy_conversation(client, owner="user-a")
    response = client.get(f"{UI}/courses/cs3481/legacy-conversations", headers=auth("Bearer token-a"))
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "conv_legacy_1"
    assert row["title"] == "Cluster analysis questions"
    assert row["message_count"] == 2
    assert row["updated_at"]
    assert row["legacy"] is True


def test_legacy_history_is_owner_scoped(client: TestClient) -> None:
    create_course(client)
    seed_legacy_conversation(client, owner="user-a")

    mine = client.get(f"{UI}/courses/cs3481/legacy-conversations", headers=auth("Bearer token-a"))
    assert len(mine.json()) == 1

    theirs = client.get(f"{UI}/courses/cs3481/legacy-conversations", headers=auth("Bearer token-b"))
    assert theirs.status_code == 200
    assert theirs.json() == []


def test_legacy_history_hides_another_users_private_course(client: TestClient) -> None:
    created = client.post(
        f"{UI}/courses",
        headers=auth("Bearer token-a"),
        json={"name": "My Stats Reading", "description": "personal", "code": "MINE"},
    )
    assert created.status_code == 201, created.text
    course_id = created.json()["id"]
    seed_legacy_conversation(client, owner="user-a", course_id=course_id, title="mine only")

    assert (
        client.get(
            f"{UI}/courses/{course_id}/legacy-conversations", headers=auth("Bearer token-b")
        ).status_code
        == 404
    )
    assert (
        len(
            client.get(
                f"{UI}/courses/{course_id}/legacy-conversations", headers=auth("Bearer token-a")
            ).json()
        )
        == 1
    )


def test_legacy_conversation_detail_returns_the_real_messages(client: TestClient) -> None:
    create_course(client)
    seed_legacy_conversation(client, owner="user-a")
    response = client.get(
        f"{UI}/courses/cs3481/legacy-conversations/conv_legacy_1", headers=auth("Bearer token-a")
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Cluster analysis questions"
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
    assert "MinPts" in body["messages"][1]["text"]
    # Citations are carried through so the reader can show the grounded source.
    assert body["messages"][1]["citations"][0]["filename"] == "lecture.md"


def test_legacy_conversation_detail_is_not_readable_by_another_user(
    client: TestClient,
) -> None:
    create_course(client)
    seed_legacy_conversation(client, owner="user-a")
    assert (
        client.get(
            f"{UI}/courses/cs3481/legacy-conversations/conv_legacy_1",
            headers=auth("Bearer token-b"),
        ).status_code
        == 404
    )


def test_unknown_legacy_conversation_is_a_404(client: TestClient) -> None:
    create_course(client)
    assert (
        client.get(
            f"{UI}/courses/cs3481/legacy-conversations/does-not-exist",
            headers=auth("Bearer token-a"),
        ).status_code
        == 404
    )


def test_legacy_history_requires_a_verified_session(client: TestClient) -> None:
    create_course(client)
    assert client.get(f"{UI}/courses/cs3481/legacy-conversations").status_code == 401
