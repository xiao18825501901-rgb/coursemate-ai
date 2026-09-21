-- Stage 4/5 assessment extension: pool preparation, frozen reference solutions,
-- unified-answer drafts/submission revisions, grading receipts, and step
-- explanation contexts. The verification METHOD enum gains a dedicated
-- `AI_REVIEWED` diagnostic channel; `MODEL_ONLY` self-assessment remains
-- excluded from every frozen blueprint and from the VALIDATED pool.

-- SQLite cannot ALTER a CHECK constraint, so the two question/blueprint-item
-- tables are recreated with the widened verification_method enum, and the two
-- model-call ledgers are recreated with new role values. A fresh `_new` table is
-- built, copied 1:1, and the old table is DROPPED (never RENAMED, so RENAME can
-- never rewrite foreign keys or triggers that still name the original table).
--
-- Invariant: no trigger may reference assessment_question_revisions or
-- assessment_blueprint_items while those tables are missing/replaced. Every
-- trigger whose body references either table is therefore dropped FIRST and
-- recreated verbatim (minus IF NOT EXISTS) AFTER both tables exist.
PRAGMA foreign_keys=OFF;
PRAGMA legacy_alter_table=ON;

-- Drop every trigger that references either recreated table (including triggers
-- defined on OTHER tables).
DROP TRIGGER IF EXISTS immutable_assessment_question_content;
DROP TRIGGER IF EXISTS revoke_assessment_question_sources_only;
DROP TRIGGER IF EXISTS immutable_assessment_question_delete;
DROP TRIGGER IF EXISTS validate_assessment_rubric_context;
DROP TRIGGER IF EXISTS validate_assessment_blueprint_item;
DROP TRIGGER IF EXISTS immutable_frozen_assessment_blueprint_item_update;
DROP TRIGGER IF EXISTS immutable_assessment_blueprint_item_delete;
DROP TRIGGER IF EXISTS freeze_valid_assessment_blueprint;
DROP TRIGGER IF EXISTS validate_assessment_question_attempt;
DROP TRIGGER IF EXISTS validate_performance_evidence_context;

-- ============================================================ question pool
CREATE TABLE assessment_question_revisions_new (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    owner_user_id TEXT,
    family_id TEXT NOT NULL CHECK(length(trim(family_id)) BETWEEN 1 AND 100),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    source_kind TEXT NOT NULL CHECK(source_kind IN (
        'OFFICIAL','WORKSPACE_PRIVATE','MODEL_GENERATED','EXTERNAL_INSPIRED'
    )),
    source_document_version_id TEXT
        REFERENCES document_versions(id) ON DELETE SET NULL,
    source_problem_revision_id TEXT
        REFERENCES problem_revisions(id) ON DELETE SET NULL,
    question_type TEXT NOT NULL CHECK(question_type IN (
        'MCQ_SINGLE','NUMERIC','SHORT_TEXT','EXPLANATION','CODE'
    )),
    difficulty INTEGER NOT NULL CHECK(difficulty BETWEEN 1 AND 5),
    prompt_text TEXT NOT NULL CHECK(length(trim(prompt_text)) BETWEEN 1 AND 6000),
    options_json TEXT NOT NULL DEFAULT '[]' CHECK(
        json_valid(options_json) AND json_type(options_json)='array'
    ),
    answer_json TEXT NOT NULL CHECK(json_valid(answer_json)),
    validation_status TEXT NOT NULL CHECK(validation_status IN (
        'CANDIDATE','VALIDATED','NEEDS_REVIEW','REJECTED'
    )),
    verification_method TEXT NOT NULL CHECK(verification_method IN (
        'OFFICIAL','OWNER_AUTHORED','DETERMINISTIC','HUMAN_REVIEWED',
        'AI_REVIEWED','MODEL_ONLY'
    )),
    content_hash TEXT NOT NULL CHECK(
        length(content_hash)=64 AND content_hash NOT GLOB '*[^0-9a-f]*'
    ),
    created_by_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK(
        (source_kind='OFFICIAL' AND owner_user_id IS NULL)
        OR (source_kind!='OFFICIAL' AND owner_user_id IS NOT NULL)
    )
);

INSERT INTO assessment_question_revisions_new(
    id,course_id,owner_user_id,family_id,revision,source_kind,
    source_document_version_id,source_problem_revision_id,question_type,difficulty,
    prompt_text,options_json,answer_json,validation_status,verification_method,
    content_hash,created_by_user_id,created_at
)
SELECT id,course_id,owner_user_id,family_id,revision,source_kind,
    source_document_version_id,source_problem_revision_id,question_type,difficulty,
    prompt_text,options_json,answer_json,validation_status,verification_method,
    content_hash,created_by_user_id,created_at
