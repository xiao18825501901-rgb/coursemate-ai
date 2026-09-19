"""New UI state database. Never point this at the legacy rag.sqlite3 / agent.sqlite3."""
import sqlite3
import hashlib
import hmac
import re
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def uid(prefix: str = '') -> str:
    return prefix + uuid4().hex

# Schema 6 adds the unified dual-lane pair model (cmui_pairs), course template
# classification, student verification, course snapshot sharing, exercises with
# hidden answers, and step explanations. The bump is additive; initialize()
# refuses to run against a newer version.
SCHEMA_VERSION = 11

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
CREATE TABLE IF NOT EXISTS cmui_directory (
 subject TEXT PRIMARY KEY REFERENCES cmui_users(id), public_id TEXT NOT NULL UNIQUE,
 active INTEGER NOT NULL, updated_ms INTEGER NOT NULL, created_ms INTEGER NOT NULL,
 avatar TEXT NOT NULL DEFAULT ''
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
 error TEXT, lease_worker TEXT, lease_heartbeat TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(owner,request_id)
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
CREATE TABLE IF NOT EXISTS cmui_delivery_submissions (
 run TEXT PRIMARY KEY REFERENCES cmui_runs(id) ON DELETE CASCADE,
 unit_id TEXT, journey_id TEXT, status TEXT NOT NULL
  CHECK(status IN ('submitted','failed')),
 covered_items TEXT NOT NULL DEFAULT '[]', error TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cmui_pairs (
  id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES cmui_users(id),
  course TEXT NOT NULL,
  teach_conversation TEXT, problem_conversation TEXT,
  title TEXT NOT NULL DEFAULT '新对话',
  bound_node TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cmui_node_starts (
 owner TEXT NOT NULL, course TEXT NOT NULL, node TEXT NOT NULL, run TEXT NOT NULL,
 PRIMARY KEY(owner,course,node)
);
CREATE UNIQUE INDEX IF NOT EXISTS cmui_pairs_node_binding
ON cmui_pairs(owner, course, bound_node) WHERE bound_node IS NOT NULL;
CREATE TABLE IF NOT EXISTS cmui_classifications (
  course TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK(status IN
   ('WAITING_FOR_MATERIALS','CLASSIFYING','CLASSIFIED','OTHER','FAILED_RETRYABLE')),
  template_id TEXT, decision TEXT, degree_level TEXT, confidence REAL,
  alternatives TEXT NOT NULL DEFAULT '[]', reason TEXT NOT NULL DEFAULT '',
  evidence_refs TEXT NOT NULL DEFAULT '[]', materials_revision TEXT,
  model TEXT, source TEXT NOT NULL DEFAULT 'auto' CHECK(source IN ('auto','manual')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cmui_verification (
  owner TEXT PRIMARY KEY REFERENCES cmui_users(id),
  verified INTEGER NOT NULL DEFAULT 0,
  method TEXT CHECK(method IN ('grandfathered','code','admin')),
  verified_at TEXT, boundary_notes TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cmui_verification_codes (
  code TEXT PRIMARY KEY CHECK(length(code)=7 AND code NOT GLOB '*[^0-9]*'),
  secret_hash TEXT NOT NULL,
  owner TEXT REFERENCES cmui_users(id),
  status TEXT NOT NULL DEFAULT 'issued' CHECK(status IN ('issued','redeemed','disabled')),
  issued_by TEXT NOT NULL, issued_at TEXT NOT NULL, redeemed_at TEXT,
  audit TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS cmui_redemption_attempts (
  id TEXT PRIMARY KEY, code TEXT NOT NULL, owner TEXT NOT NULL,
  success INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cmui_redemptions_owner ON cmui_redemption_attempts(owner, created_at);
CREATE TABLE IF NOT EXISTS cmui_shares (
  id TEXT PRIMARY KEY, sender TEXT NOT NULL REFERENCES cmui_users(id),
  course TEXT NOT NULL, snapshot_at TEXT NOT NULL,
  source_course_version TEXT NOT NULL DEFAULT '',
  history_scope TEXT NOT NULL CHECK(history_scope IN ('all','none','selected')),
  selected_pair_ids TEXT NOT NULL DEFAULT '[]',
  manifest_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'preparing' CHECK(status IN ('preparing','ready','failed')),
  requires_student_verification INTEGER NOT NULL DEFAULT 0,
  request_id TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(sender, request_id)
);
CREATE TABLE IF NOT EXISTS cmui_share_recipients (
  share TEXT NOT NULL REFERENCES cmui_shares(id) ON DELETE CASCADE,
  recipient TEXT NOT NULL REFERENCES cmui_users(id),
  status TEXT NOT NULL DEFAULT 'notified' CHECK(status IN ('notified','joined','ignored')),
  joined_course_id TEXT, joined_at TEXT,
  PRIMARY KEY(share, recipient)
);
CREATE TABLE IF NOT EXISTS cmui_share_files (
  share TEXT NOT NULL REFERENCES cmui_shares(id) ON DELETE CASCADE,
  file_id TEXT NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL,
  mime TEXT NOT NULL, sha256 TEXT NOT NULL, archived_storage_key TEXT,
  PRIMARY KEY(share, file_id)
);
CREATE TABLE IF NOT EXISTS cmui_share_imports (
 share TEXT NOT NULL REFERENCES cmui_shares(id), recipient TEXT NOT NULL REFERENCES cmui_users(id),
 course TEXT, status TEXT NOT NULL CHECK(status IN ('IMPORTING','READY','FAILED_RETRYABLE')),
 mapping_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL,
 PRIMARY KEY(share,recipient)
);
CREATE TABLE IF NOT EXISTS cmui_exercises (
  id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES cmui_users(id),
  course TEXT NOT NULL, pair TEXT NOT NULL REFERENCES cmui_pairs(id) ON DELETE CASCADE,
  node TEXT, target_node TEXT,
  question TEXT NOT NULL,
  answer_steps TEXT NOT NULL,
  references_json TEXT NOT NULL DEFAULT '[]',
  verification_status TEXT NOT NULL DEFAULT 'unverified',
  generation_version TEXT NOT NULL DEFAULT 'V1',
  run TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cmui_message_attachments (
 message TEXT PRIMARY KEY REFERENCES cmui_messages(id) ON DELETE CASCADE,
 attachments TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS cmui_answer_reveals (
  owner TEXT NOT NULL REFERENCES cmui_users(id),
  exercise TEXT NOT NULL REFERENCES cmui_exercises(id) ON DELETE CASCADE,
  revealed_at TEXT NOT NULL, PRIMARY KEY(owner, exercise)
);
CREATE TABLE IF NOT EXISTS cmui_step_explanations (
  id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES cmui_users(id),
  exercise TEXT NOT NULL REFERENCES cmui_exercises(id) ON DELETE CASCADE,
  step_id TEXT NOT NULL, answer_version TEXT NOT NULL,
  question TEXT NOT NULL, text TEXT, run TEXT,
  status TEXT NOT NULL DEFAULT 'generating'
   CHECK(status IN ('generating','completed','failed','cancelled')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cmui_explanation_messages (
  id TEXT PRIMARY KEY,
  explanation TEXT NOT NULL REFERENCES cmui_step_explanations(id) ON DELETE CASCADE,
  role TEXT NOT NULL, text TEXT NOT NULL, run TEXT, created_at TEXT NOT NULL
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

    def initialize(self, verification_secret: str | None = None):
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
            # Schema 3 amendment: run leases for cross-process ownership. Older
            # Schema-3 databases get the columns added in place; fresh ones get
            # them from SCHEMA above. Idempotent by inspection.
            run_columns = {r[1] for r in c.execute("PRAGMA table_info(cmui_runs)")}
            if 'lease_worker' not in run_columns:
                c.execute("ALTER TABLE cmui_runs ADD COLUMN lease_worker TEXT")
            if 'lease_heartbeat' not in run_columns:
                c.execute("ALTER TABLE cmui_runs ADD COLUMN lease_heartbeat TEXT")
            # Schema 5 amendment: the bridge's trace chain into the V3 ledgers.
            bridge_columns = {r[1] for r in c.execute("PRAGMA table_info(cmui_bridges)")}
            for column in ('teach_run','journey_id','spec_version','delivery_unit_id',
                           'problem_revision_id','solution_id','step_ids_json'):
                if column not in bridge_columns:
                    c.execute(f"ALTER TABLE cmui_bridges ADD COLUMN {column} TEXT")
            # Schema 6 amendments: teaching mode on runs; display type and the
            # campus verification requirement on courses.
            run_columns = {r[1] for r in c.execute("PRAGMA table_info(cmui_runs)")}
            if 'teaching_mode' not in run_columns:
                c.execute("ALTER TABLE cmui_runs ADD COLUMN teaching_mode TEXT "
                          "NOT NULL DEFAULT 'normal' CHECK(teaching_mode IN ('normal','thinking'))")
            course_columns = {r[1] for r in c.execute("PRAGMA table_info(cmui_courses)")}
            if 'display_type' not in course_columns:
                c.execute("ALTER TABLE cmui_courses ADD COLUMN display_type TEXT "
                          "CHECK(display_type IN ('private','campus','shared'))")
            if 'requires_student_verification' not in course_columns:
                c.execute("ALTER TABLE cmui_courses ADD COLUMN "
                          "requires_student_verification INTEGER NOT NULL DEFAULT 0")
            message_columns = {r[1] for r in c.execute("PRAGMA table_info(cmui_messages)")}
            if 'provenance' not in message_columns:
                c.execute("ALTER TABLE cmui_messages ADD COLUMN provenance TEXT NOT NULL DEFAULT ''")
            if 'exercise' not in message_columns:
                c.execute("ALTER TABLE cmui_messages ADD COLUMN exercise TEXT")
            conversation_columns = {r[1] for r in c.execute("PRAGMA table_info(cmui_conversations)")}
            if 'hidden' not in conversation_columns:
                c.execute("ALTER TABLE cmui_conversations ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
            explanation_columns = {r[1] for r in c.execute("PRAGMA table_info(cmui_step_explanations)")}
            if 'conversation' not in explanation_columns:
                c.execute("ALTER TABLE cmui_step_explanations ADD COLUMN conversation TEXT")
            self._migrate_verification_secrets(c, verification_secret)
            c.execute("INSERT INTO cmui_meta VALUES ('schema_version',?) ON CONFLICT(key) DO UPDATE SET value=?",(str(SCHEMA_VERSION),str(SCHEMA_VERSION)))
            self._migrate_pairs(c)

    def _migrate_verification_secrets(self, c, secret):
        """Schema 7: replace secret-bearing legacy keys transactionally.

        SCHEMA remains the historical bootstrap. Never infer a production key;
        populated legacy stores require the caller's configured HMAC secret.
        Logical scrubbing does not erase older backups or SQLite free pages.
        """
        columns = {r[1] for r in c.execute('PRAGMA table_info(cmui_verification_codes)')}
        if 'code_id' in columns:
            return
        codes = c.execute('SELECT * FROM cmui_verification_codes').fetchall()
        attempts = c.execute('SELECT * FROM cmui_redemption_attempts').fetchall()
        if (codes or attempts) and not secret:
            raise ValueError('Configured verification secret required to migrate existing verification records')
        def digest(value):
            return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
        c.execute('SAVEPOINT verification_schema_7')
        try:
            c.execute("CREATE TABLE cmui_verification_codes_v7 (code_id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL UNIQUE, owner TEXT, status TEXT NOT NULL CHECK(status IN ('issued','redeemed','disabled')), issued_by TEXT NOT NULL, issued_at TEXT NOT NULL, redeemed_at TEXT, audit TEXT NOT NULL DEFAULT '[]')")
            for row in codes:
                c.execute('INSERT INTO cmui_verification_codes_v7 VALUES(?,?,?,?,?,?,?,?)',
                          (uid('vcode_'), digest(row['code']), row['owner'], row['status'], row['issued_by'], row['issued_at'], row['redeemed_at'], row['audit']))
            for row in attempts:
                c.execute('UPDATE cmui_redemption_attempts SET code=? WHERE id=?', (digest(row['code']), row['id']))
            for row in c.execute('SELECT owner,boundary_notes FROM cmui_verification').fetchall():
                c.execute('UPDATE cmui_verification SET boundary_notes=? WHERE owner=?',
                          (re.sub(r'(?<!\d)\d{7}(?!\d)', '[redacted-code]', row['boundary_notes']), row['owner']))
            c.execute('DROP TABLE cmui_verification_codes')
            c.execute('ALTER TABLE cmui_verification_codes_v7 RENAME TO cmui_verification_codes')
            c.execute('RELEASE verification_schema_7')
        except BaseException:
            c.execute('ROLLBACK TO verification_schema_7')
            c.execute('RELEASE verification_schema_7')
            raise

    def _migrate_pairs(self, c):
        """One-time Schema-6 migration of the dual-lane history into unified pairs.

        Only evidence-backed pairings are merged: a cmui_layout row links its
        teach and problem conversation ids, so those become one pair. Every
        conversation without such evidence stays a single-lane pair (the other
        lane is NULL and renders as an empty pane). Idempotent by inspection:
        rows are only created for conversations that have no pair reference yet.
        """
        existing = {
            row[0] for row in c.execute(
                "SELECT teach_conversation FROM cmui_pairs WHERE teach_conversation IS NOT NULL"
            )
        } | {
            row[0] for row in c.execute(
                "SELECT problem_conversation FROM cmui_pairs WHERE problem_conversation IS NOT NULL"
            )
        }
        layouts = c.execute(
            "SELECT owner, course, teach_conversation, problem_conversation, active_node "
            "FROM cmui_layout"
        ).fetchall()
        for layout in layouts:
            teach = layout["teach_conversation"]
            problem = layout["problem_conversation"]
            if not teach and not problem:
                continue
            if teach in existing and problem in existing:
                continue
            title = "新对话"
            created = now()
            for conv_id in (teach, problem):
                if conv_id and conv_id not in existing:
                    row = c.execute(
                        "SELECT title, created_at FROM cmui_conversations WHERE id=?", (conv_id,)
                    ).fetchone()
                    if row is not None:
                        title = row["title"] or title
                        created = row["created_at"]
                        break
            c.execute(
                "INSERT INTO cmui_pairs(id,owner,course,teach_conversation,"
                "problem_conversation,title,bound_node,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (uid("pair_"), layout["owner"], layout["course"], teach, problem,
                 title, layout["active_node"], created, now()),
            )
            existing.add(teach)
            existing.add(problem)
        leftovers = c.execute(
            "SELECT id, owner, course, lane, title, created_at FROM cmui_conversations "
            "ORDER BY created_at"
        ).fetchall()
        for row in leftovers:
            if row["id"] in existing:
                continue
            c.execute(
                "INSERT INTO cmui_pairs(id,owner,course,teach_conversation,"
                "problem_conversation,title,bound_node,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,NULL,?,?)",
                (uid("pair_"), row["owner"], row["course"],
                 row["id"] if row["lane"] == "teach" else None,
                 row["id"] if row["lane"] == "problem" else None,
                 row["title"], row["created_at"], now()),
            )
            existing.add(row["id"])

    def all(self, sql, args=()):
        with self.connect() as c: return [dict(r) for r in c.execute(sql, args)]

    def one(self, sql, args=()):
        with self.connect() as c:
            r=c.execute(sql,args).fetchone()
            return dict(r) if r else None

    def execute(self, sql, args=()):
        with self.connect(True) as c: return c.execute(sql,args).rowcount
