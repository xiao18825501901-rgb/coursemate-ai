"""Self-contained DB fixtures for the Jev tests.

The full V3 migration suite (``Database.initialize``) is not used here so the Jev
layer is verifiable in isolation: only the ``jev_decision_receipts`` table (from
migration 028) is created, plus — for the retrieval wiring test — the minimum
``courses`` / ``learning_workspaces`` shape ``V3DomainAdapter._retrieve`` touches.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.db import Database

_MIGRATIONS = Path(__file__).parent.parent / "migrations"

COURSES_SQL = """
CREATE TABLE IF NOT EXISTS courses (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    owner_user_id TEXT,
    course_type TEXT NOT NULL DEFAULT 'official',
    visibility TEXT NOT NULL DEFAULT 'public',
    preferred_language TEXT NOT NULL DEFAULT 'auto',
    publication_status TEXT NOT NULL DEFAULT 'private',
    published_at TEXT,
    display_type TEXT,
    requires_student_verification INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
"""

WORKSPACES_SQL = """
CREATE TABLE IF NOT EXISTS learning_workspaces (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id),
    private_course_id TEXT NOT NULL UNIQUE REFERENCES courses(id),
    revision INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'AUTO',
    layout_json TEXT NOT NULL DEFAULT '{}',
    cursor_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
"""


def make_jev_database(tmp_path: Path, *, with_courses: bool = False) -> Database:
    settings = Settings(
        database_path=tmp_path / "jev.sqlite3",
        upload_dir=tmp_path / "jev-uploads",
        app_env="test",
        v3_enabled=True,
        rag_provider_mode="deterministic",
    )
    database = Database(settings)
    database.upload_dir.mkdir(parents=True, exist_ok=True)
    jev_sql = (_MIGRATIONS / "028_jev_decision_receipts.sql").read_text(encoding="utf-8")
    with database.connect() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        )
        connection.executescript(jev_sql)
        if with_courses:
            connection.executescript(COURSES_SQL + WORKSPACES_SQL)
    return database
