-- Freeze source identity and provenance without replacing V2 document/chunk rows.
CREATE TABLE IF NOT EXISTS document_versions (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK(version >= 1),
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    owner_user_id TEXT,
    source_scope TEXT NOT NULL
        CHECK(source_scope IN ('OFFICIAL','OWNER_COURSE','WORKSPACE_PRIVATE')),
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    media_type TEXT NOT NULL,
    extension TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
    byte_size INTEGER NOT NULL CHECK(byte_size >= 0),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(document_id, version),
    UNIQUE(document_id, sha256),
    CHECK(
        (source_scope = 'OFFICIAL' AND owner_user_id IS NULL)
        OR (source_scope != 'OFFICIAL' AND owner_user_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_document_versions_scope
ON document_versions(source_scope, owner_user_id, course_id, document_id, version);

CREATE TRIGGER IF NOT EXISTS immutable_document_versions
BEFORE UPDATE ON document_versions
BEGIN
    SELECT RAISE(ABORT, 'Document versions are immutable');
END;

INSERT OR IGNORE INTO document_versions(
    id, document_id, version, course_id, owner_user_id, source_scope,
    filename, stored_path, media_type, extension, sha256, byte_size, created_at
)
SELECT
    documents.id || '-v1',
    documents.id,
    1,
    documents.course_id,
    CASE
        WHEN learning_workspaces.id IS NOT NULL THEN learning_workspaces.owner_user_id
        WHEN courses.course_type = 'user' THEN courses.owner_user_id
        ELSE NULL
    END,
    CASE
        WHEN learning_workspaces.id IS NOT NULL THEN 'WORKSPACE_PRIVATE'
        WHEN courses.course_type = 'user' THEN 'OWNER_COURSE'
        ELSE 'OFFICIAL'
    END,
    documents.filename,
    documents.stored_path,
    documents.media_type,
    documents.extension,
    documents.sha256,
    documents.byte_size,
    documents.created_at
FROM documents
JOIN courses ON courses.id = documents.course_id
LEFT JOIN learning_workspaces
    ON learning_workspaces.private_course_id = documents.course_id;

CREATE TRIGGER IF NOT EXISTS create_initial_document_version
AFTER INSERT ON documents
BEGIN
    INSERT INTO document_versions(
        id, document_id, version, course_id, owner_user_id, source_scope,
        filename, stored_path, media_type, extension, sha256, byte_size, created_at
    )
    SELECT
        NEW.id || '-v1',
        NEW.id,
        1,
        NEW.course_id,
        CASE
            WHEN learning_workspaces.id IS NOT NULL THEN learning_workspaces.owner_user_id
            WHEN courses.course_type = 'user' THEN courses.owner_user_id
            ELSE NULL
        END,
        CASE
            WHEN learning_workspaces.id IS NOT NULL THEN 'WORKSPACE_PRIVATE'
            WHEN courses.course_type = 'user' THEN 'OWNER_COURSE'
            ELSE 'OFFICIAL'
        END,
        NEW.filename,
        NEW.stored_path,
        NEW.media_type,
        NEW.extension,
        NEW.sha256,
        NEW.byte_size,
        NEW.created_at
    FROM courses
    LEFT JOIN learning_workspaces
        ON learning_workspaces.private_course_id = NEW.course_id
    WHERE courses.id = NEW.course_id;
END;

CREATE TABLE IF NOT EXISTS derived_artifacts (
    id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL
        REFERENCES document_versions(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN (
        'SAFE_TEXT','TABLE_PREVIEW','NOTEBOOK_PREVIEW','PREVIEW_PDF','THUMBNAIL'
    )),
    status TEXT NOT NULL CHECK(status IN ('READY','FAILED','REVOKED')),
    media_type TEXT,
    stored_path TEXT,
    sha256 TEXT CHECK(sha256 IS NULL OR length(sha256) = 64),
    byte_size INTEGER CHECK(byte_size IS NULL OR byte_size >= 0),
    producer_version TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK(
        (status = 'READY' AND stored_path IS NOT NULL AND media_type IS NOT NULL
         AND sha256 IS NOT NULL AND byte_size IS NOT NULL AND error_code IS NULL)
        OR (status != 'READY' AND error_code IS NOT NULL)
    ),
    UNIQUE(document_version_id, kind, producer_version)
);

CREATE INDEX IF NOT EXISTS idx_derived_artifacts_version
ON derived_artifacts(document_version_id, kind, status, created_at);

CREATE TABLE IF NOT EXISTS chunk_source_versions (
    chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    document_version_id TEXT NOT NULL
        REFERENCES document_versions(id) ON DELETE CASCADE
);

INSERT OR IGNORE INTO chunk_source_versions(chunk_id, document_version_id)
SELECT chunks.id, document_versions.id
FROM chunks
JOIN document_versions
    ON document_versions.document_id = chunks.document_id
   AND document_versions.version = (
       SELECT MAX(latest.version)
       FROM document_versions AS latest
       WHERE latest.document_id = chunks.document_id
   );

CREATE TRIGGER IF NOT EXISTS bind_chunk_to_document_version
AFTER INSERT ON chunks
BEGIN
    INSERT INTO chunk_source_versions(chunk_id, document_version_id)
    SELECT NEW.id, document_versions.id
    FROM document_versions
    WHERE document_versions.document_id = NEW.document_id
    ORDER BY document_versions.version DESC
    LIMIT 1;
END;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(13,'immutable document versions and derived artifact provenance');