FROM assessment_question_revisions;

DROP TABLE assessment_question_revisions;
ALTER TABLE assessment_question_revisions_new RENAME TO assessment_question_revisions;

CREATE UNIQUE INDEX IF NOT EXISTS idx_assessment_question_family_revision
ON assessment_question_revisions(
    course_id, COALESCE(owner_user_id,'__OFFICIAL__'), family_id, revision
);

CREATE INDEX IF NOT EXISTS idx_assessment_question_pool
ON assessment_question_revisions(
    course_id, validation_status, source_kind, owner_user_id, difficulty
);

-- ============================================================ blueprint items
CREATE TABLE assessment_blueprint_items_new (
    id TEXT PRIMARY KEY,
    blueprint_id TEXT NOT NULL
        REFERENCES assessment_blueprint_versions(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 5),
    question_revision_id TEXT NOT NULL
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    family_id TEXT NOT NULL CHECK(length(family_id) BETWEEN 1 AND 100),
    marks INTEGER NOT NULL CHECK(marks BETWEEN 1 AND 100),
    source_kind TEXT NOT NULL CHECK(source_kind IN (
        'OFFICIAL','WORKSPACE_PRIVATE','MODEL_GENERATED','EXTERNAL_INSPIRED'
    )),
    verification_method TEXT NOT NULL CHECK(verification_method IN (
        'OFFICIAL','OWNER_AUTHORED','DETERMINISTIC','HUMAN_REVIEWED','AI_REVIEWED'
    )),
    UNIQUE(blueprint_id,ordinal),
    UNIQUE(blueprint_id,question_revision_id),
    UNIQUE(blueprint_id,family_id)
);

INSERT INTO assessment_blueprint_items_new(
    id,blueprint_id,ordinal,question_revision_id,family_id,marks,
    source_kind,verification_method
)
SELECT id,blueprint_id,ordinal,question_revision_id,family_id,marks,
    source_kind,verification_method
FROM assessment_blueprint_items;

DROP TABLE assessment_blueprint_items;
ALTER TABLE assessment_blueprint_items_new RENAME TO assessment_blueprint_items;

