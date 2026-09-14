"""Owned private courses must stay deletable, and never half-deleted.

Two opposite risks are checked here. Entering a course's learning or files view
creates the caller's `learning_workspaces` row (and its private corpus course) by
design, and the existing V3 ingestion service refuses to delete a course while that
workspace exists. So the mounted shell must surface the refusal as an actionable
conflict and change nothing - not half-delete the course, the workspace or the
uploaded files.
"""

from __future__ import annotations

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


def create_private_course(client: TestClient, name: str = "My Stats Reading") -> dict:
    response = client.post(
        f"{UI}/courses", headers=auth("Bearer token-a"), json={"name": name, "code": "MINE"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def delete(client: TestClient, course_id: str, confirm: str) -> object:
    return client.delete(
        f"{UI}/courses/{course_id}", headers=auth("Bearer token-a"), params={"confirm": confirm}
    )


def test_a_course_without_a_workspace_is_deleted(client: TestClient) -> None:
    course = create_private_course(client)
    response = delete(client, course["id"], course["name"])
    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True
    assert client.get(f"{UI}/courses/{course['id']}", headers=auth("Bearer token-a")).status_code == 404


def test_a_wrong_confirmation_name_is_rejected(client: TestClient) -> None:
    course = create_private_course(client)
    response = delete(client, course["id"], "not the name")
    assert response.status_code == 422
    # The course is untouched.
    assert client.get(f"{UI}/courses/{course['id']}", headers=auth("Bearer token-a")).status_code == 200


def test_a_course_with_a_learning_workspace_reports_a_conflict(client: TestClient) -> None:
    """Entering a course's learning page creates a workspace; deletion must not 500."""

    course = create_private_course(client)
    # Reading the files list is what makes the shell create the caller's workspace.
    files = client.get(f"{UI}/courses/{course['id']}/files", headers=auth("Bearer token-a"))
    assert files.status_code == 200, files.text
    with client.app.state.database.connect() as connection:
        workspace = connection.execute(
            "SELECT id, private_course_id FROM learning_workspaces WHERE course_id=? AND owner_user_id=?",
            (course["id"], "user-a"),
        ).fetchone()
    assert workspace is not None, "the adapter should have created a workspace for the caller"

    response = delete(client, course["id"], course["name"])
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "workspace" in str(detail).lower() or "归档" in str(detail)
    # Nothing was removed, and the private corpus is intact.
    assert client.get(f"{UI}/courses/{course['id']}", headers=auth("Bearer token-a")).status_code == 200
    with client.app.state.database.connect() as connection:
        still_there = connection.execute(
            "SELECT 1 FROM courses WHERE id=?", (workspace["private_course_id"],)
        ).fetchone()
    assert still_there is not None
