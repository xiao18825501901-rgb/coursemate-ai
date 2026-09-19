"""Recovery-unit tests for a deployment that also runs the refreshed UI shell.

The refreshed shell keeps its own SQLite database and its own attachment tree, so
the existing RAG + Agent + uploads backup unit is not sufficient on its own. These
tests prove the extended unit round-trips both, and that a shell database which
disappears is a hard failure rather than a silently incomplete backup.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
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


def _fixture(tmp_path: Path) -> dict[str, Path]:
    rag_database = tmp_path / "rag.sqlite3"
    agent_database = tmp_path / "agent.sqlite3"
    uploads = tmp_path / "uploads"
    ui_data = tmp_path / "ui-extension"
    uploads.joinpath("owner", "course").mkdir(parents=True)
    uploads.joinpath("owner", "course", "notes.md").write_text("shared", encoding="utf-8")
    ui_data.joinpath("uploads").mkdir(parents=True)
    ui_data.joinpath("uploads", "file_abc.md").write_text("private", encoding="utf-8")
    _database(rag_database, "courses", "cs3481")
    _database(agent_database, "tasks", "review clustering")
    _database(ui_data / "ui.sqlite3", "cmui_comments", "第一篇评论")
    return {
        "rag": rag_database,
        "agent": agent_database,
        "uploads": uploads,
        "ui_data": ui_data,
        "backups": tmp_path / "backups",
        "target": tmp_path / "restored",
    }


def test_backup_and_restore_include_the_refreshed_shell_unit(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    backup = _run(
        BACKUP_SCRIPT,
        {
            "RAG_DATABASE_PATH": str(paths["rag"]),
            "RAG_UPLOAD_DIR": str(paths["uploads"]),
            "AGENT_DATABASE_PATH": str(paths["agent"]),
            "CMUI_DATA_DIR": str(paths["ui_data"]),
            "BACKUP_ROOT": str(paths["backups"]),
        },
    )
    assert backup.returncode == 0, backup.stderr
    backup_directory = Path(backup.stdout.strip().splitlines()[-1])
    assert sorted(path.name for path in backup_directory.iterdir()) == [
        "SHA256SUMS",
        "agent.sqlite3",
        "manifest.json",
        "rag.sqlite3",
        "sqlite-check.txt",
        "ui-uploads.tar.gz",
        "ui.sqlite3",
        "uploads.tar.gz",
    ]
    manifest = json.loads((backup_directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["uiDatabase"] == "ui.sqlite3"
    assert manifest["artifacts"]["uiUploads"] == "ui-uploads.tar.gz"
    assert manifest["uiUploadFileCount"] == 1
    assert manifest["uiUploadTotalBytes"] == len("private")
    check = (backup_directory / "sqlite-check.txt").read_text(encoding="utf-8")
    assert "ui.sqlite3 integrity_check=ok" in check

    restore = _run(
        RESTORE_SCRIPT,
        {
            "RESTORE_SOURCE": str(backup_directory),
            "RESTORE_TARGET": str(paths["target"]),
        },
    )
    assert restore.returncode == 0, restore.stderr
    restored = paths["target"]
    with closing(sqlite3.connect(restored / "ui.sqlite3")) as connection:
        assert connection.execute("SELECT value FROM cmui_comments").fetchone() == ("第一篇评论",)
    assert (restored / "ui-uploads" / "file_abc.md").read_text(encoding="utf-8") == "private"


def test_backup_without_the_extension_still_produces_the_original_unit(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    backup = _run(
        BACKUP_SCRIPT,
        {
            "RAG_DATABASE_PATH": str(paths["rag"]),
            "RAG_UPLOAD_DIR": str(paths["uploads"]),
            "AGENT_DATABASE_PATH": str(paths["agent"]),
            "BACKUP_ROOT": str(paths["backups"]),
        },
    )
    assert backup.returncode == 0, backup.stderr
    backup_directory = Path(backup.stdout.strip().splitlines()[-1])
    assert not list(backup_directory.glob("ui*"))

    restore = _run(
        RESTORE_SCRIPT,
        {
            "RESTORE_SOURCE": str(backup_directory),
            "RESTORE_TARGET": str(paths["target"]),
        },
    )
    assert restore.returncode == 0, restore.stderr
    assert not (paths["target"] / "ui.sqlite3").exists()


def test_backup_refuses_a_declared_shell_directory_without_its_database(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    (paths["ui_data"] / "ui.sqlite3").unlink()
    backup = _run(
        BACKUP_SCRIPT,
        {
            "RAG_DATABASE_PATH": str(paths["rag"]),
            "RAG_UPLOAD_DIR": str(paths["uploads"]),
            "AGENT_DATABASE_PATH": str(paths["agent"]),
            "CMUI_DATA_DIR": str(paths["ui_data"]),
            "BACKUP_ROOT": str(paths["backups"]),
        },
    )
    assert backup.returncode != 0
    assert "ui.sqlite3" in backup.stderr
    assert not list(paths["backups"].glob("coursemate-v2-*"))


def test_restore_rejects_a_partially_declared_shell_unit(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    backup = _run(
        BACKUP_SCRIPT,
        {
            "RAG_DATABASE_PATH": str(paths["rag"]),
            "RAG_UPLOAD_DIR": str(paths["uploads"]),
            "AGENT_DATABASE_PATH": str(paths["agent"]),
            "CMUI_DATA_DIR": str(paths["ui_data"]),
            "BACKUP_ROOT": str(paths["backups"]),
        },
    )
    assert backup.returncode == 0, backup.stderr
    backup_directory = Path(backup.stdout.strip().splitlines()[-1])
    manifest_path = backup_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"].pop("uiUploads")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # Keep the checksum manifest self-consistent so only the declaration is wrong.
    sums = backup_directory / "SHA256SUMS"
    import hashlib

    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    sums.write_text(
        "\n".join(
            f"{digest}  manifest.json" if line.endswith("  manifest.json") else line
            for line in sums.read_text(encoding="ascii").splitlines()
        )
        + "\n",
        encoding="ascii",
    )

    restore = _run(
        RESTORE_SCRIPT,
        {
            "RESTORE_SOURCE": str(backup_directory),
            "RESTORE_TARGET": str(paths["target"]),
        },
    )
    assert restore.returncode != 0
    assert "refreshed-shell" in restore.stderr
    assert not paths["target"].exists()
