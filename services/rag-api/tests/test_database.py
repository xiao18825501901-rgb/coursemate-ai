from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.db import Database
from app.main import create_app


def make_settings(
    tmp_path: Path,
    *,
    chunk_size: int = 1_200,
    chunk_overlap: int = 200,
) -> Settings:
    return Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


def test_settings_require_overlap_smaller_than_chunk_size(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="chunk_overlap must be smaller"):
        make_settings(tmp_path, chunk_size=400, chunk_overlap=400)


def test_application_fails_closed_without_clerk_configuration(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="CLERK_SECRET_KEY"):
        create_app(settings=make_settings(tmp_path))


def test_auth_test_adapter_is_rejected_outside_test_deterministic_mode(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        auth_test_user_id="e2e-user",
        app_env="production",
        rag_provider_mode="deterministic",
    )
    with pytest.raises(RuntimeError, match="only in test deterministic mode"):
        create_app(settings=settings)


def test_database_initializes_relational_and_fts_schema(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    database = Database(settings)

    database.initialize()

    with database.connect() as connection:
        objects = {
            (row["type"], row["name"])
            for row in connection.execute(
                "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            )
        }
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]

    assert foreign_keys == 1
    assert {
        ("table", "courses"),
        ("table", "documents"),
        ("table", "ingestion_jobs"),
        ("table", "chunks"),
        ("table", "chunks_fts"),
        ("table", "conversations"),
        ("table", "messages"),
        ("table", "schema_migrations"),
        ("table", "rate_limit_windows"),
    }.issubset(objects)
    assert settings.upload_dir.is_dir()


def test_readiness_is_read_only_when_database_disappears(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    database = Database(settings)
    database.initialize()
    assert database.is_ready() is True

    settings.database_path.unlink()

    assert database.is_ready() is False
    assert settings.database_path.exists() is False


def test_readiness_requires_upload_storage_and_latest_migration(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    database = Database(settings)
    database.initialize()

    settings.upload_dir.rmdir()
    assert database.is_ready() is False

    settings.upload_dir.mkdir()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 10")
    assert database.is_ready() is False


def test_legacy_conversations_are_quarantined_and_migration_is_repeatable(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    database = Database(settings)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3

    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            "CREATE TABLE courses (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
            "description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '')"
        )
        connection.execute(
            "CREATE TABLE conversations (id TEXT PRIMARY KEY, course_id TEXT NOT NULL, "
            "created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '')"
        )
        connection.execute("INSERT INTO courses VALUES ('cs3481', 'CS3481', '', '')")
        connection.execute(
            "INSERT INTO conversations VALUES ('legacy-conv', 'cs3481', '', '')"
        )

    database.initialize()
    database.initialize()
    with database.connect() as connection:
        conversation = connection.execute(
            "SELECT owner_user_id, title, preferred_language "
            "FROM conversations WHERE id = 'legacy-conv'"
        ).fetchone()
        migrations = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        message_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(messages)")
        }
        course = connection.execute(
            "SELECT owner_user_id, course_type, visibility, updated_at "
            "FROM courses WHERE id = 'cs3481'"
        ).fetchone()

    assert tuple(conversation) == ("legacy_orphaned", "New Conversation", "auto")
    assert migrations == 10
    assert tuple(course[:3]) == (None, "official", "public")
    assert course["updated_at"]
    assert "metadata_json" in message_columns

    with database.connect() as connection:
        chunk_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(chunks)")
        }
        versions = [
            row[0] for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]

    assert {"metadata_json", "parent_key"}.issubset(chunk_columns)
    assert versions == list(range(1, 11))


def test_database_repairs_empty_course_timestamp_after_migration(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    database = Database(settings)
    database.initialize()

    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses (id, name, description) VALUES ('legacy', 'Legacy', '')"
        )
        connection.execute("UPDATE courses SET updated_at = '' WHERE id = 'legacy'")

    database.initialize()

    with database.connect() as connection:
        updated_at = connection.execute(
            "SELECT updated_at FROM courses WHERE id = 'legacy'"
        ).fetchone()["updated_at"]

    assert updated_at


def test_storage_quota_migration_backfills_existing_file_size(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    database = Database(settings)
    database.initialize()
    stored = settings.upload_dir / "legacy.md"
    stored.write_bytes(b"legacy bytes")
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO courses (id, name, description)
            VALUES ('legacy-storage', 'Legacy storage', '')
            """
        )
        connection.execute(
            """
            INSERT INTO documents (
                id, course_id, filename, stored_path, media_type, extension, sha256,
                byte_size, status
            ) VALUES (?, 'legacy-storage', 'legacy.md', ?, 'text/markdown', '.md', ?, 0, 'ready')
            """,
            ("legacy-document", str(stored), "a" * 64),
        )

    database.initialize()

    with database.connect() as connection:
        byte_size = connection.execute(
            "SELECT byte_size FROM documents WHERE id = 'legacy-document'"
        ).fetchone()["byte_size"]
        version = connection.execute(
            "SELECT name FROM schema_migrations WHERE version = 8"
        ).fetchone()["name"]

    assert byte_size == len(b"legacy bytes")
    assert version == "user course storage quotas"


def test_v2_conversation_migration_preserves_messages_and_derives_title(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    database = Database(settings)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3

    with sqlite3.connect(settings.database_path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE courses (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                citations_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO courses VALUES ('cs3481', 'CS3481', '', '');
            INSERT INTO conversations VALUES ('conv-1', 'user-a', 'cs3481', '', '');
            INSERT INTO messages VALUES (
                'msg-1', 'conv-1', 'user',
                'DBSCAN 中 core point 到底是什么？请一步一步解释。', '[]', ''
            );
            """
        )

    database.initialize()
    database.initialize()

    with database.connect() as connection:
        conversation = connection.execute(
            "SELECT title, preferred_language FROM conversations WHERE id = 'conv-1'"
        ).fetchone()
        message = connection.execute(
            "SELECT metadata_json FROM messages WHERE id = 'msg-1'"
        ).fetchone()
        versions = [
            row[0] for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]

    assert conversation["title"].startswith("DBSCAN 中 core point")
    assert conversation["preferred_language"] == "auto"
    assert message["metadata_json"] == "{}"
    assert versions == list(range(1, 11))


def test_v3_migrations_require_explicit_feature_enablement(tmp_path: Path) -> None:
    v2_settings = make_settings(tmp_path)
    v2_database = Database(v2_settings)

    v2_database.initialize()

    with v2_database.connect() as connection:
        v2_versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        v2_workspace_table = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'learning_workspaces'"
        ).fetchone()

    assert v2_versions == list(range(1, 11))
    assert v2_workspace_table is None

    v3_database = Database(
        Settings(
            database_path=v2_settings.database_path,
            upload_dir=v2_settings.upload_dir,
            v3_enabled=True,
        )
    )
    v3_database.initialize()

    with v3_database.connect() as connection:
        v3_versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        v3_workspace_table = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'learning_workspaces'"
        ).fetchone()

    assert v3_versions == list(range(1, 14))
    assert v3_workspace_table is not None


