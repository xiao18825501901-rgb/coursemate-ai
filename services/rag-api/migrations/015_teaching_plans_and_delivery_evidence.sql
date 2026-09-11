-- Stage 3 is additive. Existing units and coverage remain available and are labelled
-- LEGACY_PRESERVED instead of being silently upgraded to the stronger V3.2 contract.

CREATE TABLE IF NOT EXISTS learning_preference_versions (
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL CHECK(version >= 1),
    preference_hash TEXT NOT NULL
        CHECK(length(preference_hash) = 64 AND preference_hash NOT GLOB '*[^0-9a-f]*'),
    preference_json TEXT NOT NULL CHECK(json_valid(preference_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(workspace_id, version),
    UNIQUE(workspace_id, preference_hash)
);

CREATE TRIGGER IF NOT EXISTS immutable_learning_preference_update
BEFORE UPDATE ON learning_preference_versions
BEGIN
    SELECT RAISE(ABORT, 'Learning preference versions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_learning_preference_delete
BEFORE DELETE ON learning_preference_versions
BEGIN
    SELECT RAISE(ABORT, 'Learning preference versions are immutable');
END;

CREATE TABLE IF NOT EXISTS teaching_plan_versions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    journey_id TEXT NOT NULL REFERENCES learning_journeys(id) ON DELETE RESTRICT,
    node_id TEXT NOT NULL,
    spec_version INTEGER NOT NULL CHECK(spec_version >= 1),
    version INTEGER NOT NULL CHECK(version >= 1),
    case_type TEXT NOT NULL CHECK(case_type IN ('CASE_A','CASE_B')),
    preference_version INTEGER NOT NULL,
    preference_hash TEXT NOT NULL,
    template_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    model_id TEXT NOT NULL,
    protocol TEXT NOT NULL,
    source_version_ids_json TEXT NOT NULL CHECK(json_valid(source_version_ids_json)),
    bridge_id TEXT REFERENCES learning_bridges(id) ON DELETE RESTRICT,
    bridge_revision INTEGER,
    cache_key TEXT NOT NULL
        CHECK(length(cache_key) = 64 AND cache_key NOT GLOB '*[^0-9a-f]*'),
    input_hash TEXT NOT NULL
        CHECK(length(input_hash) = 64 AND input_hash NOT GLOB '*[^0-9a-f]*'),
    plan_json TEXT NOT NULL CHECK(json_valid(plan_json)),
    planner_operation_id TEXT NOT NULL,
    provider_usage_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(provider_usage_json)),
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK(status IN ('ACTIVE','COMPLETED','INVALIDATED')),
    invalidated_reason TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    invalidated_at TEXT,
    UNIQUE(journey_id, version),
    FOREIGN KEY(node_id, spec_version)
        REFERENCES teaching_specs(node_id, version) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id, preference_version)
        REFERENCES learning_preference_versions(workspace_id, version) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id, planner_operation_id)
        REFERENCES learning_operations(workspace_id, id) ON DELETE RESTRICT,
    CHECK((bridge_id IS NULL AND bridge_revision IS NULL)
       OR (bridge_id IS NOT NULL AND bridge_revision IS NOT NULL AND bridge_revision >= 0)),
    CHECK((status = 'INVALIDATED' AND invalidated_reason IS NOT NULL AND invalidated_at IS NOT NULL)
       OR (status != 'INVALIDATED' AND invalidated_reason IS NULL AND invalidated_at IS NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_teaching_plan_per_journey
ON teaching_plan_versions(journey_id) WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_teaching_plan_cache
ON teaching_plan_versions(workspace_id, node_id, cache_key, status);

CREATE TRIGGER IF NOT EXISTS validate_teaching_plan_context
BEFORE INSERT ON teaching_plan_versions
WHEN NOT EXISTS(
    SELECT 1 FROM learning_workspaces AS workspace
    JOIN learning_journeys AS journey
      ON journey.workspace_id = workspace.id
    WHERE workspace.id = NEW.workspace_id
      AND workspace.owner_user_id = NEW.owner_user_id
      AND workspace.course_id = NEW.course_id
      AND journey.id = NEW.journey_id
      AND journey.node_id = NEW.node_id
      AND journey.spec_version = NEW.spec_version
)
OR NOT EXISTS(
    SELECT 1 FROM learning_preference_versions AS preference
    WHERE preference.workspace_id = NEW.workspace_id
      AND preference.version = NEW.preference_version
      AND preference.preference_hash = NEW.preference_hash
)
OR (
    NEW.bridge_id IS NOT NULL AND NOT EXISTS(
        SELECT 1 FROM learning_bridges AS bridge
        WHERE bridge.id = NEW.bridge_id
          AND bridge.workspace_id = NEW.workspace_id
          AND bridge.journey_id = NEW.journey_id
          AND bridge.node_id = NEW.node_id
          AND bridge.revision = NEW.bridge_revision
    )
)
BEGIN
    SELECT RAISE(ABORT, 'Teaching plan context does not match its private workspace');
END;

CREATE TRIGGER IF NOT EXISTS immutable_teaching_plan_content
BEFORE UPDATE OF id, workspace_id, owner_user_id, course_id, journey_id, node_id,
    spec_version, version, case_type, preference_version, preference_hash,
    template_version, schema_version, model_id, protocol, source_version_ids_json,
    bridge_id, bridge_revision, cache_key, input_hash, plan_json,
    planner_operation_id, provider_usage_json, created_at
ON teaching_plan_versions
BEGIN
    SELECT RAISE(ABORT, 'Teaching plan version content is immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_teaching_plan_delete
BEFORE DELETE ON teaching_plan_versions
BEGIN
    SELECT RAISE(ABORT, 'Teaching plan versions are immutable');
END;

CREATE TABLE IF NOT EXISTS teaching_plan_units (
    plan_version_id TEXT NOT NULL REFERENCES teaching_plan_versions(id) ON DELETE RESTRICT,
    unit_key TEXT NOT NULL CHECK(length(unit_key) BETWEEN 1 AND 100),
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    target_item_ids_json TEXT NOT NULL CHECK(
        json_valid(target_item_ids_json)
        AND json_array_length(target_item_ids_json) BETWEEN 1 AND 3
    ),
    content_json TEXT NOT NULL CHECK(json_valid(content_json)),
    PRIMARY KEY(plan_version_id, unit_key),
    UNIQUE(plan_version_id, ordinal)
);

CREATE TRIGGER IF NOT EXISTS validate_teaching_plan_unit_items
BEFORE INSERT ON teaching_plan_units
WHEN EXISTS(
    SELECT 1 FROM json_each(NEW.target_item_ids_json) AS target
    WHERE NOT EXISTS(
        SELECT 1 FROM teaching_plan_versions AS plan
        JOIN teaching_items AS item
          ON item.node_id = plan.node_id
         AND item.spec_version = plan.spec_version
         AND item.item_id = target.value
        WHERE plan.id = NEW.plan_version_id
    )
)
OR EXISTS(
    SELECT 1
    FROM teaching_plan_units AS existing,
         json_each(existing.target_item_ids_json) AS old_target,
         json_each(NEW.target_item_ids_json) AS new_target
    WHERE existing.plan_version_id = NEW.plan_version_id
      AND old_target.value = new_target.value
)
BEGIN
    SELECT RAISE(ABORT, 'Teaching plan unit contains invalid or duplicate scope');
END;

CREATE TRIGGER IF NOT EXISTS immutable_teaching_plan_units_update
BEFORE UPDATE ON teaching_plan_units
BEGIN
    SELECT RAISE(ABORT, 'Teaching plan units are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_teaching_plan_units_delete
BEFORE DELETE ON teaching_plan_units
BEGIN
    SELECT RAISE(ABORT, 'Teaching plan units are immutable');
END;

CREATE TABLE IF NOT EXISTS teaching_unit_plan_links (
    teaching_unit_id TEXT PRIMARY KEY REFERENCES teaching_units(id) ON DELETE RESTRICT,
    plan_version_id TEXT NOT NULL,
    plan_unit_key TEXT NOT NULL,
    FOREIGN KEY(plan_version_id, plan_unit_key)
        REFERENCES teaching_plan_units(plan_version_id, unit_key) ON DELETE RESTRICT
);

CREATE TRIGGER IF NOT EXISTS validate_teaching_unit_plan_link
BEFORE INSERT ON teaching_unit_plan_links
WHEN NOT EXISTS(
    SELECT 1 FROM teaching_units AS unit
    JOIN learning_journeys AS journey ON journey.id = unit.journey_id
    JOIN teaching_plan_versions AS plan ON plan.id = NEW.plan_version_id
    WHERE unit.id = NEW.teaching_unit_id
      AND plan.journey_id = journey.id
      AND EXISTS(
          SELECT 1 FROM teaching_plan_units AS plan_unit
          WHERE plan_unit.plan_version_id = plan.id
            AND plan_unit.unit_key = NEW.plan_unit_key
      )
)
BEGIN
    SELECT RAISE(ABORT, 'Teaching unit does not match its plan version');
END;

CREATE TRIGGER IF NOT EXISTS immutable_teaching_unit_plan_links_update
BEFORE UPDATE ON teaching_unit_plan_links
BEGIN
    SELECT RAISE(ABORT, 'Teaching unit plan links are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_teaching_unit_plan_links_delete
BEFORE DELETE ON teaching_unit_plan_links
BEGIN
    SELECT RAISE(ABORT, 'Teaching unit plan links are immutable');
END;

CREATE TABLE IF NOT EXISTS teaching_delivery_evidence (
    id TEXT PRIMARY KEY,
    journey_id TEXT NOT NULL REFERENCES learning_journeys(id) ON DELETE RESTRICT,
    node_id TEXT NOT NULL,
    spec_version INTEGER NOT NULL CHECK(spec_version >= 1),
    item_id TEXT NOT NULL,
    teaching_unit_id TEXT NOT NULL REFERENCES teaching_units(id) ON DELETE RESTRICT,
    section_id TEXT NOT NULL CHECK(length(section_id) BETWEEN 1 AND 100),
    plan_version_id TEXT,
    plan_unit_key TEXT,
    content_hash TEXT,
    validation_status TEXT NOT NULL
        CHECK(validation_status IN ('VALIDATED','LEGACY_PRESERVED')),
    validation_reason TEXT NOT NULL CHECK(length(trim(validation_reason)) > 0),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(journey_id, item_id, teaching_unit_id, section_id),
    FOREIGN KEY(node_id, spec_version, item_id)
        REFERENCES teaching_items(node_id, spec_version, item_id) ON DELETE RESTRICT,
    FOREIGN KEY(plan_version_id, plan_unit_key)
        REFERENCES teaching_plan_units(plan_version_id, unit_key) ON DELETE RESTRICT,
    CHECK(
        (validation_status = 'LEGACY_PRESERVED'
         AND plan_version_id IS NULL AND plan_unit_key IS NULL AND content_hash IS NULL)
        OR
        (validation_status = 'VALIDATED'
         AND plan_version_id IS NOT NULL AND plan_unit_key IS NOT NULL
         AND length(content_hash) = 64 AND content_hash NOT GLOB '*[^0-9a-f]*')
    )
);

CREATE INDEX IF NOT EXISTS idx_delivery_evidence_progress
ON teaching_delivery_evidence(journey_id, item_id, validation_status);

CREATE TRIGGER IF NOT EXISTS validate_teaching_delivery_context
BEFORE INSERT ON teaching_delivery_evidence
WHEN NOT EXISTS(
    SELECT 1 FROM learning_journeys AS journey
    JOIN teaching_units AS unit ON unit.journey_id = journey.id
    WHERE journey.id = NEW.journey_id
      AND journey.node_id = NEW.node_id
      AND journey.spec_version = NEW.spec_version
      AND unit.id = NEW.teaching_unit_id
)
OR NOT EXISTS(
    SELECT 1 FROM teaching_units AS unit,
         json_each(json_extract(unit.content_json, '$.sections')) AS section
    WHERE unit.id = NEW.teaching_unit_id
      AND json_extract(section.value, '$.section_id') = NEW.section_id
)
OR (
    NEW.validation_status = 'VALIDATED' AND NOT EXISTS(
        SELECT 1 FROM teaching_unit_plan_links AS link
        JOIN teaching_plan_units AS plan_unit
          ON plan_unit.plan_version_id = link.plan_version_id
         AND plan_unit.unit_key = link.plan_unit_key
        WHERE link.teaching_unit_id = NEW.teaching_unit_id
          AND link.plan_version_id = NEW.plan_version_id
          AND link.plan_unit_key = NEW.plan_unit_key
          AND EXISTS(
              SELECT 1 FROM json_each(plan_unit.target_item_ids_json) AS target
              WHERE target.value = NEW.item_id
          )
    )
)
BEGIN
    SELECT RAISE(ABORT, 'Teaching delivery evidence does not match saved content and scope');
END;

CREATE TRIGGER IF NOT EXISTS immutable_teaching_delivery_update
BEFORE UPDATE ON teaching_delivery_evidence
BEGIN
    SELECT RAISE(ABORT, 'Teaching delivery evidence is immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_teaching_delivery_delete
BEFORE DELETE ON teaching_delivery_evidence
BEGIN
    SELECT RAISE(ABORT, 'Teaching delivery evidence is immutable');
END;

-- Only structurally locatable legacy rows are carried into the new evidence ledger.
-- Their explicit status prevents an old row from masquerading as V3.2 server validation.
INSERT OR IGNORE INTO teaching_delivery_evidence(
    id, journey_id, node_id, spec_version, item_id, teaching_unit_id, section_id,
    plan_version_id, plan_unit_key, content_hash, validation_status, validation_reason
)
SELECT
    lower(hex(randomblob(16))),
    journey.id,
    journey.node_id,
    journey.spec_version,
    coverage.item_id,
    coverage.unit_id,
    section.value,
    NULL,
    NULL,
    NULL,
    'LEGACY_PRESERVED',
    'MIGRATION_015_STRUCTURAL_PRESERVATION'
FROM learning_coverage AS coverage
JOIN learning_journeys AS journey ON journey.id = coverage.journey_id
JOIN teaching_units AS unit ON unit.id = coverage.unit_id,
     json_each(coverage.section_ids_json) AS section
WHERE EXISTS(
    SELECT 1 FROM teaching_items AS item
    WHERE item.node_id = journey.node_id
      AND item.spec_version = journey.spec_version
      AND item.item_id = coverage.item_id
)
AND EXISTS(
    SELECT 1 FROM json_each(json_extract(unit.content_json, '$.sections')) AS saved_section
    WHERE json_extract(saved_section.value, '$.section_id') = section.value
);

CREATE TABLE IF NOT EXISTS learning_model_run_evidence (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('planner','teacher','problem','grader','router')),
    model_id TEXT NOT NULL,
    provider_label TEXT NOT NULL,
    protocol TEXT NOT NULL,
    region_label TEXT NOT NULL,
    template_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    input_hash TEXT CHECK(
        input_hash IS NULL OR
        (length(input_hash) = 64 AND input_hash NOT GLOB '*[^0-9a-f]*')
    ),
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    latency_ms INTEGER NOT NULL CHECK(latency_ms >= 0),
    input_tokens INTEGER NOT NULL CHECK(input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK(output_tokens >= 0),
    status TEXT NOT NULL
        CHECK(status IN ('COMPLETED','FAILED','UNKNOWN','BLOCKED','LEGACY_COMPLETED')),
    error_class TEXT CHECK(error_class IS NULL OR length(error_class) BETWEEN 1 AND 100),
    provider_response_id TEXT,
    FOREIGN KEY(workspace_id, operation_id)
        REFERENCES learning_operations(workspace_id, id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_learning_model_run_operation
ON learning_model_run_evidence(workspace_id, operation_id, role);

INSERT OR IGNORE INTO learning_model_run_evidence(
    id, workspace_id, operation_id, role, model_id, provider_label, protocol,
    region_label, template_version, schema_version, input_hash, started_at,
    finished_at, latency_ms, input_tokens, output_tokens, status, error_class,
    provider_response_id
)
SELECT
    'legacy-' || id,
    workspace_id,
    operation_id,
    role,
    model,
    'LEGACY_UNRECORDED',
    protocol,
    'UNKNOWN',
    prompt_version,
    'LEGACY_UNRECORDED',
    NULL,
    created_at,
    created_at,
    0,
    input_tokens,
    output_tokens,
    'LEGACY_COMPLETED',
    NULL,
    provider_response_id
FROM learning_model_runs;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(15,'versioned teaching plans and delivery evidence');
