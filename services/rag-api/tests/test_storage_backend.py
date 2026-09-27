import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.db import Database
from app.storage.backends import (
    AliyunOssStorageBackend,
    LocalStorageBackend,
    StorageIntegrityError,
    StorageObjectExistsError,
)
from app.storage.backup_archive import BackupArchiveService
from app.storage.capacity import CapacityGuard, CapacityUnavailable
from app.storage.keys import canonical_object_key, quarantine_object_key
from app.storage.migration import StorageMigrationService


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_local_backend_is_immutable_and_supports_inclusive_ranges(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path / "objects")
    content = b"0123456789"

    stored = backend.put_bytes(
        "canonical/owner/course/doc/file.bin",
        content,
        expected_sha256=_sha(content),
        content_type="application/octet-stream",
    )

    assert stored.sha256 == _sha(content)
    assert backend.read_range(stored.key, start=2, end=5) == b"2345"
    assert backend.put_bytes(
        stored.key,
        content,
        expected_sha256=_sha(content),
        content_type="application/octet-stream",
    ) == stored
    with pytest.raises(StorageObjectExistsError):
        backend.put_bytes(
            stored.key,
            b"different",
            expected_sha256=_sha(b"different"),
            content_type="application/octet-stream",
        )


def test_server_side_hash_check_rejects_corruption(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path / "objects")

    with pytest.raises(StorageIntegrityError):
        backend.put_bytes(
            "canonical/a/b/c.txt",
            b"actual",
            expected_sha256=_sha(b"claimed"),
            content_type="text/plain",
        )
    assert not any((tmp_path / "objects").rglob("*.txt"))


def test_storage_keys_are_scoped_and_never_embed_identity_or_filename() -> None:
    key = canonical_object_key(
        owner_user_id="user-private@example.edu",
        course_id="course-a",
        document_id="doc-a",
        sha256="a" * 64,
        extension=".pdf",
    )
    pending = quarantine_object_key(
        owner_user_id="user-private@example.edu",
        upload_id="upl_123",
        extension=".pdf",
    )

    assert key.startswith("canonical/") and key.endswith("/" + "a" * 64 + ".pdf")
    assert pending.startswith("quarantine/") and pending.endswith("/upl_123.pdf")
    assert "user-private" not in key + pending
    assert "course-a" not in key


def test_capacity_guard_uses_larger_of_ten_gib_and_twenty_percent() -> None:
    gib = 1024**3
    guard = CapacityGuard(
        total_bytes=100 * gib,
        free_bytes=35 * gib,
        outstanding_reservations=5 * gib,
    )
    admitted = guard.reserve(peak_bytes=9 * gib)
    assert admitted.reserve_bytes == 20 * gib
    assert admitted.remaining_bytes == 21 * gib

    with pytest.raises(CapacityUnavailable) as error:
        guard.reserve(peak_bytes=11 * gib)
    assert error.value.required_free_bytes == 36 * gib


@dataclass
class _Head:
    content_length: int
    etag: str
    version_id: str
    hash_crc64: str = "crc"


class _Body:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.closed = False

    def iter_bytes(self, **_: object):
        yield self.content[:3]
        yield self.content[3:]

    def close(self) -> None:
        self.closed = True


@dataclass
class _Get:
    body: _Body
    content_length: int
    version_id: str
    etag: str = "multipart-etag-that-is-not-md5"
    hash_crc64: str = "crc"


class _FakeOssClient:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.requests: list[object] = []
        self.last_body: _Body | None = None

    def head_object(self, request: object) -> _Head:
        self.requests.append(request)
        return _Head(len(self.content), "not-the-content-hash", "version-7")

    def get_object(self, request: object) -> _Get:
        self.requests.append(request)
        self.last_body = _Body(self.content)
        return _Get(self.last_body, len(self.content), "version-7")

    def put_object(self, request: object) -> object:
        self.requests.append(request)
        body = request.body  # type: ignore[attr-defined]
        self.content = body.read() if hasattr(body, "read") else bytes(body)
        return object()


def test_oss_verification_streams_sha256_and_does_not_trust_etag() -> None:
    content = b"authoritative object bytes"
    client = _FakeOssClient(content)
    backend = AliyunOssStorageBackend(
        bucket="private-coursejesus",
        client=client,
        prefix="coursejesus",
    )

    verified = backend.verify_object(
        "quarantine/owner/upload.pdf",
        expected_size=len(content),
        expected_sha256=_sha(content),
        content_type="application/pdf",
    )

    assert verified.sha256 == _sha(content)
    assert verified.version_id == "version-7"
    assert verified.etag == "not-the-content-hash"
    assert client.last_body is not None and client.last_body.closed

    with pytest.raises(StorageIntegrityError):
        backend.verify_object(
            "quarantine/owner/upload.pdf",
            expected_size=len(content),
            expected_sha256="f" * 64,
            content_type="application/pdf",
        )


