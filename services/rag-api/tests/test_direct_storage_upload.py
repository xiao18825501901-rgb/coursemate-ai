import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import ApiError
from app.main import create_app
from app.storage.backends import AliyunOssStorageBackend


class _Auth:
    def authenticate(self, request: Request) -> str | None:
        return {
            "Bearer owner": "owner-a",
            "Bearer other": "owner-b",
        }.get(request.headers.get("authorization", ""))


class _Embedding:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0] for text in texts]


class _Body:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.closed = False

    def iter_bytes(self, **_: object):
        yield self.content[:5]
        yield self.content[5:]

    def read(self) -> bytes:
        return self.content

    def close(self) -> None:
        self.closed = True


@dataclass
class _Result:
    content_length: int | None = None
    version_id: str | None = "v1"
    etag: str | None = "multipart-etag"
    hash_crc64: str | None = "123"
    body: _Body | None = None


@dataclass
class _Presign:
    url: str
    signed_headers: dict[str, str]
    expiration: datetime


class _OssClient:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.presigned_key = ""

    def presign(self, request: object, **_: object) -> _Presign:
        self.presigned_key = request.key  # type: ignore[attr-defined]
        return _Presign(
            f"https://bucket.example/{self.presigned_key}",
            {"content-type": request.content_type},  # type: ignore[attr-defined]
            datetime.now(UTC) + timedelta(minutes=10),
        )

    def head_object(self, request: object) -> _Result:
        content = self.objects[request.key]  # type: ignore[attr-defined]
        return _Result(content_length=len(content))

    def get_object(self, request: object) -> _Result:
        content = self.objects[request.key]  # type: ignore[attr-defined]
        byte_range = getattr(request, "range_header", None)
        if byte_range:
            start_text, end_text = str(byte_range)[6:].split("-", 1)
            content = content[int(start_text) : int(end_text) + 1]
        return _Result(content_length=len(content), body=_Body(content))

    def copy_object(self, request: object) -> _Result:
        self.objects[request.key] = self.objects[request.source_key]  # type: ignore[attr-defined]
        return _Result(content_length=len(self.objects[request.key]))  # type: ignore[attr-defined]

    def put_object(self, request: object) -> _Result:
        body = request.body  # type: ignore[attr-defined]
        self.objects[request.key] = body.read() if hasattr(body, "read") else bytes(body)
        return _Result(content_length=len(self.objects[request.key]))  # type: ignore[attr-defined]


def test_direct_upload_is_verified_promoted_and_ingested(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        storage_cache_dir=tmp_path / "cache",
        storage_reserve_min_bytes=0,
        storage_reserve_fraction=0,
        app_env="test",
        rag_provider_mode="deterministic",
        v3_enabled=True,
        max_upload_bytes=1024 * 1024,
    )
    app = create_app(
        settings=settings,
        embedding_provider=_Embedding(),
        auth_verifier=_Auth(),
    )
    fake = _OssClient()
    app.state.ingestion_service.storage_backend = AliyunOssStorageBackend(
        bucket="private-bucket", client=fake, prefix="coursejesus"
    )
    content = b"# Storage\n\nVerified direct upload content."
    digest = hashlib.sha256(content).hexdigest()

    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer owner"
        course = client.post(
            "/api/courses",
            json={"id": "private-course", "name": "Private Course", "description": ""},
        )
        assert course.status_code == 201
        started = client.post(
            "/api/courses/private-course/direct-uploads",
            json={
                "filename": "storage.md",
                "mediaType": "text/markdown",
                "byteSize": len(content),
                "sha256": digest,
            },
        )
        assert started.status_code == 201, started.text
        fake.objects[fake.presigned_key] = content

        client.headers["Authorization"] = "Bearer other"
        denied = client.post(f"/api/direct-uploads/{started.json()['uploadId']}/complete")
        assert denied.status_code == 404
        client.headers["Authorization"] = "Bearer owner"

        completed = client.post(
            f"/api/direct-uploads/{started.json()['uploadId']}/complete"
        )
        assert completed.status_code == 202, completed.text
        assert completed.json()["document"]["sha256"] == digest
        assert completed.json()["job"]["status"] == "queued"

        job = client.get(f"/api/ingestion-jobs/{completed.json()['job']['id']}")
        assert job.json()["status"] == "completed"
        with app.state.database.connect() as connection:
            stored_path = Path(
                connection.execute(
                    "SELECT stored_path FROM documents WHERE id=?",
                    (completed.json()["document"]["id"],),
                ).fetchone()["stored_path"]
            )
        stored_path.unlink()
        restored = client.get(
            f"/api/learning/documents/{completed.json()['document']['id']}/content",
            headers={"Range": "bytes=0-8"},
        )
        assert restored.status_code == 206, restored.text
        assert restored.content == content[:9]
        assert not stored_path.exists(), "Range reads must not hydrate the complete object cache"
        suffix = client.get(
            f"/api/learning/documents/{completed.json()['document']['id']}/content",
            headers={"Range": "bytes=-8"},
        )
        assert suffix.status_code == 206 and suffix.content == content[-8:]
        invalid_range = client.get(
            f"/api/learning/documents/{completed.json()['document']['id']}/content",
            headers={"Range": f"bytes={len(content)}-"},
        )
        assert invalid_range.status_code == 416
        head = client.head(
            f"/api/learning/documents/{completed.json()['document']['id']}/content"
        )
        assert head.status_code == 200 and head.content == b""
        assert int(head.headers["content-length"]) == len(content)
        repeated = client.post(
            f"/api/direct-uploads/{started.json()['uploadId']}/complete"
        )
        assert repeated.status_code == 202
        assert repeated.json()["document"]["id"] == completed.json()["document"]["id"]

        server_upload = client.post(
            "/api/courses/private-course/documents",
            files={"file": ("second.md", b"# Second\n\nServer path.", "text/markdown")},
        )
        assert server_upload.status_code == 202, server_upload.text
        server_job = client.get(
            f"/api/ingestion-jobs/{server_upload.json()['job']['id']}"
        )
        assert server_job.json()["status"] == "completed"

    with app.state.database.connect() as connection:
        canonical = connection.execute(
            "SELECT state,version_id,sha256,etag FROM storage_objects WHERE state='CANONICAL'"
            " AND sha256=?",
            (digest,),
        ).fetchone()
        assert dict(canonical) == {
            "state": "CANONICAL",
            "version_id": "v1",
            "sha256": digest,
            "etag": "multipart-etag",
        }
        assert connection.execute(
            "SELECT COUNT(*) FROM documents WHERE storage_object_id IS NOT NULL"
        ).fetchone()[0] == 2


