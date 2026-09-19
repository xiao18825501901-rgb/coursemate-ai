#!/usr/bin/env python3
"""Verify and restore one CourseMate backup into a new isolated directory.

After a publication failure, leave RESTORE_SOURCE and RESTORE_TARGET unchanged
and explicitly set RESTORE_RESUME_PARTIAL to the reported hidden sibling path.
Resume re-verifies the source and every staged byte before publication.
Windows publication alone tolerates bounded transient denials; it never repairs,
overwrites, or deletes staging.
Keep the source, staging, and target parent private and quiescent while restoring.
"""

from __future__ import annotations

import hashlib
import ctypes
import errno
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import tarfile
import time
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


def _rename_no_replace(source: Path, target: Path) -> None:
    """One same-filesystem rename, refusing even a racing empty target directory."""
    if os.name == "nt":
        # Unlike POSIX rename, Windows rename rejects every existing target.
        os.rename(source, target)
        return
    if not sys.platform.startswith("linux"):
        raise OSError(errno.ENOTSUP, "Atomic no-overwrite directory publication is unavailable on this platform")
    library = ctypes.CDLL(None, use_errno=True)
    rename = getattr(library, "renameat2", None)
    if rename is None:
        raise OSError(errno.ENOTSUP, "libc renameat2 is required for no-overwrite directory publication")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    # Linux renameat2(AT_FDCWD, source, AT_FDCWD, target, RENAME_NOREPLACE).
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number), str(target))


def _publish_partial(partial: Path, target: Path) -> Path:
    # All application-owned DB/archive/file handles are closed before entry.
    # WinError 5 does not identify its cause: tolerate brief denials, but do not
    # change ACLs, kill a locker, or replace an existing target. No I/O is replayed.
    delays = (0.1, 0.2, 0.4, 0.8)
    for attempt in range(5):
        if os.path.lexists(target):
            raise FileExistsError(errno.EEXIST, "Refusing existing restore target", str(target))
        try:
            _rename_no_replace(partial, target)
            if attempt:
                print(f"Restore publication succeeded attempt={attempt + 1}", file=sys.stderr)
            return target
        except OSError as error:
            if os.path.lexists(target):
                raise FileExistsError(errno.EEXIST, "Refusing existing restore target", str(target)) from error
            if getattr(error, "winerror", None) not in {5, 32}:
                raise
            print(f"Restore publication denied attempt={attempt + 1} winerror={error.winerror} "
                  f"retry_delay_seconds={delays[attempt] if attempt < 4 else 0}", file=sys.stderr)
            if attempt == 4:
                raise RuntimeError(
                    f"Windows refused final restore publication (WinError {error.winerror}); cause unknown. "
                    f"Staging is preserved at {partial}. After resolving the cause without changing its contents, "
                    "rerun with the same RESTORE_SOURCE and RESTORE_TARGET and "
                    f"RESTORE_RESUME_PARTIAL={partial}. Exhausted 5 attempts / 1.5 seconds of bounded waiting."
                ) from error
            time.sleep(delays[attempt])


