-- One durable runtime switch coordinates API admission, provider dispatch,
-- in-flight retrieval and an operator-controlled EAS stop. Historical UNKNOWN
-- jobs remain auditable but never keep an idle GPU alive indefinitely.
BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS visual_runtime_control (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    accepting_submissions INTEGER NOT NULL DEFAULT 1
        CHECK(accepting_submissions IN (0, 1)),
    drain_started_at TEXT,
    drain_reason TEXT,
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO visual_runtime_control(
    singleton, accepting_submissions, drain_started_at, drain_reason, updated_at
) VALUES(1, 1, NULL, NULL, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(81, 'durable visual runtime drain gate');

COMMIT;
