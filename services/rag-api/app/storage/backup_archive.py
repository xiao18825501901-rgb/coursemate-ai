from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from typing import Any

from app.config import Settings
from app.storage.backends import StorageBackend
from app.storage.capacity import CapacityGuard


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(backup_dir: Path) -> tuple[str, list[dict[str, Any]]]:
    root = backup_dir.resolve(strict=True)
    checksum_path = root / "SHA256SUMS"
    manifest_path = root / "manifest.json"
    if not checksum_path.is_file() or not manifest_path.is_file():
        raise ValueError("Backup directory is missing SHA256SUMS or manifest.json")
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in checksum_path.read_text(encoding="ascii").splitlines():
        digest, separator, name = line.partition("  ")
        path = PurePosixPath(name)
        if (
            not separator
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or path.is_absolute()
            or len(path.parts) != 1
            or ".." in path.parts
            or name in seen
        ):
            raise ValueError("Backup checksum manifest contains an unsafe entry")
        source = root / name
        if not source.is_file() or source.is_symlink() or _sha256(source) != digest:
            raise ValueError(f"Backup artifact failed SHA-256 verification: {name}")
        seen.add(name)
        files.append(
            {"name": name, "sha256": digest, "byte_size": source.stat().st_size}
        )
    if "manifest.json" not in seen:
        raise ValueError("Backup checksum manifest does not cover manifest.json")
    expected_entries = seen | {"SHA256SUMS"}
    actual_entries: set[str] = set()
    for entry in root.iterdir():
        if entry.is_symlink() or not entry.is_file():
            raise ValueError("Backup directory contains a non-regular artifact")
        actual_entries.add(entry.name)
    if actual_entries != expected_entries:
        raise ValueError(
            "Backup checksum manifest must cover every regular backup artifact"
        )
    checksum_sha = _sha256(checksum_path)
    files.append(
        {
            "name": "SHA256SUMS",
            "sha256": checksum_sha,
            "byte_size": checksum_path.stat().st_size,
        }
    )
    backup_id = hashlib.sha256(
        (checksum_sha + _sha256(manifest_path)).encode("ascii")
    ).hexdigest()[:32]
    return backup_id, files


class BackupArchiveService:
    """Archive one already-verified recovery unit as immutable OSS objects."""

    def __init__(self, backend: StorageBackend, settings: Settings) -> None:
        self.backend = backend
        self.settings = settings

    def archive(self, backup_dir: Path, receipt_path: Path) -> dict[str, Any]:
        root = backup_dir.resolve(strict=True)
        backup_id, files = _manifest(root)
        objects: list[dict[str, Any]] = []
        for ordinal, item in enumerate(files, start=1):
            key = f"backups/{backup_id}/{ordinal:03d}-{item['sha256']}"
            stored = self.backend.put_path(
                key,
                root / str(item["name"]),
                expected_sha256=str(item["sha256"]),
                content_type="application/octet-stream",
            )
            objects.append(
                {
                    **item,
                    "object_key": stored.key,
                    "version_id": stored.version_id,
                }
            )
        receipt = {
            "format_version": 1,
            "backup_id": backup_id,
            "source_manifest_sha256": next(
                str(item["sha256"]) for item in files if item["name"] == "manifest.json"
            ),
            "objects": objects,
        }
        encoded = (json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n").encode()
        receipt_digest = hashlib.sha256(encoded).hexdigest()
        self.backend.put_bytes(
            f"backups/{backup_id}/receipt.json",
            encoded,
            expected_sha256=receipt_digest,
            content_type="application/json",
        )
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with receipt_path.open("xb") as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            if receipt_path.read_bytes() != encoded:
                raise ValueError("Refusing to overwrite a different backup archive receipt")
        return {**receipt, "receipt_sha256": receipt_digest}

    def verify_restore(self, receipt_path: Path, restore_root: Path) -> dict[str, Any]:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        objects = receipt.get("objects")
        if receipt.get("format_version") != 1 or not isinstance(objects, list):
            raise ValueError("Backup archive receipt is invalid")
        required = sum(int(item["byte_size"]) for item in objects)
        restore_root.mkdir(parents=True, exist_ok=True)
        disk = shutil.disk_usage(restore_root)
        CapacityGuard(
            total_bytes=disk.total,
            free_bytes=disk.free,
            outstanding_reservations=0,
            reserve_min_bytes=self.settings.storage_reserve_min_bytes,
            reserve_fraction=self.settings.storage_reserve_fraction,
        ).reserve(peak_bytes=required)
        for item in objects:
            expected_size = int(item["byte_size"])
            digest = hashlib.sha256()
            observed = 0
            with NamedTemporaryFile(dir=restore_root, prefix="backup-restore-", delete=True) as target:
                while observed < expected_size:
                    end = min(observed + 4 * 1024**2, expected_size) - 1
                    chunk = self.backend.read_range(
                        str(item["object_key"]), start=observed, end=end
                    )
                    if not chunk:
                        raise ValueError("Backup archive restore ended before manifest size")
                    target.write(chunk)
                    digest.update(chunk)
                    observed += len(chunk)
                target.flush()
                if observed != expected_size or digest.hexdigest() != item["sha256"]:
                    raise ValueError("Backup archive restore failed SHA-256 verification")
        return {
            "backup_id": str(receipt["backup_id"]),
            "restore_verified": True,
            "object_count": len(objects),
            "restored_bytes": required,
        }