def _plain_tree(root: Path) -> dict[str, str]:
    """Enumerate without following symlinks, junctions, reparse points or aliases."""
    result: dict[str, str] = {}
    pending = [root]
    while pending:
        path = pending.pop()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Refusing linked/reparse staging path: {path}")
        if stat.S_ISDIR(info.st_mode):
            kind = "directory"
            pending.extend(path.iterdir())
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            kind = "file"
        else:
            raise ValueError(f"Refusing special/aliased staging file: {path}")
        if path != root:
            result[path.relative_to(root).as_posix()] = kind
    return result


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
    unexpected = named - BASE_DATA_ARTIFACTS - OPTIONAL_ARTIFACTS - METADATA_ARTIFACTS - {'ui-shares.tar.gz'}
    if unexpected:
        raise ValueError(f"Backup manifest declares unknown artifacts: {sorted(unexpected)}")
    optional_declared = named & OPTIONAL_ARTIFACTS
    if optional_declared and optional_declared != OPTIONAL_ARTIFACTS:
        raise ValueError("Backup declares only part of the refreshed-shell artifacts.")
    if 'ui-shares.tar.gz' in named:
        if optional_declared != OPTIONAL_ARTIFACTS:
            raise ValueError('Snapshot archive requires the complete UI recovery unit.')
        optional_declared = optional_declared | {'ui-shares.tar.gz'}
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
    verify_only: bool = False,
) -> None:
    file_count = 0
    total_bytes = 0
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        validated: list[tuple[tarfile.TarInfo, PurePosixPath]] = []
        seen_paths: set[PurePosixPath] = set()
        expected_tree: dict[str, str] = {}
        for member in members:
            if "\\" in member.name or ":" in member.name:
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
            expected_tree[member_path.as_posix()] = "file" if member.isfile() else "directory"
            for parent in member_path.parents:
                if parent != PurePosixPath("."):
                    expected_tree.setdefault(parent.as_posix(), "directory")
            if member.isfile():
                file_count += 1
                total_bytes += member.size
        if (
            file_count != expected_file_count
            or total_bytes != expected_total_bytes
        ):
            raise ValueError("Upload archive does not match the backup manifest.")

        if verify_only and (not destination.is_dir() or _plain_tree(destination) != expected_tree):
            raise ValueError(f"Staged upload tree differs from verified archive: {destination.name}")

        for member, member_path in validated:
            target = destination.joinpath(*member_path.parts)
            if member.isdir():
                if not verify_only:
                    target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            if not verify_only:
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"Could not extract upload archive member: {member.name}")
            if verify_only:
                digest = hashlib.sha256()
                with extracted:
                    for block in iter(lambda: extracted.read(1024 * 1024), b""):
                        digest.update(block)
                if _sha256(target) != digest.hexdigest():
                    raise ValueError(f"Staged upload differs from verified archive: {target}")
            else:
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
    unresolved_target = Path(target_raw).expanduser().absolute()
    target = unresolved_target.parent.resolve() / unresolved_target.name
    if not source.is_dir():
        raise ValueError(f"Restore source is not a directory: {source}")
    if os.path.lexists(target):
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

    databases = ["rag.sqlite3", "agent.sqlite3"]
    if includes_ui:
        databases.append("ui.sqlite3")
    resume_raw = os.environ.get("RESTORE_RESUME_PARTIAL", "").strip()
    if resume_raw:
        partial_target = Path(resume_raw).expanduser().absolute()
        if (partial_target.parent.resolve() != target.parent
                or not re.fullmatch(re.escape(f".{target.name}.") + r"[0-9a-f]{32}\.partial", partial_target.name)
                or not partial_target.is_dir()):
            raise ValueError("RESTORE_RESUME_PARTIAL must name an existing exact staging sibling for RESTORE_TARGET")
        tree = _plain_tree(partial_target)
        top = {name: kind for name, kind in tree.items() if "/" not in name}
        expected_top = {name: "file" for name in databases} | {"uploads": "directory"}
        if includes_ui:
            expected_top["ui-uploads"] = "directory"
        if 'ui-shares.tar.gz' in data_artifacts:
            expected_top["ui-shares"] = "directory"
        if top != expected_top:
            raise ValueError("Staged restore tree does not match the verified recovery unit")
    else:
        partial_target = target.with_name(f".{target.name}.{uuid4().hex}.partial")
        partial_target.mkdir(mode=0o700, parents=True)
    uploads_target = partial_target / "uploads"
    if not resume_raw:
        uploads_target.mkdir(mode=0o700)
    for name in databases:
        destination = partial_target / name
        if resume_raw:
            if _sha256(destination) != _sha256(source / name):
                raise ValueError(f"Staged database differs from verified backup: {name}")
        else:
            shutil.copyfile(source / name, destination)
        _verify_sqlite(destination)
    _extract_uploads(
        source / "uploads.tar.gz",
        uploads_target,
        expected_file_count=expected_file_count,
        expected_total_bytes=expected_total_bytes,
        verify_only=bool(resume_raw),
    )
    if includes_ui:
        ui_uploads_target = partial_target / "ui-uploads"
        if not resume_raw:
            ui_uploads_target.mkdir(mode=0o700)
        _extract_uploads(
            source / "ui-uploads.tar.gz",
            ui_uploads_target,
            expected_file_count=ui_expected_file_count,
            expected_total_bytes=ui_expected_total_bytes,
            verify_only=bool(resume_raw),
        )
    if 'ui-shares.tar.gz' in data_artifacts:
        count, size = manifest.get('uiShareFileCount'), manifest.get('uiShareTotalBytes')
        if type(count) is not int or type(size) is not int or count < 0 or size < 0:
            raise ValueError('Invalid snapshot archive counts.')
        shares_target = partial_target / 'ui-shares'
        if not resume_raw:
            shares_target.mkdir(mode=0o700)
        _extract_uploads(source / 'ui-shares.tar.gz', shares_target,
                         expected_file_count=count, expected_total_bytes=size, verify_only=bool(resume_raw))
    # Errors leave only a hidden `.partial` directory, never a complete-looking restore.
    return _publish_partial(partial_target, target)


def main() -> int:
    try:
        print(f"Isolated restore ready at {restore_backup()}")
    except (OSError, sqlite3.Error, tarfile.TarError, ValueError, RuntimeError) as error:
        print(f"Restore failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
