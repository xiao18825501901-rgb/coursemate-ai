-- Additive only. V2 records and embeddings are unchanged.
CREATE TABLE IF NOT EXISTS learning_workspaces (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    private_course_id TEXT NOT NULL UNIQUE REFERENCES courses(id),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    mode TEXT NOT NULL DEFAULT 'AUTO' CHECK (mode IN ('AUTO','TEACHING','PROBLEM')),
    layout_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(layout_json)),
    cursor_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(cursor_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(owner_user_id,course_id)
);
CREATE TRIGGER IF NOT EXISTS workspace_corpus_never_public
BEFORE UPDATE OF visibility,publication_status,owner_user_id ON courses
WHEN EXISTS(SELECT 1 FROM learning_workspaces WHERE private_course_id=old.id)
AND (new.visibility!='private' OR new.publication_status!='private'
     OR new.owner_user_id IS NOT old.owner_user_id)
BEGIN SELECT RAISE(ABORT,'Workspace corpus cannot be published or transferred'); END;
INSERT OR IGNORE INTO schema_migrations(version,name) VALUES(11,'private learning workspaces');
