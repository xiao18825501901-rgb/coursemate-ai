CREATE TABLE IF NOT EXISTS visual_jobs (
    id TEXT PRIMARY KEY,
    parent_job_id TEXT REFERENCES visual_jobs(id) ON DELETE RESTRICT,
    request_id TEXT NOT NULL,
    request_hash TEXT NOT NULL CHECK(length(request_hash) = 64),
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    pair_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    node_id TEXT,
    action TEXT NOT NULL CHECK(action IN ('auto','diagram','visual','animate')),
    source_snapshot_hash TEXT NOT NULL CHECK(length(source_snapshot_hash) = 64),
    frozen_input_json TEXT NOT NULL,
    visual_spec_json TEXT,
    visual_spec_version TEXT,
    visual_spec_hash TEXT,
    renderer TEXT,
    provider TEXT NOT NULL DEFAULT 'mock',
    provider_job_id TEXT,
    workflow_id TEXT,
    workflow_version TEXT,
    prompt_version TEXT NOT NULL,
    prompt_hash TEXT NOT NULL CHECK(length(prompt_hash) = 64),
    model_version TEXT,
    status TEXT NOT NULL CHECK(status IN (
        'QUEUED','PLANNING','RENDERING','VALIDATING',
        'COMPLETED','FAILED','CANCELLED','RETRYING'
    )),
    cache_key TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    queue_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    lease_owner TEXT,
    lease_expires_at REAL,
    error_code TEXT,
    error_detail_safe TEXT,
    estimated_cost_micros INTEGER,
    actual_cost_micros INTEGER,
    cost_currency TEXT,
    gpu_seconds REAL,
    cache_hit INTEGER NOT NULL DEFAULT 0 CHECK(cache_hit IN (0,1)),
    output_bytes INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, request_id)
);

CREATE INDEX IF NOT EXISTS idx_visual_jobs_claim
ON visual_jobs(status, lease_expires_at, priority DESC, queue_at);
CREATE INDEX IF NOT EXISTS idx_visual_jobs_message
ON visual_jobs(user_id, course_id, message_id, created_at);
CREATE INDEX IF NOT EXISTS idx_visual_jobs_pair
ON visual_jobs(user_id, course_id, pair_id, created_at);

CREATE TABLE IF NOT EXISTS visual_assets (
    id TEXT PRIMARY KEY,
    origin_job_id TEXT NOT NULL REFERENCES visual_jobs(id) ON DELETE RESTRICT,
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    message_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('DIAGRAM','ANIMATION','IMAGE','VIDEO')),
    renderer TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    duration_seconds REAL,
    storage_backend TEXT NOT NULL,
    storage_bucket TEXT,
    storage_key TEXT NOT NULL,
    storage_version_id TEXT,
    sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
    thumbnail_asset_id TEXT REFERENCES visual_assets(id) ON DELETE RESTRICT,
    alt_text TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_version TEXT,
    workflow_id TEXT,
    workflow_version TEXT,
    semantic_validation TEXT NOT NULL CHECK(semantic_validation IN ('PASS','LIMITED','UNCERTAIN')),
    created_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS visual_job_assets (
    job_id TEXT NOT NULL REFERENCES visual_jobs(id) ON DELETE RESTRICT,
    asset_id TEXT NOT NULL REFERENCES visual_assets(id) ON DELETE RESTRICT,
    role TEXT NOT NULL DEFAULT 'primary',
    created_at TEXT NOT NULL,
    PRIMARY KEY(job_id, asset_id)
);

CREATE TABLE IF NOT EXISTS visual_cache_entries (
    cache_key TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES visual_assets(id) ON DELETE RESTRICT,
    scope_key TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    source_snapshot_hash TEXT NOT NULL,
    visual_spec_hash TEXT NOT NULL,
    renderer TEXT NOT NULL,
    renderer_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    workflow_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    language TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS visual_job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES visual_jobs(id) ON DELETE RESTRICT,
    attempt INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    safe_detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_visual_job_events_job
ON visual_job_events(job_id, id);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(67, 'visual learning engine');
