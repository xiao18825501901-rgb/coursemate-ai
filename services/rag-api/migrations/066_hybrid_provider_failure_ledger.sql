-- Hybrid provider failure ledger (additive; 065 is not modified).
--
-- Why this exists: a stored qualification run recorded only `HYBRID_REVIEW_PROVIDER_FAILED`
-- with a row id and a step number.  The provider adapter had already produced
-- error_class, terminal status, latency, response id and token counts, and the
-- reviewer carried them on the exception -- and the orchestration persisted none
-- of them.  So the 32 provider failures in the stored runs cannot be attributed
-- to a layer (local validation, HTTP/permission, transport timeout, provider
-- incomplete, empty body, complete-response schema failure, local durability),
-- and the documented rule that a schema failure is not an upstream outage stays
-- unenforceable in practice.
--
-- This table is append-only for the same reason the other ledgers are: a failure
-- is evidence about a real, metered call, and rewriting it would destroy the only
-- record that the call happened.
--
-- It deliberately does NOT reuse hybrid_review_calls.  That table is keyed
-- UNIQUE(question_revision_hash, role, input_hash) and its json columns are NOT
-- NULL, so a failure row there would block the legitimate retry of the same
-- input, which is the opposite of what a failure ledger is for.

CREATE TABLE IF NOT EXISTS hybrid_provider_failures (
    id TEXT PRIMARY KEY,
    question_revision_hash TEXT CHECK(question_revision_hash IS NULL OR length(question_revision_hash) = 64),
    blueprint_hash TEXT CHECK(blueprint_hash IS NULL OR length(blueprint_hash) = 64),
    evidence_pack_hash TEXT CHECK(evidence_pack_hash IS NULL OR length(evidence_pack_hash) = 64),
    policy_revision TEXT NOT NULL,
    role TEXT NOT NULL,
    call_id TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK(length(input_hash) = 64),
    model TEXT NOT NULL,
    provider TEXT NOT NULL,
    protocol TEXT NOT NULL,
    region TEXT NOT NULL,
    template_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    terminal_status TEXT NOT NULL CHECK(terminal_status IN ('BLOCKED','FAILED','UNKNOWN')),
    error_class TEXT NOT NULL,
    failure_layer TEXT NOT NULL CHECK(failure_layer IN (
        'LOCAL_INPUT_VALIDATION',
        'LOCAL_CONFIGURATION',
        'LOCAL_DURABILITY',
        'HTTP_OR_PERMISSION',
        'UPSTREAM_TRANSPORT',
        'PROVIDER_INCOMPLETE',
        'PROVIDER_EMPTY_OR_REFUSAL',
        'RESPONSE_SCHEMA',
        'SEMANTIC_OR_REFERENCE',
        'UNKNOWN'
    )),
    http_status INTEGER CHECK(http_status IS NULL OR http_status BETWEEN 100 AND 599),
    timeout_kind TEXT,
    cause_chain_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(cause_chain_json)),
    latency_ms INTEGER NOT NULL DEFAULT 0 CHECK(latency_ms >= 0),
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK(output_tokens >= 0),
    provider_response_id TEXT,
    response_received INTEGER NOT NULL DEFAULT 0 CHECK(response_received IN (0,1)),
    output_limit_tokens INTEGER,
    response_digest TEXT CHECK(response_digest IS NULL OR length(response_digest) = 64),
    response_text TEXT,
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS hybrid_provider_failures_by_question
ON hybrid_provider_failures(question_revision_hash, role, created_at);

CREATE INDEX IF NOT EXISTS hybrid_provider_failures_by_layer
ON hybrid_provider_failures(failure_layer, error_class, created_at);

CREATE TRIGGER IF NOT EXISTS hybrid_provider_failures_no_update
BEFORE UPDATE ON hybrid_provider_failures
BEGIN
    SELECT RAISE(ABORT, 'Hybrid provider failures are immutable');
END;

CREATE TRIGGER IF NOT EXISTS hybrid_provider_failures_no_delete
BEFORE DELETE ON hybrid_provider_failures
BEGIN
    SELECT RAISE(ABORT, 'Hybrid provider failures are immutable');
END;


