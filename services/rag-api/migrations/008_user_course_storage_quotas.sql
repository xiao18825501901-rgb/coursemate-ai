-- Operations-readable record for schema version 8.
-- Database.initialize() is the idempotent executable migrator because SQLite does
-- not support ADD COLUMN IF NOT EXISTS portably.

ALTER TABLE documents
ADD COLUMN byte_size INTEGER NOT NULL DEFAULT 0 CHECK (byte_size >= 0);

-- The application migrator attempts to backfill byte_size from each server-owned
-- stored_path. Files unavailable on this host remain zero and must be reconciled
-- against the upload manifest before public rollout.

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES (8, 'user course storage quotas');
