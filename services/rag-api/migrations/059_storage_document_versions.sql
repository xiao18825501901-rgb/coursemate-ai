-- Link durable objects to immutable source versions. Historical versions may
-- refer to different original bytes even when the mutable document row points
-- at the newest version, so document_id alone is not a sufficient restore key.
ALTER TABLE storage_objects ADD COLUMN document_version_id TEXT
    REFERENCES document_versions(id) ON DELETE SET NULL;

ALTER TABLE storage_migration_receipts ADD COLUMN document_version_id TEXT
    REFERENCES document_versions(id) ON DELETE RESTRICT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_storage_objects_document_version
ON storage_objects(document_version_id) WHERE document_version_id IS NOT NULL
    AND state='CANONICAL';

CREATE UNIQUE INDEX IF NOT EXISTS idx_storage_migration_document_version
ON storage_migration_receipts(document_version_id)
WHERE document_version_id IS NOT NULL;

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(59, 'durable storage linkage for immutable document versions');