-- ============================================================ model-call roles
-- The preparation / reference-solution / explanation roles are new model-call
-- roles; both role-typed ledgers are leaves and are recreated with the widened
-- enum (data copied 1:1).
CREATE TABLE learning_model_run_evidence_new (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN (
        'planner','teacher','problem','grader','router',
        'reference','preparation','explanation'
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

CREATE INDEX IF NOT EXISTS idx_learning_model_run_operation
ON learning_model_run_evidence(workspace_id, operation_id, role);

CREATE TABLE learning_model_call_reservations_new (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN (
        'planner','teacher','problem','grader','router',
        'reference','preparation','explanation'
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
    UNIQUE(workspace_id, operation_id, role),
    CHECK(
        (status = 'RESERVED' AND finished_at IS NULL)
        OR (status != 'RESERVED' AND finished_at IS NOT NULL)
    )
);

INSERT INTO learning_model_call_reservations_new
SELECT * FROM learning_model_call_reservations;
DROP TABLE learning_model_call_reservations;
ALTER TABLE learning_model_call_reservations_new RENAME TO learning_model_call_reservations;

CREATE INDEX IF NOT EXISTS idx_model_call_reservations_owner_day
ON learning_model_call_reservations(owner_user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_model_call_reservations_owner_course_day
ON learning_model_call_reservations(owner_user_id, course_id, created_at);

-- ============================================================ recreate triggers
-- Recreated verbatim from 017_assessment_runtime.sql (without IF NOT EXISTS) so
-- replays are idempotent after the DROP TRIGGER IF EXISTS block above.
CREATE TRIGGER immutable_assessment_question_content
BEFORE UPDATE OF id,course_id,owner_user_id,family_id,revision,source_kind,
    question_type,difficulty,prompt_text,options_json,
    answer_json,validation_status,verification_method,content_hash,
    created_by_user_id,created_at
ON assessment_question_revisions
BEGIN
    SELECT RAISE(ABORT, 'Assessment question revisions are immutable');
END;

CREATE TRIGGER revoke_assessment_question_sources_only
BEFORE UPDATE OF source_document_version_id,source_problem_revision_id
ON assessment_question_revisions
WHEN NOT (
    (
        NEW.source_document_version_id IS OLD.source_document_version_id
        OR (OLD.source_document_version_id IS NOT NULL
            AND NEW.source_document_version_id IS NULL)
    )
    AND
    (
        NEW.source_problem_revision_id IS OLD.source_problem_revision_id
        OR (OLD.source_problem_revision_id IS NOT NULL
            AND NEW.source_problem_revision_id IS NULL)
    )
)
BEGIN
    SELECT RAISE(ABORT, 'Assessment question source may only be revoked');
END;

CREATE TRIGGER immutable_assessment_question_delete
BEFORE DELETE ON assessment_question_revisions
BEGIN
    SELECT RAISE(ABORT, 'Assessment question revisions are immutable');
END;

CREATE TRIGGER validate_assessment_rubric_context
BEFORE INSERT ON assessment_rubric_criteria
WHEN NOT EXISTS(
    SELECT 1 FROM assessment_question_revisions AS question
    JOIN knowledge_nodes AS node ON node.id=NEW.node_id
    WHERE question.id=NEW.question_revision_id
      AND node.course_id=question.course_id
)
BEGIN
    SELECT RAISE(ABORT, 'Assessment rubric does not match the question course');
END;

CREATE TRIGGER validate_assessment_blueprint_item
BEFORE INSERT ON assessment_blueprint_items
WHEN NOT EXISTS(
    SELECT 1 FROM assessment_blueprint_versions AS blueprint
    JOIN assessment_question_revisions AS question
      ON question.id=NEW.question_revision_id
    JOIN assessment_rubric_criteria AS criterion
      ON criterion.question_revision_id=question.id
     AND criterion.node_id=blueprint.node_id
     AND criterion.spec_version=blueprint.spec_version
    WHERE blueprint.id=NEW.blueprint_id
      AND blueprint.status='BUILDING'
      AND question.course_id=blueprint.course_id
      AND (question.owner_user_id IS NULL
           OR question.owner_user_id=blueprint.owner_user_id)
      AND question.validation_status='VALIDATED'
      AND question.verification_method!='MODEL_ONLY'
      AND question.family_id=NEW.family_id
      AND question.source_kind=NEW.source_kind
      AND question.verification_method=NEW.verification_method
)
OR (
    SELECT COUNT(*) FROM assessment_blueprint_items
    WHERE blueprint_id=NEW.blueprint_id
) >= 5
BEGIN
    SELECT RAISE(ABORT, 'Assessment blueprint item is invalid or unauthorized');
END;

CREATE TRIGGER immutable_frozen_assessment_blueprint_item_update
BEFORE UPDATE ON assessment_blueprint_items
WHEN (SELECT status FROM assessment_blueprint_versions WHERE id=OLD.blueprint_id)
     != 'BUILDING'
BEGIN
    SELECT RAISE(ABORT, 'Frozen Assessment blueprint items are immutable');
END;

CREATE TRIGGER immutable_assessment_blueprint_item_delete
BEFORE DELETE ON assessment_blueprint_items
BEGIN
    SELECT RAISE(ABORT, 'Assessment blueprint items are immutable');
END;

CREATE TRIGGER freeze_valid_assessment_blueprint
BEFORE UPDATE OF status ON assessment_blueprint_versions
WHEN NEW.status='FROZEN' AND OLD.status='BUILDING' AND (
    (SELECT COUNT(*) FROM assessment_blueprint_items WHERE blueprint_id=OLD.id) != 5
    OR (SELECT COALESCE(SUM(marks),0) FROM assessment_blueprint_items
        WHERE blueprint_id=OLD.id) != 100
    OR (SELECT MIN(marks) FROM assessment_blueprint_items
        WHERE blueprint_id=OLD.id) =
       (SELECT MAX(marks) FROM assessment_blueprint_items
        WHERE blueprint_id=OLD.id)
)
BEGIN
    SELECT RAISE(ABORT, 'Assessment blueprint needs five unequal marks totaling 100');
END;

CREATE TRIGGER validate_assessment_question_attempt
BEFORE INSERT ON assessment_question_attempts
WHEN NOT EXISTS(
    SELECT 1 FROM assessment_sessions AS session
    JOIN assessment_blueprint_items AS item ON item.blueprint_id=session.blueprint_id
    WHERE session.id=NEW.session_id AND item.id=NEW.blueprint_item_id
)
BEGIN
    SELECT RAISE(ABORT, 'Assessment attempt item is outside the frozen session');
END;

CREATE TRIGGER validate_performance_evidence_context
BEFORE INSERT ON performance_evidence
WHEN NOT EXISTS(
    SELECT 1 FROM assessment_sessions AS session
    JOIN assessment_question_attempts AS attempt ON attempt.session_id=session.id
    JOIN assessment_blueprint_items AS item ON item.id=attempt.blueprint_item_id
    WHERE session.id=NEW.assessment_session_id
      AND session.workspace_id=NEW.workspace_id
      AND attempt.id=NEW.question_attempt_id
      AND item.question_revision_id=NEW.question_revision_id
)
BEGIN
    SELECT RAISE(ABORT, 'Performance evidence is outside the Assessment session');
END;

PRAGMA legacy_alter_table=OFF;
PRAGMA foreign_keys=ON;

-- ============================================================ preparation job
CREATE TABLE IF NOT EXISTS assessment_preparation_jobs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    spec_version INTEGER NOT NULL CHECK(spec_version >= 1),
    status TEXT NOT NULL DEFAULT 'PREPARING'
        CHECK(status IN ('PREPARING','READY','BLOCKED','CANCELLED','FAILED')),
    channel TEXT NOT NULL DEFAULT 'VALIDATED'
        CHECK(channel IN ('VALIDATED','AI_REVIEWED')),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    completed_at TEXT,
    UNIQUE(workspace_id, node_id, spec_version)
);

-- ============================================================ reference solutions
CREATE TABLE IF NOT EXISTS assessment_reference_solutions (
    id TEXT PRIMARY KEY,
    question_revision_id TEXT NOT NULL
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    blueprint_item_id TEXT
        REFERENCES assessment_blueprint_items(id) ON DELETE SET NULL,
    solution_revision INTEGER NOT NULL CHECK(solution_revision >= 1),
    steps_json TEXT NOT NULL CHECK(json_valid(steps_json)),
    answer_json TEXT NOT NULL CHECK(json_valid(answer_json)),
    source_refs_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_refs_json)),
    prompt_version TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK(
        length(content_hash)=64 AND content_hash NOT GLOB '*[^0-9a-f]*'
    ),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(question_revision_id, solution_revision)
);

-- ============================================================ drafts
CREATE TABLE IF NOT EXISTS assessment_answer_drafts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES assessment_sessions(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    unified_answer_json TEXT NOT NULL CHECK(json_valid(unified_answer_json)),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(session_id)
);

-- ============================================================ submission revisions
CREATE TABLE IF NOT EXISTS assessment_submission_revisions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES assessment_sessions(id) ON DELETE RESTRICT,
    submission_revision INTEGER NOT NULL CHECK(submission_revision >= 1),
    content_hash TEXT NOT NULL CHECK(
        length(content_hash)=64 AND content_hash NOT GLOB '*[^0-9a-f]*'
    ),
    unified_answer_json TEXT CHECK(unified_answer_json IS NULL OR json_valid(unified_answer_json)),
    mapped_answers_json TEXT NOT NULL CHECK(json_valid(mapped_answers_json)),
    transcription_json TEXT CHECK(transcription_json IS NULL OR json_valid(transcription_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(session_id, submission_revision)
);

-- ============================================================ grading receipts
CREATE TABLE IF NOT EXISTS assessment_grading_receipts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES assessment_sessions(id) ON DELETE RESTRICT,
    submission_revision INTEGER NOT NULL CHECK(submission_revision >= 1),
    grader_input_hash TEXT NOT NULL CHECK(
        length(grader_input_hash)=64 AND grader_input_hash NOT GLOB '*[^0-9a-f]*'
    ),
    grade_proposal_json TEXT CHECK(grade_proposal_json IS NULL OR json_valid(grade_proposal_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(session_id, submission_revision)
);

-- ============================================================ explanation contexts
CREATE TABLE IF NOT EXISTS assessment_explanation_contexts (
    id TEXT PRIMARY KEY,
    assessment_session_id TEXT NOT NULL
        REFERENCES assessment_sessions(id) ON DELETE RESTRICT,
    blueprint_item_id TEXT NOT NULL
        REFERENCES assessment_blueprint_items(id) ON DELETE RESTRICT,
    solution_revision INTEGER NOT NULL CHECK(solution_revision >= 1),
    step_id TEXT NOT NULL CHECK(length(step_id) BETWEEN 1 AND 100),
    owner_user_id TEXT NOT NULL,
    content_json TEXT CHECK(content_json IS NULL OR json_valid(content_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(assessment_session_id, blueprint_item_id, solution_revision, step_id)
);

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(27,'assessment preparation reference solutions drafts and explanations');