-- ---------------------------------------------------------------------------
-- Widening the call identity of hybrid_review_calls (065 itself is untouched).
--
-- Two measured defects in the 065 shape:
--
-- 1. Its unique key is (question_revision_hash, role, input_hash), and the
--    provider's input hash covers the authorised context and the output schema
--    but NOT the instructions.  The same question reviewed under a new prompt
--    version therefore collides with the old row, which makes the documented
--    rule -- a new schema or input version produces a new receipt -- impossible
--    to record.
-- 2. The writer used INSERT OR REPLACE.  SQLite fires a BEFORE DELETE trigger
--    from REPLACE only when PRAGMA recursive_triggers is on, and it defaults to
--    off (measured on the runtime: 0).  So the append-only triggers did not
--    protect the row and an existing call row was silently replaced.  The writer
--    now uses a plain INSERT: a duplicate identity refuses loudly instead of
--    overwriting audit history.
--
-- This rebuild copies every existing row and re-creates the index and both
-- triggers.  Production held zero rows in this table when it ran; the rehearsal
-- compares the row count and a content digest across the rebuild rather than
-- assuming it is lossless.
DROP TRIGGER IF EXISTS hybrid_review_calls_no_update;
DROP TRIGGER IF EXISTS hybrid_review_calls_no_delete;
DROP INDEX IF EXISTS hybrid_review_calls_by_question;
ALTER TABLE hybrid_review_calls RENAME TO hybrid_review_calls_v65;

CREATE TABLE hybrid_review_calls (
    id TEXT PRIMARY KEY,
    question_revision_hash TEXT NOT NULL CHECK(length(question_revision_hash) = 64),
    blueprint_hash TEXT NOT NULL CHECK(length(blueprint_hash) = 64),
    evidence_pack_hash TEXT NOT NULL CHECK(length(evidence_pack_hash) = 64),
    policy_revision TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN (
        'evidence_audit','adversarial_audit','specification_audit'
    )),
    call_id TEXT NOT NULL,
    model TEXT NOT NULL,
    provider TEXT NOT NULL,
    protocol TEXT NOT NULL,
    region TEXT NOT NULL,
    template_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK(length(input_hash) = 64),
    response_digest TEXT NOT NULL CHECK(length(response_digest) = 64),
    response_json TEXT NOT NULL CHECK(json_valid(response_json)),
    findings_json TEXT NOT NULL CHECK(json_valid(findings_json)),
    verification_json TEXT NOT NULL CHECK(json_valid(verification_json)),
    references_verified INTEGER NOT NULL CHECK(references_verified IN (0,1)),
    terminal TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK(output_tokens >= 0),
    latency_ms INTEGER NOT NULL DEFAULT 0 CHECK(latency_ms >= 0),
    provider_response_id TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(question_revision_hash, role, input_hash, template_version, schema_version)
);

INSERT INTO hybrid_review_calls (id,question_revision_hash,blueprint_hash,evidence_pack_hash,policy_revision,role,call_id,model,provider,protocol,region,template_version,schema_version,input_hash,response_digest,response_json,findings_json,verification_json,references_verified,terminal,input_tokens,output_tokens,latency_ms,provider_response_id,created_at)
SELECT id,question_revision_hash,blueprint_hash,evidence_pack_hash,policy_revision,role,call_id,model,provider,protocol,region,template_version,schema_version,input_hash,response_digest,response_json,findings_json,verification_json,references_verified,terminal,input_tokens,output_tokens,latency_ms,provider_response_id,created_at FROM hybrid_review_calls_v65;

DROP TABLE hybrid_review_calls_v65;

CREATE INDEX IF NOT EXISTS hybrid_review_calls_by_question
ON hybrid_review_calls(question_revision_hash, role, created_at);

CREATE TRIGGER IF NOT EXISTS hybrid_review_calls_no_update
BEFORE UPDATE ON hybrid_review_calls
BEGIN
    SELECT RAISE(ABORT, 'Hybrid review calls are immutable');
END;

CREATE TRIGGER IF NOT EXISTS hybrid_review_calls_no_delete
BEFORE DELETE ON hybrid_review_calls
BEGIN
    SELECT RAISE(ABORT, 'Hybrid review calls are immutable');
END;
INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(66,'hybrid provider failure ledger with a named failure layer');
