from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from app.config import Settings
from app.db import Database
from app.storage.backends import StorageBackend
from app.storage.capacity import CapacityGuard
from app.storage.keys import canonical_object_key


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class StorageMigrationService:
    """Copy immutable document versions without deleting or re-indexing sources."""

    def __init__(self, database: Database, settings: Settings, backend: StorageBackend) -> None:
        self.database = database
        self.settings = settings
        self.backend = backend

    def plan(self) -> dict[str, Any]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT version.id,version.document_id,version.filename,version.stored_path,"
                "version.byte_size,version.sha256,version.source_scope,version.owner_user_id,"
                "version.course_id,version.extension,version.media_type,"
                "object.id AS storage_object_id,receipt.restore_verified_at "
                "FROM document_versions AS version "
                "LEFT JOIN storage_objects AS object "
                "ON object.document_version_id=version.id AND object.state='CANONICAL' "
                "LEFT JOIN storage_migration_receipts AS receipt "
                "ON receipt.document_version_id=version.id ORDER BY version.course_id,version.id"
            ).fetchall()
        items = []
        for row in rows:
            path = Path(str(row["stored_path"]))
            items.append(
                {
                    "document_version_id": str(row["id"]),
                    "course_id": str(row["course_id"]),
                    "filename": str(row["filename"]),
                    "byte_size": int(row["byte_size"]),
                    "source_exists": path.is_file(),
                    "remote_linked": row["storage_object_id"] is not None,
                    "restore_verified": row["restore_verified_at"] is not None,
                }
            )
        return {
            "versions": items,
            "version_count": len(items),
            "candidate_count": sum(not item["remote_linked"] for item in items),
            "candidate_bytes": sum(
                item["byte_size"] for item in items if not item["remote_linked"]
            ),
            "missing_source_count": sum(
                not item["source_exists"] and not item["remote_linked"] for item in items
            ),
        }

    def migrate_version(self, document_version_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT version.*,object.id AS storage_object_id,object.object_key,"
                "receipt.restore_verified_at FROM document_versions AS version "
                "LEFT JOIN storage_objects AS object "
                "ON object.document_version_id=version.id AND object.state='CANONICAL' "
                "LEFT JOIN storage_migration_receipts AS receipt "
                "ON receipt.document_version_id=version.id WHERE version.id=?",
                (document_version_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Document version was not found")
        if row["storage_object_id"] is not None:
            return {
                "document_version_id": document_version_id,
                "storage_object_id": str(row["storage_object_id"]),
                "object_key": str(row["object_key"]),
                "reused": True,
                "restore_verified": row["restore_verified_at"] is not None,
            }
        source = Path(str(row["stored_path"])).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        if source.stat().st_size != int(row["byte_size"]) or _file_sha256(source) != str(
            row["sha256"]
        ):
            raise ValueError("Local source does not match its immutable version manifest")
        owner = str(row["owner_user_id"] or "official-system")
        key = canonical_object_key(
            owner_user_id=owner,
            course_id=str(row["course_id"]),
            document_id=str(row["document_id"]),
            sha256=str(row["sha256"]),
            extension=str(row["extension"]),
        )
        stored = self.backend.put_path(
            key,
            source,
            expected_sha256=str(row["sha256"]),
            content_type=str(row["media_type"]),
        )
        object_id = "obj_mig_" + hashlib.sha256(
            f"{document_version_id}:{key}".encode()
        ).hexdigest()[:32]
        receipt_id = "storage_migration_" + hashlib.sha256(
            document_version_id.encode()
        ).hexdigest()[:32]
        backend_name = "ALIYUN_OSS" if stored.backend == "aliyun_oss" else "LOCAL"
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            inserted = connection.execute(
                "INSERT OR IGNORE INTO storage_objects("
                "id,backend,bucket,object_key,version_id,byte_size,sha256,crc64,etag,"
                "media_type,state,owner_user_id,course_id,document_id,local_cache_path,"
                "verified_at,document_version_id) VALUES(?,?,?,?,?,?,?,?,?,?,'CANONICAL',"
                "?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'),?)",
                (
                    object_id,
                    backend_name,
                    stored.bucket,
                    stored.key,
                    stored.version_id,
                    stored.size,
                    stored.sha256,
                    stored.crc64,
                    stored.etag,
                    stored.content_type,
                    owner,
                    row["course_id"],
                    row["document_id"],
                    str(source),
                    document_version_id,
                ),
            ).rowcount
            persisted = connection.execute(
                "SELECT id,backend,bucket,object_key,byte_size,sha256,document_version_id "
                "FROM storage_objects WHERE document_version_id=? AND state='CANONICAL'",
                (document_version_id,),
            ).fetchone()
            if persisted is None or (
                str(persisted["backend"]) != backend_name
                or persisted["bucket"] != stored.bucket
                or str(persisted["object_key"]) != stored.key
                or int(persisted["byte_size"]) != stored.size
                or str(persisted["sha256"]) != stored.sha256
            ):
                raise RuntimeError(
                    "A concurrent storage migration recorded different immutable bytes"
                )
            object_id = str(persisted["id"])
            connection.execute(
                "INSERT OR IGNORE INTO storage_migration_receipts("
                "id,storage_object_id,source_path,source_sha256,remote_verified_at,"
                "local_delete_eligible,document_version_id) VALUES(?,?,?,?,"
                "strftime('%Y-%m-%dT%H:%M:%fZ','now'),0,?)",
                (receipt_id, object_id, str(source), row["sha256"], document_version_id),
            )
            latest = connection.execute(
                "SELECT id,stored_path FROM document_versions WHERE document_id=? "
                "ORDER BY version DESC LIMIT 1",
                (row["document_id"],),
            ).fetchone()
            if latest is not None and latest["id"] == document_version_id:
                connection.execute(
                    "UPDATE documents SET storage_object_id=? WHERE id=? AND stored_path=?",
                    (object_id, row["document_id"], latest["stored_path"]),
                )
        return {
            "document_version_id": document_version_id,
            "storage_object_id": object_id,
            "object_key": stored.key,
            "reused": inserted == 0,
            "restore_verified": False,
        }

    def verify_restore(self, document_version_id: str, restore_root: Path) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT object.id,object.object_key,object.byte_size,object.sha256,"
                "receipt.id AS receipt_id,receipt.restore_verified_at "
                "FROM storage_objects AS object JOIN storage_migration_receipts AS receipt "
                "ON receipt.storage_object_id=object.id "
                "WHERE object.document_version_id=? AND object.state='CANONICAL'",
                (document_version_id,),
            ).fetchone()
            outstanding = int(
                connection.execute(
                    "SELECT COALESCE(SUM(peak_bytes),0) FROM storage_capacity_reservations "
                    "WHERE status='ACTIVE' AND expires_at>strftime('%Y-%m-%dT%H:%M:%fZ','now')"
                ).fetchone()[0]
            )
        if row is None:
            raise ValueError("The document version has no verified durable object")
        if row["restore_verified_at"] is not None:
            return {"document_version_id": document_version_id, "restore_verified": True}
        restore_root.mkdir(parents=True, exist_ok=True)
        disk = shutil.disk_usage(restore_root)
        CapacityGuard(
            total_bytes=disk.total,
            free_bytes=disk.free,
            outstanding_reservations=outstanding,
            reserve_min_bytes=self.settings.storage_reserve_min_bytes,
            reserve_fraction=self.settings.storage_reserve_fraction,
        ).reserve(peak_bytes=int(row["byte_size"]))
        digest = hashlib.sha256()
        observed = 0
        with NamedTemporaryFile(dir=restore_root, prefix="restore-", delete=True) as restored:
            while observed < int(row["byte_size"]):
                end = min(observed + 4 * 1024**2, int(row["byte_size"])) - 1
                chunk = self.backend.read_range(
                    str(row["object_key"]), start=observed, end=end
                )
                if not chunk:
                    raise ValueError("Durable restore ended before the manifest size")
                restored.write(chunk)
                digest.update(chunk)
                observed += len(chunk)
            restored.flush()
            if observed != int(row["byte_size"]) or digest.hexdigest() != str(row["sha256"]):
                raise ValueError("Isolated restore does not match the immutable manifest")
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE storage_migration_receipts SET restore_verified_at="
                "strftime('%Y-%m-%dT%H:%M:%fZ','now'),local_delete_eligible=1 "
                "WHERE id=? AND restore_verified_at IS NULL",
                (row["receipt_id"],),
            )
        return {"document_version_id": document_version_id, "restore_verified": True}
