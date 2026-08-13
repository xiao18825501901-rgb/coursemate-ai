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
            "Bearer owner": "user-a",
            "Bearer other": "user-b",
            "Bearer admin": "admin",
        }.get(request.headers.get("authorization", ""))


def client_for(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            settings=Settings(
                database_path=tmp_path / "rag.sqlite3",
                upload_dir=tmp_path / "uploads",
                admin_user_ids="admin",
            ),
            embedding_provider=FakeEmbeddingProvider(),
            auth_verifier=FakeAuthVerifier(),
        )
    )


def create_private_course(client: TestClient) -> None:
    response = client.post(
        "/api/courses",
        json={"id": "community-candidate", "name": "Candidate"},
        headers={"Authorization": "Bearer owner"},
    )
    assert response.status_code == 201


def submit(client: TestClient) -> object:
    return client.post(
        "/api/courses/community-candidate/publication-requests",
        json={
            "shareMaterialsConsent": True,
            "rightsConfirmation": True,
            "consentVersion": "v1",
        },
        headers={"Authorization": "Bearer owner"},
    )


def test_publication_requires_both_explicit_consents(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        create_private_course(client)
        response = client.post(
            "/api/courses/community-candidate/publication-requests",
            json={
                "shareMaterialsConsent": True,
                "rightsConfirmation": False,
                "consentVersion": "v1",
            },
            headers={"Authorization": "Bearer owner"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PUBLICATION_CONSENT_REQUIRED"


def test_pending_and_rejected_courses_remain_private(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        create_private_course(client)
        pending = submit(client)
        hidden_pending = client.get(
            "/api/courses", headers={"Authorization": "Bearer other"}
        )
        reviewed = client.post(
            f"/api/admin/publication-requests/{pending.json()['id']}/review",
            json={"decision": "reject", "reviewNote": "Copyright evidence missing."},
            headers={"Authorization": "Bearer admin"},
        )
        hidden_rejected = client.get(
            "/api/courses", headers={"Authorization": "Bearer other"}
        )

    assert pending.status_code == 201
    assert pending.json()["status"] == "pending"
    assert hidden_pending.json()["total"] == 0
    assert reviewed.json()["status"] == "rejected"
    assert hidden_rejected.json()["total"] == 0


def test_only_admin_approval_makes_course_public_and_read_only(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        create_private_course(client)
        pending = submit(client)
        denied = client.post(
            f"/api/admin/publication-requests/{pending.json()['id']}/review",
            json={"decision": "approve", "reviewNote": "Looks good."},
            headers={"Authorization": "Bearer other"},
        )
        approved = client.post(
            f"/api/admin/publication-requests/{pending.json()['id']}/review",
            json={"decision": "approve", "reviewNote": "Rights verified."},
            headers={"Authorization": "Bearer admin"},
        )
        visible = client.get(
            "/api/courses", headers={"Authorization": "Bearer other"}
        )
        mutate = client.patch(
            "/api/courses/community-candidate",
            json={"name": "Hijacked"},
            headers={"Authorization": "Bearer other"},
        )
        upload = client.post(
            "/api/courses/community-candidate/documents",
            files={"file": ("bad.md", b"bad", "text/markdown")},
            headers={"Authorization": "Bearer other"},
        )

    assert denied.status_code == 403
    assert approved.json()["status"] == "approved"
    assert visible.json()["items"][0]["publicationStatus"] == "published"
    assert visible.json()["items"][0]["canManage"] is False
    assert mutate.status_code == 404
    assert upload.status_code == 404


def test_admin_can_unpublish_an_approved_course(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        create_private_course(client)
        pending = submit(client)
        client.post(
            f"/api/admin/publication-requests/{pending.json()['id']}/review",
            json={"decision": "approve", "reviewNote": "Approved."},
            headers={"Authorization": "Bearer admin"},
        )
        unpublished = client.delete(
            "/api/admin/courses/community-candidate/publication",
            headers={"Authorization": "Bearer admin"},
        )
        hidden = client.get(
            "/api/courses", headers={"Authorization": "Bearer other"}
        )

    assert unpublished.status_code == 204
    assert hidden.json()["total"] == 0
