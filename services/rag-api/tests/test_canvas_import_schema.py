"""Schema for the Canvas private import: connections, jobs and per-file records.

Migration 031 has to hold three properties the pack states as requirements, and they are
checked here as schema facts rather than as intentions:

* **no Canvas token can be stored** — a job references a connection and the credential lives
  in the encrypted store, so a database dump cannot contain a token;
* **the per-file identity is `origin + course_id + file_id`**, never the filename, so two
  files with the same name are two rows;
* **the same frozen request is idempotent** — a UNIQUE key on (connection, fingerprint)
  refuses a second job for the same selection;
* the status vocabulary matches `app/canvas/job.py` exactly, so the code and the CHECK
  constraint cannot drift apart.
"""

from __future__ import annotations

import json
import sqlite3

from app.canvas.job import ALL_STATES
from app.config import Settings
from app.db import Database


def migrated(tmp_path) -> Database:
    database = Database(
        Settings(
            database_path=tmp_path / "rag.sqlite3",
            upload_dir=tmp_path / "uploads",
            app_env="test",
            v3_enabled=True,
            rag_provider_mode="deterministic",
            ui_web_dir=tmp_path / "no-web-build",
        )
    )
    database.initialize()
    return database


def table_sql(connection: sqlite3.Connection, table: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    assert row is not None, f"{table} does not exist"
    return str(row[0])


def columns(connection: sqlite3.Connection, table: str) -> dict[str, tuple[str, int]]:
    return {row[1]: (row[2], row[3]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def test_the_migration_applies_and_records_its_version(tmp_path) -> None:
    database = migrated(tmp_path)
    with database.connect() as connection:
        versions = [
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        present = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert 31 in versions
    assert versions == sorted(versions)
    assert {"canvas_connections", "canvas_import_jobs", "canvas_import_files"} <= present


def test_replaying_the_migration_set_is_idempotent(tmp_path) -> None:
    database = migrated(tmp_path)
    database.initialize()
    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version=31"
        ).fetchone()[0]
    assert count == 1


def test_no_column_can_hold_a_canvas_token(tmp_path) -> None:
    """The whole point of storing `connection_id` only."""
    database = migrated(tmp_path)
    with database.connect() as connection:
        for table in ("canvas_connections", "canvas_import_jobs", "canvas_import_files"):
            names = {name.lower() for name in columns(connection, table)}
            for forbidden in ("access_token", "refresh_token", "token", "pat", "secret"):
                assert forbidden not in names, f"{table} has a {forbidden} column"


def test_job_status_check_matches_the_code_vocabulary(tmp_path) -> None:
    database = migrated(tmp_path)
    with database.connect() as connection:
        sql = table_sql(connection, "canvas_import_jobs")
    for state in ALL_STATES:
        assert f"'{state}'" in sql, f"{state} missing from the status CHECK"
    assert "DEFAULT 'DISCOVERING'" in sql


def test_file_status_check_covers_every_terminal_state(tmp_path) -> None:
    database = migrated(tmp_path)
    with database.connect() as connection:
        sql = table_sql(connection, "canvas_import_files")
    for status in (
        "PENDING",
        "DOWNLOADED",
        "DOWNLOAD_ONLY",
        "INDEXED",
        "SKIPPED_IDENTICAL",
        "WARNING",
        "FAILED",
        "CANCELLED",
    ):
        assert f"'{status}'" in sql


def test_the_file_key_is_the_external_identity_not_the_name(tmp_path) -> None:
    database = migrated(tmp_path)
    with database.connect() as connection:
        sql = table_sql(connection, "canvas_import_files")
        assert "UNIQUE(job_id, origin, source_course_id, source_file_id)" in sql
        assert "UNIQUE(job_id, display_name)" not in sql


def test_the_same_frozen_selection_cannot_create_two_jobs(tmp_path) -> None:
    database = migrated(tmp_path)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO canvas_connections(id, owner_user_id, institution_key, "
            "institution_origin, canvas_user_id) VALUES('c1','u1','cityu',?, '4242')",
            ("https://canvas.cityu.edu.hk",),
        )
        insert = (
            "INSERT INTO canvas_import_jobs(id, connection_id, owner_user_id, "
            "institution_origin, course_ids_json, selection_fingerprint) VALUES(?,?,?,?,?,?)"
        )
        payload = (
            "j1",
            "c1",
            "u1",
            "https://canvas.cityu.edu.hk",
            json.dumps(["560", "240"]),
            "fingerprint-1",
        )
        connection.execute(insert, payload)
        try:
            connection.execute(
                insert,
                (
                    "j2",
                    "c1",
                    "u1",
                    "https://canvas.cityu.edu.hk",
                    json.dumps(["240", "560"]),
                    "fingerprint-1",
                ),
            )
        except sqlite3.IntegrityError:
            return
        raise AssertionError("a duplicate frozen selection was accepted")


def test_a_job_cannot_reference_an_unknown_connection(tmp_path) -> None:
    database = migrated(tmp_path)
    with database.connect() as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            connection.execute(
                "INSERT INTO canvas_import_jobs(id, connection_id, owner_user_id, "
                "institution_origin, course_ids_json, selection_fingerprint) "
                "VALUES('j1','missing','u1',?,'[]','f')",
                ("https://canvas.cityu.edu.hk",),
            )
        except sqlite3.IntegrityError:
            return
        raise AssertionError("a job referencing an unknown connection was accepted")


def test_a_connection_cannot_be_deleted_while_a_job_uses_it(tmp_path) -> None:
    database = migrated(tmp_path)
    with database.connect() as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO canvas_connections(id, owner_user_id, institution_key, "
            "institution_origin, canvas_user_id) VALUES('c1','u1','cityu',?, '4242')",
            ("https://canvas.cityu.edu.hk",),
        )
        connection.execute(
            "INSERT INTO canvas_import_jobs(id, connection_id, owner_user_id, "
            "institution_origin, course_ids_json, selection_fingerprint) "
            "VALUES('j1','c1','u1',?, '[\"560\"]','f')",
            ("https://canvas.cityu.edu.hk",),
        )
        try:
            connection.execute("DELETE FROM canvas_connections WHERE id='c1'")
        except sqlite3.IntegrityError:
            return
        raise AssertionError("a connection in use by a job was deleted")


def test_saved_connection_flag_is_boolean_and_defaults_to_not_saved(tmp_path) -> None:
    database = migrated(tmp_path)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO canvas_connections(id, owner_user_id, institution_key, "
            "institution_origin, canvas_user_id) VALUES('c1','u1','cityu',?, '4242')",
            ("https://canvas.cityu.edu.hk",),
        )
        saved = connection.execute(
            "SELECT saved_for_reuse FROM canvas_connections WHERE id='c1'"
        ).fetchone()[0]
        assert saved == 0, "a connection must not be kept for reuse unless the user asked"
        try:
            connection.execute("UPDATE canvas_connections SET saved_for_reuse=2 WHERE id='c1'")
        except sqlite3.IntegrityError:
            return
        raise AssertionError("a non-boolean saved_for_reuse was accepted")
