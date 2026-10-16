-- Stable learner intent across the separate configure/prepare/open actions.
-- Existing configurations, questions, sessions, submissions and grades remain
-- immutable and are referenced rather than copied.

CREATE TABLE IF NOT EXISTS assessment_start_intents (
    workspace_id TEXT NOT NULL
        REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    client_intent_id TEXT NOT NULL CHECK(length(trim(client_intent_id)) BETWEEN 1 AND 100),
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    payload_hash TEXT NOT NULL CHECK(
        length(payload_hash)=64 AND payload_hash NOT GLOB '*[^0-9a-f]*'
    ),
    configuration_id TEXT NOT NULL
        REFERENCES assessment_configurations(id) ON DELETE RESTRICT,
    preparation_id TEXT
        REFERENCES assessment_configuration_preparations(id) ON DELETE RESTRICT,
    session_id TEXT REFERENCES assessment_sessions(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK(status IN (
        'CONFIGURED','PREPARING','READY','OPEN','FAILED','ABANDONED'
    )),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(workspace_id,client_intent_id)
);

CREATE INDEX IF NOT EXISTS idx_assessment_start_intent_session
ON assessment_start_intents(workspace_id,session_id);

CREATE TRIGGER IF NOT EXISTS validate_assessment_start_intent_context
BEFORE INSERT ON assessment_start_intents
WHEN NOT EXISTS(
    SELECT 1 FROM assessment_configurations AS configuration
    JOIN learning_workspaces AS workspace
      ON workspace.id=configuration.workspace_id
    WHERE configuration.id=NEW.configuration_id
      AND configuration.status='FROZEN'
      AND configuration.workspace_id=NEW.workspace_id
      AND configuration.owner_user_id=NEW.owner_user_id
      AND configuration.course_id=NEW.course_id
      AND configuration.node_id=NEW.node_id
      AND workspace.owner_user_id=NEW.owner_user_id
)
BEGIN
    SELECT RAISE(ABORT, 'Assessment start intent is outside its owner workspace');
END;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(70,'assessment start intents and history cursor support');
