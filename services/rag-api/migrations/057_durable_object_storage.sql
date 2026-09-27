-- Durable object metadata is additive: historical stored_path values remain
-- valid while each object is copied, byte-verified and recovery-tested.
CREATE TABLE IF NOT EXISTS storage_objects (
    id TEXT PRIMARY KEY,
    backend TEXT NOT NULL CHECK (backend IN ('LOCAL','ALIYUN_OSS')),
    bucket TEXT,
    object_key TEXT NOT NULL,
    version_id TEXT,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    crc64 TEXT,
    etag TEXT,
    media_type TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN ('QUARANTINE','CANONICAL','INVALID','DELETING','DELETED')
    ),
    owner_user_id TEXT NOT NULL,
    course_id TEXT REFERENCES courses(id) ON DELETE SET NULL,
    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    local_cache_path TEXT,
    verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (backend, bucket, object_key, version_id)
);

CREATE INDEX IF NOT EXISTS idx_storage_objects_document
ON storage_objects(document_id, state);
CREATE INDEX IF NOT EXISTS idx_storage_objects_owner_course
ON storage_objects(owner_user_id, course_id, state);

CREATE TABLE IF NOT EXISTS storage_upload_sessions (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL,
    media_type TEXT NOT NULL,
    expected_size INTEGER NOT NULL CHECK (expected_size >= 0),
    expected_sha256 TEXT NOT NULL CHECK (length(expected_sha256) = 64),
    quarantine_object_id TEXT NOT NULL REFERENCES storage_objects(id),
    canonical_object_id TEXT REFERENCES storage_objects(id),
    status TEXT NOT NULL CHECK (
        status IN ('CREATED','VERIFYING','FINALIZED','INVALID','EXPIRED')
    ),
    expires_at TEXT NOT NULL,
    finalized_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_storage_upload_owner_status
ON storage_upload_sessions(owner_user_id, status, expires_at);

CREATE TABLE IF NOT EXISTS storage_capacity_reservations (
    id TEXT PRIMARY KEY,
    filesystem_id TEXT NOT NULL,
    owner_kind TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    peak_bytes INTEGER NOT NULL CHECK (peak_bytes >= 0),
    actual_bytes INTEGER NOT NULL DEFAULT 0 CHECK (actual_bytes >= 0),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','RELEASED','EXPIRED')),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    released_at TEXT,
    UNIQUE (owner_kind, owner_id)
);

CREATE INDEX IF NOT EXISTS idx_capacity_active
ON storage_capacity_reservations(filesystem_id, status, expires_at);

CREATE TABLE IF NOT EXISTS storage_migration_receipts (
    id TEXT PRIMARY KEY,
    storage_object_id TEXT NOT NULL REFERENCES storage_objects(id),
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
    remote_verified_at TEXT NOT NULL,
    restore_verified_at TEXT,
    local_delete_eligible INTEGER NOT NULL DEFAULT 0 CHECK (local_delete_eligible IN (0,1)),
    local_deleted_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Documents gain storage_object_id through a guarded ALTER in Database.initialize.
INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(57, 'durable object storage metadata and capacity reservations');
