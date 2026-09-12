CREATE TABLE IF NOT EXISTS learning_model_call_reservations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('planner','teacher','problem','grader','router')),
    reserved_output_tokens INTEGER NOT NULL CHECK(reserved_output_tokens > 0),
    status TEXT NOT NULL
        CHECK(status IN ('RESERVED','COMPLETED','FAILED','UNKNOWN','BLOCKED')),
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK(output_tokens >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at TEXT,
    FOREIGN KEY(workspace_id, operation_id)
        REFERENCES learning_operations(workspace_id, id) ON DELETE RESTRICT,
    UNIQUE(workspace_id, operation_id, role),
    CHECK(
        (status = 'RESERVED' AND finished_at IS NULL)
        OR (status != 'RESERVED' AND finished_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_model_call_reservations_owner_day
ON learning_model_call_reservations(owner_user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_model_call_reservations_owner_course_day
ON learning_model_call_reservations(owner_user_id, course_id, created_at);

INSERT OR IGNORE INTO learning_model_call_reservations(
    id,workspace_id,operation_id,owner_user_id,course_id,role,
    reserved_output_tokens,status,input_tokens,output_tokens,created_at,finished_at
)
SELECT
    'evidence-' || evidence.id,
    evidence.workspace_id,
    evidence.operation_id,
    workspace.owner_user_id,
    workspace.course_id,
    evidence.role,
    MAX(1,evidence.output_tokens),
    CASE evidence.status
        WHEN 'LEGACY_COMPLETED' THEN 'COMPLETED'
        ELSE evidence.status
    END,
    evidence.input_tokens,
    evidence.output_tokens,
    evidence.started_at,
    evidence.finished_at
FROM learning_model_run_evidence AS evidence
JOIN learning_workspaces AS workspace ON workspace.id=evidence.workspace_id;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(21,'model call budget reservations');
