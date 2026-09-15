-- 016_shell_delivery_evidence.sql
-- Add a third, plan-free evidence channel for reviewed free-text deliveries.
--
-- The refreshed shell teaches with free text (two-stage Qwen prompt -> teaching)
-- and cannot satisfy the plan linkage the plan-based teach() records require.
-- This migration widens the evidence ledger instead of forging plan rows or
-- abusing LEGACY_PRESERVED:
--
--   VALIDATED        plan-based teach() (unchanged contract)
--   LEGACY_PRESERVED pre-plan rows carried by migration 015 (unchanged)
--   REVIEWED         shell free-text deliveries, confirmed by an injected
--                    coverage reviewer; structurally anchored to a real
--                    teaching unit, journey, node and spec version
--
-- The CHECK constraint on validation_status cannot be altered in place, so the
-- table is rebuilt through the documented SQLite 12-step pattern. No column is
-- added, dropped or renamed; foreign keys are recreated identically.
-- The coverage counters (app/learning/knowledge.py:_atomic_learning and
-- orchestrator teach()) are extended to count REVIEWED in the same update.

PRAGMA foreign_keys = OFF;

CREATE TABLE teaching_delivery_evidence_new (
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
        CHECK(validation_status IN ('VALIDATED','LEGACY_PRESERVED','REVIEWED')),
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
        OR
        (validation_status = 'REVIEWED'
         AND plan_version_id IS NULL AND plan_unit_key IS NULL
         AND length(content_hash) = 64 AND content_hash NOT GLOB '*[^0-9a-f]*')
    )
);

INSERT INTO teaching_delivery_evidence_new(
    id, journey_id, node_id, spec_version, item_id, teaching_unit_id, section_id,
    plan_version_id, plan_unit_key, content_hash, validation_status,
    validation_reason, created_at
)
SELECT
    id, journey_id, node_id, spec_version, item_id, teaching_unit_id, section_id,
    plan_version_id, plan_unit_key, content_hash, validation_status,
    validation_reason, created_at
FROM teaching_delivery_evidence;

DROP TABLE teaching_delivery_evidence;
ALTER TABLE teaching_delivery_evidence_new RENAME TO teaching_delivery_evidence;

CREATE INDEX IF NOT EXISTS idx_delivery_evidence_progress
ON teaching_delivery_evidence(journey_id, item_id, validation_status);

-- Scope checks: the unit must belong to the same journey/node/spec, the
-- section must exist in the unit's saved content, and plan-linked VALIDATED
-- rows still need the plan-unit target check. REVIEWED rows skip the plan
-- linkage but keep the same journey/node/spec/section anchors.
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

-- One teaching unit per operation within a journey: retries of the same shell
-- run replay the same bookkeeping instead of inserting a second unit.
CREATE UNIQUE INDEX IF NOT EXISTS one_teaching_unit_per_operation
ON teaching_units(journey_id, operation_id);

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(22,'reviewed shell delivery evidence channel');

PRAGMA foreign_keys = ON;
