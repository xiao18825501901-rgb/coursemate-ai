#!/usr/bin/env python3
"""Verify and restore one CourseMate backup into a new isolated directory."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tarfile
from pathlib import Path, PurePosixPath
from uuid import uuid4

REQUIRED_ARTIFACTS = {
    "rag.sqlite3",
    "agent.sqlite3",
    "uploads.tar.gz",
    "manifest.json",
    "sqlite-check.txt",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_checksums(source: Path) -> None:
    checksum_path = source / "SHA256SUMS"
    if not checksum_path.is_file():
        raise ValueError("Backup checksum manifest is missing.")
    verified: set[str] = set()
    for line in checksum_path.read_text(encoding="ascii").splitlines():
        digest, separator, filename = line.partition("  ")
        if not separator or filename not in REQUIRED_ARTIFACTS:
            raise ValueError("Backup checksum manifest is invalid.")
        artifact = source / filename
        if not artifact.is_file() or _sha256(artifact) != digest:
            raise ValueError(f"Backup checksum mismatch: {filename}")
        verified.add(filename)
    if verified != REQUIRED_ARTIFACTS:
        raise ValueError("Backup checksum manifest does not cover every required artifact.")


def _verify_sqlite(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()
    if integrity != "ok" or foreign_keys:
        raise ValueError(
            f"Restored SQLite verification failed for {path.name}: "
            f"integrity={integrity}, foreign_key_rows={len(foreign_keys)}"
        )


def _extract_uploads(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            if "\\" in member.name:
                raise ValueError(f"Unsafe upload archive path: {member.name}")
            member_path = PurePosixPath(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(f"Unsafe upload archive path: {member.name}")
            if not member.isfile() and not member.isdir():
                raise ValueError(f"Unsupported upload archive member: {member.name}")
            target = destination.joinpath(*member_path.parts)
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"Could not extract upload archive member: {member.name}")
            with extracted, target.open("wb") as output:
                while block := extracted.read(1024 * 1024):
                    output.write(block)


def restore_backup() -> Path:
    source_raw = os.environ.get("RESTORE_SOURCE", "").strip()
    target_raw = os.environ.get("RESTORE_TARGET", "").strip()
    if not source_raw:
        raise ValueError("Set RESTORE_SOURCE to one verified backup directory.")
    if not target_raw:
        raise ValueError("Set RESTORE_TARGET to a new rehearsal directory.")
    source = Path(source_raw).expanduser().resolve()
    target = Path(target_raw).expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"Restore source is not a directory: {source}")
    if target.exists():
        raise ValueError(f"Refusing to overwrite existing restore target: {target}")
    if target == source or source in target.parents:
        raise ValueError("RESTORE_TARGET must be outside the verified backup source.")

    _verify_checksums(source)
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("formatVersion") != 1:
        raise ValueError("Unsupported backup manifest version.")

    partial_target = target.with_name(f".{target.name}.{uuid4().hex}.partial")
    if partial_target.exists():
        raise ValueError(f"Refusing existing partial restore target: {partial_target}")
    partial_target.mkdir(mode=0o700, parents=True)
    uploads_target = partial_target / "uploads"
    uploads_target.mkdir(mode=0o700)
    try:
        for name in ("rag.sqlite3", "agent.sqlite3"):
            destination = partial_target / name
            shutil.copyfile(source / name, destination)
            _verify_sqlite(destination)
        _extract_uploads(source / "uploads.tar.gz", uploads_target)
        partial_target.replace(target)
    except Exception:
        # A .partial directory is deliberately retained for operator forensics and can
        # never be mistaken for a completed isolated restore.
        raise
    return target


def main() -> int:
    try:
        print(f"Isolated restore ready at {restore_backup()}")
    except Exception as error:
        print(f"Restore failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
