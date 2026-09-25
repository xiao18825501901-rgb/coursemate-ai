from __future__ import annotations

import hashlib
import io
import json
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


def test_backup_and_restore_preserve_validated_nonsecret_release_descriptor(
    tmp_path: Path,
) -> None:
    rag_database = tmp_path / "rag.sqlite3"
    agent_database = tmp_path / "agent.sqlite3"
    uploads = tmp_path / "uploads"
    backup_root = tmp_path / "backups"
    restore_target = tmp_path / "restored"
    uploads.mkdir()
    _database(rag_database, "courses", "cs3481")
    _database(agent_database, "tasks", "review clustering")
    descriptor = tmp_path / "release-descriptor.json"
    descriptor.write_text(
        json.dumps(
            {
                "formatVersion": 1,
                "applicationReleaseSha": "a" * 40,
                "frontendDeployId": "deploy-coursejesus-20260925",
                "runtimeConfigVersion": "p5-20260925-v1",
                "model": "deepseek-flash",
                "modelEndpointIdentity": "api.deepseek.com",
                "jevDefinitionModes": {
                    "question.ambiguity.v1": "on",
                    "question.answer_agreement.v1": "on",
                    "question.mcq_distractor_quality.v1": "on",
                    "question.rule_violation_quality.v1": "on",
                },
                "templateVersions": {"questionAuthor": "question-author.v3"},
                "serviceUnitHashes": {
                    "coursemate-rag.service": "b" * 64,
                    "coursemate-agent.service": "c" * 64,
                    "Caddyfile": "d" * 64,
                },
                "credentialRecovery": "EXTERNAL_NOT_INCLUDED",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    backup = _run(
        BACKUP_SCRIPT,
        {
            "RAG_DATABASE_PATH": str(rag_database),
            "RAG_UPLOAD_DIR": str(uploads),
            "AGENT_DATABASE_PATH": str(agent_database),
            "BACKUP_ROOT": str(backup_root),
            "RECOVERY_CONFIG_MANIFEST": str(descriptor),
            "REQUIRE_RECOVERY_CONFIG": "true",
        },
    )
    assert backup.returncode == 0, backup.stderr
    backup_directory = Path(backup.stdout.strip().splitlines()[-1])
    manifest = json.loads((backup_directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["releaseConfig"] == "release-config.json"
    assert (backup_directory / "release-config.json").read_bytes() == descriptor.read_bytes()

    restore = _run(
        RESTORE_SCRIPT,
        {"RESTORE_SOURCE": str(backup_directory), "RESTORE_TARGET": str(restore_target)},
    )
    assert restore.returncode == 0, restore.stderr
    restored = json.loads((restore_target / "release-config.json").read_text(encoding="utf-8"))
    assert restored["credentialRecovery"] == "EXTERNAL_NOT_INCLUDED"
    assert restored["applicationReleaseSha"] == "a" * 40


def test_production_backup_refuses_missing_or_unexpected_release_descriptor(
    tmp_path: Path,
) -> None:
    rag_database = tmp_path / "rag.sqlite3"
    agent_database = tmp_path / "agent.sqlite3"
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    _database(rag_database, "courses", "cs3481")
    _database(agent_database, "tasks", "review clustering")
    environment = {
        "RAG_DATABASE_PATH": str(rag_database),
        "RAG_UPLOAD_DIR": str(uploads),
        "AGENT_DATABASE_PATH": str(agent_database),
        "BACKUP_ROOT": str(tmp_path / "backups"),
        "REQUIRE_RECOVERY_CONFIG": "true",
    }
    missing = _run(BACKUP_SCRIPT, environment)
    assert missing.returncode != 0
    assert "RECOVERY_CONFIG_MANIFEST" in missing.stderr

    descriptor = tmp_path / "unsafe-release-descriptor.json"
    descriptor.write_text(
        json.dumps({"formatVersion": 1, "apiKey": "must-not-enter-backup"}),
        encoding="utf-8",
    )
    unsafe = _run(
        BACKUP_SCRIPT,
        {**environment, "RECOVERY_CONFIG_MANIFEST": str(descriptor)},
    )
    assert unsafe.returncode != 0
    assert "keys" in unsafe.stderr.casefold()


def test_backup_from_wal_databases_has_no_unverified_sidecars(tmp_path: Path) -> None:
    rag_database = tmp_path / "rag.sqlite3"
    agent_database = tmp_path / "agent.sqlite3"
    uploads = tmp_path / "uploads"
    backup_root = tmp_path / "backups"
    uploads.mkdir()
    _database(rag_database, "courses", "cs3481")
    _database(agent_database, "tasks", "review clustering")
    for database in (rag_database, agent_database):
        connection = sqlite3.connect(database)
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        connection.close()

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
    assert not list(backup_directory.glob("*.sqlite3-wal"))
    assert not list(backup_directory.glob("*.sqlite3-shm"))
    for name, table in (("rag.sqlite3", "courses"), ("agent.sqlite3", "tasks")):
        snapshot = backup_directory / name
        connection = sqlite3.connect(
            f"file:{snapshot.as_posix()}?mode=ro&immutable=1", uri=True
        )
        try:
            assert connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone() == (
                1,
            )
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        finally:
            connection.close()


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


def test_backup_rejects_one_database_path_for_both_services(tmp_path: Path) -> None:
    shared_database = tmp_path / "shared.sqlite3"
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    _database(shared_database, "tasks", "ambiguous state")

    backup = _run(
        BACKUP_SCRIPT,
        {
            "RAG_DATABASE_PATH": str(shared_database),
            "RAG_UPLOAD_DIR": str(uploads),
            "AGENT_DATABASE_PATH": str(shared_database),
            "BACKUP_ROOT": str(tmp_path / "backups"),
        },
    )

    assert backup.returncode != 0
    assert "different" in backup.stderr.casefold()


def test_restore_rejects_upload_archive_that_disagrees_with_manifest(
    tmp_path: Path,
) -> None:
    rag_database = tmp_path / "rag.sqlite3"
    agent_database = tmp_path / "agent.sqlite3"
    uploads = tmp_path / "uploads"
    backup_root = tmp_path / "backups"
    restore_target = tmp_path / "restored"
    uploads.mkdir()
    uploads.joinpath("notes.md").write_text("expected", encoding="utf-8")
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
    payload = b"unexpected"
    with tarfile.open(archive_path, "w:gz") as archive:
        member = tarfile.TarInfo("different.md")
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
    assert "manifest" in restore.stderr.casefold()


def test_restore_rejects_duplicate_upload_archive_paths(tmp_path: Path) -> None:
    rag_database = tmp_path / "rag.sqlite3"
    agent_database = tmp_path / "agent.sqlite3"
    uploads = tmp_path / "uploads"
    backup_root = tmp_path / "backups"
    restore_target = tmp_path / "restored"
    uploads.mkdir()
    uploads.joinpath("notes.md").write_text("expected", encoding="utf-8")
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
    payload = b"expected"
    with tarfile.open(archive_path, "w:gz") as archive:
        for _ in range(2):
            member = tarfile.TarInfo("notes.md")
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
    assert "duplicate" in restore.stderr.casefold()
