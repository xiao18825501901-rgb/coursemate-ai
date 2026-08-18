#!/usr/bin/env python3
"""Create a verified CourseMate backup containing both databases and uploads."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ARTIFACTS = (
    "rag.sqlite3",
    "agent.sqlite3",
    "uploads.tar.gz",
    "manifest.json",
    "sqlite-check.txt",
)


def _required_path(name: str, *, directory: bool = False) -> Path:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        raise ValueError(f"Set {name} to an explicit path.")
    path = Path(raw_value).expanduser().resolve()
    if directory and not path.is_dir():
        raise ValueError(f"{name} is not an existing directory: {path}")
    if not directory and not path.is_file():
        raise ValueError(f"{name} is not an existing file: {path}")
    return path


def _sqlite_backup(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()


def _sqlite_check(path: Path) -> tuple[str, list[tuple[object, ...]]]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()
    if integrity != "ok" or foreign_keys:
        raise RuntimeError(
            f"SQLite verification failed for {path.name}: "
            f"integrity={integrity}, foreign_key_rows={len(foreign_keys)}"
        )
    return integrity, foreign_keys


def _archive_uploads(upload_root: Path, destination: Path) -> tuple[int, int]:
    members = sorted(upload_root.rglob("*"), key=lambda path: path.as_posix())
    for member in members:
        if member.is_symlink():
            raise ValueError(f"Refusing symlink in upload tree: {member}")
        if not member.is_dir() and not member.is_file():
            raise ValueError(f"Refusing special file in upload tree: {member}")
    with tarfile.open(destination, "w:gz") as archive:
        for member in members:
            archive.add(member, arcname=member.relative_to(upload_root), recursive=False)
    files = [member for member in members if member.is_file()]
    return len(files), sum(member.stat().st_size for member in files)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_backup() -> Path:
    rag_database = _required_path("RAG_DATABASE_PATH")
    agent_database = _required_path("AGENT_DATABASE_PATH")
    if rag_database == agent_database:
        raise ValueError("RAG_DATABASE_PATH and AGENT_DATABASE_PATH must be different files.")
    upload_root = _required_path("RAG_UPLOAD_DIR", directory=True)
    backup_root_raw = os.environ.get("BACKUP_ROOT", "").strip()
    if not backup_root_raw:
        raise ValueError("Set BACKUP_ROOT to a dedicated backup directory.")
    backup_root = Path(backup_root_raw).expanduser().resolve()
    if backup_root == upload_root or upload_root in backup_root.parents:
        raise ValueError("BACKUP_ROOT must be outside the private upload tree.")
    backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)

    created_at = datetime.now(UTC)
    stamp = created_at.strftime("%Y%m%dT%H%M%S.%fZ")
    final_destination = backup_root / f"coursemate-v2-{stamp}"
    partial_destination = backup_root / f".coursemate-v2-{stamp}.{uuid4().hex}.partial"
    partial_destination.mkdir(mode=0o700)
    _sqlite_backup(rag_database, partial_destination / "rag.sqlite3")
    _sqlite_backup(agent_database, partial_destination / "agent.sqlite3")
    upload_file_count, upload_total_bytes = _archive_uploads(
        upload_root, partial_destination / "uploads.tar.gz"
    )
    check_lines: list[str] = []
    for name in ("rag.sqlite3", "agent.sqlite3"):
        integrity, foreign_keys = _sqlite_check(partial_destination / name)
        check_lines.extend(
            (
                f"{name} integrity_check={integrity}",
                f"{name} foreign_key_rows={len(foreign_keys)}",
            )
        )
    (partial_destination / "sqlite-check.txt").write_text(
        "\n".join(check_lines) + "\n", encoding="utf-8"
    )
    manifest = {
        "formatVersion": 1,
        "createdAt": created_at.isoformat(),
        "artifacts": {
            "ragDatabase": "rag.sqlite3",
            "agentDatabase": "agent.sqlite3",
            "uploads": "uploads.tar.gz",
        },
        "uploadFileCount": upload_file_count,
        "uploadTotalBytes": upload_total_bytes,
        "verification": {
            "sqliteIntegrity": "ok",
            "foreignKeyViolations": 0,
        },
    }
    (partial_destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    checksum_lines = [
        f"{_sha256(partial_destination / name)}  {name}" for name in ARTIFACTS
    ]
    (partial_destination / "SHA256SUMS").write_text(
        "\n".join(checksum_lines) + "\n", encoding="ascii"
    )
    # Errors leave only a hidden `.partial` directory, never a complete-looking backup.
    partial_destination.replace(final_destination)
    return final_destination


def main() -> int:
    try:
        print(create_backup())
    except (OSError, sqlite3.Error, tarfile.TarError, ValueError, RuntimeError) as error:
        print(f"Backup failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