def test_low_capacity_keeps_remote_object_and_resumes_after_space_recovers(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        storage_cache_dir=tmp_path / "cache",
        storage_reserve_min_bytes=100 * 1024**4,
        storage_reserve_fraction=0,
        app_env="test",
        rag_provider_mode="deterministic",
        v3_enabled=True,
        max_upload_bytes=1024 * 1024,
    )
    app = create_app(
        settings=settings,
        embedding_provider=_Embedding(),
        auth_verifier=_Auth(),
    )
    fake = _OssClient()
    app.state.ingestion_service.storage_backend = AliyunOssStorageBackend(
        bucket="private-bucket", client=fake, prefix="coursejesus"
    )
    content = b"# Durable\n\nWait for local capacity."

    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer owner"
        assert client.post(
            "/api/courses",
            json={"id": "capacity-course", "name": "Capacity", "description": ""},
        ).status_code == 201
        started = client.post(
            "/api/courses/capacity-course/direct-uploads",
            json={
                "filename": "capacity.md",
                "mediaType": "text/markdown",
                "byteSize": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            },
        )
        fake.objects[fake.presigned_key] = content
        completed = client.post(
            f"/api/direct-uploads/{started.json()['uploadId']}/complete"
        )

        assert completed.status_code == 202
        assert completed.json()["job"]["errorMessage"] == "WAITING_CAPACITY"
        assert fake.objects
        assert not settings.storage_cache_dir.exists()

        settings.storage_reserve_min_bytes = 0
        resumed = client.post(
            f"/api/ingestion-jobs/{completed.json()['job']['id']}/resume"
        )
        assert resumed.status_code == 202
        job = client.get(f"/api/ingestion-jobs/{completed.json()['job']['id']}")
        assert job.json()["status"] == "completed"
        assert list(settings.storage_cache_dir.rglob("*.md"))


def test_promoted_object_is_recorded_when_document_transaction_loses_admission_race(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        storage_cache_dir=tmp_path / "cache",
        storage_reserve_min_bytes=0,
        storage_reserve_fraction=0,
        app_env="test",
        rag_provider_mode="deterministic",
        v3_enabled=True,
        max_upload_bytes=1024 * 1024,
    )
    app = create_app(
        settings=settings,
        embedding_provider=_Embedding(),
        auth_verifier=_Auth(),
    )
    fake = _OssClient()
    app.state.ingestion_service.storage_backend = AliyunOssStorageBackend(
        bucket="private-bucket", client=fake, prefix="coursejesus"
    )
    content = b"# Race\n\nDurable object must remain auditable."
    digest = hashlib.sha256(content).hexdigest()

    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer owner"
        assert client.post(
            "/api/courses",
            json={"id": "race-course", "name": "Race", "description": ""},
        ).status_code == 201
        started = client.post(
            "/api/courses/race-course/direct-uploads",
            json={
                "filename": "race.md",
                "mediaType": "text/markdown",
                "byteSize": len(content),
                "sha256": digest,
            },
        )
        assert started.status_code == 201
        fake.objects[fake.presigned_key] = content

        def reject_commit(**_):
            raise ApiError(409, "SIMULATED_ADMISSION_RACE", "Synthetic race")

        monkeypatch.setattr(
            app.state.ingestion_service, "_check_document_admission_sql", reject_commit
        )
        failed = client.post(
            f"/api/direct-uploads/{started.json()['uploadId']}/complete"
        )
        assert failed.status_code == 409

    with app.state.database.connect() as connection:
        session = connection.execute(
            "SELECT status,canonical_object_id FROM storage_upload_sessions WHERE id=?",
            (started.json()["uploadId"],),
        ).fetchone()
        durable = connection.execute(
            "SELECT state,document_id,sha256 FROM storage_objects WHERE id=?",
            (session["canonical_object_id"],),
        ).fetchone()
        assert session["status"] == "INVALID"
        assert dict(durable) == {
            "state": "CANONICAL",
            "document_id": None,
            "sha256": digest,
        }


