from pathlib import Path

from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class FakeAuthVerifier:
    def authenticate(self, request: Request) -> str | None:
        return {
            "Bearer owner": "owner",
            "Bearer other": "other",
            "Bearer admin-author": "admin-author",
            "Bearer admin-reviewer": "admin-reviewer",
        }.get(request.headers.get("authorization", ""))


def v3_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            settings=Settings(
                app_env="test",
                rag_provider_mode="deterministic",
                database_path=tmp_path / "rag.sqlite3",
                upload_dir=tmp_path / "uploads",
                admin_user_ids="admin-author,admin-reviewer",
                v3_enabled=True,
            ),
            embedding_provider=FakeEmbeddingProvider(),
            auth_verifier=FakeAuthVerifier(),
        )
    )


def create_private_course_with_document(client: TestClient) -> tuple[str, str]:
    created = client.post(
        "/api/courses",
        json={"id": "share-me", "name": "Share me", "description": "Frozen copy"},
        headers={"Authorization": "Bearer owner"},
    )
    assert created.status_code == 201, created.text
    uploaded = client.post(
        "/api/courses/share-me/documents",
        files={"file": ("notes.md", b"# Reviewed notes\n\nExact source.", "text/markdown")},
        headers={"Authorization": "Bearer owner"},
    )
    assert uploaded.status_code == 202, uploaded.text
    assert uploaded.json()["job"]["status"] in {"queued", "processing", "completed"}
    with client.app.state.database.connect() as connection:
        version_id = connection.execute(
            "SELECT id FROM document_versions WHERE document_id=?",
            (uploaded.json()["document"]["id"],),
        ).fetchone()["id"]
    return uploaded.json()["document"]["id"], version_id


def test_v3_course_publication_freezes_a_scoped_review_snapshot(tmp_path: Path) -> None:
    with v3_client(tmp_path) as client:
        document_id, version_id = create_private_course_with_document(client)
        submitted = client.post(
            "/api/courses/share-me/publication-requests",
            json={
                "shareMaterialsConsent": True,
                "rightsConfirmation": True,
                "consentVersion": "v1",
            },
            headers={"Authorization": "Bearer owner"},
        )
        assert submitted.status_code == 201, submitted.text
        request_id = submitted.json()["id"]

        generic_private_browse = client.get(
            "/api/courses/share-me/documents",
            headers={"Authorization": "Bearer admin-author"},
        )
        snapshot = client.get(
            f"/api/admin/publication-requests/{request_id}/snapshot",
            headers={"Authorization": "Bearer admin-reviewer"},
        )
        scoped_content = client.get(
            f"/api/admin/publication-requests/{request_id}/documents/{version_id}/content",
            headers={"Authorization": "Bearer admin-reviewer"},
        )
        locked = client.patch(
            "/api/courses/share-me",
            json={"name": "Changed while pending"},
            headers={"Authorization": "Bearer owner"},
        )

    assert submitted.json()["snapshotId"].startswith("snapshot_")
    assert len(submitted.json()["snapshotHash"]) == 64
    assert submitted.json()["resourceCount"] >= 2
    assert generic_private_browse.status_code == 404
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["id"] == submitted.json()["snapshotId"]
    resources = snapshot.json()["resources"]
    frozen_document = next(item for item in resources if item["kind"] == "DOCUMENT_VERSION")
    assert frozen_document["id"] == version_id
    assert frozen_document["displayName"] == "notes.md"
    assert frozen_document["metadata"]["documentId"] == document_id
    assert "storedPath" not in frozen_document["metadata"]
    assert "ownerUserId" not in frozen_document["metadata"]
    assert scoped_content.status_code == 200
    assert scoped_content.content == b"# Reviewed notes\n\nExact source."
    assert scoped_content.headers["cache-control"] == "private, no-store"
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "PUBLICATION_REVIEW_LOCKED"


def test_owner_withdrawal_revokes_an_approved_course_release(tmp_path: Path) -> None:
    with v3_client(tmp_path) as client:
        _, version_id = create_private_course_with_document(client)
        submitted = client.post(
            "/api/courses/share-me/publication-requests",
            json={
                "shareMaterialsConsent": True,
                "rightsConfirmation": True,
                "consentVersion": "v1",
            },
            headers={"Authorization": "Bearer owner"},
        )
        request_id = submitted.json()["id"]
        approved = client.post(
            f"/api/admin/publication-requests/{request_id}/review",
            json={"decision": "approve", "reviewNote": "Exact snapshot reviewed."},
            headers={"Authorization": "Bearer admin-reviewer"},
        )
        visible_before = client.get(
            "/api/courses", headers={"Authorization": "Bearer other"}
        )
        withdrawn = client.delete(
            "/api/courses/share-me/publication-requests/current",
            headers={"Authorization": "Bearer owner"},
        )
        hidden_after = client.get(
            "/api/courses", headers={"Authorization": "Bearer other"}
        )
        stale_review_access = client.get(
            f"/api/admin/publication-requests/{request_id}/documents/{version_id}/content",
            headers={"Authorization": "Bearer admin-reviewer"},
        )
        editable_after = client.patch(
            "/api/courses/share-me",
            json={"name": "Editable after withdrawal"},
            headers={"Authorization": "Bearer owner"},
        )
        with client.app.state.database.connect() as connection:
            release = connection.execute(
                "SELECT status,cache_generation FROM publication_releases "
                "WHERE subject_kind='COURSE' AND request_id=?",
                (request_id,),
            ).fetchone()

    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert visible_before.json()["total"] == 1
    assert withdrawn.status_code == 204
    assert hidden_after.json()["total"] == 0
    assert stale_review_access.status_code == 404
    assert editable_after.status_code == 200
    assert tuple(release) == ("WITHDRAWN", 2)
