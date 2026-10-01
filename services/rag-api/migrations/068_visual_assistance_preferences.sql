CREATE TABLE IF NOT EXISTS visual_assistance_preferences (
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
    consent_version TEXT NOT NULL,
    enabled_at TEXT,
    last_request_id TEXT NOT NULL,
    last_request_hash TEXT NOT NULL CHECK(length(last_request_hash) = 64),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, course_id)
);

CREATE INDEX IF NOT EXISTS idx_visual_assistance_course_enabled
ON visual_assistance_preferences(course_id, enabled);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(68, 'visual assistance preferences');
