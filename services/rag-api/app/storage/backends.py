import hashlib
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from uuid import uuid4


class StorageError(RuntimeError):
    pass


class StorageIntegrityError(StorageError):
    pass


class StorageObjectExistsError(StorageError):
    pass


@dataclass(frozen=True)
class StoredObject:
    backend: str
    bucket: str | None
    key: str
    version_id: str | None
    size: int
    sha256: str
    crc64: str | None
    etag: str | None
    content_type: str


class StorageBackend(Protocol):
    def put_bytes(
        self,
        key: str,
        content: bytes,
        *,
        expected_sha256: str,
        content_type: str,
    ) -> StoredObject: ...

    def put_path(
        self,
        key: str,
        path: Path,
        *,
        expected_sha256: str,
        content_type: str,
    ) -> StoredObject: ...

    def read_range(self, key: str, *, start: int, end: int) -> bytes: ...


def _safe_key(key: str) -> str:
    path = PurePosixPath(key)
    if (
        not key
        or "\\" in key
        or path.is_absolute()
        or ".." in path.parts
        or any(not part or ":" in part for part in path.parts)
    ):
        raise ValueError("Storage object key is unsafe")
    return path.as_posix()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class LocalStorageBackend:
    """Filesystem backend with immutable, atomically published objects."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / _safe_key(key)).resolve()
        path.relative_to(self.root)
        return path

    def put_bytes(
        self,
        key: str,
        content: bytes,
        *,
        expected_sha256: str,
        content_type: str,
    ) -> StoredObject:
        actual = _sha256(content)
        if actual != expected_sha256:
            raise StorageIntegrityError("Content SHA-256 does not match the trusted manifest")
        path = self._path(key)
        if path.exists():
            current = _sha256(path.read_bytes())
            if current != actual:
                raise StorageObjectExistsError("An immutable object already exists at this key")
            return StoredObject(
                "local", None, _safe_key(key), None, path.stat().st_size,
                actual, None, None, content_type,
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.part")
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                temporary.replace(path)
            except OSError:
                if path.exists() and _sha256(path.read_bytes()) == actual:
                    temporary.unlink(missing_ok=True)
                else:
                    raise
        finally:
            temporary.unlink(missing_ok=True)
        return StoredObject(
            "local", None, _safe_key(key), None, len(content), actual,
            None, None, content_type,
        )

    def read_range(self, key: str, *, start: int, end: int) -> bytes:
        if start < 0 or end < start:
            raise ValueError("Invalid byte range")
        with self._path(key).open("rb") as stream:
            stream.seek(start)
            return stream.read(end - start + 1)

    def put_path(
        self,
        key: str,
        path: Path,
        *,
        expected_sha256: str,
        content_type: str,
    ) -> StoredObject:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            raise StorageIntegrityError("File SHA-256 does not match the trusted manifest")
        destination = self._path(key)
        if destination.exists():
            return self.verify_object(
                key,
                expected_size=path.stat().st_size,
                expected_sha256=expected_sha256,
                content_type=content_type,
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.part")
        try:
            with path.open("rb") as source, temporary.open("xb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return self.verify_object(
            key,
            expected_size=path.stat().st_size,
            expected_sha256=expected_sha256,
            content_type=content_type,
        )

    def verify_object(
        self,
        key: str,
        *,
        expected_size: int,
        expected_sha256: str,
        content_type: str,
    ) -> StoredObject:
        path = self._path(key)
        digest = hashlib.sha256()
        observed = 0
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                observed += len(chunk)
                digest.update(chunk)
        if observed != expected_size or digest.hexdigest() != expected_sha256:
            raise StorageIntegrityError("Stored file does not match the trusted manifest")
        return StoredObject(
            "local", None, _safe_key(key), None, observed, expected_sha256,
            None, None, content_type,
        )


class AliyunOssStorageBackend:
    """Small OSS V2 adapter whose integrity boundary is SHA-256, never ETag."""

    def __init__(self, *, bucket: str, client: Any, prefix: str = "") -> None:
        if not bucket:
            raise ValueError("OSS bucket is required")
        self.bucket = bucket
        self.client = client
        self.prefix = prefix.strip("/")

    def _key(self, key: str) -> str:
        safe = _safe_key(key)
        return f"{self.prefix}/{safe}" if self.prefix else safe

    def put_bytes(
        self,
        key: str,
        content: bytes,
        *,
        expected_sha256: str,
        content_type: str,
    ) -> StoredObject:
        if _sha256(content) != expected_sha256:
            raise StorageIntegrityError("Content SHA-256 does not match the trusted manifest")
        from alibabacloud_oss_v2 import PutObjectRequest

        try:
            self.client.put_object(
                PutObjectRequest(
                    bucket=self.bucket,
                    key=self._key(key),
                    body=content,
                    content_length=len(content),
                    content_type=content_type,
                    forbid_overwrite=True,
                    metadata={"coursemate-sha256": expected_sha256},
                )
            )
        except Exception as upload_error:
            try:
                return self.verify_object(
                    key,
                    expected_size=len(content),
                    expected_sha256=expected_sha256,
                    content_type=content_type,
                )
            except Exception:
                raise upload_error
        return self.verify_object(
            key,
            expected_size=len(content),
            expected_sha256=expected_sha256,
            content_type=content_type,
        )

    def verify_object(
        self,
        key: str,
        *,
        expected_size: int,
        expected_sha256: str,
        content_type: str,
    ) -> StoredObject:
        from alibabacloud_oss_v2 import GetObjectRequest, HeadObjectRequest

        full_key = self._key(key)
        head = self.client.head_object(
            HeadObjectRequest(bucket=self.bucket, key=full_key)
        )
        if head.content_length != expected_size:
            raise StorageIntegrityError("OSS object size does not match the trusted manifest")
        response = self.client.get_object(
            GetObjectRequest(
                bucket=self.bucket,
                key=full_key,
                version_id=getattr(head, "version_id", None),
            )
        )
        digest = hashlib.sha256()
        observed = 0
        body = response.body
        if body is None:
            raise StorageIntegrityError("OSS returned no object body")
        try:
            for chunk in body.iter_bytes():
                observed += len(chunk)
                digest.update(chunk)
        finally:
            body.close()
        if observed != expected_size or digest.hexdigest() != expected_sha256:
            raise StorageIntegrityError("OSS object bytes do not match the trusted manifest")
        return StoredObject(
            backend="aliyun_oss",
            bucket=self.bucket,
            key=_safe_key(key),
            version_id=getattr(head, "version_id", None),
            size=observed,
            sha256=digest.hexdigest(),
            crc64=getattr(head, "hash_crc64", None),
            etag=getattr(head, "etag", None),
            content_type=content_type,
        )

    def put_path(
        self,
        key: str,
        path: Path,
        *,
        expected_sha256: str,
        content_type: str,
    ) -> StoredObject:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            raise StorageIntegrityError("File SHA-256 does not match the trusted manifest")
        from alibabacloud_oss_v2 import PutObjectRequest

        size = path.stat().st_size
        try:
            with path.open("rb") as source:
                self.client.put_object(
                    PutObjectRequest(
                        bucket=self.bucket,
                        key=self._key(key),
                        body=source,
                        content_length=size,
                        content_type=content_type,
                        forbid_overwrite=True,
                        metadata={"coursemate-sha256": expected_sha256},
                    )
                )
        except Exception as upload_error:
            try:
                return self.verify_object(
                    key,
                    expected_size=size,
                    expected_sha256=expected_sha256,
                    content_type=content_type,
                )
            except Exception:
                raise upload_error
        return self.verify_object(
            key,
            expected_size=size,
            expected_sha256=expected_sha256,
            content_type=content_type,
        )

    def read_range(self, key: str, *, start: int, end: int) -> bytes:
        if start < 0 or end < start:
            raise ValueError("Invalid byte range")
        from alibabacloud_oss_v2 import GetObjectRequest

        response = self.client.get_object(
            GetObjectRequest(
                bucket=self.bucket,
                key=self._key(key),
                range_header=f"bytes={start}-{end}",
            )
        )
        if response.body is None:
            raise StorageIntegrityError("OSS returned no object body")
        try:
            return response.body.read()
        finally:
            response.body.close()

    def presign_quarantine_put(
        self,
        key: str,
        *,
        size: int,
        sha256: str,
        content_type: str,
        ttl_seconds: int,
    ) -> tuple[str, dict[str, str], str]:
        from alibabacloud_oss_v2 import PutObjectRequest

        if ttl_seconds < 60 or ttl_seconds > 900:
            raise ValueError("Direct upload signatures must expire in 60-900 seconds")
        if not _safe_key(key).startswith("quarantine/"):
            raise ValueError("Direct upload signatures are restricted to quarantine objects")
        result = self.client.presign(
            PutObjectRequest(
                bucket=self.bucket,
                key=self._key(key),
                content_type=content_type,
                forbid_overwrite=True,
                metadata={"coursemate-sha256": sha256},
            ),
            expires=timedelta(seconds=ttl_seconds),
        )
        headers = {str(key): str(value) for key, value in (result.signed_headers or {}).items()}
        return str(result.url), headers, result.expiration.isoformat()

    def promote_verified(
        self,
        source_key: str,
        destination_key: str,
        *,
        expected_size: int,
        expected_sha256: str,
        content_type: str,
    ) -> StoredObject:
        from alibabacloud_oss_v2 import CopyObjectRequest

        self.verify_object(
            source_key,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            content_type=content_type,
        )
        self.client.copy_object(
            CopyObjectRequest(
                bucket=self.bucket,
                key=self._key(destination_key),
                source_bucket=self.bucket,
                source_key=self._key(source_key),
                content_type=content_type,
                metadata={"coursemate-sha256": expected_sha256},
                metadata_directive="REPLACE",
                forbid_overwrite=True,
            )
        )
        return self.verify_object(
            destination_key,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            content_type=content_type,
        )
