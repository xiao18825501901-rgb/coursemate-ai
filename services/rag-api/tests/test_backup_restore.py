from __future__ import annotations

import hashlib
import io
import os
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[3]
BACKUP_SCRIPT = REPOSITORY_ROOT / "ops" / "backup_v2.py"
RESTORE_SCRIPT = REPOSITORY_ROOT / "ops" / "restore_v2.py"


def _database(path: Path, table: str, value: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute(f"CREATE TABLE {table} (value TEXT NOT NULL)")
    connection.execute(f"INSERT INTO {table} (value) VALUES (?)", (value,))
    connection.commit()
    connection.close()


def _run(script: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script)],
        check=False,
        capture_output=True,
        env={**os.environ, **environment},
        text=True,
    )


def _replace_checksum(backup_directory: Path, filename: str) -> None:
    artifact = backup_directory / filename
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    checksum_path = backup_directory / "SHA256SUMS"
    lines = checksum_path.read_text(encoding="ascii").splitlines()
    checksum_path.write_text(
        "\n".join(
            f"{digest}  {filename}" if line.endswith(f"  {filename}") else line
            for line in lines
        )
        + "\n",
        encoding="ascii",
    )


def test_backup_and_restore_preserve_both_databases_and_uploads(tmp_path: Path) -> None:
    rag_database = tmp_path / "rag.sqlite3"
    agent_database = tmp_path / "agent.sqlite3"
    uploads = tmp_path / "uploads"
    backup_root = tmp_path / "backups"
    restore_target = tmp_path / "restored"
    uploads.joinpath("owner", "course").mkdir(parents=True)
    uploads.joinpath("owner", "course", "notes.md").write_text(
        "private course evidence", encoding="utf-8"
    )
    _database(rag_database, "courses", "cs3481")
    _database(agent_database, "tasks", "review clustering")

    backup = _run(
        BACKUP_SCRIPT,
        {
            "RAG_DATABASE_PATH": str(rag_database),
            "RAG_UPLOAD_DIR": str(uploads),
            "AGENT_DATABASE_PATH": str(agent_database),
            "BACKUP_ROOT": str(backup_root),
        },
    )

    assert backup.returncode == 0, backup.stderr
    backup_directory = Path(backup.stdout.strip().splitlines()[-1])
    assert backup_directory.name.startswith("coursemate-v2-")
    assert sorted(path.name for path in backup_directory.iterdir()) == [
        "SHA256SUMS",
        "agent.sqlite3",
        "manifest.json",
        "rag.sqlite3",
        "sqlite-check.txt",
        "uploads.tar.gz",
    ]

    restore = _run(
        RESTORE_SCRIPT,
        {
            "RESTORE_SOURCE": str(backup_directory),
            "RESTORE_TARGET": str(restore_target),
        },
    )

    assert restore.returncode == 0, restore.stderr
    assert sqlite3.connect(restore_target / "rag.sqlite3").execute(
        "SELECT value FROM courses"
    ).fetchone() == ("cs3481",)
    assert sqlite3.connect(restore_target / "agent.sqlite3").execute(
        "SELECT value FROM tasks"
    ).fetchone() == ("review clustering",)
    assert restore_target.joinpath("uploads", "owner", "course", "notes.md").read_text(
        encoding="utf-8"
    ) == "private course evidence"


def test_restore_rejects_tampered_agent_snapshot_before_creating_target(
    tmp_path: Path,
) -> None:
    rag_database = tmp_path / "rag.sqlite3"
    agent_database = tmp_path / "agent.sqlite3"
    uploads = tmp_path / "uploads"
    backup_root = tmp_path / "backups"
    restore_target = tmp_path / "restored"
    uploads.mkdir()
    _database(rag_database, "courses", "cs3481")
    _database(agent_database, "tasks", "private task")
    backup = _run(
        BACKUP_SCRIPT,
        {
            "RAG_DATABASE_PATH": str(rag_database),
            "RAG_UPLOAD_DIR": str(uploads),
            "AGENT_DATABASE_PATH": str(agent_database),
            "BACKUP_ROOT": str(backup_root),
        },
    )
    assert backup.returncode == 0, backup.stderr
    backup_directory = Path(backup.stdout.strip().splitlines()[-1])
    backup_directory.joinpath("agent.sqlite3").write_bytes(b"tampered")

    restore = _run(
        RESTORE_SCRIPT,
        {
            "RESTORE_SOURCE": str(backup_directory),
            "RESTORE_TARGET": str(restore_target),
        },
    )

    assert restore.returncode != 0
    assert "checksum" in restore.stderr.casefold()
    assert not restore_target.exists()


