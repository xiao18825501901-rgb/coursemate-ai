"""Plan or execute immutable document-version migration to configured private OSS."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "rag-api"))

from app.config import Settings
from app.db import Database
from app.storage.backends import AliyunOssStorageBackend
from app.storage.factory import storage_backend_from_settings
from app.storage.migration import StorageMigrationService


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="copy and byte-verify candidates")
    parser.add_argument(
        "--verify-restore", action="store_true", help="perform an isolated range restore"
    )
    parser.add_argument("--version-id", action="append", default=[])
    parser.add_argument("--restore-root", type=Path)
    return parser.parse_args()


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True), flush=True)


def main() -> int:
    args = arguments()
    settings = Settings()
    database = Database(settings)
    database.initialize()
    backend = storage_backend_from_settings(settings)
    service = StorageMigrationService(database, settings, backend)
    plan = service.plan()
    emit({"kind": "plan", **plan})
    if not args.apply and not args.verify_restore:
        return 0
    if not isinstance(backend, AliyunOssStorageBackend):
        raise SystemExit("--apply/--verify-restore requires STORAGE_BACKEND=aliyun_oss")
    candidates = args.version_id or [
        item["document_version_id"]
        for item in plan["versions"]
        if not item["remote_linked"]
    ]
    if args.apply:
        for version_id in candidates:
            emit({"kind": "migration", **service.migrate_version(version_id)})
    if args.verify_restore:
        if args.restore_root is None:
            raise SystemExit("--verify-restore requires --restore-root")
        verified = args.version_id or [
            item["document_version_id"]
            for item in service.plan()["versions"]
            if item["remote_linked"] and not item["restore_verified"]
        ]
        for version_id in verified:
            emit(
                {
                    "kind": "restore",
                    **service.verify_restore(version_id, args.restore_root),
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
