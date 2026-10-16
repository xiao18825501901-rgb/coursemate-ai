PRAGMA foreign_keys=OFF;
PRAGMA legacy_alter_table=ON;
BEGIN IMMEDIATE;

CREATE TABLE learning_model_run_evidence_new (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN (
        'planner','teacher','problem','grader','router',
        'reference','preparation','explanation',
        'QUESTION_AUTHOR','QUESTION_BLIND_SOLVER',
        'PRACTICE_HINT','PRACTICE_FEEDBACK',
        'evidence_audit','adversarial_audit','specification_audit'
    )),
    model_id TEXT NOT NULL,
    provider_label TEXT NOT NULL,
    protocol TEXT NOT NULL,
    region_label TEXT NOT NULL,
    template_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    input_hash TEXT CHECK(
        input_hash IS NULL OR
        (length(input_hash) = 64 AND input_hash NOT GLOB '*[^0-9a-f]*')
    ),
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    latency_ms INTEGER NOT NULL CHECK(latency_ms >= 0),
    input_tokens INTEGER NOT NULL CHECK(input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK(output_tokens >= 0),
    status TEXT NOT NULL
        CHECK(status IN ('COMPLETED','FAILED','UNKNOWN','BLOCKED','LEGACY_COMPLETED')),
    error_class TEXT CHECK(error_class IS NULL OR length(error_class) BETWEEN 1 AND 100),
    provider_response_id TEXT
);

INSERT INTO learning_model_run_evidence_new
SELECT * FROM learning_model_run_evidence;
DROP TABLE learning_model_run_evidence;
ALTER TABLE learning_model_run_evidence_new RENAME TO learning_model_run_evidence;

CREATE INDEX idx_learning_model_run_operation
ON learning_model_run_evidence(workspace_id, operation_id, role);

CREATE TRIGGER validate_model_run_operation_insert
BEFORE INSERT ON learning_model_run_evidence
WHEN NOT EXISTS(
    SELECT 1 FROM learning_operations
    WHERE workspace_id=NEW.workspace_id AND id=NEW.operation_id
)
AND NOT EXISTS(
    SELECT 1 FROM practice_interaction_operations
    WHERE workspace_id=NEW.workspace_id AND operation_id=NEW.operation_id
)
BEGIN
    SELECT RAISE(ABORT, 'Model run does not reference a known operation');
END;

CREATE TRIGGER validate_model_run_operation_update
BEFORE UPDATE OF workspace_id, operation_id ON learning_model_run_evidence
WHEN NOT EXISTS(
    SELECT 1 FROM learning_operations
    WHERE workspace_id=NEW.workspace_id AND id=NEW.operation_id
)
AND NOT EXISTS(
    SELECT 1 FROM practice_interaction_operations
    WHERE workspace_id=NEW.workspace_id AND operation_id=NEW.operation_id
)
BEGIN
    SELECT RAISE(ABORT, 'Model run does not reference a known operation');
END;

CREATE TABLE learning_model_call_reservations_new (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN (
        'planner','teacher','problem','grader','router',
        'reference','preparation','explanation',
        'QUESTION_AUTHOR','QUESTION_BLIND_SOLVER',
        'PRACTICE_HINT','PRACTICE_FEEDBACK',
        'evidence_audit','adversarial_audit','specification_audit'
    )),
    reserved_output_tokens INTEGER NOT NULL CHECK(reserved_output_tokens > 0),
    status TEXT NOT NULL
        CHECK(status IN ('RESERVED','COMPLETED','FAILED','UNKNOWN','BLOCKED')),
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK(output_tokens >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at TEXT,
    quota_scope TEXT NOT NULL DEFAULT 'INTERACTIVE'
        CHECK(quota_scope IN ('INTERACTIVE','BACKGROUND_AUTO_MAP')),
    CHECK(
        (status = 'RESERVED' AND finished_at IS NULL)
        OR (status != 'RESERVED' AND finished_at IS NOT NULL)
    )
);

INSERT INTO learning_model_call_reservations_new
SELECT * FROM learning_model_call_reservations;
DROP TABLE learning_model_call_reservations;
ALTER TABLE learning_model_call_reservations_new RENAME TO learning_model_call_reservations;

CREATE INDEX idx_model_call_reservations_owner_day
ON learning_model_call_reservations(owner_user_id, created_at);

CREATE INDEX idx_model_call_reservations_owner_course_day
ON learning_model_call_reservations(owner_user_id, course_id, created_at);

CREATE TRIGGER validate_model_reservation_operation_insert
BEFORE INSERT ON learning_model_call_reservations
WHEN NOT EXISTS(
    SELECT 1 FROM learning_operations
    WHERE workspace_id=NEW.workspace_id AND id=NEW.operation_id
)
AND NOT EXISTS(
    SELECT 1 FROM practice_interaction_operations
    WHERE workspace_id=NEW.workspace_id AND operation_id=NEW.operation_id
)
BEGIN
    SELECT RAISE(ABORT, 'Model reservation does not reference a known operation');
END;

CREATE TRIGGER validate_model_reservation_operation_update
BEFORE UPDATE OF workspace_id, operation_id ON learning_model_call_reservations
WHEN NOT EXISTS(
    SELECT 1 FROM learning_operations
    WHERE workspace_id=NEW.workspace_id AND id=NEW.operation_id
)
AND NOT EXISTS(
    SELECT 1 FROM practice_interaction_operations
    WHERE workspace_id=NEW.workspace_id AND operation_id=NEW.operation_id
)
BEGIN
    SELECT RAISE(ABORT, 'Model reservation does not reference a known operation');
END;


INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(77,'explicit metered strong review roles');
COMMIT;
PRAGMA legacy_alter_table=OFF;
PRAGMA foreign_keys=ON;
