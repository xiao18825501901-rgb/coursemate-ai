-- Owner-scoped practice interactions for one READY Question Engine revision.
--
-- These rows are diagnostic learning records only.  They do not reference an
-- assessment session, do not create performance_evidence or grade_snapshots,
-- and cannot update learning_coverage / LEARNED.  A hint or revealed answer is
-- recorded explicitly so an assisted attempt is never presented as independent.

CREATE TABLE IF NOT EXISTS practice_interaction_operations (
    workspace_id TEXT NOT NULL
        REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    operation_id TEXT NOT NULL CHECK(length(trim(operation_id)) BETWEEN 8 AND 100),
    question_revision_id TEXT NOT NULL
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL CHECK(length(trim(owner_user_id)) BETWEEN 1 AND 150),
    kind TEXT NOT NULL CHECK(kind IN ('HINT','ATTEMPT')),
    input_hash TEXT NOT NULL CHECK(
        length(input_hash)=64 AND input_hash NOT GLOB '*[^0-9a-f]*'
    ),
    status TEXT NOT NULL CHECK(status IN ('CLAIMED','COMPLETED','FAILED')),
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(workspace_id, operation_id),
    CHECK(
        (status='CLAIMED' AND result_json IS NULL AND error_code IS NULL)
        OR (status='COMPLETED' AND result_json IS NOT NULL AND error_code IS NULL)
        OR (status='FAILED' AND result_json IS NULL AND length(trim(error_code)) BETWEEN 1 AND 100)
    )
);

CREATE TRIGGER IF NOT EXISTS validate_practice_operation_scope
BEFORE INSERT ON practice_interaction_operations
WHEN NOT EXISTS(
    SELECT 1
    FROM question_engine_provenance AS provenance
    JOIN learning_workspaces AS workspace ON workspace.id=provenance.workspace_id
    JOIN assessment_question_revisions AS question
      ON question.id=provenance.question_revision_id
    WHERE provenance.question_revision_id=NEW.question_revision_id
      AND provenance.workspace_id=NEW.workspace_id
      AND provenance.publication_status='READY'
      AND workspace.owner_user_id=NEW.owner_user_id
      AND question.owner_user_id=NEW.owner_user_id
)
BEGIN
    SELECT RAISE(ABORT, 'Practice operation does not match its READY owner workspace');
END;

CREATE TRIGGER IF NOT EXISTS validate_practice_operation_transition
BEFORE UPDATE ON practice_interaction_operations
WHEN OLD.status!='CLAIMED'
  OR NEW.status NOT IN ('COMPLETED','FAILED')
  OR NEW.workspace_id!=OLD.workspace_id
  OR NEW.operation_id!=OLD.operation_id
  OR NEW.question_revision_id!=OLD.question_revision_id
  OR NEW.owner_user_id!=OLD.owner_user_id
  OR NEW.kind!=OLD.kind
  OR NEW.input_hash!=OLD.input_hash
  OR NEW.created_at!=OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'Invalid practice operation transition');
END;

CREATE TRIGGER IF NOT EXISTS immutable_practice_operation_delete
BEFORE DELETE ON practice_interaction_operations
BEGIN
    SELECT RAISE(ABORT, 'Practice operation receipts are immutable');
END;

