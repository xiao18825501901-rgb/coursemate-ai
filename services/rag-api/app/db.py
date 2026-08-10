import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from app.config import Settings

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS courses (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    media_type TEXT NOT NULL,
    extension TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    status TEXT NOT NULL
        CHECK (status IN ('pending', 'processing', 'ready', 'failed', 'unsupported')),
    chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (course_id, sha256)
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    processed_chunks INTEGER NOT NULL DEFAULT 0 CHECK (processed_chunks >= 0),
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    content TEXT NOT NULL CHECK (length(trim(content)) > 0),
    locator_type TEXT NOT NULL,
    locator_value TEXT NOT NULL,
    section TEXT,
    embedding TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (document_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_documents_course ON documents(course_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chunks_course ON chunks(course_id, document_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_jobs_document ON ingestion_jobs(document_id, created_at);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    chunk_id UNINDEXED,
    course_id UNINDEXED,
    tokenize = 'unicode61'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, content, chunk_id, course_id)
    VALUES (new.rowid, new.content, new.id, new.course_id);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    DELETE FROM chunks_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE OF content, id, course_id ON chunks BEGIN
    DELETE FROM chunks_fts WHERE rowid = old.rowid;
    INSERT INTO chunks_fts(rowid, content, chunk_id, course_id)
    VALUES (new.rowid, new.content, new.id, new.course_id);
END;
"""


class Database:
    """Own SQLite connections and initialize the RAG schema."""

    def __init__(self, settings: Settings) -> None:
        self.path = settings.database_path
        self.upload_dir = settings.upload_dir

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA_SQL)
