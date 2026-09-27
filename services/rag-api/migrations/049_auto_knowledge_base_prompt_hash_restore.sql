-- A short-lived release changed the common automatic-map Prompt before an
-- already-authorized exact REQUIRED-item r3 repair could run.  Accepted paid
-- artifacts then correctly rejected replay under the different input hash,
-- consuming the generic artifact-rehydration receipt without sending r3.
--
-- V49 widens only the immutable recovery-reason ledger. Application code is
-- still the authorization gate: it requires the exact historical hash-conflict
-- message, the prior REQUIRED_ITEM_REPAIR_V1 and rehydration receipts, durable
-- rejected r2 evidence, and proof that no r3 attempt/reservation/artifact exists.

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
        'BASE_PROMPT_HASH_RESTORE_V1'
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
VALUES(49,'automatic knowledge-map base Prompt hash restoration');
