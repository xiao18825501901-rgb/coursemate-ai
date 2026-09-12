-- Bind every V3 publication decision to an immutable, least-privilege review snapshot.
-- The three workflows remain distinct: user course, official tree/spec, and private overlay.

CREATE TABLE IF NOT EXISTS publication_review_snapshots (
    id TEXT PRIMARY KEY,
    subject_kind TEXT NOT NULL
        CHECK(subject_kind IN ('COURSE','OFFICIAL_KNOWLEDGE','OVERLAY')),
    request_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    workspace_id TEXT,
    owner_user_id TEXT,
    summary_json TEXT NOT NULL CHECK(json_valid(summary_json)),
    content_hash TEXT NOT NULL CHECK(length(content_hash) = 64),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(subject_kind, request_id)
);

CREATE TABLE IF NOT EXISTS publication_snapshot_resources (
    snapshot_id TEXT NOT NULL
        REFERENCES publication_review_snapshots(id) ON DELETE CASCADE,
    resource_kind TEXT NOT NULL CHECK(resource_kind IN (
        'COURSE_METADATA','DOCUMENT_VERSION','CHUNK','DERIVED_ARTIFACT',
        'TEACHING_PROFILE','TREE_VERSION','KNOWLEDGE_NODE','TEACHING_SPEC',
        'MATERIAL_EVIDENCE','CANONICAL_NODE_REFERENCE'
    )),
    resource_id TEXT NOT NULL,
    version_label TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL CHECK(length(trim(display_name)) > 0),
    source_scope TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK(length(content_hash) = 64),
    metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
    PRIMARY KEY(snapshot_id, resource_kind, resource_id, version_label)
);

CREATE INDEX IF NOT EXISTS idx_publication_snapshot_resource_lookup
ON publication_snapshot_resources(resource_kind, resource_id, snapshot_id);

