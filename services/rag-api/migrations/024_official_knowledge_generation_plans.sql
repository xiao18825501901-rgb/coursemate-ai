-- Additive M6D4 bulk-generation plan ledger. The course builder persists one
-- generation plan per course so multi-batch runs are resumable and auditable
-- without inventing content or bypassing any existing gate. Older releases
-- never read this table, so application rollback stays compatible.

CREATE TABLE IF NOT EXISTS official_knowledge_generation_plans (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    plan_hash TEXT NOT NULL CHECK(length(plan_hash) = 64),
    plan_json TEXT NOT NULL CHECK(json_valid(plan_json)),
    builder_version TEXT NOT NULL,
    corpus_fingerprint TEXT NOT NULL CHECK(length(corpus_fingerprint) = 64),
    status TEXT NOT NULL CHECK(status IN ('GENERATING','FINALIZED','SUPERSEDED')),
    node_count INTEGER NOT NULL DEFAULT 0 CHECK(node_count >= 0),
    progress_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(progress_json)),
    final_tree_version_id TEXT REFERENCES knowledge_tree_versions(id),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_generation_plans_course
ON official_knowledge_generation_plans(course_id, status, updated_at);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(24, 'official knowledge generation plans');
