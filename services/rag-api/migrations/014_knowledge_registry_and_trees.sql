-- Additive Knowledge Registry, immutable Spec items, and versioned tree views.
-- Existing node/spec/journey IDs remain authoritative and are never rewritten.

CREATE TABLE IF NOT EXISTS knowledge_node_aliases (
    node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    alias TEXT NOT NULL CHECK(length(trim(alias)) BETWEEN 1 AND 200),
    normalized_alias TEXT NOT NULL CHECK(length(normalized_alias) BETWEEN 1 AND 200),
    locale TEXT NOT NULL DEFAULT 'und' CHECK(length(locale) BETWEEN 1 AND 20),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(node_id, normalized_alias, locale)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_alias_lookup
ON knowledge_node_aliases(normalized_alias, locale, node_id);

CREATE TABLE IF NOT EXISTS knowledge_node_lineage (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    from_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    to_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    operation TEXT NOT NULL CHECK(operation IN ('MERGE','SPLIT','REPLACED_BY')),
    reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
    actor_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK(from_node_id != to_node_id),
    UNIQUE(from_node_id, to_node_id, operation)
);

CREATE TABLE IF NOT EXISTS material_evidence (
    id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    document_version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE RESTRICT,
    chunk_id TEXT REFERENCES chunks(id) ON DELETE RESTRICT,
    owner_user_id TEXT,
    source_scope TEXT NOT NULL
        CHECK(source_scope IN ('OFFICIAL','OWNER_COURSE','WORKSPACE_PRIVATE')),
    locator_type TEXT NOT NULL CHECK(length(trim(locator_type)) > 0),
    locator_value TEXT NOT NULL CHECK(length(trim(locator_value)) > 0),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','REVOKED')),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK(
        (source_scope = 'OFFICIAL' AND owner_user_id IS NULL)
        OR (source_scope != 'OFFICIAL' AND owner_user_id IS NOT NULL)
    ),
    UNIQUE(node_id, document_version_id, chunk_id, locator_type, locator_value)
);

CREATE INDEX IF NOT EXISTS idx_material_evidence_node
ON material_evidence(node_id, status, source_scope, owner_user_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_material_evidence_identity
ON material_evidence(
    node_id,
    document_version_id,
    COALESCE(chunk_id, '__DOCUMENT_LEVEL__'),
    locator_type,
    locator_value
);

CREATE TABLE IF NOT EXISTS teaching_spec_metadata (
    node_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version >= 1),
    status TEXT NOT NULL
        CHECK(status IN ('DRAFT','PRIVATE_ACTIVE','PUBLISHED','RETIRED')),
    change_reason TEXT NOT NULL DEFAULT 'Initial specification'
        CHECK(length(trim(change_reason)) > 0),
    created_by_user_id TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(node_id, version),
    FOREIGN KEY(node_id, version)
        REFERENCES teaching_specs(node_id, version) ON DELETE RESTRICT
);

INSERT OR IGNORE INTO teaching_spec_metadata(
    node_id, version, status, change_reason, created_by_user_id
)
SELECT
    teaching_specs.node_id,
    teaching_specs.version,
    CASE
        WHEN knowledge_nodes.owner_user_id IS NOT NULL THEN 'PRIVATE_ACTIVE'
        WHEN knowledge_nodes.status = 'PUBLISHED' THEN 'PUBLISHED'
        ELSE 'DRAFT'
    END,
    'Backfilled existing specification',
    knowledge_nodes.owner_user_id
FROM teaching_specs
JOIN knowledge_nodes ON knowledge_nodes.id = teaching_specs.node_id;

CREATE TABLE IF NOT EXISTS teaching_items (
    node_id TEXT NOT NULL,
    spec_version INTEGER NOT NULL CHECK(spec_version >= 1),
    item_id TEXT NOT NULL CHECK(length(item_id) BETWEEN 1 AND 100),
    requirement TEXT NOT NULL
        CHECK(requirement IN ('REQUIRED','RECOMMENDED','OPTIONAL')),
    objective TEXT NOT NULL CHECK(length(trim(objective)) > 0),
    acceptance TEXT NOT NULL CHECK(length(trim(acceptance)) > 0),
    evidence_ids_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(evidence_ids_json)),
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    PRIMARY KEY(node_id, spec_version, item_id),
    UNIQUE(node_id, spec_version, ordinal),
    FOREIGN KEY(node_id, spec_version)
        REFERENCES teaching_specs(node_id, version) ON DELETE RESTRICT
);

