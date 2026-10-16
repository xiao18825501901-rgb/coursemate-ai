-- Supplemental metadata, not a second billing authority. No old-row backfill.
CREATE TABLE IF NOT EXISTS learning_model_call_audit (
 reservation_id TEXT PRIMARY KEY REFERENCES learning_model_call_reservations(id) ON DELETE RESTRICT,
 route_snapshot_hash TEXT NOT NULL CHECK(length(route_snapshot_hash)=64),
 generic_role TEXT NOT NULL, operation_family TEXT NOT NULL, model_alias TEXT NOT NULL,
 provider_revision TEXT,
 revision_status TEXT NOT NULL DEFAULT 'UNKNOWN_UPSTREAM_ALIAS_ONLY',
 usage_status TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(usage_status IN ('UNKNOWN','REPORTED')),
 input_tokens INTEGER CHECK(input_tokens IS NULL OR input_tokens>=0),
 output_tokens INTEGER CHECK(output_tokens IS NULL OR output_tokens>=0),
 cost_amount REAL CHECK(cost_amount IS NULL OR cost_amount>=0),
 returned_model TEXT,
 send_intent_recorded INTEGER NOT NULL DEFAULT 0 CHECK(send_intent_recorded IN (0,1)),
 status TEXT NOT NULL DEFAULT 'RESERVED' CHECK(status IN
 ('RESERVED','SEND_INTENT','RESPONSE_COMPLETE','COMPLETED','FAILED','UNKNOWN','BLOCKED')),
 created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')), finished_at TEXT
);
CREATE TABLE IF NOT EXISTS learning_model_transport_events (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,
 reservation_id TEXT NOT NULL REFERENCES learning_model_call_audit(reservation_id) ON DELETE RESTRICT,
 phase TEXT NOT NULL CHECK(length(phase) BETWEEN 1 AND 64),
 metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
 created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TRIGGER IF NOT EXISTS learning_call_audit_identity_immutable
BEFORE UPDATE OF reservation_id,route_snapshot_hash,generic_role,operation_family,model_alias,
 provider_revision,revision_status,cost_amount,created_at ON learning_model_call_audit
BEGIN SELECT RAISE(ABORT,'Learning call audit identity is immutable'); END;
CREATE TRIGGER IF NOT EXISTS learning_call_audit_terminal_immutable BEFORE UPDATE
ON learning_model_call_audit WHEN OLD.status IN ('COMPLETED','FAILED','UNKNOWN','BLOCKED')
BEGIN SELECT RAISE(ABORT,'Learning call terminal audit is immutable'); END;
CREATE TRIGGER IF NOT EXISTS learning_call_audit_no_delete BEFORE DELETE ON learning_model_call_audit
BEGIN SELECT RAISE(ABORT,'Learning call audit cannot be erased'); END;
CREATE TRIGGER IF NOT EXISTS learning_transport_event_no_update
BEFORE UPDATE ON learning_model_transport_events
BEGIN SELECT RAISE(ABORT,'Learning transport events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS learning_transport_event_no_delete
BEFORE DELETE ON learning_model_transport_events
BEGIN SELECT RAISE(ABORT,'Learning transport events cannot be erased'); END;
INSERT OR IGNORE INTO schema_migrations(version,name) VALUES(76,'nullable learning transport audit');
