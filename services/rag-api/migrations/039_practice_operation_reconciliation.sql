-- Meter diagnostic practice calls through the existing model-call ledger and
-- add append-only operator evidence for claims orphaned by process death.
--
-- A practice CLAIMED row alone cannot prove whether a paid request was sent.
-- New claims therefore receive an immutable metering guard in the same local
-- transaction.  The existing reservation/run-evidence ledgers then distinguish
-- no reservation, terminal failure, completed upstream work and unknown state.
-- Reconciliation never deletes or reopens the original operation and never
-- reuses its operation id for another provider call.

PRAGMA foreign_keys=OFF;
PRAGMA legacy_alter_table=ON;

CREATE TABLE learning_model_run_evidence_new (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN (
        'planner','teacher','problem','grader','router',
        'reference','preparation','explanation',
        'QUESTION_AUTHOR','QUESTION_BLIND_SOLVER',
        'PRACTICE_HINT','PRACTICE_FEEDBACK'
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
        'PRACTICE_HINT','PRACTICE_FEEDBACK'
    )),
    reserved_output_tokens INTEGER NOT NULL CHECK(reserved_output_tokens > 0),
    status TEXT NOT NULL
        CHECK(status IN ('RESERVED','COMPLETED','FAILED','UNKNOWN','BLOCKED')),
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK(output_tokens >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at TEXT,
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

CREATE TRIGGER IF NOT EXISTS restrict_metered_learning_operation_delete
BEFORE DELETE ON learning_operations
WHEN EXISTS(
    SELECT 1 FROM learning_model_call_reservations
    WHERE workspace_id=OLD.workspace_id AND operation_id=OLD.id
)
OR EXISTS(
    SELECT 1 FROM learning_model_run_evidence
    WHERE workspace_id=OLD.workspace_id AND operation_id=OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'Metered learning operations cannot be deleted');
END;

CREATE TABLE IF NOT EXISTS practice_operation_metering_guards (
    workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    guard_version TEXT NOT NULL CHECK(guard_version='metered-practice.v1'),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(workspace_id, operation_id),
    FOREIGN KEY(workspace_id, operation_id)
        REFERENCES practice_interaction_operations(workspace_id, operation_id)
        ON DELETE RESTRICT
);

CREATE TRIGGER IF NOT EXISTS immutable_practice_metering_guard_update
BEFORE UPDATE ON practice_operation_metering_guards
BEGIN
    SELECT RAISE(ABORT, 'Practice operation metering guards are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_practice_metering_guard_delete
BEFORE DELETE ON practice_operation_metering_guards
BEGIN
    SELECT RAISE(ABORT, 'Practice operation metering guards are immutable');
END;

CREATE TABLE IF NOT EXISTS practice_operation_reconciliations (
    id TEXT PRIMARY KEY CHECK(length(trim(id)) BETWEEN 8 AND 100),
    workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK(disposition IN (
        'NOT_SENT','UPSTREAM_FAILED','UPSTREAM_UNKNOWN','UPSTREAM_COMPLETED_NO_RESULT'
    )),
    evidence_hash TEXT NOT NULL CHECK(
        length(evidence_hash)=64 AND evidence_hash NOT GLOB '*[^0-9a-f]*'
    ),
    operator_ref TEXT NOT NULL CHECK(length(trim(operator_ref)) BETWEEN 1 AND 150),
    supersedes_id TEXT REFERENCES practice_operation_reconciliations(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(workspace_id, operation_id)
        REFERENCES practice_interaction_operations(workspace_id, operation_id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_practice_reconciliation_operation
ON practice_operation_reconciliations(workspace_id, operation_id, created_at);

CREATE TRIGGER IF NOT EXISTS immutable_practice_reconciliation_update
BEFORE UPDATE ON practice_operation_reconciliations
BEGIN
    SELECT RAISE(ABORT, 'Practice operation reconciliations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_practice_reconciliation_delete
BEFORE DELETE ON practice_operation_reconciliations
BEGIN
    SELECT RAISE(ABORT, 'Practice operation reconciliations are immutable');
END;

PRAGMA legacy_alter_table=OFF;
PRAGMA foreign_keys=ON;

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(39, 'metered practice operations and explicit reconciliation evidence');
