#!/usr/bin/env python3
"""Archive or restore-verify one CourseJesus recovery unit in private OSS."""

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--verify-restore", action="store_true")
    parser.add_argument("--restore-root", type=Path)
    args = parser.parse_args()
    settings = Settings()
    backend = storage_backend_from_settings(settings)
    if not isinstance(backend, AliyunOssStorageBackend):
        raise SystemExit("Private OSS configuration is required")
    service = BackupArchiveService(backend, settings)
    if args.verify_restore:
        if args.restore_root is None:
            raise SystemExit("--verify-restore requires --restore-root")
        result = service.verify_restore(args.receipt, args.restore_root)
    else:
        if args.backup_dir is None:
            raise SystemExit("archive requires --backup-dir")
        result = service.archive(args.backup_dir, args.receipt)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