def test_backup_rejects_destination_inside_private_upload_tree(tmp_path: Path) -> None:
    rag_database = tmp_path / "rag.sqlite3"
    agent_database = tmp_path / "agent.sqlite3"
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    _database(rag_database, "courses", "cs3481")
    _database(agent_database, "tasks", "private task")

    backup = _run(
        BACKUP_SCRIPT,
        {
            "RAG_DATABASE_PATH": str(rag_database),
            "RAG_UPLOAD_DIR": str(uploads),
            "AGENT_DATABASE_PATH": str(agent_database),
            "BACKUP_ROOT": str(uploads / "backups"),
        },
    )

    assert backup.returncode != 0
    assert "outside" in backup.stderr.casefold()
    assert not uploads.joinpath("backups").exists()


def test_restore_rejects_target_inside_backup_source(tmp_path: Path) -> None:
    rag_database = tmp_path / "rag.sqlite3"
    agent_database = tmp_path / "agent.sqlite3"
    uploads = tmp_path / "uploads"
    backup_root = tmp_path / "backups"
    uploads.mkdir()
    _database(rag_database, "courses", "cs3481")
    _database(agent_database, "tasks", "private task")
    backup = _run(
        BACKUP_SCRIPT,
        {
            "RAG_DATABASE_PATH": str(rag_database),
            "RAG_UPLOAD_DIR": str(uploads),
            "AGENT_DATABASE_PATH": str(agent_database),
            "BACKUP_ROOT": str(backup_root),
        },
    )
    assert backup.returncode == 0, backup.stderr
    backup_directory = Path(backup.stdout.strip().splitlines()[-1])
    nested_target = backup_directory / "restored"

    restore = _run(
        RESTORE_SCRIPT,
        {
            "RESTORE_SOURCE": str(backup_directory),
            "RESTORE_TARGET": str(nested_target),
        },
    )

    assert restore.returncode != 0
    assert "outside" in restore.stderr.casefold()
    assert not nested_target.exists()


def test_restore_rejects_windows_style_archive_traversal(tmp_path: Path) -> None:
    rag_database = tmp_path / "rag.sqlite3"
    agent_database = tmp_path / "agent.sqlite3"
    uploads = tmp_path / "uploads"
    backup_root = tmp_path / "backups"
    restore_target = tmp_path / "restored"
    uploads.mkdir()
    _database(rag_database, "courses", "cs3481")
    _database(agent_database, "tasks", "private task")
    backup = _run(
        BACKUP_SCRIPT,
        {
            "RAG_DATABASE_PATH": str(rag_database),
            "RAG_UPLOAD_DIR": str(uploads),
            "AGENT_DATABASE_PATH": str(agent_database),
            "BACKUP_ROOT": str(backup_root),
        },
    )
    assert backup.returncode == 0, backup.stderr
    backup_directory = Path(backup.stdout.strip().splitlines()[-1])
    archive_path = backup_directory / "uploads.tar.gz"
    payload = b"escaped"
    with tarfile.open(archive_path, "w:gz") as archive:
        member = tarfile.TarInfo("..\\..\\..\\escaped.txt")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    _replace_checksum(backup_directory, "uploads.tar.gz")

    restore = _run(
        RESTORE_SCRIPT,
        {
            "RESTORE_SOURCE": str(backup_directory),
            "RESTORE_TARGET": str(restore_target),
        },
    )

    assert restore.returncode != 0
    assert "unsafe" in restore.stderr.casefold()
    assert not tmp_path.joinpath("escaped.txt").exists()
