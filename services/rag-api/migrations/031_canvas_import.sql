-- Canvas private import: institution connections, import jobs and per-file records.
--
-- Task B2/B4 of the CourseJesus pack. The job row follows the conventions migration 027
-- established for `assessment_preparation_jobs`: TEXT primary key, scope columns with
-- ON DELETE RESTRICT, CHECK-constrained status, error_code/error_message, ISO timestamps
-- written with strftime, and a UNIQUE constraint that makes re-submitting the same frozen
-- request idempotent instead of creating a second job.
--
-- Two deliberate choices, because the schema is where they can actually be enforced:
--
--   1. NO TOKEN COLUMN EXISTS. A job references a connection; the credential lives in the
--      encrypted store keyed by connection_id and a key id. A dump of this database cannot
--      contain a Canvas token, which is the property the pack requires ("job 只存 connection_id").
--   2. The per-file unique key is (origin, course_id, file_id) -- never the filename. That is
--      what makes "same name, different id" two rows and "same id, new version" an UPDATE
--      rather than a silent skip.

CREATE TABLE IF NOT EXISTS canvas_connections (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    institution_key TEXT NOT NULL,
    institution_origin TEXT NOT NULL,
    canvas_user_id TEXT NOT NULL,
    canvas_display_name TEXT NOT NULL DEFAULT '',
    granted_scopes TEXT NOT NULL DEFAULT '',
    -- True only when the user explicitly asked to keep the connection for later updates.
    -- A default import stores nothing: the credential is cleared once the job window ends.
    saved_for_reuse INTEGER NOT NULL DEFAULT 0 CHECK(saved_for_reuse IN (0, 1)),
    credential_key_id TEXT,
    credential_expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    revoked_at TEXT,
    -- One Canvas account per (user, institution): reconnecting the same school must update
    -- the existing row, not accumulate connections, and a different Canvas user id is a
    -- distinct identity that the application layer refuses to swap in silently.
    UNIQUE(owner_user_id, institution_origin, canvas_user_id)
);

CREATE TABLE IF NOT EXISTS canvas_import_jobs (
    id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL REFERENCES canvas_connections(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    institution_origin TEXT NOT NULL,
    -- The frozen selection: the courses chosen at confirmation, as a JSON array. It is
    -- frozen precisely so "all accessible history" cannot grow into future courses.
    course_ids_json TEXT NOT NULL,
    -- Idempotency: the same connection, owner, courses and observed material versions.
    selection_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DISCOVERING'
        CHECK(status IN ('DISCOVERING','AWAITING_SELECTION','QUEUED','DOWNLOADING','VERIFYING',
                         'INGESTING','INDEXING','COMPLETED','COMPLETED_WITH_WARNINGS',
                         'NEEDS_REAUTH','FAILED','CANCELLED')),
    error_code TEXT,
    error_message TEXT,
    -- Worker bookkeeping: a lease, not a long HTTP request. Expired leases may be reclaimed.
    leased_until TEXT,
    worker_id TEXT,
    -- The private course this import created, once it exists. Never a public course.
    target_course_id TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    completed_at TEXT,
    UNIQUE(connection_id, selection_fingerprint)
);

CREATE TABLE IF NOT EXISTS canvas_import_files (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES canvas_import_jobs(id) ON DELETE CASCADE,
    -- External identity. The filename is display-only and is deliberately not part of the key.
    origin TEXT NOT NULL,
    source_course_id TEXT NOT NULL,
    source_file_id TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    source_updated_at TEXT NOT NULL DEFAULT '',
    etag TEXT NOT NULL DEFAULT '',
    source_folder_or_module TEXT NOT NULL DEFAULT '',
    bytes_sha256 TEXT NOT NULL DEFAULT '',
    local_document_id TEXT,
    local_document_version_id TEXT,
    -- Bytes, parsing and indexing are three separate facts: a stored video is DOWNLOAD_ONLY
    -- and must never be reported as indexed material a model can read.
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK(status IN ('PENDING','DOWNLOADED','DOWNLOAD_ONLY','INDEXED','SKIPPED_IDENTICAL',
                         'WARNING','FAILED','CANCELLED')),
    parse_state TEXT NOT NULL DEFAULT '',
    index_state TEXT NOT NULL DEFAULT '',
    error_class TEXT,
    error_detail TEXT,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(job_id, origin, source_course_id, source_file_id)
);

CREATE INDEX IF NOT EXISTS idx_canvas_jobs_claimable
    ON canvas_import_jobs(status, leased_until);
CREATE INDEX IF NOT EXISTS idx_canvas_jobs_owner
    ON canvas_import_jobs(owner_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_canvas_files_job
    ON canvas_import_files(job_id, status);
CREATE INDEX IF NOT EXISTS idx_canvas_connections_owner
    ON canvas_connections(owner_user_id, institution_key);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(31, 'canvas private import');
