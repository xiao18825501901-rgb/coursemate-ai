-- Additive route metadata: no old model receipt, assessment or UNKNOWN rewrite.
CREATE TABLE IF NOT EXISTS model_route_epochs (
    id INTEGER PRIMARY KEY CHECK(id=1),
    policy_version TEXT NOT NULL CHECK(policy_version='cj.route.v1'),
    baseline_route_json TEXT NOT NULL CHECK(json_valid(baseline_route_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS model_route_legacy_jobs (
    job_id TEXT PRIMARY KEY REFERENCES auto_knowledge_jobs(id) ON DELETE CASCADE,
    epoch_id INTEGER NOT NULL REFERENCES model_route_epochs(id),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS auto_knowledge_operation_context (
    workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    job_id TEXT NOT NULL REFERENCES auto_knowledge_jobs(id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK(stage IN ('SECTION_MAP','TEACHING_SPEC')),
    PRIMARY KEY(workspace_id,operation_id),
    FOREIGN KEY(workspace_id,operation_id) REFERENCES learning_operations(workspace_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS learning_role_routes (
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    operation_id TEXT NOT NULL,
    caller_role TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
    snapshot_hash TEXT NOT NULL CHECK(length(snapshot_hash)=64),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(workspace_id,operation_id,caller_role)
);
CREATE TRIGGER IF NOT EXISTS model_route_epoch_immutable BEFORE UPDATE ON model_route_epochs
BEGIN SELECT RAISE(ABORT,'Route epoch is immutable'); END;
CREATE TRIGGER IF NOT EXISTS model_route_epoch_no_delete BEFORE DELETE ON model_route_epochs
BEGIN SELECT RAISE(ABORT,'Route epoch cannot be reset'); END;
CREATE TRIGGER IF NOT EXISTS model_route_legacy_job_immutable BEFORE UPDATE ON model_route_legacy_jobs
BEGIN SELECT RAISE(ABORT,'Legacy job identity is immutable'); END;
CREATE TRIGGER IF NOT EXISTS auto_operation_context_immutable BEFORE UPDATE ON auto_knowledge_operation_context
BEGIN SELECT RAISE(ABORT,'Auto operation context is immutable'); END;
CREATE TRIGGER IF NOT EXISTS learning_role_route_immutable BEFORE UPDATE ON learning_role_routes
BEGIN SELECT RAISE(ABORT,'Role snapshot is immutable'); END;
CREATE TRIGGER IF NOT EXISTS learning_role_route_no_delete BEFORE DELETE ON learning_role_routes
BEGIN SELECT RAISE(ABORT,'Role snapshots cannot be reset'); END;
INSERT OR IGNORE INTO schema_migrations(version,name) VALUES(75,'immutable learning role route snapshots');