def test_oss_put_path_streams_source_and_verifies_full_object(tmp_path: Path) -> None:
    content = (b"course-material-" * 1024) + b"end"
    source = tmp_path / "large-source.bin"
    source.write_bytes(content)
    client = _FakeOssClient(b"")
    backend = AliyunOssStorageBackend(
        bucket="private-coursejesus", client=client, prefix="coursejesus"
    )

    stored = backend.put_path(
        "canonical/owner/course/doc/file.bin",
        source,
        expected_sha256=_sha(content),
        content_type="application/octet-stream",
    )

    assert stored.size == len(content)
    assert stored.sha256 == _sha(content)
    assert client.content == content


def test_oss_configuration_refuses_missing_resource_identity(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="OSS_REGION"):
        Settings(
            database_path=tmp_path / "db.sqlite3",
            upload_dir=tmp_path / "uploads",
            v3_enabled=True,
            storage_backend="aliyun_oss",
        )


def test_version_migration_is_idempotent_restore_verified_and_never_deletes_source(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        storage_cache_dir=tmp_path / "cache",
        storage_reserve_min_bytes=0,
        storage_reserve_fraction=0,
        v3_enabled=True,
        app_env="test",
        rag_provider_mode="deterministic",
    )
    database = Database(settings)
    database.initialize()
    source = settings.upload_dir / "legacy.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    content = b"immutable legacy source"
    source.write_bytes(content)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,course_type,visibility,publication_status) "
            "VALUES('legacy-course','Legacy','official','public','draft')"
        )
        connection.execute(
            "INSERT INTO documents(id,course_id,filename,stored_path,media_type,extension,"
            "sha256,byte_size,status) VALUES('legacy-doc','legacy-course','legacy.txt',?,"
            "'text/plain','.txt',?,?,'ready')",
            (str(source), _sha(content), len(content)),
        )
        version_id = str(
            connection.execute(
                "SELECT id FROM document_versions WHERE document_id='legacy-doc'"
            ).fetchone()["id"]
        )
    backend = LocalStorageBackend(tmp_path / "durable-object-fixture")
    migration = StorageMigrationService(database, settings, backend)

    first = migration.migrate_version(version_id)
    repeated = migration.migrate_version(version_id)
    restored = migration.verify_restore(version_id, tmp_path / "isolated-restore")

    assert first["reused"] is False
    assert repeated["reused"] is True
    assert restored["restore_verified"] is True
    assert source.read_bytes() == content
    with database.connect() as connection:
        receipt = connection.execute(
            "SELECT local_delete_eligible,restore_verified_at FROM storage_migration_receipts "
            "WHERE document_version_id=?",
            (version_id,),
        ).fetchone()
        linked = connection.execute(
            "SELECT storage_object_id FROM documents WHERE id='legacy-doc'"
        ).fetchone()["storage_object_id"]
    assert receipt["local_delete_eligible"] == 1
    assert receipt["restore_verified_at"] is not None
    assert linked == first["storage_object_id"]


def test_verified_backup_is_archived_as_individual_objects_and_restore_checked(
    tmp_path: Path,
) -> None:
    backup = tmp_path / "backup"
    backup.mkdir()
    artifacts = {
        "rag.sqlite3": b"synthetic database snapshot",
        "uploads.tar.gz": b"synthetic upload archive",
        "manifest.json": b'{"formatVersion":1}\n',
    }
    for name, content in artifacts.items():
        (backup / name).write_bytes(content)
    (backup / "SHA256SUMS").write_text(
        "".join(f"{_sha(content)}  {name}\n" for name, content in artifacts.items()),
        encoding="ascii",
    )
    settings = Settings(
        database_path=tmp_path / "unused.sqlite3",
        upload_dir=tmp_path / "uploads",
        storage_reserve_min_bytes=0,
        storage_reserve_fraction=0,
        app_env="test",
    )
    service = BackupArchiveService(
        LocalStorageBackend(tmp_path / "durable-backups"), settings
    )
    receipt_path = tmp_path / "receipts" / "backup.json"

    archived = service.archive(backup, receipt_path)
    repeated = service.archive(backup, receipt_path)
    restored = service.verify_restore(receipt_path, tmp_path / "restore-check")

    assert archived == repeated
    assert restored == {
        "backup_id": archived["backup_id"],
        "restore_verified": True,
        "object_count": 4,
        "restored_bytes": sum(path.stat().st_size for path in backup.iterdir()),
    }
    assert all(
        not item["object_key"].endswith(item["name"])
        for item in archived["objects"]
    )


def test_backup_archive_rejects_unmanifested_artifact(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    backup.mkdir()
    manifest = b'{"formatVersion":1}\n'
    (backup / "manifest.json").write_bytes(manifest)
    (backup / "SHA256SUMS").write_text(
        f"{_sha(manifest)}  manifest.json\n", encoding="ascii"
    )
    (backup / "untracked.sqlite3").write_bytes(b"must not be silently omitted")
    settings = Settings(
        database_path=tmp_path / "unused.sqlite3",
        upload_dir=tmp_path / "uploads",
        storage_reserve_min_bytes=0,
        storage_reserve_fraction=0,
        app_env="test",
    )
    service = BackupArchiveService(
        LocalStorageBackend(tmp_path / "durable-backups"), settings
    )

    with pytest.raises(ValueError, match="every regular backup artifact"):
        service.archive(backup, tmp_path / "receipt.json")
