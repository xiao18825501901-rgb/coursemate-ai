ALTER TABLE visual_jobs ADD COLUMN renderer_wait_started_at TEXT;
ALTER TABLE visual_jobs ADD COLUMN renderer_ready_at TEXT;
ALTER TABLE visual_jobs ADD COLUMN renderer_wait_seconds REAL
    CHECK(renderer_wait_seconds IS NULL OR renderer_wait_seconds >= 0);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(69, 'visual renderer cold start receipts');
