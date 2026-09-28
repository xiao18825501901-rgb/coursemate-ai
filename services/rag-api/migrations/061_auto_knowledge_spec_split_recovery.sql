-- Auditable recovery for a complete Teaching-Spec batch whose exhausted r3
-- response still leaves one or more nodes without a grounded REQUIRED item.
-- The immutable row freezes the rejected response and the exact single-node
-- operations allowed to replace only those invalid Specs. Other Specs from
-- the saved response are reused and the source tree remains active until the
-- complete candidate validates and activates atomically.

CREATE TABLE IF NOT EXISTS auto_knowledge_spec_split_receipts (
    job_id TEXT NOT NULL REFERENCES auto_knowledge_jobs(id) ON DELETE RESTRICT,
    shard_key TEXT NOT NULL,
    source_operation_id TEXT NOT NULL,
    source_output_hash TEXT NOT NULL CHECK(
        length(source_output_hash)=64
        AND source_output_hash NOT GLOB '*[^0-9a-f]*'
    ),
    invalid_node_keys_json TEXT NOT NULL CHECK(json_valid(invalid_node_keys_json)),
    split_operation_ids_json TEXT NOT NULL CHECK(json_valid(split_operation_ids_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(job_id,shard_key),
    UNIQUE(source_operation_id),
    CHECK(json_array_length(invalid_node_keys_json)>0),
    CHECK(
        json_array_length(invalid_node_keys_json)
        = json_array_length(split_operation_ids_json)
    )
);

CREATE TRIGGER IF NOT EXISTS immutable_auto_knowledge_spec_split_update
BEFORE UPDATE ON auto_knowledge_spec_split_receipts
BEGIN
    SELECT RAISE(ABORT, 'Automatic-map Spec split receipts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_auto_knowledge_spec_split_delete
BEFORE DELETE ON auto_knowledge_spec_split_receipts
BEGIN
    SELECT RAISE(ABORT, 'Automatic-map Spec split receipts are immutable');
END;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(61,'automatic knowledge-map Teaching-Spec split recovery');
