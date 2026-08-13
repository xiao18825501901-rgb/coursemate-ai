from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0] for text in texts]


class RecordingEmbeddingProvider:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.batch_sizes.append(len(texts))
        return [[float(len(text)), 1.0] for text in texts]


class FakeAuthVerifier:
    def authenticate(self, request: Request) -> str | None:
        tokens = {
            "Bearer admin-token": "user-admin",
            "Bearer user-token": "user-a",
            "Bearer user-b-token": "user-b",
        }
        return tokens.get(request.headers.get("authorization", ""))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        chunk_size=200,
        chunk_overlap=20,
        max_upload_bytes=1_024,
        admin_user_ids="user-admin",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = "Bearer admin-token"
        yield test_client


def create_course(client: TestClient, course_id: str = "cs3481") -> None:
    response = client.post(
        "/api/courses",
        json={
            "id": course_id,
            "name": course_id.upper(),
            "description": "Course notes",
        },
    )
    assert response.status_code == 201


def test_health_and_course_pagination(client: TestClient) -> None:
    health = client.get("/health")
    create_course(client)
    courses = client.get("/api/courses", params={"page": 1, "pageSize": 10})

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "rag-api"}
    assert courses.status_code == 200
    assert courses.json()["total"] == 1
    assert courses.json()["items"][0]["id"] == "cs3481"


