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

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'New Conversation'
        CHECK (length(trim(title)) BETWEEN 1 AND 120),
    preferred_language TEXT NOT NULL DEFAULT 'auto'
        CHECK (preferred_language IN ('auto', 'zh-CN', 'en', 'bilingual')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL CHECK (length(trim(content)) > 0),
    citations_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(citations_json)),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_documents_course ON documents(course_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chunks_course ON chunks(course_id, document_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_jobs_document ON ingestion_jobs(document_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_course ON conversations(course_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS rate_limit_windows (
    owner_user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    request_count INTEGER NOT NULL CHECK (request_count >= 0),
    PRIMARY KEY (owner_user_id, action, window_start)
);

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
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(conversations)")
            }
            v2_applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 2"
            ).fetchone() is not None
            if "owner_user_id" not in columns:
                connection.execute(
                    "ALTER TABLE conversations ADD COLUMN owner_user_id "
                    "TEXT NOT NULL DEFAULT 'legacy_orphaned'"
                )
            if "title" not in columns:
                connection.execute(
                    "ALTER TABLE conversations ADD COLUMN title "
                    "TEXT NOT NULL DEFAULT 'New Conversation'"
                )
            if "preferred_language" not in columns:
                connection.execute(
                    "ALTER TABLE conversations ADD COLUMN preferred_language "
                    "TEXT NOT NULL DEFAULT 'auto' "
                    "CHECK (preferred_language IN ('auto', 'zh-CN', 'en', 'bilingual'))"
                )
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_conversations_owner_updated
                ON conversations(owner_user_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_conversations_owner_course_updated
                ON conversations(owner_user_id, course_id, updated_at);
                INSERT OR IGNORE INTO schema_migrations (version, name)
                VALUES (1, 'conversation ownership and per-user limits');
                """
            )
            if not v2_applied:
                connection.executescript(
                    """
                    UPDATE conversations
                    SET title = COALESCE(
                        NULLIF(substr((
                            SELECT trim(content)
                            FROM messages
                            WHERE messages.conversation_id = conversations.id
                              AND messages.role = 'user'
                            ORDER BY messages.created_at, messages.rowid
                            LIMIT 1
                        ), 1, 80), ''),
                        'New Conversation'
                    )
                    WHERE title = 'New Conversation';
                    INSERT OR IGNORE INTO schema_migrations (version, name)
                    VALUES (2, 'conversation history metadata');
                    """
                )
            message_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(messages)")
            }
            if "metadata_json" not in message_columns:
                connection.execute(
                    "ALTER TABLE messages ADD COLUMN metadata_json "
                    "TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))"
                )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (?, ?)",
                (3, "assistant message routing metadata"),
            )

    def consume_rate_limit(
        self,
        *,
        owner_user_id: str,
        action: str,
        limit: int,
        now_epoch_seconds: int,
    ) -> bool:
        window_start = now_epoch_seconds - (now_epoch_seconds % 60)
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM rate_limit_windows WHERE window_start < ?",
                (window_start - 3_600,),
            )
            row = connection.execute(
                """
                INSERT INTO rate_limit_windows (
                    owner_user_id, action, window_start, request_count
                ) VALUES (?, ?, ?, 1)
                ON CONFLICT(owner_user_id, action, window_start)
                DO UPDATE SET request_count = request_count + 1
                RETURNING request_count
                """,
                (owner_user_id, action, window_start),
            ).fetchone()
        return row is not None and int(row["request_count"]) <= limit
