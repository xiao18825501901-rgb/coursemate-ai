CREATE TABLE IF NOT EXISTS compact_node_mappings (
    id TEXT PRIMARY KEY,
    compact_tree_version_id TEXT NOT NULL
        REFERENCES knowledge_tree_versions(id) ON DELETE RESTRICT,
    compact_node_id TEXT REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    legacy_tree_version_id TEXT NOT NULL
        REFERENCES knowledge_tree_versions(id) ON DELETE RESTRICT,
    legacy_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    relation TEXT NOT NULL CHECK (relation IN ('EXACT','MERGED_INTO','RELATED','UNMAPPED')),
    shared_evidence_count INTEGER NOT NULL DEFAULT 0 CHECK (shared_evidence_count >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (compact_tree_version_id, legacy_tree_version_id, legacy_node_id),
    CHECK (relation='UNMAPPED' OR compact_node_id IS NOT NULL),
    CHECK (relation!='UNMAPPED' OR compact_node_id IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_compact_mapping_legacy
ON compact_node_mappings(legacy_tree_version_id, legacy_node_id);

CREATE TABLE IF NOT EXISTS compact_pair_selections (
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE CASCADE,
    compact_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    primary_pair_id TEXT NOT NULL REFERENCES learning_pairs(id) ON DELETE RESTRICT,
    selected_from_legacy_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    selected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (workspace_id, compact_node_id)
);

CREATE TABLE IF NOT EXISTS compact_tree_receipts (
    compact_tree_version_id TEXT PRIMARY KEY
        REFERENCES knowledge_tree_versions(id) ON DELETE RESTRICT,
    legacy_tree_version_id TEXT NOT NULL
        REFERENCES knowledge_tree_versions(id) ON DELETE RESTRICT,
    legacy_member_count INTEGER NOT NULL CHECK (legacy_member_count > 50),
    compact_member_count INTEGER NOT NULL CHECK (compact_member_count BETWEEN 1 AND 50),
    exact_node_reuse_count INTEGER NOT NULL DEFAULT 0,
    mapped_legacy_count INTEGER NOT NULL DEFAULT 0,
    unmapped_legacy_count INTEGER NOT NULL DEFAULT 0,
    source_coverage_json TEXT NOT NULL CHECK (json_valid(source_coverage_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(58, 'compact tree lineage progress and primary pair selection');