CREATE TABLE IF NOT EXISTS practice_hint_events (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL
        REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    question_revision_id TEXT NOT NULL
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL CHECK(length(trim(owner_user_id)) BETWEEN 1 AND 150),
    operation_id TEXT NOT NULL CHECK(length(trim(operation_id)) BETWEEN 8 AND 100),
    input_hash TEXT NOT NULL CHECK(
        length(input_hash)=64 AND input_hash NOT GLOB '*[^0-9a-f]*'
    ),
    hint_json TEXT NOT NULL CHECK(json_valid(hint_json)),
    provider_run_json TEXT NOT NULL CHECK(json_valid(provider_run_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(workspace_id, operation_id),
    FOREIGN KEY(workspace_id, operation_id)
        REFERENCES practice_interaction_operations(workspace_id, operation_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS practice_question_attempts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL
        REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    question_revision_id TEXT NOT NULL
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL CHECK(length(trim(owner_user_id)) BETWEEN 1 AND 150),
    operation_id TEXT NOT NULL CHECK(length(trim(operation_id)) BETWEEN 8 AND 100),
    input_hash TEXT NOT NULL CHECK(
        length(input_hash)=64 AND input_hash NOT GLOB '*[^0-9a-f]*'
    ),
    submitted_answer TEXT NOT NULL CHECK(length(trim(submitted_answer)) BETWEEN 1 AND 6000),
    assistance TEXT NOT NULL CHECK(assistance IN ('NONE','HINT','ANSWER_REVEALED')),
    status TEXT NOT NULL CHECK(status IN ('GRADED','NEEDS_REVIEW')),
    feedback_json TEXT NOT NULL CHECK(json_valid(feedback_json)),
    provider_run_json TEXT NOT NULL CHECK(json_valid(provider_run_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(workspace_id, operation_id),
    FOREIGN KEY(workspace_id, operation_id)
        REFERENCES practice_interaction_operations(workspace_id, operation_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_practice_hints_question
ON practice_hint_events(workspace_id, question_revision_id, created_at);

CREATE INDEX IF NOT EXISTS idx_practice_attempts_question
ON practice_question_attempts(workspace_id, question_revision_id, created_at);

CREATE TRIGGER IF NOT EXISTS validate_practice_hint_scope
BEFORE INSERT ON practice_hint_events
WHEN NOT EXISTS(
    SELECT 1
    FROM practice_interaction_operations AS operation
    WHERE operation.workspace_id=NEW.workspace_id
      AND operation.operation_id=NEW.operation_id
      AND operation.question_revision_id=NEW.question_revision_id
      AND operation.owner_user_id=NEW.owner_user_id
      AND operation.kind='HINT'
      AND operation.input_hash=NEW.input_hash
      AND operation.status='CLAIMED'
) OR NOT EXISTS(
    SELECT 1
    FROM question_engine_provenance AS provenance
    JOIN learning_workspaces AS workspace ON workspace.id=provenance.workspace_id
    JOIN assessment_question_revisions AS question
      ON question.id=provenance.question_revision_id
    WHERE provenance.question_revision_id=NEW.question_revision_id
      AND provenance.workspace_id=NEW.workspace_id
      AND provenance.publication_status='READY'
      AND workspace.owner_user_id=NEW.owner_user_id
      AND question.owner_user_id=NEW.owner_user_id
)
BEGIN
    SELECT RAISE(ABORT, 'Practice hint does not match its READY owner workspace');
END;

CREATE TRIGGER IF NOT EXISTS validate_practice_attempt_scope
BEFORE INSERT ON practice_question_attempts
WHEN NOT EXISTS(
    SELECT 1
    FROM practice_interaction_operations AS operation
    WHERE operation.workspace_id=NEW.workspace_id
      AND operation.operation_id=NEW.operation_id
      AND operation.question_revision_id=NEW.question_revision_id
      AND operation.owner_user_id=NEW.owner_user_id
      AND operation.kind='ATTEMPT'
      AND operation.input_hash=NEW.input_hash
      AND operation.status='CLAIMED'
) OR NOT EXISTS(
    SELECT 1
    FROM question_engine_provenance AS provenance
    JOIN learning_workspaces AS workspace ON workspace.id=provenance.workspace_id
    JOIN assessment_question_revisions AS question
      ON question.id=provenance.question_revision_id
    WHERE provenance.question_revision_id=NEW.question_revision_id
      AND provenance.workspace_id=NEW.workspace_id
      AND provenance.publication_status='READY'
      AND workspace.owner_user_id=NEW.owner_user_id
      AND question.owner_user_id=NEW.owner_user_id
)
BEGIN
    SELECT RAISE(ABORT, 'Practice attempt does not match its READY owner workspace');
END;

CREATE TRIGGER IF NOT EXISTS immutable_practice_hint_update
BEFORE UPDATE ON practice_hint_events
BEGIN
    SELECT RAISE(ABORT, 'Practice hint events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_practice_hint_delete
BEFORE DELETE ON practice_hint_events
BEGIN
    SELECT RAISE(ABORT, 'Practice hint events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_practice_attempt_update
BEFORE UPDATE ON practice_question_attempts
BEGIN
    SELECT RAISE(ABORT, 'Practice attempts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_practice_attempt_delete
BEFORE DELETE ON practice_question_attempts
BEGIN
    SELECT RAISE(ABORT, 'Practice attempts are immutable');
END;

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(37, 'owner scoped practice question interactions');