def test_course_name_cannot_be_blank(client: TestClient) -> None:
    response = client.post(
        "/api/courses",
        json={"id": "blank-name", "name": "   ", "description": "No name"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_markdown_upload_completes_real_ingestion_pipeline(
    client: TestClient,
    settings: Settings,
) -> None:
    create_course(client)
    response = client.post(
        "/api/courses/cs3481/documents",
        files={
            "file": (
                "lighting.md",
                b"# Lighting\n\nPhong has diffuse and specular terms.",
                "text/markdown",
            )
        },
    )

    assert response.status_code == 202
    payload = response.json()
    job = client.get(f"/api/ingestion-jobs/{payload['job']['id']}")
    documents = client.get("/api/courses/cs3481/documents")

    assert job.status_code == 200
    assert job.json()["status"] == "completed"
    assert job.json()["processedChunks"] == 1
    assert documents.json()["items"][0]["status"] == "ready"
    assert documents.json()["items"][0]["chunkCount"] == 1
    assert len(list(settings.upload_dir.rglob("*.md"))) == 1


def test_embedding_ingestion_batches_at_most_ten_chunks(tmp_path: Path) -> None:
    provider = RecordingEmbeddingProvider()
    batch_settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        chunk_size=200,
        chunk_overlap=20,
        max_upload_bytes=5_000,
        admin_user_ids="user-admin",
    )
    paragraphs = [f"Paragraph {index} " + ("word " * 32) for index in range(12)]
    content = ("# Batching\n\n" + "\n\n".join(paragraphs)).encode()

    with TestClient(
        create_app(
            settings=batch_settings,
            embedding_provider=provider,
            auth_verifier=FakeAuthVerifier(),
        )
    ) as batch_client:
        batch_client.headers["Authorization"] = "Bearer admin-token"
        create_course(batch_client)
        upload = batch_client.post(
            "/api/courses/cs3481/documents",
            files={"file": ("batching.md", content, "text/markdown")},
        )
        job = batch_client.get(f"/api/ingestion-jobs/{upload.json()['job']['id']}")

    assert upload.status_code == 202
    assert job.json()["status"] == "completed"
    assert job.json()["processedChunks"] > 10
    assert max(provider.batch_sizes) <= 10
    assert sum(provider.batch_sizes) == job.json()["processedChunks"]


def test_duplicate_content_is_rejected_without_second_document(client: TestClient) -> None:
    create_course(client)
    upload = {
        "file": ("notes.md", b"# Notes\n\nSame content", "text/markdown")
    }
    assert client.post("/api/courses/cs3481/documents", files=upload).status_code == 202

    duplicate = client.post("/api/courses/cs3481/documents", files=upload)
    documents = client.get("/api/courses/cs3481/documents").json()

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_DOCUMENT"
    assert documents["total"] == 1


@pytest.mark.parametrize(
    ("filename", "content_type", "content", "code"),
    [
        ("../notes.md", "text/markdown", b"content", "INVALID_FILENAME"),
        ("malware.exe", "application/octet-stream", b"content", "UNSUPPORTED_EXTENSION"),
        ("notes.md", "application/x-msdownload", b"content", "INVALID_MEDIA_TYPE"),
        ("large.md", "text/markdown", b"x" * 1_025, "FILE_TOO_LARGE"),
    ],
)
def test_upload_boundary_rejects_unsafe_files(
    client: TestClient,
    filename: str,
    content_type: str,
    content: bytes,
    code: str,
) -> None:
    create_course(client)

    response = client.post(
        "/api/courses/cs3481/documents",
        files={"file": (filename, content, content_type)},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == code


def test_missing_course_and_request_validation_use_error_envelope(client: TestClient) -> None:
    missing = client.get("/api/courses/missing/documents")
    invalid = client.post("/api/courses", json={"id": "BAD ID", "name": "", "extra": 1})

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "COURSE_NOT_FOUND"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"


def test_authentication_admin_boundary_and_shared_read_access(client: TestClient) -> None:
    create_course(client)
    client.headers["Authorization"] = "Bearer user-token"

    shared_read = client.get("/api/courses")
    private_course = client.post(
        "/api/courses",
        json={"id": "ge2324", "name": "GE2324", "description": "Notes"},
    )
    client.headers.pop("Authorization")
    missing = client.get("/api/courses")
    invalid = client.get("/api/courses", headers={"Authorization": "Bearer invalid"})

    assert shared_read.status_code == 200
    assert shared_read.json()["items"][0]["id"] == "cs3481"
    assert private_course.status_code == 201
    assert private_course.json()["courseType"] == "user"
    assert private_course.json()["visibility"] == "private"
    assert private_course.json()["isOwner"] is True
    assert private_course.json()["canManage"] is True
    assert "ownerUserId" not in private_course.json()
    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_private_course_is_visible_and_mutable_only_by_owner_or_admin(
    client: TestClient,
) -> None:
    client.headers["Authorization"] = "Bearer user-token"
    created = client.post(
        "/api/courses",
        json={"id": "private-course", "name": "Private Course", "description": "Mine"},
    )
    owner_list = client.get("/api/courses")
    owner_upload = client.post(
        "/api/courses/private-course/documents",
        files={"file": ("notes.md", b"# Private\n\nOwner only.", "text/markdown")},
    )

    assert created.status_code == 201
    assert owner_list.json()["items"][0]["id"] == "private-course"
    assert owner_upload.status_code == 202

    client.headers["Authorization"] = "Bearer user-b-token"
    other_list = client.get("/api/courses")
    other_documents = client.get("/api/courses/private-course/documents")
    other_upload = client.post(
        "/api/courses/private-course/documents",
        files={"file": ("stolen.md", b"# No", "text/markdown")},
    )
    other_job = client.get(f"/api/ingestion-jobs/{owner_upload.json()['job']['id']}")

    assert other_list.status_code == 200
    assert other_list.json()["total"] == 0
    assert other_documents.status_code == 404
    assert other_upload.status_code == 404
    assert other_job.status_code == 404

    client.headers["Authorization"] = "Bearer admin-token"
    assert client.get("/api/courses/private-course/documents").status_code == 200


def test_owner_can_update_and_delete_private_course(client: TestClient) -> None:
    client.headers["Authorization"] = "Bearer user-token"
    assert client.post(
        "/api/courses",
        json={"id": "editable-course", "name": "Draft", "description": "Mine"},
    ).status_code == 201

    updated = client.patch(
        "/api/courses/editable-course",
        json={"name": "Updated", "description": "Revised"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Updated"

    client.headers["Authorization"] = "Bearer user-b-token"
    assert client.patch(
        "/api/courses/editable-course", json={"name": "Stolen"}
    ).status_code == 404
    assert client.delete("/api/courses/editable-course").status_code == 404

    client.headers["Authorization"] = "Bearer user-token"
    assert client.delete("/api/courses/editable-course").status_code == 204
    assert client.get("/api/courses/editable-course/documents").status_code == 404


def test_owner_can_delete_document_but_other_user_cannot(client: TestClient) -> None:
    client.headers["Authorization"] = "Bearer user-token"
    assert client.post(
        "/api/courses",
        json={"id": "document-course", "name": "Documents", "description": "Mine"},
    ).status_code == 201
    upload = client.post(
        "/api/courses/document-course/documents",
        files={"file": ("notes.md", b"# Notes\n\nDelete me.", "text/markdown")},
    )
    document_id = upload.json()["document"]["id"]

    client.headers["Authorization"] = "Bearer user-b-token"
    assert client.delete(
        f"/api/courses/document-course/documents/{document_id}"
    ).status_code == 404

    client.headers["Authorization"] = "Bearer user-token"
    assert client.delete(
        f"/api/courses/document-course/documents/{document_id}"
    ).status_code == 204
    assert client.get("/api/courses/document-course/documents").json()["total"] == 0
    assert not any(
        candidate.name.startswith(document_id)
        for candidate in client.app.state.settings.upload_dir.rglob("*")
    )


def test_cors_preflight_allows_authorization_header(client: TestClient) -> None:
    response = client.options(
        "/api/courses",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert response.status_code == 200
    assert "Authorization" in response.headers["access-control-allow-headers"]