CREATE TRIGGER IF NOT EXISTS immutable_publication_snapshot
BEFORE UPDATE ON publication_review_snapshots
BEGIN
    SELECT RAISE(ABORT, 'Publication review snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_publication_snapshot_resource
BEFORE UPDATE ON publication_snapshot_resources
BEGIN
    SELECT RAISE(ABORT, 'Publication snapshot resources are immutable');
END;

CREATE TABLE IF NOT EXISTS publication_releases (
    id TEXT PRIMARY KEY,
    subject_kind TEXT NOT NULL
        CHECK(subject_kind IN ('COURSE','OFFICIAL_KNOWLEDGE','OVERLAY')),
    request_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL
        REFERENCES publication_review_snapshots(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK(status IN ('ACTIVE','WITHDRAWN')),
    cache_generation INTEGER NOT NULL DEFAULT 1 CHECK(cache_generation >= 1),
    activated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    withdrawn_at TEXT,
    withdrawn_by_user_id TEXT,
    UNIQUE(subject_kind, request_id)
);

CREATE TABLE IF NOT EXISTS publication_audit_events (
    id TEXT PRIMARY KEY,
    subject_kind TEXT NOT NULL
        CHECK(subject_kind IN ('COURSE','OFFICIAL_KNOWLEDGE','OVERLAY')),
    request_id TEXT NOT NULL,
    actor_user_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN (
        'SUBMITTED','APPROVED','REJECTED','WITHDRAWN','UNPUBLISHED'
    )),
    details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_publication_audit_subject
ON publication_audit_events(subject_kind, request_id, created_at);

CREATE TABLE IF NOT EXISTS official_knowledge_publication_requests (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    tree_version_id TEXT NOT NULL
        REFERENCES knowledge_tree_versions(id) ON DELETE RESTRICT,
    snapshot_id TEXT NOT NULL UNIQUE
        REFERENCES publication_review_snapshots(id) ON DELETE RESTRICT,
    submitted_by_user_id TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK(status IN ('pending','approved','rejected','withdrawn')),
    submitted_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    reviewed_at TEXT,
    reviewed_by_user_id TEXT,
    review_note TEXT NOT NULL DEFAULT '',
    CHECK(reviewed_by_user_id IS NULL OR reviewed_by_user_id != submitted_by_user_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_pending_official_tree_review
ON official_knowledge_publication_requests(tree_version_id)
WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_official_review_queue
ON official_knowledge_publication_requests(status, submitted_at);

CREATE TABLE IF NOT EXISTS overlay_publication_requests (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL UNIQUE
        REFERENCES publication_review_snapshots(id) ON DELETE RESTRICT,
    status TEXT NOT NULL
        CHECK(status IN ('pending','approved','rejected','withdrawn')),
    share_selected_content_consent INTEGER NOT NULL
        CHECK(share_selected_content_consent = 1),
    rights_confirmation INTEGER NOT NULL CHECK(rights_confirmation = 1),
    consent_version TEXT NOT NULL,
    consented_at TEXT NOT NULL,
    submitted_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    reviewed_at TEXT,
    reviewed_by_user_id TEXT,
    review_note TEXT NOT NULL DEFAULT '',
    CHECK(reviewed_by_user_id IS NULL OR reviewed_by_user_id != owner_user_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_pending_overlay_review
ON overlay_publication_requests(workspace_id)
WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_overlay_review_queue
ON overlay_publication_requests(status, submitted_at);

-- A pending or live course release is an exact reviewed object. It must be withdrawn
-- before its metadata, source set, chunks, previews, or teaching profile can change.
CREATE TRIGGER IF NOT EXISTS lock_course_metadata_during_publication
BEFORE UPDATE OF name, description, preferred_language, owner_user_id, course_type
ON courses
WHEN OLD.publication_status IN ('pending','published')
BEGIN
    SELECT RAISE(ABORT, 'Course content is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_course_delete_during_publication
BEFORE DELETE ON courses
WHEN OLD.publication_status IN ('pending','published')
BEGIN
    SELECT RAISE(ABORT, 'Course content is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_course_document_insert_during_publication
BEFORE INSERT ON documents
WHEN EXISTS(
    SELECT 1 FROM courses
    WHERE id=NEW.course_id AND publication_status IN ('pending','published')
)
BEGIN
    SELECT RAISE(ABORT, 'Course content is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_course_document_update_during_publication
BEFORE UPDATE ON documents
WHEN EXISTS(
    SELECT 1 FROM courses
    WHERE id=OLD.course_id AND publication_status IN ('pending','published')
)
BEGIN
    SELECT RAISE(ABORT, 'Course content is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_course_document_delete_during_publication
BEFORE DELETE ON documents
WHEN EXISTS(
    SELECT 1 FROM courses
    WHERE id=OLD.course_id AND publication_status IN ('pending','published')
)
BEGIN
    SELECT RAISE(ABORT, 'Course content is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_course_chunk_insert_during_publication
BEFORE INSERT ON chunks
WHEN EXISTS(
    SELECT 1 FROM courses
    WHERE id=NEW.course_id AND publication_status IN ('pending','published')
)
BEGIN
    SELECT RAISE(ABORT, 'Course content is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_course_chunk_update_during_publication
BEFORE UPDATE ON chunks
WHEN EXISTS(
    SELECT 1 FROM courses
    WHERE id=OLD.course_id AND publication_status IN ('pending','published')
)
BEGIN
    SELECT RAISE(ABORT, 'Course content is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_course_chunk_delete_during_publication
BEFORE DELETE ON chunks
WHEN EXISTS(
    SELECT 1 FROM courses
    WHERE id=OLD.course_id AND publication_status IN ('pending','published')
)
BEGIN
    SELECT RAISE(ABORT, 'Course content is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_course_profile_insert_during_publication
BEFORE INSERT ON course_teaching_profiles
WHEN EXISTS(
    SELECT 1 FROM courses
    WHERE id=NEW.course_id AND publication_status IN ('pending','published')
)
BEGIN
    SELECT RAISE(ABORT, 'Course content is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_course_profile_delete_during_publication
BEFORE DELETE ON course_teaching_profiles
WHEN EXISTS(
    SELECT 1 FROM courses
    WHERE id=OLD.course_id AND publication_status IN ('pending','published')
)
BEGIN
    SELECT RAISE(ABORT, 'Course content is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_course_artifact_insert_during_publication
BEFORE INSERT ON derived_artifacts
WHEN EXISTS(
    SELECT 1
    FROM document_versions AS version
    JOIN courses ON courses.id=version.course_id
    WHERE version.id=NEW.document_version_id
      AND courses.publication_status IN ('pending','published')
)
BEGIN
    SELECT RAISE(ABORT, 'Course content is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_course_artifact_update_during_publication
BEFORE UPDATE ON derived_artifacts
WHEN EXISTS(
    SELECT 1
    FROM document_versions AS version
    JOIN courses ON courses.id=version.course_id
    WHERE version.id=OLD.document_version_id
      AND courses.publication_status IN ('pending','published')
)
BEGIN
    SELECT RAISE(ABORT, 'Course content is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_course_artifact_delete_during_publication
BEFORE DELETE ON derived_artifacts
WHEN EXISTS(
    SELECT 1
    FROM document_versions AS version
    JOIN courses ON courses.id=version.course_id
    WHERE version.id=OLD.document_version_id
      AND courses.publication_status IN ('pending','published')
)
BEGIN
    SELECT RAISE(ABORT, 'Course content is locked by publication review');
END;

-- A submitted official tree stays editable only after rejection/withdrawal. Published
-- trees already have the migration-014 immutability guards; these cover review-pending drafts.
CREATE TRIGGER IF NOT EXISTS lock_pending_official_membership_insert
BEFORE INSERT ON knowledge_tree_memberships
WHEN EXISTS(
    SELECT 1 FROM official_knowledge_publication_requests
    WHERE tree_version_id=NEW.tree_version_id AND status='pending'
)
BEGIN
    SELECT RAISE(ABORT, 'Official tree is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_pending_official_membership_update
BEFORE UPDATE ON knowledge_tree_memberships
WHEN EXISTS(
    SELECT 1 FROM official_knowledge_publication_requests
    WHERE tree_version_id=OLD.tree_version_id AND status='pending'
)
BEGIN
    SELECT RAISE(ABORT, 'Official tree is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_pending_official_membership_delete
BEFORE DELETE ON knowledge_tree_memberships
WHEN EXISTS(
    SELECT 1 FROM official_knowledge_publication_requests
    WHERE tree_version_id=OLD.tree_version_id AND status='pending'
)
BEGIN
    SELECT RAISE(ABORT, 'Official tree is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_pending_official_edge_insert
BEFORE INSERT ON knowledge_prerequisite_edges
WHEN EXISTS(
    SELECT 1 FROM official_knowledge_publication_requests
    WHERE tree_version_id=NEW.tree_version_id AND status='pending'
)
BEGIN
    SELECT RAISE(ABORT, 'Official tree is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_pending_official_edge_update
BEFORE UPDATE ON knowledge_prerequisite_edges
WHEN EXISTS(
    SELECT 1 FROM official_knowledge_publication_requests
    WHERE tree_version_id=OLD.tree_version_id AND status='pending'
)
BEGIN
    SELECT RAISE(ABORT, 'Official tree is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_pending_official_edge_delete
BEFORE DELETE ON knowledge_prerequisite_edges
WHEN EXISTS(
    SELECT 1 FROM official_knowledge_publication_requests
    WHERE tree_version_id=OLD.tree_version_id AND status='pending'
)
BEGIN
    SELECT RAISE(ABORT, 'Official tree is locked by publication review');
END;

-- Only the private resources explicitly named in an active overlay package are locked.
-- Other files, nodes, chats, progress, and assessments in the workspace remain untouched.
CREATE TRIGGER IF NOT EXISTS lock_selected_overlay_document_delete
BEFORE DELETE ON documents
WHEN EXISTS(
    SELECT 1
    FROM publication_snapshot_resources AS resource
    JOIN publication_review_snapshots AS snapshot ON snapshot.id=resource.snapshot_id
    JOIN overlay_publication_requests AS request ON request.snapshot_id=snapshot.id
    WHERE snapshot.subject_kind='OVERLAY'
      AND request.status IN ('pending','approved')
      AND resource.resource_kind='DOCUMENT_VERSION'
      AND json_extract(resource.metadata_json,'$.documentId')=OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'Selected overlay resource is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_selected_overlay_node_update
BEFORE UPDATE OF course_id, owner_user_id, title, description, major, kind
ON knowledge_nodes
WHEN EXISTS(
    SELECT 1
    FROM publication_snapshot_resources AS resource
    JOIN publication_review_snapshots AS snapshot ON snapshot.id=resource.snapshot_id
    JOIN overlay_publication_requests AS request ON request.snapshot_id=snapshot.id
    WHERE snapshot.subject_kind='OVERLAY'
      AND request.status IN ('pending','approved')
      AND resource.resource_kind='KNOWLEDGE_NODE'
      AND resource.resource_id=OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'Selected overlay resource is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_selected_overlay_evidence_update
BEFORE UPDATE ON material_evidence
WHEN EXISTS(
    SELECT 1
    FROM publication_snapshot_resources AS resource
    JOIN publication_review_snapshots AS snapshot ON snapshot.id=resource.snapshot_id
    JOIN overlay_publication_requests AS request ON request.snapshot_id=snapshot.id
    WHERE snapshot.subject_kind='OVERLAY'
      AND request.status IN ('pending','approved')
      AND resource.resource_kind='MATERIAL_EVIDENCE'
      AND resource.resource_id=OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'Selected overlay resource is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_selected_overlay_evidence_delete
BEFORE DELETE ON material_evidence
WHEN EXISTS(
    SELECT 1
    FROM publication_snapshot_resources AS resource
    JOIN publication_review_snapshots AS snapshot ON snapshot.id=resource.snapshot_id
    JOIN overlay_publication_requests AS request ON request.snapshot_id=snapshot.id
    WHERE snapshot.subject_kind='OVERLAY'
      AND request.status IN ('pending','approved')
      AND resource.resource_kind='MATERIAL_EVIDENCE'
      AND resource.resource_id=OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'Selected overlay resource is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_selected_overlay_artifact_update
BEFORE UPDATE ON derived_artifacts
WHEN EXISTS(
    SELECT 1
    FROM publication_snapshot_resources AS resource
    JOIN publication_review_snapshots AS snapshot ON snapshot.id=resource.snapshot_id
    JOIN overlay_publication_requests AS request ON request.snapshot_id=snapshot.id
    WHERE snapshot.subject_kind='OVERLAY'
      AND request.status IN ('pending','approved')
      AND resource.resource_kind='DERIVED_ARTIFACT'
      AND resource.resource_id=OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'Selected overlay resource is locked by publication review');
END;

CREATE TRIGGER IF NOT EXISTS lock_selected_overlay_artifact_delete
BEFORE DELETE ON derived_artifacts
WHEN EXISTS(
    SELECT 1
    FROM publication_snapshot_resources AS resource
    JOIN publication_review_snapshots AS snapshot ON snapshot.id=resource.snapshot_id
    JOIN overlay_publication_requests AS request ON request.snapshot_id=snapshot.id
    WHERE snapshot.subject_kind='OVERLAY'
      AND request.status IN ('pending','approved')
      AND resource.resource_kind='DERIVED_ARTIFACT'
      AND resource.resource_id=OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'Selected overlay resource is locked by publication review');
END;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(19,'scoped immutable publication review snapshots');
