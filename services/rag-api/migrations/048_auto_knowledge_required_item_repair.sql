-- A complete production Teaching-Spec response can still fail the schema when
-- one node contains items but none is explicitly REQUIRED.  The ordinary two
-- repairs stay the default.  V48 records one narrowly classified, auditable
-- final prompt repair for that exact complete-response defect only.

DROP TRIGGER IF EXISTS immutable_auto_knowledge_recovery_update;
DROP TRIGGER IF EXISTS immutable_auto_knowledge_recovery_delete;

CREATE TABLE auto_knowledge_job_recovery_receipts_new (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES auto_knowledge_jobs(id) ON DELETE RESTRICT,
    reason TEXT NOT NULL CHECK(reason IN (
        'BACKGROUND_QUOTA_SCOPE_V1',
        'PER_SHARD_REPAIR_SCOPE_V1',
        'FINAL_DISPOSITION_NORMALIZATION_V1',
        'REPAIRED_ARTIFACT_REHYDRATION_V1',
        'LEGACY_REJECTION_FEEDBACK_REHYDRATION_V1',
        'STAGED_COURSE_WORKSPACE_V1',
        'REQUIRED_ITEM_REPAIR_V1'
    )),
    prior_receipt_json TEXT NOT NULL CHECK(json_valid(prior_receipt_json)),
    prior_receipt_hash TEXT NOT NULL CHECK(
        length(prior_receipt_hash)=64
        AND prior_receipt_hash NOT GLOB '*[^0-9a-f]*'
    ),
    blocked_operation_ids_json TEXT NOT NULL CHECK(json_valid(blocked_operation_ids_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(job_id,reason)
);

INSERT INTO auto_knowledge_job_recovery_receipts_new(
    id,job_id,reason,prior_receipt_json,prior_receipt_hash,
    blocked_operation_ids_json,created_at
)
SELECT
    id,job_id,reason,prior_receipt_json,prior_receipt_hash,
    blocked_operation_ids_json,created_at
FROM auto_knowledge_job_recovery_receipts;

DROP TABLE auto_knowledge_job_recovery_receipts;
ALTER TABLE auto_knowledge_job_recovery_receipts_new
RENAME TO auto_knowledge_job_recovery_receipts;

-- Ordinal 3 is valid only when application code has already written the exact
-- REQUIRED_ITEM_REPAIR_V1 recovery receipt.  The database widens storage; the
-- service remains the authorization gate and keeps every other shard at two.
CREATE TABLE auto_knowledge_repair_reservations_new (
    job_id TEXT NOT NULL REFERENCES auto_knowledge_jobs(id) ON DELETE RESTRICT,
    stage TEXT NOT NULL CHECK(stage IN ('SECTION_MAP','TEACHING_SPEC')),
    shard_key TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 3),
    operation_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(job_id,stage,shard_key,ordinal)
);

INSERT INTO auto_knowledge_repair_reservations_new(
    job_id,stage,shard_key,ordinal,operation_id,created_at
)
SELECT job_id,stage,shard_key,ordinal,operation_id,created_at
FROM auto_knowledge_repair_reservations;

DROP TABLE auto_knowledge_repair_reservations;
ALTER TABLE auto_knowledge_repair_reservations_new
RENAME TO auto_knowledge_repair_reservations;

CREATE TRIGGER immutable_auto_knowledge_recovery_update
BEFORE UPDATE ON auto_knowledge_job_recovery_receipts
BEGIN
    SELECT RAISE(ABORT, 'Automatic-map recovery receipts are immutable');
END;

CREATE TRIGGER immutable_auto_knowledge_recovery_delete
BEFORE DELETE ON auto_knowledge_job_recovery_receipts
BEGIN
    SELECT RAISE(ABORT, 'Automatic-map recovery receipts are immutable');
END;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(48,'automatic knowledge-map required-item prompt repair');
