-- Additive learning-start fact. An accepted teaching request for a concrete
-- owner/workspace/node/spec is a real fact that must be independent of coverage:
-- "started but nothing covered yet" is LEARNING, while "never started" stays
-- NOT_STARTED. Coverage keeps living exclusively in teaching_delivery_evidence;
-- this table never grants coverage and never writes LEARNED.
--
-- Idempotent per (workspace,node,spec,operation): replaying the same accepted run
-- (or a retried UI request id) inserts nothing new. Older releases ignore the
-- table, so application rollback stays compatible.

CREATE TABLE IF NOT EXISTS learning_start_events (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    node_id TEXT NOT NULL,
    spec_version INTEGER NOT NULL CHECK(spec_version >= 1),
    operation_id TEXT NOT NULL CHECK(length(operation_id) BETWEEN 1 AND 120),
    source TEXT NOT NULL CHECK(source IN ('UI_RUN','V3_TEACH','DELIVERY','BACKFILL')),
    accepted_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(workspace_id, node_id, spec_version, operation_id),
    FOREIGN KEY(node_id, spec_version)
        REFERENCES teaching_specs(node_id, version) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_learning_start_scope
ON learning_start_events(workspace_id, node_id, spec_version, accepted_at);

-- Backfill for learning that started BEFORE this table existed. Only journeys
-- that carry a real accepted artifact are converted: a delivered teaching unit,
-- coverage, delivery evidence, or a LEARNED status. A bare journey row is
-- deliberately NOT backfilled — failed/cancelled/rejected submissions can leave
-- an empty shell behind and an empty shell is not a start. Idempotent: the
-- primary key and UNIQUE(workspace,node,spec,operation) make replays no-ops.
INSERT OR IGNORE INTO learning_start_events
    (id, workspace_id, node_id, spec_version, operation_id, source, accepted_at)
SELECT
    'start-bf-' || journey.id,
    journey.workspace_id,
    journey.node_id,
    journey.spec_version,
    'legacy-journey:' || journey.id,
    'BACKFILL',
    COALESCE(
        (SELECT MIN(unit.created_at) FROM teaching_units AS unit
         WHERE unit.journey_id = journey.id),
        (SELECT MIN(ev.created_at) FROM teaching_delivery_evidence AS ev
         WHERE ev.journey_id = journey.id),
        strftime('%Y-%m-%dT%H:%M:%fZ','now')
    )
FROM learning_journeys AS journey
WHERE journey.status = 'LEARNED'
   OR EXISTS(SELECT 1 FROM teaching_units AS unit WHERE unit.journey_id = journey.id)
   OR EXISTS(SELECT 1 FROM learning_coverage AS cov WHERE cov.journey_id = journey.id)
   OR EXISTS(SELECT 1 FROM teaching_delivery_evidence AS ev WHERE ev.journey_id = journey.id);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(26, 'learning start events');
