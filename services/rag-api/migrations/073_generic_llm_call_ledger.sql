-- Additive: old learning/assessment/model receipts are not rewritten.
-- A durable send intent without a terminal result must never be replayed.
CREATE TABLE IF NOT EXISTS generic_llm_calls (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    source_visual_job_id TEXT REFERENCES visual_jobs(id) ON DELETE RESTRICT,
    role TEXT NOT NULL CHECK(role IN (
        'TEACH_NORMAL','TEACH_PLAN','TEACH_WORK','QUESTION_TEXT','QUESTION_IMAGE',
        'EXERCISE_AUTHOR','BLIND_SOLVER','ASSESSMENT_AUTHOR','ASSESSMENT_GRADE',
        'LLM_REVIEW','EXPLANATION','HINT','COURSE_CLASSIFY','ASSESSABLE_POINT_COMPILE',
        'TASK_AGENT','VISUAL_LANGUAGE_PLAN'
    )),
    operation_family TEXT NOT NULL,
    policy_version TEXT NOT NULL DEFAULT 'cj.route.v1',
    model_id TEXT NOT NULL DEFAULT 'qwen3.8-max' CHECK(model_id='qwen3.8-max'),
    provider_label TEXT NOT NULL DEFAULT 'ALIBABA_MODEL_STUDIO_COMPATIBLE',
    protocol TEXT NOT NULL DEFAULT 'chat_completions' CHECK(protocol='chat_completions'),
    region_label TEXT NOT NULL DEFAULT 'ENDPOINT_CN',
    provider_revision TEXT,
    revision_status TEXT NOT NULL DEFAULT 'UNKNOWN_UPSTREAM_ALIAS_ONLY',
    capability_receipt_id TEXT NOT NULL,
    secret_generation_id TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK(length(input_hash)=64),
    template_version TEXT NOT NULL,
    template_hash TEXT NOT NULL CHECK(length(template_hash)=64),
    schema_version TEXT NOT NULL,
    content_language TEXT NOT NULL,
    reserved_output_tokens INTEGER NOT NULL DEFAULT 4000 CHECK(reserved_output_tokens BETWEEN 500 AND 8000),
    status TEXT NOT NULL DEFAULT 'RESERVED' CHECK(status IN (
        'RESERVED','SEND_INTENT','COMPLETED','FAILED','UNKNOWN','BLOCKED','CANCELLED'
    )),
    output_json TEXT CHECK(output_json IS NULL OR json_valid(output_json)),
    audit_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(audit_json)),
    input_tokens INTEGER CHECK(input_tokens IS NULL OR input_tokens>=0),
    output_tokens INTEGER CHECK(output_tokens IS NULL OR output_tokens>=0),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    finished_at TEXT,
    UNIQUE(source_visual_job_id,role)
);
CREATE INDEX IF NOT EXISTS idx_generic_llm_daily_budget
ON generic_llm_calls(owner_user_id,course_id,created_at,status);
CREATE TRIGGER IF NOT EXISTS generic_llm_identity_immutable
BEFORE UPDATE OF id,owner_user_id,course_id,source_visual_job_id,role,operation_family,
    policy_version,model_id,provider_label,protocol,region_label,provider_revision,
    revision_status,capability_receipt_id,secret_generation_id,input_hash,template_version,
    template_hash,schema_version,content_language,reserved_output_tokens,created_at
ON generic_llm_calls
BEGIN SELECT RAISE(ABORT,'LLM route identity is immutable'); END;
CREATE TRIGGER IF NOT EXISTS generic_llm_terminal_immutable
BEFORE UPDATE ON generic_llm_calls
WHEN OLD.status IN ('COMPLETED','FAILED','UNKNOWN','BLOCKED','CANCELLED')
BEGIN SELECT RAISE(ABORT,'Terminal LLM receipts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS generic_llm_state_transition
BEFORE UPDATE OF status ON generic_llm_calls
WHEN NOT (
    (OLD.status='RESERVED' AND NEW.status IN ('SEND_INTENT','FAILED','UNKNOWN','BLOCKED','CANCELLED'))
    OR (OLD.status='SEND_INTENT' AND NEW.status IN ('COMPLETED','FAILED','UNKNOWN','CANCELLED'))
)
BEGIN SELECT RAISE(ABORT,'Invalid LLM receipt transition'); END;
CREATE TRIGGER IF NOT EXISTS generic_llm_no_delete BEFORE DELETE ON generic_llm_calls
BEGIN SELECT RAISE(ABORT,'LLM receipts are append-only'); END;
INSERT OR IGNORE INTO schema_migrations(version,name) VALUES(73,'generic LLM immutable call ledger');