INSERT OR IGNORE INTO teaching_items(
    node_id, spec_version, item_id, requirement, objective, acceptance,
    evidence_ids_json, ordinal
)
SELECT
    teaching_specs.node_id,
    teaching_specs.version,
    json_extract(item.value, '$.item_id'),
    json_extract(item.value, '$.requirement'),
    json_extract(item.value, '$.objective'),
    json_extract(item.value, '$.acceptance'),
    COALESCE(json_extract(item.value, '$.evidence_ids'), '[]'),
    CAST(item.key AS INTEGER)
FROM teaching_specs, json_each(teaching_specs.content_json) AS item;

CREATE TRIGGER IF NOT EXISTS normalize_new_teaching_spec
AFTER INSERT ON teaching_specs
BEGIN
    INSERT INTO teaching_spec_metadata(
        node_id, version, status, change_reason, created_by_user_id
    )
    SELECT
        NEW.node_id,
        NEW.version,
        CASE
            WHEN knowledge_nodes.owner_user_id IS NOT NULL THEN 'PRIVATE_ACTIVE'
            WHEN knowledge_nodes.status = 'PUBLISHED' THEN 'PUBLISHED'
            ELSE 'DRAFT'
        END,
        'Initial specification',
        knowledge_nodes.owner_user_id
    FROM knowledge_nodes
    WHERE knowledge_nodes.id = NEW.node_id;

    INSERT INTO teaching_items(
        node_id, spec_version, item_id, requirement, objective, acceptance,
        evidence_ids_json, ordinal
    )
    SELECT
        NEW.node_id,
        NEW.version,
        json_extract(item.value, '$.item_id'),
        json_extract(item.value, '$.requirement'),
        json_extract(item.value, '$.objective'),
        json_extract(item.value, '$.acceptance'),
        COALESCE(json_extract(item.value, '$.evidence_ids'), '[]'),
        CAST(item.key AS INTEGER)
    FROM json_each(NEW.content_json) AS item;
END;

