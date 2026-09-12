from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _fastapi_app(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


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


def test_health_returns_503_when_persistent_state_is_not_ready(
    client: TestClient,
) -> None:
    with _fastapi_app(client).state.database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 10")

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "service": "rag-api"}
    assert "path" not in response.text.casefold()


def test_api_responses_include_production_security_headers(client: TestClient) -> None:
    response = client.get("/health")

    assert response.headers["content-security-policy"] == (
        "default-src 'none'; frame-ancestors 'none'"
    )
    assert response.headers["strict-transport-security"] == (
        "max-age=31536000; includeSubDomains"
    )
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_course_detail_obeys_private_visibility_policy(client: TestClient) -> None:
    client.headers["Authorization"] = "Bearer user-token"
    assert client.post(
        "/api/courses",
        json={"id": "detail-course", "name": "Detail"},
    ).status_code == 201
    owner = client.get("/api/courses/detail-course")
    other = client.get(
        "/api/courses/detail-course",
        headers={"Authorization": "Bearer user-b-token"},
    )
    admin = client.get(
        "/api/courses/detail-course",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert owner.status_code == 200
    assert owner.json()["isOwner"] is True
    assert other.status_code == 404
    assert admin.status_code == 404


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
    course = client.get("/api/courses").json()["items"][0]
    assert course["documentCount"] == 1
    assert course["indexStatus"] == "indexed"
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


def test_private_course_is_visible_and_mutable_only_by_owner(
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
    assert client.get("/api/courses/private-course/documents").status_code == 404


def test_owner_can_update_and_delete_private_course(client: TestClient) -> None:
    client.headers["Authorization"] = "Bearer user-token"
    assert client.post(
        "/api/courses",
        json={"id": "editable-course", "name": "Draft", "description": "Mine"},
    ).status_code == 201

    updated = client.patch(
        "/api/courses/editable-course",
        json={"name": "Updated", "description": "Revised", "preferredLanguage": "zh-CN"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Updated"
    assert updated.json()["preferredLanguage"] == "zh-CN"

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
        for candidate in _fastapi_app(client).state.settings.upload_dir.rglob("*")
    )


def test_user_course_count_quota_is_configurable_and_admin_is_exempt(tmp_path: Path) -> None:
    quota_settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        user_course_max_courses=1,
        admin_user_ids="user-admin",
    )
    with TestClient(
        create_app(
            settings=quota_settings,
            embedding_provider=FakeEmbeddingProvider(),
            auth_verifier=FakeAuthVerifier(),
        )
    ) as quota_client:
        first = quota_client.post(
            "/api/courses",
            json={"id": "mine-one", "name": "Mine one"},
            headers={"Authorization": "Bearer user-token"},
        )
        exceeded = quota_client.post(
            "/api/courses",
            json={"id": "mine-two", "name": "Mine two"},
            headers={"Authorization": "Bearer user-token"},
        )
        admin = quota_client.post(
            "/api/courses",
            json={"id": "official-one", "name": "Official"},
            headers={"Authorization": "Bearer admin-token"},
        )

    assert first.status_code == 201
    assert exceeded.status_code == 429
    assert exceeded.json()["error"]["code"] == "COURSE_QUOTA_EXCEEDED"
    assert admin.status_code == 201


def test_file_count_and_total_upload_quotas_are_owner_scoped(tmp_path: Path) -> None:
    quota_settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        max_upload_bytes=1_024,
        user_course_max_files=1,
        user_course_max_total_upload_bytes=1_024,
        admin_user_ids="user-admin",
    )
    with TestClient(
        create_app(
            settings=quota_settings,
            embedding_provider=FakeEmbeddingProvider(),
            auth_verifier=FakeAuthVerifier(),
        )
    ) as quota_client:
        for token, course_id in (
            ("Bearer user-token", "user-a-one"),
            ("Bearer user-token", "user-a-two"),
            ("Bearer user-b-token", "user-b-one"),
        ):
            assert quota_client.post(
                "/api/courses",
                json={"id": course_id, "name": course_id},
                headers={"Authorization": token},
            ).status_code == 201

        first = quota_client.post(
            "/api/courses/user-a-one/documents",
            files={"file": ("one.md", b"# One\n\n" + b"a" * 692, "text/markdown")},
            headers={"Authorization": "Bearer user-token"},
        )
        file_count = quota_client.post(
            "/api/courses/user-a-one/documents",
            files={"file": ("two.md", b"different", "text/markdown")},
            headers={"Authorization": "Bearer user-token"},
        )
        total_bytes = quota_client.post(
            "/api/courses/user-a-two/documents",
            files={"file": ("more.md", b"# More\n\n" + b"b" * 392, "text/markdown")},
            headers={"Authorization": "Bearer user-token"},
        )
        other_owner = quota_client.post(
            "/api/courses/user-b-one/documents",
            files={"file": ("other.md", b"# Other\n\n" + b"c" * 390, "text/markdown")},
            headers={"Authorization": "Bearer user-b-token"},
        )

    assert first.status_code == 202
    assert first.json()["document"]["byteSize"] == 699
    assert file_count.status_code == 429
    assert file_count.json()["error"]["code"] == "COURSE_FILE_QUOTA_EXCEEDED"
    assert total_bytes.status_code == 413
    assert total_bytes.json()["error"]["code"] == "USER_STORAGE_QUOTA_EXCEEDED"
    assert other_owner.status_code == 202


def test_user_upload_storage_path_is_namespaced_by_owner_course_and_document(
    client: TestClient, settings: Settings
) -> None:
    client.headers["Authorization"] = "Bearer user-token"
    assert client.post(
        "/api/courses",
        json={"id": "path-course", "name": "Paths"},
    ).status_code == 201
    upload = client.post(
        "/api/courses/path-course/documents",
        files={"file": ("notes.md", b"# Safe path", "text/markdown")},
    )
    document_id = upload.json()["document"]["id"]
    with _fastapi_app(client).state.database.connect() as connection:
        stored = Path(
            connection.execute(
                "SELECT stored_path FROM documents WHERE id = ?", (document_id,)
            ).fetchone()["stored_path"]
        )

    relative = stored.resolve().relative_to(settings.upload_dir.resolve())
    assert relative.parts[0] == "users"
    assert relative.parts[1] != "user-a"
    assert relative.parts[2] == "path-course"
    assert relative.stem == document_id


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
