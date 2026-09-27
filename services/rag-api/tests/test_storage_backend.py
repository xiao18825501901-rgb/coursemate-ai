import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.storage.backends import (
    AliyunOssStorageBackend,
    LocalStorageBackend,
    StorageIntegrityError,
    StorageObjectExistsError,
)
from app.storage.capacity import CapacityGuard, CapacityUnavailable
from app.storage.keys import canonical_object_key, quarantine_object_key


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


def test_oss_configuration_refuses_missing_resource_identity(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="OSS_REGION"):
        Settings(
            database_path=tmp_path / "db.sqlite3",
            upload_dir=tmp_path / "uploads",
            v3_enabled=True,
            storage_backend="aliyun_oss",
        )
