-- Local Canvas Bridge: a short-lived import session for a user's own machine.
--
-- The OAuth path (migration 031) is the production route for every user. This table serves the one
-- case OAuth cannot cover while a school has not issued a Developer Key: the user runs the local
-- CourseJesus bridge on their own machine, where a Personal Access Token is read through a hidden
-- prompt and kept in the operating system's credential store.
--
-- Three properties are enforced here rather than promised in prose:
--
--   1. NO COLUMN CAN HOLD A PAT. The session stores a *hash* of the one-time code the user pastes
--      into their terminal; the token itself never leaves the user's machine, so there is nowhere in
--      this schema for it to be written even by accident.
--   2. The code is single-use and short-lived: `claimed_at` makes a replay refuse, `expires_at`
--      bounds it, and `code_hash` is UNIQUE so two sessions can never share a code.
--   3. The session belongs to exactly one CourseJesus user and one institution origin. Every bridge
--      request carries the user's own authentication *and* the code, and both must match the row, so
--      one user cannot take over another's session even with the code.
--
-- The per-file key is (session, canvas course id, canvas file id, content hash): a renamed file with
-- a new Canvas file id is a second row, the same file id with new bytes is a new version rather than
-- a permanent skip, and an identical retry is idempotent instead of duplicating a document.

CREATE TABLE IF NOT EXISTS canvas_local_sessions (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    institution_key TEXT NOT NULL,
    institution_origin TEXT NOT NULL,
    -- SHA-256 of the one-time code. The plaintext code exists only in the page that displayed it and
    -- in the user's terminal; it is never stored, logged or returned again.
    code_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'OPEN'
        CHECK(status IN ('OPEN','CLAIMED','SELECTED','IMPORTING','COMPLETED',
                         'COMPLETED_WITH_WARNINGS','FAILED','CANCELLED','EXPIRED')),
    -- What the bridge said about itself at claim time (host label, display name). Descriptive only:
    -- never used for authorization, never a credential.
    claimed_by TEXT NOT NULL DEFAULT '',
    canvas_user_id TEXT NOT NULL DEFAULT '',
    canvas_display_name TEXT NOT NULL DEFAULT '',
    discovery_json TEXT NOT NULL DEFAULT '[]',
    selection_json TEXT NOT NULL DEFAULT '[]',
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    expires_at TEXT NOT NULL,
    claimed_at TEXT,
    selection_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS canvas_local_files (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES canvas_local_sessions(id) ON DELETE CASCADE,
    canvas_course_id TEXT NOT NULL,
    -- External identity; the display name is descriptive and deliberately not part of the key.
    canvas_file_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
    content_sha256 TEXT NOT NULL,
    source_updated_at TEXT NOT NULL DEFAULT '',
    target_course_id TEXT NOT NULL DEFAULT '',
    local_document_id TEXT,
    -- Same vocabulary the OAuth import uses for a file's fate, so one report can honestly describe
    -- both routes, plus REJECTED for a file the upload layer refuses outright (a format outside the
    -- allow-list): that is neither a parse warning nor our failure, and calling it either would hide
    -- which of the two happened.
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK(status IN ('PENDING','DOWNLOADED','DOWNLOAD_ONLY','INDEXED','SKIPPED_IDENTICAL',
                         'WARNING','REJECTED','FAILED','CANCELLED')),
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    -- Idempotency for a retried upload of the *same* bytes, and a new row for a genuinely new
    -- version of the same Canvas file id.
    UNIQUE(session_id, canvas_course_id, canvas_file_id, content_sha256)
);

CREATE INDEX IF NOT EXISTS idx_canvas_local_sessions_owner
    ON canvas_local_sessions(owner_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_canvas_local_sessions_status
    ON canvas_local_sessions(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_canvas_local_files_session
    ON canvas_local_files(session_id, canvas_course_id);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES (33, '033_canvas_local_bridge.sql');
