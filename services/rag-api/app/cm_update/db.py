"""New UI state database. Never point this at the legacy rag.sqlite3 / agent.sqlite3."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def uid(prefix: str = '') -> str:
    return prefix + uuid4().hex

# Schema 3 adds cmui_run_v3, the cross-reference from a UI generation run to the
# authoritative V3 learning journey it started. The bump is additive; initialize()
# refuses to run against a newer version.
SCHEMA_VERSION = 3

SCHEMA = '''
CREATE TABLE IF NOT EXISTS cmui_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cmui_users (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, handle TEXT NOT NULL UNIQUE,
 bio TEXT NOT NULL DEFAULT '', language TEXT NOT NULL DEFAULT 'zh-CN',
 timezone TEXT NOT NULL DEFAULT 'Asia/Hong_Kong', discoverable INTEGER NOT NULL DEFAULT 1,
 reply_notify INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cmui_sessions (
 token_hash TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES cmui_users(id), expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cmui_courses (
 id TEXT PRIMARY KEY, owner TEXT REFERENCES cmui_users(id), code TEXT NOT NULL,
 name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', color TEXT NOT NULL,
 visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private','public')),
 official INTEGER NOT NULL DEFAULT 0, requirements TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cmui_pins (
 owner TEXT NOT NULL REFERENCES cmui_users(id), course TEXT NOT NULL,
 position INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(owner, course)
);
CREATE TABLE IF NOT EXISTS cmui_files (
 id TEXT PRIMARY KEY, course TEXT NOT NULL, owner TEXT REFERENCES cmui_users(id),
 name TEXT NOT NULL, folder TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL,
 mime TEXT NOT NULL, storage_key TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL,
 scope TEXT NOT NULL DEFAULT 'private', status TEXT NOT NULL, error TEXT,
 created_at TEXT NOT NULL, UNIQUE(course, owner, sha256)
);
CREATE TABLE IF NOT EXISTS cmui_chunks (
 id TEXT PRIMARY KEY, file TEXT NOT NULL REFERENCES cmui_files(id) ON DELETE CASCADE,
 page INTEGER, ordinal INTEGER NOT NULL, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cmui_comments (
 id TEXT PRIMARY KEY, course TEXT NOT NULL, author TEXT NOT NULL REFERENCES cmui_users(id),
 parent TEXT REFERENCES cmui_comments(id), text TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
 request_id TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(author,request_id)
);
CREATE INDEX IF NOT EXISTS cmui_comment_course ON cmui_comments(course,created_at);
CREATE TABLE IF NOT EXISTS cmui_likes (owner TEXT NOT NULL REFERENCES cmui_users(id), comment TEXT NOT NULL REFERENCES cmui_comments(id), PRIMARY KEY(owner,comment));
CREATE TABLE IF NOT EXISTS cmui_notifications (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES cmui_users(id), actor TEXT NOT NULL REFERENCES cmui_users(id),
 kind TEXT NOT NULL, ref TEXT NOT NULL, course TEXT, text TEXT NOT NULL, read_at TEXT,
 created_at TEXT NOT NULL, UNIQUE(owner,kind,ref)
);
CREATE TABLE IF NOT EXISTS cmui_threads (
 id TEXT PRIMARY KEY, a TEXT NOT NULL REFERENCES cmui_users(id), b TEXT NOT NULL REFERENCES cmui_users(id),
 created_at TEXT NOT NULL, UNIQUE(a,b), CHECK(a<>b)
);
CREATE TABLE IF NOT EXISTS cmui_direct_messages (
 id TEXT PRIMARY KEY, thread TEXT NOT NULL REFERENCES cmui_threads(id), sender TEXT NOT NULL REFERENCES cmui_users(id),
 text TEXT NOT NULL, request_id TEXT NOT NULL, read_at TEXT, created_at TEXT NOT NULL,
 UNIQUE(sender,request_id)
);
CREATE TABLE IF NOT EXISTS cmui_blocks (owner TEXT NOT NULL REFERENCES cmui_users(id), blocked TEXT NOT NULL REFERENCES cmui_users(id), PRIMARY KEY(owner,blocked));
CREATE TABLE IF NOT EXISTS cmui_tasks (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES cmui_users(id), course TEXT,
 title TEXT NOT NULL, due_at TEXT NOT NULL, timezone TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'todo', version INTEGER NOT NULL DEFAULT 1,
 request_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(owner,request_id)
);
CREATE TABLE IF NOT EXISTS cmui_conversations (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES cmui_users(id), course TEXT NOT NULL,
 lane TEXT NOT NULL CHECK(lane IN ('teach','problem')), title TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cmui_messages (
 id TEXT PRIMARY KEY, conversation TEXT NOT NULL REFERENCES cmui_conversations(id) ON DELETE CASCADE,
 role TEXT NOT NULL, text TEXT NOT NULL, citations TEXT NOT NULL DEFAULT '[]',
 run TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cmui_runs (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES cmui_users(id), conversation TEXT NOT NULL REFERENCES cmui_conversations(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL, status TEXT NOT NULL, user_text TEXT NOT NULL, generated_prompt TEXT,
 partial_text TEXT NOT NULL DEFAULT '', citations TEXT NOT NULL DEFAULT '[]', usage TEXT NOT NULL DEFAULT '[]',
 error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(owner,request_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS cmui_one_active_run ON cmui_runs(conversation) WHERE status IN ('queued','planning','generating');
CREATE TABLE IF NOT EXISTS cmui_run_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT NOT NULL REFERENCES cmui_runs(id) ON DELETE CASCADE,
 type TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cmui_layout (
 owner TEXT NOT NULL REFERENCES cmui_users(id), course TEXT NOT NULL, ratio REAL NOT NULL DEFAULT 0.5,
 teach_conversation TEXT, problem_conversation TEXT, active_node TEXT, PRIMARY KEY(owner,course)
);
CREATE TABLE IF NOT EXISTS cmui_nodes (
 id TEXT PRIMARY KEY, course TEXT NOT NULL, parent TEXT, title TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cmui_learning (
 owner TEXT NOT NULL REFERENCES cmui_users(id), node TEXT NOT NULL,
 progress TEXT NOT NULL DEFAULT 'NOT_STARTED', grade TEXT, PRIMARY KEY(owner,node)
);
CREATE TABLE IF NOT EXISTS cmui_bridges (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES cmui_users(id), course TEXT NOT NULL,
 problem_message TEXT NOT NULL REFERENCES cmui_messages(id), step INTEGER NOT NULL,
 question TEXT NOT NULL, node TEXT, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cmui_limits (owner TEXT NOT NULL, bucket TEXT NOT NULL, window INTEGER NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(owner,bucket,window));
CREATE TABLE IF NOT EXISTS cmui_run_inputs (
 run TEXT PRIMARY KEY REFERENCES cmui_runs(id) ON DELETE CASCADE,
 payload_hash TEXT NOT NULL, attachments TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS cmui_agent_receipts (
 owner TEXT NOT NULL REFERENCES cmui_users(id), request_id TEXT NOT NULL,
 payload_hash TEXT NOT NULL, lease_hash TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('running','completed','failed')),
 result TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(owner,request_id)
);
CREATE TABLE IF NOT EXISTS cmui_run_v3 (
 run TEXT PRIMARY KEY REFERENCES cmui_runs(id) ON DELETE CASCADE,
 workspace_id TEXT NOT NULL, journey_id TEXT NOT NULL,
 node_id TEXT NOT NULL, spec_version INTEGER NOT NULL,
 created_at TEXT NOT NULL
);
'''


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self, write: bool = False):
        c = sqlite3.connect(self.path, timeout=20)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA busy_timeout=20000')
        try:
            if write: c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables.intersection({'courses','chunks','tasks','schema_migrations'}):
                raise ValueError('Refusing to initialize UI database over an existing CourseMate domain database')
            if 'cmui_meta' in tables:
                current=c.execute("SELECT value FROM cmui_meta WHERE key='schema_version'").fetchone()
                if current and int(current[0])>SCHEMA_VERSION: raise ValueError('Newer UI database schema detected; do not downgrade')
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript(SCHEMA)
            c.execute("INSERT INTO cmui_meta VALUES ('schema_version',?) ON CONFLICT(key) DO UPDATE SET value=?",(str(SCHEMA_VERSION),str(SCHEMA_VERSION)))

    def all(self, sql, args=()):
        with self.connect() as c: return [dict(r) for r in c.execute(sql, args)]

    def one(self, sql, args=()):
        with self.connect() as c:
            r=c.execute(sql,args).fetchone()
            return dict(r) if r else None

    def execute(self, sql, args=()):
        with self.connect(True) as c: return c.execute(sql,args).rowcount
