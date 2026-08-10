from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.db import Database


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
    }.issubset(objects)
    assert settings.upload_dir.is_dir()


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
