-- Server creation authority, not a backfill of all private courses.
-- Old courses, operations, model calls, tree artifacts and UNKNOWN stay unchanged.
CREATE TABLE IF NOT EXISTS new_private_tree_origins (
    course_id TEXT PRIMARY KEY REFERENCES courses(id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL,
    operation_family TEXT NOT NULL DEFAULT 'NEW_PRIVATE_COURSE_TREE'
        CHECK(operation_family='NEW_PRIVATE_COURSE_TREE'),
    route_json TEXT NOT NULL CHECK(json_valid(route_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS private_tree_job_bindings (
    job_id TEXT PRIMARY KEY REFERENCES auto_knowledge_jobs(id) ON DELETE CASCADE,
    origin_course_id TEXT NOT NULL REFERENCES new_private_tree_origins(course_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_private_tree_jobs_origin ON private_tree_job_bindings(origin_course_id);
CREATE TABLE IF NOT EXISTS private_tree_operation_bindings (
    workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    job_id TEXT NOT NULL REFERENCES private_tree_job_bindings(job_id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK(stage IN ('SECTION_MAP','TEACHING_SPEC')),
    operation_family TEXT NOT NULL DEFAULT 'NEW_PRIVATE_COURSE_TREE'
        CHECK(operation_family='NEW_PRIVATE_COURSE_TREE'),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(workspace_id,operation_id),
    FOREIGN KEY(workspace_id,operation_id) REFERENCES learning_operations(workspace_id,id) ON DELETE CASCADE
);
CREATE TRIGGER IF NOT EXISTS private_tree_origin_immutable BEFORE UPDATE ON new_private_tree_origins
BEGIN SELECT RAISE(ABORT,'Private tree origin is immutable'); END;
CREATE TRIGGER IF NOT EXISTS private_tree_job_binding_immutable BEFORE UPDATE ON private_tree_job_bindings
BEGIN SELECT RAISE(ABORT,'Private tree job identity is immutable'); END;
CREATE TRIGGER IF NOT EXISTS private_tree_operation_binding_immutable BEFORE UPDATE ON private_tree_operation_bindings
BEGIN SELECT RAISE(ABORT,'Private tree operation family is immutable'); END;
INSERT OR IGNORE INTO schema_migrations(version,name) VALUES(74,'server-owned new private tree origins');
