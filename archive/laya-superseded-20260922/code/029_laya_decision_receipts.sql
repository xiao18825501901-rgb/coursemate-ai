-- Laya semantic-decision call receipts (successor to the retired TypeSafe Jev).
--
-- One row per Laya decision (successful OR failed), so every transport hit is
-- auditable: provider (neutral, "laya"), model revision, definition id + version,
-- compiler version, calibration version, the applied-temperature payload (NULL when
-- the model's identity temperature all-1.0 is in effect), mode (off/shadow/on/
-- advisory), outcome, the authorization/course/version cache-scope keys, the input
-- hash, output_json (the typed suggestion + probability mass + confidence_kind),
-- and latency.
--
-- This is purely additive: migration 028's ``jev_decision_receipts`` table and its
-- executed content are untouched, and historical rows stay readable. No table is
-- renamed, so there are no ``*_new`` / ``*_old`` leftovers.
--
-- The cache lookup index matches the catalog ``cache_scope`` dimensions with the
-- provider-model-version dimension mapped to ``model_revision``, so a
-- material-revision change or an authorization change is a natural cache miss.

CREATE TABLE IF NOT EXISTS laya_decision_receipts (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'laya',
    definition_id TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    compiler_version TEXT NOT NULL,
    calibration_version TEXT,
    temperature TEXT,
    mode TEXT NOT NULL CHECK(mode IN ('off','shadow','on','advisory')),
    outcome TEXT NOT NULL,
    owner_scope_hash TEXT NOT NULL,
    course_id TEXT,
    workspace_id TEXT,
    material_revision TEXT,
    node_id TEXT,
    spec_version TEXT,
    question_hash TEXT,
    input_hash TEXT NOT NULL,
    output_json TEXT NOT NULL,
    latency_ms REAL,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_laya_receipts_cache
ON laya_decision_receipts(
    definition_id, owner_scope_hash, course_id, workspace_id, material_revision,
    node_id, spec_version, question_hash, input_hash, model_revision, created_at DESC
);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(29, 'laya decision receipts');
