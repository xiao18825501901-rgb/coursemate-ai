-- Durable configured-assessment preparation.
--
-- A frozen configuration is cheap and synchronous.  Question authoring is not:
-- it may make several independently metered provider calls.  These additive
-- fields turn the existing preparation row into a leased, resumable job without
-- changing frozen configurations or already-bound question slots.

ALTER TABLE assessment_configuration_preparations
    ADD COLUMN operation_id TEXT;
ALTER TABLE assessment_configuration_preparations
    ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt >= 0);
ALTER TABLE assessment_configuration_preparations
    ADD COLUMN total_slots INTEGER NOT NULL DEFAULT 0 CHECK(total_slots >= 0);
ALTER TABLE assessment_configuration_preparations
    ADD COLUMN prepared_slots INTEGER NOT NULL DEFAULT 0 CHECK(prepared_slots >= 0);
ALTER TABLE assessment_configuration_preparations
    ADD COLUMN current_ordinal INTEGER CHECK(current_ordinal IS NULL OR current_ordinal >= 1);
ALTER TABLE assessment_configuration_preparations
    ADD COLUMN current_stage TEXT;
ALTER TABLE assessment_configuration_preparations
    ADD COLUMN diagnostic_id TEXT;
ALTER TABLE assessment_configuration_preparations
    ADD COLUMN lease_owner TEXT;
ALTER TABLE assessment_configuration_preparations
    ADD COLUMN lease_expires_at TEXT;
ALTER TABLE assessment_configuration_preparations
    ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1));

UPDATE assessment_configuration_preparations
SET total_slots=(
        SELECT COUNT(*) FROM assessment_configuration_slots AS slot
        WHERE slot.configuration_id=assessment_configuration_preparations.configuration_id
    ),
    prepared_slots=(
        SELECT COUNT(*) FROM assessment_configuration_questions AS question
        WHERE question.configuration_id=assessment_configuration_preparations.configuration_id
    );

CREATE INDEX IF NOT EXISTS assessment_configuration_preparation_claim
ON assessment_configuration_preparations(status,cancel_requested,lease_expires_at,created_at);

CREATE TABLE assessment_configuration_recovery_receipts (
    id TEXT PRIMARY KEY,
    preparation_id TEXT NOT NULL
        REFERENCES assessment_configuration_preparations(id) ON DELETE RESTRICT,
    configuration_id TEXT NOT NULL
        REFERENCES assessment_configurations(id) ON DELETE RESTRICT,
    prior_status TEXT NOT NULL CHECK(prior_status IN ('PREPARING','BLOCKED','CANCELLED')),
    reason TEXT NOT NULL CHECK(reason IN (
        'COMPATIBLE_POOL_COMPLETE','SAVED_RESPONSE_RECONCILED'
    )),
    prepared_slots INTEGER NOT NULL CHECK(prepared_slots >= 5),
    model_calls_added INTEGER NOT NULL DEFAULT 0 CHECK(model_calls_added = 0),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(preparation_id,reason,prepared_slots)
);

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(64,'durable configured assessment preparation');
