-- Persistent, resumable automatic knowledge-map builds.
--
-- Source-change triggers only enqueue cheap local events. They never call a
-- model.  A leased worker freezes the exact readable document versions before
-- any generation and records a terminal receipt after activation/failure.

CREATE TABLE IF NOT EXISTS auto_knowledge_source_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_course_id TEXT NOT NULL,
    document_id TEXT,
    event_kind TEXT NOT NULL CHECK(event_kind IN (
        'DOCUMENT_READY','DOCUMENT_UNAVAILABLE','DOCUMENT_DELETED','RECONCILIATION'
    )),
    batch_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK(status IN ('PENDING','CONSUMED')),
    not_before TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    consumed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_auto_knowledge_events_due
ON auto_knowledge_source_events(status,not_before,source_course_id,id);

CREATE TABLE IF NOT EXISTS auto_knowledge_targets (
    target_key TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    workspace_id TEXT REFERENCES learning_workspaces(id) ON DELETE CASCADE,
    owner_user_id TEXT,
    target_kind TEXT NOT NULL CHECK(target_kind IN (
        'PRIVATE','SUPPLEMENT','AUTO_COURSE'
    )),
    status TEXT NOT NULL CHECK(status IN (
        'WAITING_SOURCE','QUEUED','BUILDING','READY','READY_WITH_EXCEPTIONS',
        'EXISTING_ACTIVE','BLOCKED','FAILED','UNKNOWN'
    )),
    corpus_fingerprint TEXT CHECK(
        corpus_fingerprint IS NULL OR length(corpus_fingerprint)=64
    ),
    active_job_id TEXT,
    active_tree_version_id TEXT REFERENCES knowledge_tree_versions(id) ON DELETE RESTRICT,
    readable_document_count INTEGER NOT NULL DEFAULT 0 CHECK(readable_document_count>=0),
    unreadable_document_count INTEGER NOT NULL DEFAULT 0 CHECK(unreadable_document_count>=0),
    message TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK(
        (target_kind='AUTO_COURSE' AND workspace_id IS NULL AND owner_user_id IS NULL)
        OR (target_kind!='AUTO_COURSE' AND workspace_id IS NOT NULL AND owner_user_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_auto_knowledge_targets_course
ON auto_knowledge_targets(course_id,owner_user_id,target_kind,status);

CREATE TABLE IF NOT EXISTS auto_knowledge_jobs (
    id TEXT PRIMARY KEY,
    target_key TEXT NOT NULL REFERENCES auto_knowledge_targets(target_key) ON DELETE CASCADE,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    workspace_id TEXT REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    owner_user_id TEXT,
    target_kind TEXT NOT NULL CHECK(target_kind IN (
        'PRIVATE','SUPPLEMENT','AUTO_COURSE'
    )),
    corpus_fingerprint TEXT NOT NULL CHECK(length(corpus_fingerprint)=64),
    builder_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'QUEUED','RUNNING','READY','READY_WITH_EXCEPTIONS','BLOCKED',
        'FAILED','UNKNOWN','SUPERSEDED'
    )),
    source_snapshot_json TEXT NOT NULL CHECK(json_valid(source_snapshot_json)),
    unreadable_sources_json TEXT NOT NULL DEFAULT '[]'
        CHECK(json_valid(unreadable_sources_json)),
    result_tree_version_id TEXT REFERENCES knowledge_tree_versions(id) ON DELETE RESTRICT,
    model_calls_made INTEGER NOT NULL DEFAULT 0 CHECK(model_calls_made>=0),
    repair_calls_made INTEGER NOT NULL DEFAULT 0 CHECK(repair_calls_made BETWEEN 0 AND 2),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
    lease_owner TEXT,
    lease_expires_at TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    completed_at TEXT,
    UNIQUE(target_key,corpus_fingerprint,builder_version)
);

CREATE INDEX IF NOT EXISTS idx_auto_knowledge_jobs_claim
ON auto_knowledge_jobs(status,lease_expires_at,created_at);

CREATE TABLE IF NOT EXISTS auto_knowledge_job_artifacts (
    job_id TEXT NOT NULL REFERENCES auto_knowledge_jobs(id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK(stage IN ('SECTION_MAP','TEACHING_SPEC')),
    shard_key TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK(length(input_hash)=64),
    model_operation_id TEXT NOT NULL,
    output_json TEXT NOT NULL CHECK(json_valid(output_json)),
    output_hash TEXT NOT NULL CHECK(length(output_hash)=64),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(job_id,stage,shard_key),
    UNIQUE(model_operation_id)
);

CREATE INDEX IF NOT EXISTS idx_auto_knowledge_artifacts_job
ON auto_knowledge_job_artifacts(job_id,stage,created_at);

CREATE TABLE IF NOT EXISTS auto_knowledge_job_sources (
    job_id TEXT NOT NULL REFERENCES auto_knowledge_jobs(id) ON DELETE CASCADE,
    -- These are frozen audit identities, not lifecycle locks. A learner may
    -- later delete a private source; its hash/identity remains in the receipt
    -- while the original document follows the existing deletion policy.
    document_id TEXT NOT NULL,
    document_version_id TEXT NOT NULL,
    source_scope TEXT NOT NULL CHECK(source_scope IN (
        'OFFICIAL','OWNER_COURSE','WORKSPACE_PRIVATE'
    )),
    owner_user_id TEXT,
    sha256 TEXT NOT NULL CHECK(length(sha256)=64),
    chunk_count INTEGER NOT NULL CHECK(chunk_count>=0),
    PRIMARY KEY(job_id,document_version_id)
);

CREATE TABLE IF NOT EXISTS auto_knowledge_job_receipts (
    job_id TEXT PRIMARY KEY REFERENCES auto_knowledge_jobs(id) ON DELETE RESTRICT,
    target_key TEXT NOT NULL,
    corpus_fingerprint TEXT NOT NULL CHECK(length(corpus_fingerprint)=64),
    status TEXT NOT NULL CHECK(status IN (
        'READY','READY_WITH_EXCEPTIONS','BLOCKED','FAILED','UNKNOWN','SUPERSEDED'
    )),
    tree_version_id TEXT REFERENCES knowledge_tree_versions(id) ON DELETE RESTRICT,
    source_snapshot_hash TEXT NOT NULL CHECK(length(source_snapshot_hash)=64),
    result_hash TEXT CHECK(result_hash IS NULL OR length(result_hash)=64),
    model_calls_made INTEGER NOT NULL CHECK(model_calls_made>=0),
    detail_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(detail_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Machine-validated course-wide maps are intentionally distinct from reviewed
-- OFFICIAL publication. The referenced tree stays OFFICIAL/DRAFT and therefore
-- can never be mistaken for an independently reviewed release.
CREATE TABLE IF NOT EXISTS auto_course_tree_activations (
    course_id TEXT PRIMARY KEY REFERENCES courses(id) ON DELETE CASCADE,
    tree_version_id TEXT NOT NULL UNIQUE
        REFERENCES knowledge_tree_versions(id) ON DELETE RESTRICT,
    corpus_fingerprint TEXT NOT NULL CHECK(length(corpus_fingerprint)=64),
    status TEXT NOT NULL CHECK(status IN ('ACTIVE','RETIRED')),
    label TEXT NOT NULL DEFAULT 'AI整理 · 未经人工审核',
    activated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    retired_at TEXT
);

-- Browser multi-file selections are one logical corpus revision. Individual
-- files still use the existing single-file ingestion API, while this durable
-- envelope prevents a worker from rebuilding the course between items.
CREATE TABLE IF NOT EXISTS auto_knowledge_upload_batches (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    source_course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL,
    expected_items INTEGER NOT NULL CHECK(expected_items BETWEEN 1 AND 500),
    status TEXT NOT NULL DEFAULT 'OPEN'
        CHECK(status IN ('OPEN','SEALED','ABANDONED')),
    expires_at TEXT NOT NULL,
    seal_hash TEXT CHECK(seal_hash IS NULL OR length(seal_hash)=64),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    sealed_at TEXT,
    UNIQUE(owner_user_id,course_id,id)
);

CREATE INDEX IF NOT EXISTS idx_auto_knowledge_upload_batches_open
ON auto_knowledge_upload_batches(source_course_id,status,expires_at);

CREATE TABLE IF NOT EXISTS auto_knowledge_upload_batch_items (
    batch_id TEXT NOT NULL REFERENCES auto_knowledge_upload_batches(id) ON DELETE CASCADE,
    item_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'ACCEPTED','INDEXED','FAILED','CANCELLED','ABANDONED'
    )),
    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    error_code TEXT,
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(batch_id,item_key)
);

CREATE INDEX IF NOT EXISTS idx_auto_knowledge_upload_items_batch
ON auto_knowledge_upload_batch_items(batch_id,status,item_key);

-- A learner supplement may reuse the currently activated machine course map,
-- just as it may reuse a reviewed official map. Replace migration 014's guard
-- with the same policy plus this narrowly scoped candidate branch. Candidate
-- nodes from any non-active draft remain forbidden.
DROP TRIGGER IF EXISTS validate_tree_membership_insert;
CREATE TRIGGER validate_tree_membership_insert
BEFORE INSERT ON knowledge_tree_memberships
WHEN NOT EXISTS(
    SELECT 1
    FROM knowledge_tree_versions AS tree
    JOIN knowledge_nodes AS node
      ON node.id=NEW.node_id AND node.course_id=tree.course_id
    LEFT JOIN teaching_spec_metadata AS spec
      ON spec.node_id=NEW.node_id AND spec.version=NEW.teaching_spec_version
    WHERE tree.id=NEW.tree_version_id AND (
      (tree.tree_kind='OFFICIAL' AND node.owner_user_id IS NULL
       AND node.status IN ('CANDIDATE','PUBLISHED') AND (
         (node.kind='COMPOSITE' AND NEW.teaching_spec_version IS NULL) OR
         (node.kind='ATOMIC' AND NEW.teaching_spec_version IS NOT NULL
          AND spec.status IN ('DRAFT','PUBLISHED'))
       )) OR
      (tree.tree_kind='PERSONALIZED' AND (
        (node.owner_user_id=tree.owner_user_id AND node.status='PRIVATE' AND (
          (node.kind='COMPOSITE' AND NEW.teaching_spec_version IS NULL) OR
          (node.kind='ATOMIC' AND NEW.teaching_spec_version IS NOT NULL
           AND spec.status='PRIVATE_ACTIVE')
        )) OR
        (node.owner_user_id IS NULL AND node.status='PUBLISHED' AND (
          (node.kind='COMPOSITE' AND NEW.teaching_spec_version IS NULL) OR
          (node.kind='ATOMIC' AND NEW.teaching_spec_version IS NOT NULL
           AND spec.status='PUBLISHED')
        )) OR
        (node.owner_user_id IS NULL AND node.status='CANDIDATE' AND
         EXISTS(
           SELECT 1 FROM auto_course_tree_activations AS activation
           JOIN knowledge_tree_memberships AS active_member
             ON active_member.tree_version_id=activation.tree_version_id
           WHERE activation.course_id=tree.course_id
             AND activation.status='ACTIVE'
             AND active_member.node_id=NEW.node_id
             AND active_member.teaching_spec_version IS NEW.teaching_spec_version
         ) AND (
          (node.kind='COMPOSITE' AND NEW.teaching_spec_version IS NULL) OR
          (node.kind='ATOMIC' AND NEW.teaching_spec_version IS NOT NULL
           AND spec.status='DRAFT')
        ))
      ))
    )
)
BEGIN
    SELECT RAISE(ABORT, 'Knowledge node is not an authorized tree source');
END;

DROP TRIGGER IF EXISTS validate_tree_membership_update;
CREATE TRIGGER validate_tree_membership_update
BEFORE UPDATE OF tree_version_id,node_id,teaching_spec_version
ON knowledge_tree_memberships
WHEN NOT EXISTS(
    SELECT 1
    FROM knowledge_tree_versions AS tree
    JOIN knowledge_nodes AS node
      ON node.id=NEW.node_id AND node.course_id=tree.course_id
    LEFT JOIN teaching_spec_metadata AS spec
      ON spec.node_id=NEW.node_id AND spec.version=NEW.teaching_spec_version
    WHERE tree.id=NEW.tree_version_id AND (
      (tree.tree_kind='OFFICIAL' AND node.owner_user_id IS NULL
       AND node.status IN ('CANDIDATE','PUBLISHED') AND (
         (node.kind='COMPOSITE' AND NEW.teaching_spec_version IS NULL) OR
         (node.kind='ATOMIC' AND NEW.teaching_spec_version IS NOT NULL
          AND spec.status IN ('DRAFT','PUBLISHED'))
       )) OR
      (tree.tree_kind='PERSONALIZED' AND (
        (node.owner_user_id=tree.owner_user_id AND node.status='PRIVATE' AND (
          (node.kind='COMPOSITE' AND NEW.teaching_spec_version IS NULL) OR
          (node.kind='ATOMIC' AND NEW.teaching_spec_version IS NOT NULL
           AND spec.status='PRIVATE_ACTIVE')
        )) OR
        (node.owner_user_id IS NULL AND node.status='PUBLISHED' AND (
          (node.kind='COMPOSITE' AND NEW.teaching_spec_version IS NULL) OR
          (node.kind='ATOMIC' AND NEW.teaching_spec_version IS NOT NULL
           AND spec.status='PUBLISHED')
        )) OR
        (node.owner_user_id IS NULL AND node.status='CANDIDATE' AND
         EXISTS(
           SELECT 1 FROM auto_course_tree_activations AS activation
           JOIN knowledge_tree_memberships AS active_member
             ON active_member.tree_version_id=activation.tree_version_id
           WHERE activation.course_id=tree.course_id
             AND activation.status='ACTIVE'
             AND active_member.node_id=NEW.node_id
             AND active_member.teaching_spec_version IS NEW.teaching_spec_version
         ) AND (
          (node.kind='COMPOSITE' AND NEW.teaching_spec_version IS NULL) OR
          (node.kind='ATOMIC' AND NEW.teaching_spec_version IS NOT NULL
           AND spec.status='DRAFT')
        ))
      ))
    )
)
BEGIN
    SELECT RAISE(ABORT, 'Knowledge node is not an authorized tree source');
END;

CREATE TRIGGER IF NOT EXISTS auto_knowledge_document_ready
AFTER UPDATE OF status ON documents
WHEN NEW.status='ready' AND OLD.status!='ready'
BEGIN
    INSERT INTO auto_knowledge_source_events(
        source_course_id,document_id,event_kind,batch_key,not_before
    ) VALUES(
        NEW.course_id,NEW.id,'DOCUMENT_READY','document:' || NEW.course_id,
        strftime('%Y-%m-%dT%H:%M:%fZ','now','+60 seconds')
    );
END;

-- Normal ingestion transitions pending -> ready, but a trusted importer may
-- atomically insert an already indexed READY document.  Capture that path too
-- so every ingress reaches the same quiet-window/reconciliation pipeline.
CREATE TRIGGER IF NOT EXISTS auto_knowledge_document_inserted_ready
AFTER INSERT ON documents
WHEN NEW.status='ready'
BEGIN
    INSERT INTO auto_knowledge_source_events(
        source_course_id,document_id,event_kind,batch_key,not_before
    ) VALUES(
        NEW.course_id,NEW.id,'DOCUMENT_READY','document:' || NEW.course_id,
        strftime('%Y-%m-%dT%H:%M:%fZ','now','+60 seconds')
    );
END;

CREATE TRIGGER IF NOT EXISTS auto_knowledge_document_unavailable
AFTER UPDATE OF status ON documents
WHEN OLD.status='ready' AND NEW.status!='ready'
BEGIN
    INSERT INTO auto_knowledge_source_events(
        source_course_id,document_id,event_kind,batch_key,not_before
    ) VALUES(
        NEW.course_id,NEW.id,'DOCUMENT_UNAVAILABLE','document:' || NEW.course_id,
        strftime('%Y-%m-%dT%H:%M:%fZ','now','+60 seconds')
    );
END;

CREATE TRIGGER IF NOT EXISTS auto_knowledge_document_deleted
AFTER DELETE ON documents
BEGIN
    INSERT INTO auto_knowledge_source_events(
        source_course_id,document_id,event_kind,batch_key,not_before
    ) VALUES(
        OLD.course_id,OLD.id,'DOCUMENT_DELETED','document:' || OLD.course_id,
        strftime('%Y-%m-%dT%H:%M:%fZ','now','+60 seconds')
    );
END;

CREATE TRIGGER IF NOT EXISTS auto_knowledge_upload_batch_released
AFTER UPDATE OF status ON auto_knowledge_upload_batches
WHEN OLD.status='OPEN' AND NEW.status IN ('SEALED','ABANDONED')
BEGIN
    INSERT INTO auto_knowledge_source_events(
        source_course_id,document_id,event_kind,batch_key,not_before
    ) VALUES(
        NEW.source_course_id,NULL,'RECONCILIATION','upload-batch:' || NEW.id,
        strftime('%Y-%m-%dT%H:%M:%fZ','now')
    );
END;

-- Canvas imports already have authoritative job/session terminal states. Their
-- ordinary per-document events remain useful, while these completion receipts
-- release the whole imported course without relying on browser timing.
CREATE TRIGGER IF NOT EXISTS auto_knowledge_canvas_import_finished
AFTER UPDATE OF status ON canvas_import_jobs
WHEN OLD.status NOT IN ('COMPLETED','COMPLETED_WITH_WARNINGS','FAILED','CANCELLED')
 AND NEW.status IN ('COMPLETED','COMPLETED_WITH_WARNINGS','FAILED','CANCELLED')
 AND NEW.target_course_id IS NOT NULL
BEGIN
    INSERT INTO auto_knowledge_source_events(
        source_course_id,document_id,event_kind,batch_key,not_before
    ) VALUES(
        NEW.target_course_id,NULL,'RECONCILIATION','canvas-job:' || NEW.id,
        strftime('%Y-%m-%dT%H:%M:%fZ','now')
    );
END;

CREATE TRIGGER IF NOT EXISTS auto_knowledge_canvas_local_finished
AFTER UPDATE OF status ON canvas_local_sessions
WHEN OLD.status NOT IN ('COMPLETED','COMPLETED_WITH_WARNINGS','FAILED','CANCELLED','EXPIRED')
 AND NEW.status IN ('COMPLETED','COMPLETED_WITH_WARNINGS','FAILED','CANCELLED','EXPIRED')
BEGIN
    INSERT INTO auto_knowledge_source_events(
        source_course_id,document_id,event_kind,batch_key,not_before
    )
    SELECT DISTINCT file.target_course_id,NULL,'RECONCILIATION',
           'canvas-local:' || NEW.id,strftime('%Y-%m-%dT%H:%M:%fZ','now')
    FROM canvas_local_files AS file
    WHERE file.session_id=NEW.id AND length(file.target_course_id)>0;
END;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(42,'persistent automatic knowledge map jobs and activations');