CREATE TRIGGER IF NOT EXISTS immutable_teaching_spec_delete
BEFORE DELETE ON teaching_specs
BEGIN
    SELECT RAISE(ABORT, 'Teaching specifications are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_teaching_items_update
BEFORE UPDATE ON teaching_items
BEGIN
    SELECT RAISE(ABORT, 'Teaching specification items are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_teaching_items_delete
BEFORE DELETE ON teaching_items
BEGIN
    SELECT RAISE(ABORT, 'Teaching specification items are immutable');
END;

CREATE TABLE IF NOT EXISTS knowledge_tree_versions (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    workspace_id TEXT REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    owner_user_id TEXT,
    tree_kind TEXT NOT NULL CHECK(tree_kind IN ('OFFICIAL','PERSONALIZED')),
    version INTEGER NOT NULL CHECK(version >= 1),
    status TEXT NOT NULL CHECK(status IN ('DRAFT','PUBLISHED','ACTIVE','RETIRED')),
    title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 200),
    change_reason TEXT NOT NULL CHECK(length(trim(change_reason)) > 0),
    content_hash TEXT NOT NULL CHECK(length(content_hash) = 64),
    base_tree_version_id TEXT REFERENCES knowledge_tree_versions(id) ON DELETE RESTRICT,
    reviewed_by_user_id TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK(
        (tree_kind = 'OFFICIAL' AND workspace_id IS NULL AND owner_user_id IS NULL
         AND status IN ('DRAFT','PUBLISHED','RETIRED'))
        OR
        (tree_kind = 'PERSONALIZED' AND workspace_id IS NOT NULL
         AND owner_user_id IS NOT NULL AND status IN ('DRAFT','ACTIVE','RETIRED'))
    ),
    CHECK(
        status != 'PUBLISHED'
        OR (reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_official_tree_version
ON knowledge_tree_versions(course_id, version)
WHERE tree_kind = 'OFFICIAL';

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_personal_tree_version
ON knowledge_tree_versions(workspace_id, version)
WHERE tree_kind = 'PERSONALIZED';

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_published_official_tree
ON knowledge_tree_versions(course_id)
WHERE tree_kind = 'OFFICIAL' AND status = 'PUBLISHED';

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_personal_tree
ON knowledge_tree_versions(workspace_id)
WHERE tree_kind = 'PERSONALIZED' AND status = 'ACTIVE';

CREATE TRIGGER IF NOT EXISTS validate_personalized_tree_workspace
BEFORE INSERT ON knowledge_tree_versions
WHEN NEW.tree_kind = 'PERSONALIZED' AND NOT EXISTS(
    SELECT 1
    FROM learning_workspaces
    WHERE id = NEW.workspace_id
      AND course_id = NEW.course_id
      AND owner_user_id = NEW.owner_user_id
)
BEGIN
    SELECT RAISE(ABORT, 'Personalized tree must match workspace identity');
END;

CREATE TABLE IF NOT EXISTS knowledge_tree_memberships (
    tree_version_id TEXT NOT NULL
        REFERENCES knowledge_tree_versions(id) ON DELETE RESTRICT,
    node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    parent_node_id TEXT,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    teaching_spec_version INTEGER,
    PRIMARY KEY(tree_version_id, node_id),
    FOREIGN KEY(tree_version_id, parent_node_id)
        REFERENCES knowledge_tree_memberships(tree_version_id, node_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY(node_id, teaching_spec_version)
        REFERENCES teaching_specs(node_id, version) ON DELETE RESTRICT,
    CHECK(node_id IS NOT parent_node_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tree_sibling_order
ON knowledge_tree_memberships(
    tree_version_id,
    COALESCE(parent_node_id, '__COURSE_ROOT__'),
    ordinal
);

CREATE TRIGGER IF NOT EXISTS validate_tree_membership_insert
BEFORE INSERT ON knowledge_tree_memberships
WHEN NOT EXISTS(
    SELECT 1
    FROM knowledge_tree_versions AS tree
    JOIN knowledge_nodes AS node
      ON node.id = NEW.node_id
     AND node.course_id = tree.course_id
    LEFT JOIN teaching_spec_metadata AS spec
      ON spec.node_id = NEW.node_id
     AND spec.version = NEW.teaching_spec_version
    WHERE tree.id = NEW.tree_version_id
      AND (
        (
          tree.tree_kind = 'OFFICIAL'
          AND node.owner_user_id IS NULL
          AND node.status IN ('CANDIDATE','PUBLISHED')
          AND (
            (node.kind = 'COMPOSITE' AND NEW.teaching_spec_version IS NULL)
            OR
            (node.kind = 'ATOMIC' AND NEW.teaching_spec_version IS NOT NULL
             AND spec.status IN ('DRAFT','PUBLISHED'))
          )
        )
        OR
        (
          tree.tree_kind = 'PERSONALIZED'
          AND (
            (
              node.owner_user_id = tree.owner_user_id
              AND node.status = 'PRIVATE'
              AND (
                (node.kind = 'COMPOSITE' AND NEW.teaching_spec_version IS NULL)
                OR
                (node.kind = 'ATOMIC' AND NEW.teaching_spec_version IS NOT NULL
                 AND spec.status = 'PRIVATE_ACTIVE')
              )
            )
            OR
            (
              node.owner_user_id IS NULL
              AND node.status = 'PUBLISHED'
              AND (
                (node.kind = 'COMPOSITE' AND NEW.teaching_spec_version IS NULL)
                OR
                (node.kind = 'ATOMIC' AND NEW.teaching_spec_version IS NOT NULL
                 AND spec.status = 'PUBLISHED')
              )
            )
          )
        )
      )
)
BEGIN
    SELECT RAISE(ABORT, 'Knowledge node is not an authorized tree source');
END;

CREATE TRIGGER IF NOT EXISTS validate_tree_membership_update
BEFORE UPDATE OF tree_version_id, node_id, teaching_spec_version
ON knowledge_tree_memberships
WHEN NOT EXISTS(
    SELECT 1
    FROM knowledge_tree_versions AS tree
    JOIN knowledge_nodes AS node
      ON node.id = NEW.node_id
     AND node.course_id = tree.course_id
    LEFT JOIN teaching_spec_metadata AS spec
      ON spec.node_id = NEW.node_id
     AND spec.version = NEW.teaching_spec_version
    WHERE tree.id = NEW.tree_version_id
      AND (
        (
          tree.tree_kind = 'OFFICIAL'
          AND node.owner_user_id IS NULL
          AND node.status IN ('CANDIDATE','PUBLISHED')
          AND (
            (node.kind = 'COMPOSITE' AND NEW.teaching_spec_version IS NULL)
            OR
            (node.kind = 'ATOMIC' AND NEW.teaching_spec_version IS NOT NULL
             AND spec.status IN ('DRAFT','PUBLISHED'))
          )
        )
        OR
        (
          tree.tree_kind = 'PERSONALIZED'
          AND (
            (
              node.owner_user_id = tree.owner_user_id
              AND node.status = 'PRIVATE'
              AND (
                (node.kind = 'COMPOSITE' AND NEW.teaching_spec_version IS NULL)
                OR
                (node.kind = 'ATOMIC' AND NEW.teaching_spec_version IS NOT NULL
                 AND spec.status = 'PRIVATE_ACTIVE')
              )
            )
            OR
            (
              node.owner_user_id IS NULL
              AND node.status = 'PUBLISHED'
              AND (
                (node.kind = 'COMPOSITE' AND NEW.teaching_spec_version IS NULL)
                OR
                (node.kind = 'ATOMIC' AND NEW.teaching_spec_version IS NOT NULL
                 AND spec.status = 'PUBLISHED')
              )
            )
          )
        )
      )
)
BEGIN
    SELECT RAISE(ABORT, 'Knowledge node is not an authorized tree source');
END;

CREATE TABLE IF NOT EXISTS knowledge_prerequisite_edges (
    tree_version_id TEXT NOT NULL
        REFERENCES knowledge_tree_versions(id) ON DELETE RESTRICT,
    node_id TEXT NOT NULL,
    prerequisite_node_id TEXT NOT NULL,
    PRIMARY KEY(tree_version_id, node_id, prerequisite_node_id),
    FOREIGN KEY(tree_version_id, node_id)
        REFERENCES knowledge_tree_memberships(tree_version_id, node_id)
        ON DELETE RESTRICT,
    FOREIGN KEY(tree_version_id, prerequisite_node_id)
        REFERENCES knowledge_tree_memberships(tree_version_id, node_id)
        ON DELETE RESTRICT,
    CHECK(node_id != prerequisite_node_id)
);

CREATE TRIGGER IF NOT EXISTS immutable_tree_identity
BEFORE UPDATE OF id, course_id, workspace_id, owner_user_id, tree_kind, version,
                 title, change_reason, content_hash, base_tree_version_id
ON knowledge_tree_versions
BEGIN
    SELECT RAISE(ABORT, 'Knowledge tree versions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_tree_review_metadata
BEFORE UPDATE OF reviewed_by_user_id, reviewed_at ON knowledge_tree_versions
WHEN OLD.status != 'DRAFT' AND (
    NEW.reviewed_by_user_id IS NOT OLD.reviewed_by_user_id
    OR NEW.reviewed_at IS NOT OLD.reviewed_at
)
BEGIN
    SELECT RAISE(ABORT, 'Knowledge tree review metadata is immutable');
END;

CREATE TRIGGER IF NOT EXISTS valid_tree_status_transition
BEFORE UPDATE OF status ON knowledge_tree_versions
WHEN NOT (
    OLD.status = NEW.status
    OR (OLD.status = 'DRAFT' AND OLD.tree_kind = 'OFFICIAL' AND NEW.status = 'PUBLISHED')
    OR (OLD.status = 'DRAFT' AND OLD.tree_kind = 'PERSONALIZED' AND NEW.status = 'ACTIVE')
    OR (OLD.status IN ('PUBLISHED','ACTIVE') AND NEW.status = 'RETIRED')
)
BEGIN
    SELECT RAISE(ABORT, 'Invalid knowledge tree status transition');
END;

CREATE TRIGGER IF NOT EXISTS reviewed_official_tree_has_published_nodes
BEFORE UPDATE OF status ON knowledge_tree_versions
WHEN NEW.status = 'PUBLISHED' AND (
    NOT EXISTS(
        SELECT 1 FROM knowledge_tree_memberships
        WHERE tree_version_id = NEW.id
    )
    OR EXISTS(
        SELECT 1
        FROM knowledge_tree_memberships AS membership
        JOIN knowledge_nodes ON knowledge_nodes.id = membership.node_id
        LEFT JOIN teaching_spec_metadata AS spec
          ON spec.node_id = membership.node_id
         AND spec.version = membership.teaching_spec_version
        WHERE membership.tree_version_id = NEW.id
          AND (
              knowledge_nodes.status != 'PUBLISHED'
              OR (knowledge_nodes.kind = 'ATOMIC' AND (
                  membership.teaching_spec_version IS NULL
                  OR COALESCE(spec.status, '') != 'PUBLISHED'
              ))
              OR (knowledge_nodes.kind = 'COMPOSITE'
                  AND membership.teaching_spec_version IS NOT NULL)
          )
    )
)
BEGIN
    SELECT RAISE(ABORT, 'Published tree members require reviewed nodes and specs');
END;

CREATE TRIGGER IF NOT EXISTS lock_tree_membership_insert
BEFORE INSERT ON knowledge_tree_memberships
WHEN (SELECT status FROM knowledge_tree_versions WHERE id = NEW.tree_version_id) != 'DRAFT'
BEGIN
    SELECT RAISE(ABORT, 'Knowledge tree membership is immutable');
END;

CREATE TRIGGER IF NOT EXISTS lock_tree_membership_update
BEFORE UPDATE ON knowledge_tree_memberships
WHEN (SELECT status FROM knowledge_tree_versions WHERE id = OLD.tree_version_id) != 'DRAFT'
BEGIN
    SELECT RAISE(ABORT, 'Knowledge tree membership is immutable');
END;

CREATE TRIGGER IF NOT EXISTS lock_tree_membership_delete
BEFORE DELETE ON knowledge_tree_memberships
WHEN (SELECT status FROM knowledge_tree_versions WHERE id = OLD.tree_version_id) != 'DRAFT'
BEGIN
    SELECT RAISE(ABORT, 'Knowledge tree membership is immutable');
END;

CREATE TRIGGER IF NOT EXISTS lock_prerequisite_insert
BEFORE INSERT ON knowledge_prerequisite_edges
WHEN (SELECT status FROM knowledge_tree_versions WHERE id = NEW.tree_version_id) != 'DRAFT'
BEGIN
    SELECT RAISE(ABORT, 'Knowledge tree prerequisites are immutable');
END;

CREATE TRIGGER IF NOT EXISTS lock_prerequisite_update
BEFORE UPDATE ON knowledge_prerequisite_edges
WHEN (SELECT status FROM knowledge_tree_versions WHERE id = OLD.tree_version_id) != 'DRAFT'
BEGIN
    SELECT RAISE(ABORT, 'Knowledge tree prerequisites are immutable');
END;

CREATE TRIGGER IF NOT EXISTS lock_prerequisite_delete
BEFORE DELETE ON knowledge_prerequisite_edges
WHEN (SELECT status FROM knowledge_tree_versions WHERE id = OLD.tree_version_id) != 'DRAFT'
BEGIN
    SELECT RAISE(ABORT, 'Knowledge tree prerequisites are immutable');
END;

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(14, 'knowledge registry normalized specs and versioned trees');
