-- Jev semantic-decision call receipts and the suggestion cache.
--
-- One row per gateway call (successful OR failed), so every transport hit is
-- auditable: model/version, definition key, primitive, mode (off/shadow/on),
-- caller role, the authorization/course/version scope, the input hash and the
-- outcome. The ``output_json`` carries the typed suggestion (choice / noul
-- probability / score level) — never a grade and never a state write.
--
-- The cache lookup index below matches the catalog ``cache_scope`` dimensions
-- (authorization scope, course, workspace, material revision, node/spec,
-- question definition hash, input hash, provider model version), so a
-- material-revision change or an authorization change is a natural cache miss.
--
-- Jev never writes learning state, grades, LEARNED or budgets; this table is the
-- ONLY thing the semantic layer may write.

CREATE TABLE IF NOT EXISTS jev_decision_receipts (
    id TEXT PRIMARY KEY,
    definition_key TEXT NOT NULL,
    primitive TEXT NOT NULL CHECK(primitive IN ('Choice','Noul','Score')),
    mode TEXT NOT NULL CHECK(mode IN ('off','shadow','on')),
    caller_role TEXT NOT NULL,
    owner_scope_hash TEXT NOT NULL,
    course_id TEXT,
    workspace_id TEXT,
    material_revision TEXT,
    node_id TEXT,
    spec_version TEXT,
    question_hash TEXT,
    input_hash TEXT NOT NULL,
    output_json TEXT NOT NULL,
    outcome TEXT NOT NULL,
    latency_ms REAL,
    model_version TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_jev_receipts_cache
ON jev_decision_receipts(
    definition_key, owner_scope_hash, course_id, workspace_id, material_revision,
    node_id, spec_version, question_hash, input_hash, model_version, created_at DESC
);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(28, 'jev decision receipts');