def test_admin_path_import_streams_to_oss_and_ordinary_actor_cannot_read_server_path(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        storage_cache_dir=tmp_path / "cache",
        storage_reserve_min_bytes=0,
        storage_reserve_fraction=0,
        app_env="test",
        rag_provider_mode="deterministic",
        v3_enabled=True,
    )
    app = create_app(
        settings=settings,
        embedding_provider=_Embedding(),
        auth_verifier=_Auth(),
    )
    fake = _OssClient()
    app.state.ingestion_service.storage_backend = AliyunOssStorageBackend(
        bucket="private-bucket", client=fake, prefix="coursejesus"
    )
    source = tmp_path / "operator-source.md"
    source.write_bytes(b"# Campus batch\n\nStream this original to durable storage.")

    with TestClient(app):
        with app.state.database.connect() as connection:
            connection.execute(
                "INSERT INTO courses(id,name,course_type,visibility,publication_status) "
                "VALUES('path-course','Path','official','private','private')"
            )
        try:
            app.state.ingestion_service.queue_document_path(
                course_id="path-course",
                filename="operator-source.md",
                media_type="text/markdown",
                source_path=source,
                is_admin=False,
            )
        except ApiError as error:
            assert error.code == "ADMIN_PATH_IMPORT_REQUIRED"
        else:  # pragma: no cover - a regression would make this assertion explain the breach
            raise AssertionError("ordinary callers must never import arbitrary server paths")

        accepted = app.state.ingestion_service.queue_document_path(
            course_id="path-course",
            filename="operator-source.md",
            media_type="text/markdown",
            source_path=source,
            is_admin=True,
        )
        assert accepted.job.status.value == "queued"
        assert any(value == source.read_bytes() for value in fake.objects.values())


def test_admin_path_import_records_durable_object_when_duplicate_race_wins(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        storage_cache_dir=tmp_path / "cache",
        storage_reserve_min_bytes=0,
        storage_reserve_fraction=0,
        app_env="test",
        rag_provider_mode="deterministic",
        v3_enabled=True,
    )
    app = create_app(
        settings=settings,
        embedding_provider=_Embedding(),
        auth_verifier=_Auth(),
    )
    fake = _OssClient()
    backend = AliyunOssStorageBackend(
        bucket="private-bucket", client=fake, prefix="coursejesus"
    )
    app.state.ingestion_service.storage_backend = backend
    source = tmp_path / "operator-race.md"
    content = b"# Campus race\n\nOne winning database admission."
    source.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()

    with TestClient(app):
        with app.state.database.connect() as connection:
            connection.execute(
                "INSERT INTO courses(id,name,course_type,visibility,publication_status) "
                "VALUES('path-race','Path race','official','private','private')"
            )
        original_put = backend.put_path

        def put_then_win_admission(*args, **kwargs):
            stored = original_put(*args, **kwargs)
            with app.state.database.connect() as connection:
                connection.execute(
                    "INSERT INTO documents(id,course_id,filename,stored_path,media_type,"
                    "extension,sha256,byte_size,status) VALUES("
                    "'race-winner','path-race','winner.md',?,'text/markdown','.md',?,?,"
                    "'ready')",
                    (str(source), digest, len(content)),
                )
            return stored

        monkeypatch.setattr(backend, "put_path", put_then_win_admission)
        with pytest.raises(ApiError, match="same content") as error:
            app.state.ingestion_service.queue_document_path(
                course_id="path-race",
                filename="operator-race.md",
                media_type="text/markdown",
                source_path=source,
                is_admin=True,
            )
        assert error.value.code == "DUPLICATE_DOCUMENT"

    with app.state.database.connect() as connection:
        orphan = connection.execute(
            "SELECT state,document_id,sha256 FROM storage_objects "
            "WHERE course_id='path-race'"
        ).fetchone()
    assert dict(orphan) == {
        "state": "CANONICAL",
        "document_id": None,
        "sha256": digest,
    }
