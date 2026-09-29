-- Hybrid strict quality review (policy hybrid-strict-v1).
--
-- Additive only.  The pre-existing jev_decision_receipts table, its rows and
-- its historical decoding are untouched: an old TypeSafe/OpenJev receipt keeps
-- its own identity and is never relabelled as a hybrid review.  These tables
-- hold the *new* evidence a hybrid publication needs:
--
--   hybrid_review_calls          one row per strong-review provider call
--   hybrid_local_observations    advisory-only local (OpenJev) observations
--   hybrid_quality_receipts      the final receipt that binds a question
--                                revision to two reviews, the deterministic
--                                report and the optional local observations
--   hybrid_qualifications        a versioned, scoped qualification record
--
-- A qualification row is an *evidence* record, not a permission flag: the gate
-- still re-checks scope, expiry, method identity and every reference at
-- publication time.

CREATE TABLE IF NOT EXISTS hybrid_review_calls (
    id TEXT PRIMARY KEY,
    question_revision_hash TEXT NOT NULL CHECK(length(question_revision_hash) = 64),
    blueprint_hash TEXT NOT NULL CHECK(length(blueprint_hash) = 64),
    evidence_pack_hash TEXT NOT NULL CHECK(length(evidence_pack_hash) = 64),
    policy_revision TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('evidence_audit','adversarial_audit')),
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
    UNIQUE(question_revision_hash, role, input_hash)
);

CREATE INDEX IF NOT EXISTS hybrid_review_calls_by_question
ON hybrid_review_calls(question_revision_hash, role, created_at);

CREATE TABLE IF NOT EXISTS hybrid_local_observations (
    id TEXT PRIMARY KEY,
    question_revision_hash TEXT NOT NULL CHECK(length(question_revision_hash) = 64),
    case_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('OBSERVED','SKIPPED','UNAVAILABLE')),
    verdict TEXT,
    probabilities_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(probabilities_json)),
    model_revision TEXT,
    dtype TEXT,
    tokenizer_hash TEXT,
    transform_version TEXT,
    model_input_hash TEXT,
    state_tokens INTEGER CHECK(state_tokens IS NULL OR state_tokens >= 0),
    reason TEXT,
    latency_ms REAL CHECK(latency_ms IS NULL OR latency_ms >= 0),
    qualification TEXT NOT NULL DEFAULT 'UNQUALIFIED_ADVISORY',
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS hybrid_local_observations_by_question
ON hybrid_local_observations(question_revision_hash, case_key);

CREATE TABLE IF NOT EXISTS hybrid_quality_receipts (
    id TEXT PRIMARY KEY,
    question_revision_hash TEXT NOT NULL CHECK(length(question_revision_hash) = 64),
    blueprint_hash TEXT NOT NULL CHECK(length(blueprint_hash) = 64),
    evidence_pack_hash TEXT NOT NULL CHECK(length(evidence_pack_hash) = 64),
    policy_revision TEXT NOT NULL,
    method_identity TEXT NOT NULL CHECK(length(method_identity) = 64),
    qualification_id TEXT NOT NULL,
    owner_scope_hash TEXT NOT NULL CHECK(length(owner_scope_hash) = 64),
    course_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    spec_version INTEGER NOT NULL CHECK(spec_version >= 1),
    language TEXT NOT NULL,
    domain TEXT NOT NULL,
    required_cases_json TEXT NOT NULL CHECK(json_valid(required_cases_json)),
    case_outcomes_json TEXT NOT NULL CHECK(json_valid(case_outcomes_json)),
    projected_verdicts_json TEXT NOT NULL CHECK(json_valid(projected_verdicts_json)),
    review_call_ids_json TEXT NOT NULL CHECK(json_valid(review_call_ids_json)),
    local_observation_ids_json TEXT NOT NULL DEFAULT '[]'
        CHECK(json_valid(local_observation_ids_json)),
    local_status TEXT NOT NULL DEFAULT 'NOT_APPLICABLE',
    deterministic_report_json TEXT NOT NULL CHECK(json_valid(deterministic_report_json)),
    deterministic_digest TEXT NOT NULL CHECK(length(deterministic_digest) = 64),
    reasons_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(reasons_json)),
    status TEXT NOT NULL CHECK(status IN ('QUALITY_ACCEPTED','QUALITY_NOT_ACCEPTED')),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(question_revision_hash, policy_revision, method_identity)
);

CREATE INDEX IF NOT EXISTS hybrid_quality_receipts_by_question
ON hybrid_quality_receipts(question_revision_hash, policy_revision);

CREATE TABLE IF NOT EXISTS hybrid_qualifications (
    id TEXT PRIMARY KEY,
    policy_revision TEXT NOT NULL,
    method_identity TEXT NOT NULL CHECK(length(method_identity) = 64),
    status TEXT NOT NULL CHECK(status IN (
        'DRAFT','SCOPED_QUALITY_ACCEPTED','WITHDRAWN'
    )),
    reviewer_label TEXT NOT NULL CHECK(reviewer_label IN (
        'SCOPED_QUALITY_ACCEPTED','PROVEN_IDENTICAL_TO_JEV'
    )),
    languages_json TEXT NOT NULL CHECK(json_valid(languages_json)),
    domains_json TEXT NOT NULL CHECK(json_valid(domains_json)),
    cases_json TEXT NOT NULL CHECK(json_valid(cases_json)),
    roles_json TEXT NOT NULL CHECK(json_valid(roles_json)),
    sample_counts_json TEXT NOT NULL CHECK(json_valid(sample_counts_json)),
    metrics_json TEXT NOT NULL CHECK(json_valid(metrics_json)),
    evidence_manifest_digest TEXT NOT NULL CHECK(length(evidence_manifest_digest) = 64),
    observed_model_facts_json TEXT NOT NULL DEFAULT '{}'
        CHECK(json_valid(observed_model_facts_json)),
    expires_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS hybrid_qualifications_lookup
ON hybrid_qualifications(policy_revision, method_identity, active);

-- Append-only: a published hybrid receipt is audit history and must survive a
-- later policy revision rather than being rewritten in place.
CREATE TRIGGER IF NOT EXISTS hybrid_quality_receipts_no_update
BEFORE UPDATE ON hybrid_quality_receipts
BEGIN
    SELECT RAISE(ABORT, 'Hybrid quality receipts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS hybrid_quality_receipts_no_delete
BEFORE DELETE ON hybrid_quality_receipts
BEGIN
    SELECT RAISE(ABORT, 'Hybrid quality receipts are immutable');
END;

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
VALUES(65,'hybrid strict quality review receipts and qualification');
