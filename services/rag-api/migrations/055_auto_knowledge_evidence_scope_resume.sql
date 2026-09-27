-- V54 briefly treated one shard's local-normalization receipt as though it
-- applied to every shard in the same course build. V55 admits one exact,
-- receipted no-dispatch resume for that terminal state.

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
        'REQUIRED_ITEM_REPAIR_V1',
        'BASE_PROMPT_HASH_RESTORE_V1',
        'UNIQUE_KEY_REPAIR_V1',
        'EVIDENCE_SCOPE_REPAIR_V1',
        'EVIDENCE_SCOPE_NORMALIZATION_V1',
        'EVIDENCE_SCOPE_NORMALIZATION_RETRY_V1',
        'EVIDENCE_SCOPE_RESUME_V1'
    )),
    prior_receipt_json TEXT NOT NULL CHECK(json_valid(prior_receipt_json)),
    prior_receipt_hash TEXT NOT NULL CHECK(
        length(prior_receipt_hash)=64
        AND prior_receipt_hash NOT GLOB '*[^0-9a-f]*'
    ),
    blocked_operation_ids_json TEXT NOT NULL CHECK(json_valid(blocked_operation_ids_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(job_id,reason,blocked_operation_ids_json)
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
VALUES(55,'automatic knowledge-map atomic-evidence no-dispatch resume');
