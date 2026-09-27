-- Durable pre-parse response evidence for automatic knowledge-map generation.
--
-- The generic model-call ledger records intent, usage and transport outcome but
-- intentionally does not retain private response bodies.  Automatic course
-- builds need a narrower, permission-bound record so a complete paid response
-- is saved before schema/business validation and can be diagnosed without
-- repeating a charge.  Rows are owned by an existing frozen build job and are
-- never exposed through the learner status API.

CREATE TABLE IF NOT EXISTS auto_knowledge_model_attempts (
    operation_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES auto_knowledge_jobs(id) ON DELETE RESTRICT,
    stage TEXT NOT NULL CHECK(stage IN ('SECTION_MAP','TEACHING_SPEC')),
    shard_key TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK(length(input_hash)=64),
    status TEXT NOT NULL CHECK(status IN (
        'SEND_INTENT','RESPONSE_SAVED','CONTRACT_VALID','BUSINESS_REJECTED',
        'ACCEPTED','RESPONSE_UNKNOWN','CONTRACT_REJECTED'
    )),
    provider_response_id TEXT,
    output_text TEXT,
    output_hash TEXT CHECK(output_hash IS NULL OR length(output_hash)=64),
    rejection_code TEXT,
    rejection_detail_json TEXT NOT NULL DEFAULT '{}'
        CHECK(json_valid(rejection_detail_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(job_id,stage,shard_key,operation_id),
    CHECK(
        (status='SEND_INTENT' AND output_text IS NULL AND output_hash IS NULL)
        OR status!='SEND_INTENT'
    )
);

CREATE INDEX IF NOT EXISTS idx_auto_knowledge_attempts_job
ON auto_knowledge_model_attempts(job_id,stage,shard_key,created_at);

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(43,'durable automatic knowledge-map model attempts');