def test_v3_readiness_requires_latest_v3_migration(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        v3_enabled=True,
    )
    database = Database(settings)
    database.initialize()

    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 13")

    assert database.is_ready() is False


def test_deployment_path_environment_aliases_are_honored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_DATABASE_PATH", str(tmp_path / "deployed.sqlite3"))
    monkeypatch.setenv("RAG_UPLOAD_DIR", str(tmp_path / "deployed-uploads"))

    settings = Settings(_env_file=None)

    assert settings.database_path == tmp_path / "deployed.sqlite3"
    assert settings.upload_dir == tmp_path / "deployed-uploads"


def test_chunk_fts_is_synchronized_and_document_delete_cascades(tmp_path: Path) -> None:
    database = Database(make_settings(tmp_path))
    database.initialize()

    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses (id, name, description) VALUES (?, ?, ?)",
            ("cs3481", "CS3481", "Computer graphics"),
        )
        connection.execute(
            """
            INSERT INTO documents (
                id, course_id, filename, stored_path, media_type, extension, sha256, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc-1",
                "cs3481",
                "lighting.md",
                "uploads/lighting.md",
                "text/markdown",
                ".md",
                "a" * 64,
                "ready",
            ),
        )
        connection.execute(
            """
            INSERT INTO chunks (
                id, document_id, course_id, ordinal, content, locator_type,
                locator_value, section, embedding
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "chunk-1",
                "doc-1",
                "cs3481",
                0,
                "Phong lighting has ambient diffuse and specular terms.",
                "section",
                "Lighting",
                "Lighting",
                "[1.0,0.0]",
            ),
        )
        hits = connection.execute(
            """
            SELECT chunk_id FROM chunks_fts
            WHERE chunks_fts MATCH ? AND course_id = ?
            """,
            ("Phong", "cs3481"),
        ).fetchall()
        connection.execute("DELETE FROM documents WHERE id = ?", ("doc-1",))
        remaining_chunks = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        remaining_fts = connection.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]

    assert [row["chunk_id"] for row in hits] == ["chunk-1"]
    assert remaining_chunks == 0
    assert remaining_fts == 0


def test_course_activity_tracks_documents_conversations_and_profiles(tmp_path: Path) -> None:
    database = Database(make_settings(tmp_path))
    database.initialize()

    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses (id, name, description, updated_at) VALUES (?, ?, ?, ?)",
            ("activity-course", "Activity", "", "2000-01-01T00:00:00.000Z"),
        )
        connection.execute(
            """
            INSERT INTO documents (
                id, course_id, filename, stored_path, media_type, extension, sha256, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "activity-doc",
                "activity-course",
                "notes.md",
                "uploads/notes.md",
                "text/markdown",
                ".md",
                "c" * 64,
                "pending",
            ),
        )
        after_document = connection.execute(
            "SELECT updated_at FROM courses WHERE id = 'activity-course'"
        ).fetchone()["updated_at"]

        connection.execute(
            "UPDATE courses SET updated_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00.000Z", "activity-course"),
        )
        connection.execute(
            """
            INSERT INTO conversations (id, owner_user_id, course_id, title)
            VALUES (?, ?, ?, ?)
            """,
            ("activity-conversation", "user-a", "activity-course", "Activity chat"),
        )
        after_conversation = connection.execute(
            "SELECT updated_at FROM courses WHERE id = 'activity-course'"
        ).fetchone()["updated_at"]

        connection.execute(
            "UPDATE courses SET updated_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00.000Z", "activity-course"),
        )
        connection.execute(
            """
            INSERT INTO course_teaching_profiles (
                id, course_id, version, created_by_user_id, language, student_level,
                learning_goal, teaching_styles_json, answer_depth, example_preference,
                exercise_policy, exam_orientation, citation_preference, math_detail_level,
                terminology_style, custom_requirements, generated_prompt
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "activity-profile", "activity-course", 1, "user-a", "auto", "beginner",
                "Learn", '["step-by-step"]', "balanced", "when-helpful", "offer", 0,
                "standard", "standard", "plain", "", "Teach step by step",
            ),
        )
        after_profile = connection.execute(
            "SELECT updated_at FROM courses WHERE id = 'activity-course'"
        ).fetchone()["updated_at"]

    assert after_document != "2000-01-01T00:00:00.000Z"
    assert after_conversation != "2000-01-01T00:00:00.000Z"
    assert after_profile != "2000-01-01T00:00:00.000Z"
