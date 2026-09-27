import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
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
        return _Result(content_length=len(content), body=_Body(content))

    def copy_object(self, request: object) -> _Result:
        self.objects[request.key] = self.objects[request.source_key]  # type: ignore[attr-defined]
        return _Result(content_length=len(self.objects[request.key]))  # type: ignore[attr-defined]

    def put_object(self, request: object) -> _Result:
        self.objects[request.key] = bytes(request.body)  # type: ignore[attr-defined]
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
