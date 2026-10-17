-- Durable, public-safe progress for on-demand configured assessment slots.
--
-- This is a workflow sidecar only. READY remains authoritative only when a
-- matching row exists in assessment_configuration_questions. Historical
-- questions, sessions, scores, model receipts, and UNKNOWN requests are not
-- changed.

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS assessment_configuration_slot_preparations (
    preparation_id TEXT NOT NULL
        REFERENCES assessment_configuration_preparations(id) ON DELETE RESTRICT,
    configuration_id TEXT NOT NULL
        REFERENCES assessment_configurations(id) ON DELETE RESTRICT,
    slot_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 1),
    status TEXT NOT NULL CHECK(status IN (
        'PENDING','PREPARING','READY','BLOCKED','CANCELLED'
    )),
    current_stage TEXT,
    error_code TEXT,
    error_message TEXT,
    diagnostic_id TEXT,
    operation_id TEXT,
    attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt >= 0),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(preparation_id,slot_id),
    UNIQUE(preparation_id,ordinal),
    FOREIGN KEY(configuration_id,slot_id)
        REFERENCES assessment_configuration_slots(configuration_id,slot_id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS assessment_slot_preparation_claim
ON assessment_configuration_slot_preparations(
    preparation_id,status,error_code,ordinal
);

INSERT OR IGNORE INTO assessment_configuration_slot_preparations(
    preparation_id,configuration_id,slot_id,ordinal,status,current_stage
)
SELECT prep.id,slot.configuration_id,slot.slot_id,slot.ordinal,
       CASE WHEN bound.slot_id IS NULL THEN 'PENDING' ELSE 'READY' END,
       CASE WHEN bound.slot_id IS NULL THEN 'QUEUED' ELSE 'READY_REUSED' END
FROM assessment_configuration_preparations AS prep
JOIN assessment_configuration_slots AS slot
  ON slot.configuration_id=prep.configuration_id
LEFT JOIN assessment_configuration_questions AS bound
  ON bound.configuration_id=slot.configuration_id AND bound.slot_id=slot.slot_id;

CREATE TRIGGER IF NOT EXISTS validate_ready_slot_preparation_insert
BEFORE INSERT ON assessment_configuration_slot_preparations
WHEN NEW.status='READY' AND NOT EXISTS (
    SELECT 1 FROM assessment_configuration_questions question
    WHERE question.configuration_id=NEW.configuration_id
      AND question.slot_id=NEW.slot_id
)
BEGIN SELECT RAISE(ABORT,'READY slot progress requires an authoritative question binding'); END;

CREATE TRIGGER IF NOT EXISTS validate_ready_slot_preparation_update
BEFORE UPDATE OF status ON assessment_configuration_slot_preparations
WHEN NEW.status='READY' AND NOT EXISTS (
    SELECT 1 FROM assessment_configuration_questions question
    WHERE question.configuration_id=NEW.configuration_id
      AND question.slot_id=NEW.slot_id
)
BEGIN SELECT RAISE(ABORT,'READY slot progress requires an authoritative question binding'); END;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(82,'configured assessment per-slot preparation progress');

COMMIT;
