CREATE TABLE IF NOT EXISTS knowledge_nodes (
 id TEXT PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(id), owner_user_id TEXT,
 title TEXT NOT NULL, description TEXT NOT NULL, major TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('ATOMIC','COMPOSITE')),
 status TEXT NOT NULL CHECK(status IN ('PRIVATE','CANDIDATE','PUBLISHED','RETIRED')),
 created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK((owner_user_id IS NOT NULL AND status='PRIVATE') OR (owner_user_id IS NULL AND status!='PRIVATE'))
);
CREATE TABLE IF NOT EXISTS teaching_specs (
 node_id TEXT NOT NULL REFERENCES knowledge_nodes(id), version INTEGER NOT NULL CHECK(version>0),
 content_json TEXT NOT NULL CHECK(json_valid(content_json)), content_hash TEXT NOT NULL,
 PRIMARY KEY(node_id,version)
);
CREATE TRIGGER IF NOT EXISTS immutable_teaching_specs BEFORE UPDATE ON teaching_specs
BEGIN SELECT RAISE(ABORT,'Teaching specifications are immutable'); END;
CREATE TABLE IF NOT EXISTS learning_journeys (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id),
 node_id TEXT NOT NULL, spec_version INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'LEARNING' CHECK(status IN ('LEARNING','PAUSED','LEARNED')),
 FOREIGN KEY(node_id,spec_version) REFERENCES teaching_specs(node_id,version),
 UNIQUE(workspace_id,node_id,spec_version)
);
CREATE TABLE IF NOT EXISTS learning_operations (
 workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id), id TEXT NOT NULL,
 request_hash TEXT NOT NULL, kind TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('RUNNING','COMPLETED','FAILED','UNKNOWN')),
 result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
 created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 PRIMARY KEY(workspace_id,id)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_learning_operation
 ON learning_operations(workspace_id) WHERE status='RUNNING';
CREATE TABLE IF NOT EXISTS learning_events (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,
 workspace_id TEXT NOT NULL, operation_id TEXT NOT NULL, kind TEXT NOT NULL,
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
 FOREIGN KEY(workspace_id,operation_id) REFERENCES learning_operations(workspace_id,id)
);
CREATE TABLE IF NOT EXISTS learning_problems (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id),
 version INTEGER NOT NULL DEFAULT 1, question TEXT NOT NULL, conditions_json TEXT NOT NULL,
 source_refs_json TEXT NOT NULL DEFAULT '[]', attempt_id TEXT NOT NULL UNIQUE,
 assistance TEXT NOT NULL DEFAULT 'ANSWER_EXPOSED',
 UNIQUE(id,workspace_id)
);
CREATE TABLE IF NOT EXISTS learning_solutions (
 id TEXT PRIMARY KEY, problem_id TEXT NOT NULL REFERENCES learning_problems(id),
 version INTEGER NOT NULL, content_json TEXT NOT NULL CHECK(json_valid(content_json)),
 UNIQUE(problem_id,version)
);
CREATE TABLE IF NOT EXISTS learning_steps (
 id TEXT PRIMARY KEY, solution_id TEXT NOT NULL REFERENCES learning_solutions(id),
 ordinal INTEGER NOT NULL, content_json TEXT NOT NULL CHECK(json_valid(content_json)),
 UNIQUE(solution_id,ordinal)
);
CREATE TABLE IF NOT EXISTS learning_bridges (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id),
 step_id TEXT NOT NULL REFERENCES learning_steps(id), node_id TEXT NOT NULL REFERENCES knowledge_nodes(id),
 journey_id TEXT NOT NULL REFERENCES learning_journeys(id), snapshot_json TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('OPEN','LEARNING','READY_TO_RETURN','COMPLETED','CANCELLED','SOURCE_UNAVAILABLE')),
 revision INTEGER NOT NULL DEFAULT 0,
 UNIQUE(workspace_id,step_id,node_id)
);
CREATE TABLE IF NOT EXISTS teaching_units (
 id TEXT PRIMARY KEY, journey_id TEXT NOT NULL REFERENCES learning_journeys(id),
 operation_id TEXT NOT NULL, workflow TEXT NOT NULL CHECK(workflow IN ('TEACHING','PROBLEM')),
 content_json TEXT NOT NULL CHECK(json_valid(content_json)), plan_json TEXT NOT NULL,
 provenance_json TEXT NOT NULL CHECK(json_valid(provenance_json)),
 created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS learning_coverage (
 journey_id TEXT NOT NULL REFERENCES learning_journeys(id), item_id TEXT NOT NULL,
 unit_id TEXT NOT NULL REFERENCES teaching_units(id), section_ids_json TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 PRIMARY KEY(journey_id,item_id,unit_id)
);
CREATE TABLE IF NOT EXISTS learning_model_runs (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id), operation_id TEXT NOT NULL,
 role TEXT NOT NULL, model TEXT NOT NULL, protocol TEXT NOT NULL,
 prompt_version TEXT NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
 provider_response_id TEXT, created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT OR IGNORE INTO schema_migrations(version,name) VALUES(12,'versioned learning journey and bridge ledger');
