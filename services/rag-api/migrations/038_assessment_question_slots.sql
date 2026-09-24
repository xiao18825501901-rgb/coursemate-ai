-- Bind five server-authored assessment intents to the READY question revisions
-- produced for one existing preparation job.  This is selection provenance,
-- not a second question pool and not grade/progress state.

-- One five-slot preparation performs five author calls and five independent
-- blind-solver calls inside one idempotent learning operation.  Widen the two
-- existing ledgers to name those roles and allow more than one call with the
-- same role in that operation.  Reservation ids remain unique; operation
-- claim/replay remains the idempotency boundary.
PRAGMA foreign_keys=OFF;
PRAGMA legacy_alter_table=ON;

CREATE TABLE learning_model_run_evidence_new (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN (
        'planner','teacher','problem','grader','router',
        'reference','preparation','explanation',
        'QUESTION_AUTHOR','QUESTION_BLIND_SOLVER'
    )),
    model_id TEXT NOT NULL,
    provider_label TEXT NOT NULL,
    protocol TEXT NOT NULL,
    region_label TEXT NOT NULL,
    template_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    input_hash TEXT CHECK(
        input_hash IS NULL OR
        (length(input_hash) = 64 AND input_hash NOT GLOB '*[^0-9a-f]*')
    ),
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    latency_ms INTEGER NOT NULL CHECK(latency_ms >= 0),
    input_tokens INTEGER NOT NULL CHECK(input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK(output_tokens >= 0),
    status TEXT NOT NULL
        CHECK(status IN ('COMPLETED','FAILED','UNKNOWN','BLOCKED','LEGACY_COMPLETED')),
    error_class TEXT CHECK(error_class IS NULL OR length(error_class) BETWEEN 1 AND 100),
    provider_response_id TEXT,
    FOREIGN KEY(workspace_id, operation_id)
        REFERENCES learning_operations(workspace_id, id) ON DELETE RESTRICT
);

INSERT INTO learning_model_run_evidence_new
SELECT * FROM learning_model_run_evidence;
DROP TABLE learning_model_run_evidence;
ALTER TABLE learning_model_run_evidence_new RENAME TO learning_model_run_evidence;

CREATE INDEX idx_learning_model_run_operation
ON learning_model_run_evidence(workspace_id, operation_id, role);

CREATE TABLE learning_model_call_reservations_new (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN (
        'planner','teacher','problem','grader','router',
        'reference','preparation','explanation',
        'QUESTION_AUTHOR','QUESTION_BLIND_SOLVER'
    )),
    reserved_output_tokens INTEGER NOT NULL CHECK(reserved_output_tokens > 0),
    status TEXT NOT NULL
        CHECK(status IN ('RESERVED','COMPLETED','FAILED','UNKNOWN','BLOCKED')),
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK(output_tokens >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at TEXT,
    FOREIGN KEY(workspace_id, operation_id)
        REFERENCES learning_operations(workspace_id, id) ON DELETE RESTRICT,
    CHECK(
        (status = 'RESERVED' AND finished_at IS NULL)
        OR (status != 'RESERVED' AND finished_at IS NOT NULL)
    )
);

INSERT INTO learning_model_call_reservations_new
SELECT * FROM learning_model_call_reservations;
DROP TABLE learning_model_call_reservations;
ALTER TABLE learning_model_call_reservations_new RENAME TO learning_model_call_reservations;

CREATE INDEX idx_model_call_reservations_owner_day
ON learning_model_call_reservations(owner_user_id, created_at);

CREATE INDEX idx_model_call_reservations_owner_course_day
ON learning_model_call_reservations(owner_user_id, course_id, created_at);

CREATE TABLE IF NOT EXISTS assessment_preparation_questions (
    preparation_job_id TEXT NOT NULL
        REFERENCES assessment_preparation_jobs(id) ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL
        REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 5),
    slot_key TEXT NOT NULL CHECK(length(trim(slot_key)) BETWEEN 1 AND 100),
    marks INTEGER NOT NULL,
    objective_id TEXT NOT NULL CHECK(length(trim(objective_id)) BETWEEN 1 AND 100),
    blueprint_id TEXT NOT NULL CHECK(length(trim(blueprint_id)) BETWEEN 1 AND 100),
    question_revision_id TEXT NOT NULL
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    family_id TEXT NOT NULL CHECK(length(trim(family_id)) BETWEEN 1 AND 100),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(preparation_job_id, ordinal),
    UNIQUE(preparation_job_id, slot_key),
    UNIQUE(preparation_job_id, question_revision_id),
    UNIQUE(preparation_job_id, family_id),
    CHECK(
        (ordinal=1 AND marks=10) OR
        (ordinal=2 AND marks=15) OR
        (ordinal=3 AND marks=20) OR
        (ordinal=4 AND marks=25) OR
        (ordinal=5 AND marks=30)
    )
);

CREATE TRIGGER IF NOT EXISTS validate_assessment_preparation_question
BEFORE INSERT ON assessment_preparation_questions
WHEN NOT EXISTS(
    SELECT 1
    FROM assessment_preparation_jobs AS job
    JOIN question_engine_provenance AS provenance
      ON provenance.question_revision_id=NEW.question_revision_id
    JOIN assessment_question_revisions AS question
      ON question.id=provenance.question_revision_id
    WHERE job.id=NEW.preparation_job_id
      AND job.workspace_id=NEW.workspace_id
      AND job.node_id=provenance.node_id
      AND job.spec_version=provenance.spec_version
      AND provenance.workspace_id=NEW.workspace_id
      AND provenance.objective_id=NEW.objective_id
      AND provenance.blueprint_id=NEW.blueprint_id
      AND provenance.publication_status='READY'
      AND question.validation_status='VALIDATED'
      AND question.verification_method='AI_REVIEWED'
      AND question.family_id=NEW.family_id
      AND json_extract(provenance.blueprint_json,'$.marks')=NEW.marks
      AND json_extract(provenance.blueprint_json,'$.generation_policy_version')=
          'assessment-question-slot-policy-v1'
)
BEGIN
    SELECT RAISE(ABORT, 'Assessment slot does not match its READY preparation question');
END;

CREATE TRIGGER IF NOT EXISTS immutable_assessment_preparation_question_update
BEFORE UPDATE ON assessment_preparation_questions
BEGIN
    SELECT RAISE(ABORT, 'Assessment preparation question bindings are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_assessment_preparation_question_delete
BEFORE DELETE ON assessment_preparation_questions
BEGIN
    SELECT RAISE(ABORT, 'Assessment preparation question bindings are immutable');
END;

PRAGMA legacy_alter_table=OFF;
PRAGMA foreign_keys=ON;

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(38, 'five complementary assessment question slot bindings');
