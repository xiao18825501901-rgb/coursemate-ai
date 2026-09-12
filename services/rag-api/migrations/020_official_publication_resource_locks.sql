-- Forward-only hardening for versionless canonical-node metadata used by an active
-- official review. Private evidence on the same canonical node remains owner-scoped
-- and is intentionally not blocked or promoted.

CREATE TRIGGER IF NOT EXISTS lock_reviewed_official_node_update
BEFORE UPDATE OF course_id, owner_user_id, title, description, major, kind
ON knowledge_nodes
WHEN EXISTS(
    SELECT 1
    FROM publication_snapshot_resources AS resource
    JOIN official_knowledge_publication_requests AS request
      ON request.snapshot_id=resource.snapshot_id
    WHERE request.status IN ('pending','approved')
      AND resource.resource_kind='KNOWLEDGE_NODE'
      AND resource.resource_id=OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'Official node is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_reviewed_official_alias_insert
BEFORE INSERT ON knowledge_node_aliases
WHEN EXISTS(
    SELECT 1
    FROM publication_snapshot_resources AS resource
    JOIN official_knowledge_publication_requests AS request
      ON request.snapshot_id=resource.snapshot_id
    WHERE request.status IN ('pending','approved')
      AND resource.resource_kind='KNOWLEDGE_NODE'
      AND resource.resource_id=NEW.node_id
)
BEGIN
    SELECT RAISE(ABORT, 'Official node is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_reviewed_official_alias_update
BEFORE UPDATE ON knowledge_node_aliases
WHEN EXISTS(
    SELECT 1
    FROM publication_snapshot_resources AS resource
    JOIN official_knowledge_publication_requests AS request
      ON request.snapshot_id=resource.snapshot_id
    WHERE request.status IN ('pending','approved')
      AND resource.resource_kind='KNOWLEDGE_NODE'
      AND resource.resource_id=OLD.node_id
)
BEGIN
    SELECT RAISE(ABORT, 'Official node is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_reviewed_official_alias_delete
BEFORE DELETE ON knowledge_node_aliases
WHEN EXISTS(
    SELECT 1
    FROM publication_snapshot_resources AS resource
    JOIN official_knowledge_publication_requests AS request
      ON request.snapshot_id=resource.snapshot_id
    WHERE request.status IN ('pending','approved')
      AND resource.resource_kind='KNOWLEDGE_NODE'
      AND resource.resource_id=OLD.node_id
)
BEGIN
    SELECT RAISE(ABORT, 'Official node is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_reviewed_official_evidence_insert
BEFORE INSERT ON material_evidence
WHEN NEW.source_scope='OFFICIAL' AND EXISTS(
    SELECT 1
    FROM publication_snapshot_resources AS resource
    JOIN official_knowledge_publication_requests AS request
      ON request.snapshot_id=resource.snapshot_id
    WHERE request.status IN ('pending','approved')
      AND resource.resource_kind='KNOWLEDGE_NODE'
      AND resource.resource_id=NEW.node_id
)
BEGIN
    SELECT RAISE(ABORT, 'Official evidence is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_reviewed_official_evidence_update
BEFORE UPDATE ON material_evidence
WHEN OLD.source_scope='OFFICIAL' AND EXISTS(
    SELECT 1
    FROM publication_snapshot_resources AS resource
    JOIN official_knowledge_publication_requests AS request
      ON request.snapshot_id=resource.snapshot_id
    WHERE request.status IN ('pending','approved')
      AND resource.resource_kind='KNOWLEDGE_NODE'
      AND resource.resource_id=OLD.node_id
)
BEGIN
    SELECT RAISE(ABORT, 'Official evidence is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_reviewed_official_evidence_delete
BEFORE DELETE ON material_evidence
WHEN OLD.source_scope='OFFICIAL' AND EXISTS(
    SELECT 1
    FROM publication_snapshot_resources AS resource
    JOIN official_knowledge_publication_requests AS request
      ON request.snapshot_id=resource.snapshot_id
    WHERE request.status IN ('pending','approved')
      AND resource.resource_kind='KNOWLEDGE_NODE'
      AND resource.resource_id=OLD.node_id
)
BEGIN
    SELECT RAISE(ABORT, 'Official evidence is locked by publication review');
END;

-- Once an owner has withdrawn/rejected publication, normal course deletion may proceed.
-- Remove the now-private review package as part of the same transaction so filenames,
-- descriptions, and consent metadata do not survive as orphaned rows.
CREATE TRIGGER IF NOT EXISTS purge_deleted_course_publication_snapshot
AFTER DELETE ON course_publication_requests
BEGIN
    DELETE FROM publication_releases
    WHERE subject_kind='COURSE' AND request_id=OLD.id;
    DELETE FROM publication_audit_events
    WHERE subject_kind='COURSE' AND request_id=OLD.id;
    DELETE FROM publication_review_snapshots
    WHERE subject_kind='COURSE' AND request_id=OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS purge_deleted_overlay_publication_snapshot
AFTER DELETE ON overlay_publication_requests
BEGIN
    DELETE FROM publication_releases
    WHERE subject_kind='OVERLAY' AND request_id=OLD.id;
    DELETE FROM publication_audit_events
    WHERE subject_kind='OVERLAY' AND request_id=OLD.id;
    DELETE FROM publication_review_snapshots
    WHERE subject_kind='OVERLAY' AND request_id=OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS lock_course_profile_update_during_publication
BEFORE UPDATE ON course_teaching_profiles
WHEN EXISTS(
    SELECT 1 FROM courses
    WHERE id=OLD.course_id AND publication_status IN ('pending','published')
)
BEGIN
    SELECT RAISE(ABORT, 'Course content is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS immutable_chunk_source_version_update
BEFORE UPDATE ON chunk_source_versions
BEGIN
    SELECT RAISE(ABORT, 'Chunk source-version bindings are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_chunk_source_version_delete
BEFORE DELETE ON chunk_source_versions
WHEN EXISTS(
    SELECT 1
    FROM publication_snapshot_resources AS resource
    JOIN publication_review_snapshots AS snapshot
      ON snapshot.id=resource.snapshot_id
    LEFT JOIN course_publication_requests AS course_request
      ON snapshot.subject_kind='COURSE'
     AND course_request.id=snapshot.request_id
    LEFT JOIN overlay_publication_requests AS overlay_request
      ON snapshot.subject_kind='OVERLAY'
     AND overlay_request.snapshot_id=snapshot.id
    WHERE resource.resource_kind='DOCUMENT_VERSION'
      AND resource.resource_id=OLD.document_version_id
      AND (
        course_request.status IN ('pending','approved')
        OR overlay_request.status IN ('pending','approved')
      )
)
BEGIN
    SELECT RAISE(ABORT, 'Reviewed chunk source-version bindings are immutable');
END;

CREATE TRIGGER IF NOT EXISTS lock_selected_overlay_node_status_update
BEFORE UPDATE OF status ON knowledge_nodes
WHEN EXISTS(
    SELECT 1
    FROM publication_snapshot_resources AS resource
    JOIN overlay_publication_requests AS request
      ON request.snapshot_id=resource.snapshot_id
    WHERE request.status IN ('pending','approved')
      AND resource.resource_kind='KNOWLEDGE_NODE'
      AND resource.resource_id=OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'Selected overlay resource is locked by publication review');
END;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(20,'official publication resource locks');
