-- Task-level transient Canvas credential: the receipt, never the credential.
--
-- The owner-authorised import path holds a pasted Canvas personal access token in the service
-- process for exactly one task (`app/canvas/transient_credential.py`) and destroys it before
-- indexing starts. This migration adds what the *business database* is allowed to know about
-- that credential, and the line is drawn deliberately:
--
--   * WHAT IS STORED: an opaque `credential_ref` (a random id), the lifecycle *state*, whether
--     it was a transient task credential or a saved OAuth connection, and the timings.
--   * WHAT IS NOT STORED, EVER: the token, any part of it, any hash that could be tested
--     against a guess, and the Canvas base URL + token pair. `credential_key_id` on the
--     connection row stays NULL for a transient task, which is how a reader can tell that no
--     encrypted credential file was written for it.
--
-- The event table exists so "the credential was cleared as soon as the Canvas reads finished,
-- before indexing" is a checkable claim after the fact rather than a description of intent:
-- each transition is a row with its own timestamp, and the indexing transition can be compared
-- against the destruction timestamp.
--
-- The three `canvas_import_jobs` columns this migration's docstring describes are added by
-- `Database._migrate` under a `PRAGMA table_info` guard, because SQLite has no
-- `ADD COLUMN IF NOT EXISTS` and every migration file is re-run on every start (the ledger
-- entry for the columns lives here, exactly as migrations 023 and 025 do it). Their shape:
--
--   credential_ref    TEXT NOT NULL DEFAULT ''
--   credential_kind   TEXT NOT NULL DEFAULT 'connection'
--                     CHECK(credential_kind IN ('connection','transient_task'))
--   credential_state  TEXT NOT NULL DEFAULT 'NEVER_STORED'
--                     CHECK(credential_state IN ('NEVER_STORED','PRESENT_TRANSIENTLY','DESTROYING',
--                                                'DESTROYED','EXPIRED','LOST_ON_RESTART'))

CREATE TABLE IF NOT EXISTS canvas_credential_lifecycle_events (
    id TEXT PRIMARY KEY,
    -- Nullable on purpose: the first event of a task credential happens before any job exists,
    -- and losing that row would hide the moment the token entered the process.
    job_id TEXT REFERENCES canvas_import_jobs(id) ON DELETE CASCADE,
    credential_ref TEXT NOT NULL,
    subject TEXT NOT NULL,
    institution_origin TEXT NOT NULL,
    -- The six lifecycle states, plus the reason a terminal one was reached.
    state TEXT NOT NULL CHECK(state IN ('NEVER_STORED','PRESENT_TRANSIENTLY','DESTROYING',
                                        'DESTROYED','EXPIRED','LOST_ON_RESTART')),
    reason TEXT NOT NULL DEFAULT '',
    -- How many Canvas reads this credential performed before it was destroyed. Bounded by the
    -- task, and the number that makes "it was used for the reads it was given for" auditable.
    read_calls INTEGER NOT NULL DEFAULT 0 CHECK(read_calls >= 0),
    -- Bytes overwritten in memory at destruction, as reported by the store. Zero for states
    -- that never held a credential.
    zeroed_bytes INTEGER NOT NULL DEFAULT 0 CHECK(zeroed_bytes >= 0),
    -- Which process lifetime the credential belonged to. A receipt whose credential is not in
    -- the current process is LOST_ON_RESTART, and this column is how that is established
    -- without storing anything about the machine or the user.
    store_instance_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_canvas_credential_events_ref
    ON canvas_credential_lifecycle_events(credential_ref, created_at);
CREATE INDEX IF NOT EXISTS idx_canvas_credential_events_subject
    ON canvas_credential_lifecycle_events(subject, created_at);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES (35, '035_canvas_task_credential.sql');
