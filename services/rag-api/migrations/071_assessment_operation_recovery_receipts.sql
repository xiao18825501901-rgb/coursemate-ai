-- Immutable receipts for narrowly scoped configured-assessment recovery.
-- Only identifiers, hashes, and safe state metadata are stored here.

CREATE TABLE IF NOT EXISTS assessment_operation_recovery_receipts (
    id TEXT PRIMARY KEY,
    plan_hash TEXT NOT NULL CHECK(
        length(plan_hash)=64 AND plan_hash NOT GLOB '*[^0-9a-f]*'
    ),
    preparation_id TEXT NOT NULL
        REFERENCES assessment_configuration_preparations(id) ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    operation_id TEXT NOT NULL,
    retry_of_operation_id TEXT,
    action TEXT NOT NULL CHECK(action IN (
        'SETTLE_READY_PARENT','REGISTER_RETRY_EPOCH'
    )),
    before_hash TEXT NOT NULL CHECK(length(before_hash)=64),
    after_hash TEXT NOT NULL CHECK(length(after_hash)=64),
    details_json TEXT NOT NULL CHECK(json_valid(details_json)),
    model_calls_added INTEGER NOT NULL DEFAULT 0 CHECK(model_calls_added=0),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(plan_hash,preparation_id)
);

CREATE TRIGGER IF NOT EXISTS immutable_assessment_operation_recovery_receipt_update
BEFORE UPDATE ON assessment_operation_recovery_receipts
BEGIN
    SELECT RAISE(ABORT, 'Assessment operation recovery receipts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_assessment_operation_recovery_receipt_delete
BEFORE DELETE ON assessment_operation_recovery_receipts
BEGIN
    SELECT RAISE(ABORT, 'Assessment operation recovery receipts are immutable');
END;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(71,'configured assessment operation recovery receipts');
