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

# Data artifacts a backup always carries, independent of what the manifest lists.
BASE_DATA_ARTIFACTS = {"rag.sqlite3", "agent.sqlite3", "uploads.tar.gz"}
METADATA_ARTIFACTS = {"manifest.json", "sqlite-check.txt"}

# Present only when the refreshed learning shell is part of the deployment.
OPTIONAL_ARTIFACTS = {"ui.sqlite3", "ui-uploads.tar.gz"}


def _data_artifacts(manifest: dict[str, object]) -> set[str]:
    """Return the data artifacts this backup carries.

    The `artifacts` map is derived state: older backups may omit it or list only
    some entries, so it is never trusted as the source of truth. It can only add
    the refreshed-shell database and attachment archive, which are recognised
    explicitly; anything else it names is a corrupt or forged backup.
    """

    declared = BASE_DATA_ARTIFACTS
    artifacts = manifest.get("artifacts")
    if artifacts is None:
        return declared
    if not isinstance(artifacts, dict):
        raise ValueError("Backup manifest artifacts must be an object.")
    named = {value for value in artifacts.values() if isinstance(value, str)}
    unexpected = named - BASE_DATA_ARTIFACTS - OPTIONAL_ARTIFACTS - METADATA_ARTIFACTS
    if unexpected:
        raise ValueError(f"Backup manifest declares unknown artifacts: {sorted(unexpected)}")
    optional_declared = named & OPTIONAL_ARTIFACTS
    if optional_declared and optional_declared != OPTIONAL_ARTIFACTS:
        raise ValueError("Backup declares only part of the refreshed-shell artifacts.")
    return declared | optional_declared


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_checksums(source: Path, data_artifacts: set[str]) -> None:
    covered = data_artifacts | METADATA_ARTIFACTS
    checksum_path = source / "SHA256SUMS"
    if not checksum_path.is_file():
        raise ValueError("Backup checksum manifest is missing.")
    verified: set[str] = set()
    for line in checksum_path.read_text(encoding="ascii").splitlines():
        digest, separator, filename = line.partition("  ")
        if not separator or filename not in covered:
            raise ValueError("Backup checksum manifest is invalid.")
        artifact = source / filename
        if not artifact.is_file() or _sha256(artifact) != digest:
            raise ValueError(f"Backup checksum mismatch: {filename}")
        verified.add(filename)
    if verified != covered:
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


def _extract_uploads(
    archive_path: Path,
    destination: Path,
    *,
    expected_file_count: int,
    expected_total_bytes: int,
) -> None:
    file_count = 0
    total_bytes = 0
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        validated: list[tuple[tarfile.TarInfo, PurePosixPath]] = []
        seen_paths: set[PurePosixPath] = set()
        for member in members:
            if "\\" in member.name:
                raise ValueError(f"Unsafe upload archive path: {member.name}")
            member_path = PurePosixPath(member.name)
            if (
                not member_path.parts
                or member_path == PurePosixPath(".")
                or member_path.is_absolute()
                or ".." in member_path.parts
            ):
                raise ValueError(f"Unsafe upload archive path: {member.name}")
            if member_path in seen_paths:
                raise ValueError(f"Duplicate upload archive path: {member.name}")
            seen_paths.add(member_path)
            if not member.isfile() and not member.isdir():
                raise ValueError(f"Unsupported upload archive member: {member.name}")
            if member.size < 0:
                raise ValueError(f"Invalid upload archive member size: {member.name}")
            validated.append((member, member_path))
            if member.isfile():
                file_count += 1
                total_bytes += member.size
        if (
            file_count != expected_file_count
            or total_bytes != expected_total_bytes
        ):
            raise ValueError("Upload archive does not match the backup manifest.")

        for member, member_path in validated:
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

    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("formatVersion") != 1:
        raise ValueError("Unsupported backup manifest version.")
    data_artifacts = _data_artifacts(manifest)
    _verify_checksums(source, data_artifacts)
    expected_file_count = manifest.get("uploadFileCount")
    expected_total_bytes = manifest.get("uploadTotalBytes")
    if (
        not isinstance(expected_file_count, int)
        or isinstance(expected_file_count, bool)
        or expected_file_count < 0
        or not isinstance(expected_total_bytes, int)
        or isinstance(expected_total_bytes, bool)
        or expected_total_bytes < 0
    ):
        raise ValueError("Backup upload manifest is invalid.")
    includes_ui = "ui.sqlite3" in data_artifacts
    ui_expected_file_count = manifest.get("uiUploadFileCount")
    ui_expected_total_bytes = manifest.get("uiUploadTotalBytes")
    if includes_ui and (
        not isinstance(ui_expected_file_count, int)
        or isinstance(ui_expected_file_count, bool)
        or ui_expected_file_count < 0
        or not isinstance(ui_expected_total_bytes, int)
        or isinstance(ui_expected_total_bytes, bool)
        or ui_expected_total_bytes < 0
    ):
        raise ValueError("Backup refreshed-shell upload manifest is invalid.")

    partial_target = target.with_name(f".{target.name}.{uuid4().hex}.partial")
    if partial_target.exists():
        raise ValueError(f"Refusing existing partial restore target: {partial_target}")
    partial_target.mkdir(mode=0o700, parents=True)
    uploads_target = partial_target / "uploads"
    uploads_target.mkdir(mode=0o700)
    databases = ["rag.sqlite3", "agent.sqlite3"]
    if includes_ui:
        databases.append("ui.sqlite3")
    for name in databases:
        destination = partial_target / name
        shutil.copyfile(source / name, destination)
        _verify_sqlite(destination)
    _extract_uploads(
        source / "uploads.tar.gz",
        uploads_target,
        expected_file_count=expected_file_count,
        expected_total_bytes=expected_total_bytes,
    )
    if includes_ui:
        ui_uploads_target = partial_target / "ui-uploads"
        ui_uploads_target.mkdir(mode=0o700)
        _extract_uploads(
            source / "ui-uploads.tar.gz",
            ui_uploads_target,
            expected_file_count=ui_expected_file_count,
            expected_total_bytes=ui_expected_total_bytes,
        )
    # Errors leave only a hidden `.partial` directory, never a complete-looking restore.
    partial_target.replace(target)
    return target


def main() -> int:
    try:
        print(f"Isolated restore ready at {restore_backup()}")
    except (OSError, sqlite3.Error, tarfile.TarError, ValueError, RuntimeError) as error:
        print(f"Restore failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
