from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0] for text in texts]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        chunk_size=200,
        chunk_overlap=20,
        max_upload_bytes=1_024,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings=settings, embedding_provider=FakeEmbeddingProvider())
    with TestClient(app) as test_client:
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
