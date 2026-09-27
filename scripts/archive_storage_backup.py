"""Archive or restore-verify one manifest-complete recovery unit in private OSS."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "rag-api"))

from app.config import Settings
from app.storage.backends import AliyunOssStorageBackend
from app.storage.backup_archive import BackupArchiveService
from app.storage.factory import storage_backend_from_settings


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Archive and isolated-restore a checked CourseJesus backup"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    archive = subparsers.add_parser("archive")
    archive.add_argument("--backup-dir", required=True, type=Path)
    archive.add_argument("--receipt", required=True, type=Path)

    verify = subparsers.add_parser("verify-restore")
    verify.add_argument("--receipt", required=True, type=Path)
    verify.add_argument("--restore-root", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = arguments()
    settings = Settings()
    backend = storage_backend_from_settings(settings)
    if not isinstance(backend, AliyunOssStorageBackend):
        raise SystemExit("backup archive operations require STORAGE_BACKEND=aliyun_oss")
    service = BackupArchiveService(backend, settings)
    if args.command == "archive":
        result = service.archive(args.backup_dir, args.receipt)
    else:
        result = service.verify_restore(args.receipt, args.restore_root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
