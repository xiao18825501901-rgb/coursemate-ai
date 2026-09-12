-- Stage 5 assessment runtime. Answers and rubrics are server-side records and are
-- never part of the pre-submit client projection.

CREATE TABLE IF NOT EXISTS assessment_question_revisions (
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
        'OFFICIAL','OWNER_AUTHORED','DETERMINISTIC','HUMAN_REVIEWED','MODEL_ONLY'
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

CREATE UNIQUE INDEX IF NOT EXISTS idx_assessment_question_family_revision
ON assessment_question_revisions(
    course_id, COALESCE(owner_user_id,'__OFFICIAL__'), family_id, revision
);

CREATE INDEX IF NOT EXISTS idx_assessment_question_pool
ON assessment_question_revisions(
    course_id, validation_status, source_kind, owner_user_id, difficulty
);

CREATE TRIGGER IF NOT EXISTS immutable_assessment_question_content
BEFORE UPDATE OF id,course_id,owner_user_id,family_id,revision,source_kind,
    question_type,difficulty,prompt_text,options_json,
    answer_json,validation_status,verification_method,content_hash,
    created_by_user_id,created_at
ON assessment_question_revisions
BEGIN
    SELECT RAISE(ABORT, 'Assessment question revisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS revoke_assessment_question_sources_only
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

CREATE TRIGGER IF NOT EXISTS immutable_assessment_question_delete
BEFORE DELETE ON assessment_question_revisions
BEGIN
    SELECT RAISE(ABORT, 'Assessment question revisions are immutable');
END;

CREATE TABLE IF NOT EXISTS assessment_rubric_criteria (
    question_revision_id TEXT NOT NULL
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    criterion_id TEXT NOT NULL CHECK(length(criterion_id) BETWEEN 1 AND 100),
    node_id TEXT NOT NULL,
    spec_version INTEGER NOT NULL CHECK(spec_version >= 1),
    item_id TEXT NOT NULL CHECK(length(item_id) BETWEEN 1 AND 100),
    dimension TEXT NOT NULL CHECK(dimension IN (
        'CONCEPT','TERMINOLOGY','METHOD_REASONING','CALCULATION','DERIVATION',
        'CODE_APPLICATION','CLARITY'
    )),
    max_fraction INTEGER NOT NULL CHECK(max_fraction BETWEEN 1 AND 100),
    description TEXT NOT NULL CHECK(length(trim(description)) BETWEEN 1 AND 2000),
    deterministic_rule_json TEXT NOT NULL DEFAULT '{}'
        CHECK(json_valid(deterministic_rule_json)),
    PRIMARY KEY(question_revision_id, criterion_id),
    FOREIGN KEY(node_id, spec_version, item_id)
        REFERENCES teaching_items(node_id, spec_version, item_id) ON DELETE RESTRICT
);

CREATE TRIGGER IF NOT EXISTS validate_assessment_rubric_context
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

CREATE TRIGGER IF NOT EXISTS immutable_assessment_rubric_update
BEFORE UPDATE ON assessment_rubric_criteria
BEGIN
    SELECT RAISE(ABORT, 'Assessment rubric criteria are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_assessment_rubric_delete
BEFORE DELETE ON assessment_rubric_criteria
BEGIN
    SELECT RAISE(ABORT, 'Assessment rubric criteria are immutable');
END;

CREATE TABLE IF NOT EXISTS assessment_blueprint_versions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    node_id TEXT NOT NULL,
    spec_version INTEGER NOT NULL CHECK(spec_version >= 1),
    version INTEGER NOT NULL CHECK(version >= 1),
    status TEXT NOT NULL DEFAULT 'BUILDING'
        CHECK(status IN ('BUILDING','FROZEN','RETIRED')),
    selection_policy_json TEXT NOT NULL CHECK(json_valid(selection_policy_json)),
    content_hash TEXT NOT NULL CHECK(
        length(content_hash)=64 AND content_hash NOT GLOB '*[^0-9a-f]*'
    ),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(workspace_id,node_id,version),
    FOREIGN KEY(node_id,spec_version)
        REFERENCES teaching_specs(node_id,version) ON DELETE RESTRICT
);

CREATE TRIGGER IF NOT EXISTS validate_assessment_blueprint_context
BEFORE INSERT ON assessment_blueprint_versions
WHEN NOT EXISTS(
    SELECT 1 FROM learning_workspaces AS workspace
    JOIN knowledge_nodes AS node ON node.id=NEW.node_id
    JOIN teaching_spec_metadata AS spec
      ON spec.node_id=node.id AND spec.version=NEW.spec_version
    WHERE workspace.id=NEW.workspace_id
      AND workspace.owner_user_id=NEW.owner_user_id
      AND workspace.course_id=NEW.course_id
      AND node.course_id=workspace.course_id
      AND (
        (node.owner_user_id=workspace.owner_user_id
         AND node.status='PRIVATE' AND spec.status='PRIVATE_ACTIVE')
        OR
        (node.owner_user_id IS NULL
         AND node.status='PUBLISHED' AND spec.status='PUBLISHED')
      )
)
BEGIN
    SELECT RAISE(ABORT, 'Assessment blueprint is not authorized for this workspace');
END;

CREATE TRIGGER IF NOT EXISTS immutable_assessment_blueprint_content
BEFORE UPDATE OF id,workspace_id,owner_user_id,course_id,node_id,spec_version,
    version,selection_policy_json,content_hash,created_at
ON assessment_blueprint_versions
BEGIN
    SELECT RAISE(ABORT, 'Assessment blueprint content is immutable');
END;

CREATE TRIGGER IF NOT EXISTS validate_assessment_blueprint_status
BEFORE UPDATE OF status ON assessment_blueprint_versions
WHEN NOT (
    (OLD.status='BUILDING' AND NEW.status='FROZEN')
    OR (OLD.status='FROZEN' AND NEW.status='RETIRED')
    OR OLD.status=NEW.status
)
BEGIN
    SELECT RAISE(ABORT, 'Invalid Assessment blueprint transition');
END;

CREATE TABLE IF NOT EXISTS assessment_blueprint_items (
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
        'OFFICIAL','OWNER_AUTHORED','DETERMINISTIC','HUMAN_REVIEWED'
    )),
    UNIQUE(blueprint_id,ordinal),
    UNIQUE(blueprint_id,question_revision_id),
    UNIQUE(blueprint_id,family_id)
);

CREATE TRIGGER IF NOT EXISTS validate_assessment_blueprint_item
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

CREATE TRIGGER IF NOT EXISTS freeze_valid_assessment_blueprint
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

CREATE TRIGGER IF NOT EXISTS immutable_frozen_assessment_blueprint_item_update
BEFORE UPDATE ON assessment_blueprint_items
WHEN (SELECT status FROM assessment_blueprint_versions WHERE id=OLD.blueprint_id)
     != 'BUILDING'
BEGIN
    SELECT RAISE(ABORT, 'Frozen Assessment blueprint items are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_assessment_blueprint_item_delete
BEFORE DELETE ON assessment_blueprint_items
BEGIN
    SELECT RAISE(ABORT, 'Assessment blueprint items are immutable');
END;

CREATE TABLE IF NOT EXISTS assessment_sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    blueprint_id TEXT NOT NULL
        REFERENCES assessment_blueprint_versions(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'IN_PROGRESS' CHECK(status IN (
        'IN_PROGRESS','SUBMITTED','GRADED','ABANDONED','INVALIDATED'
    )),
    mode TEXT NOT NULL DEFAULT 'INDEPENDENT'
        CHECK(mode IN ('INDEPENDENT','PRACTICE')),
    assistance_status TEXT NOT NULL DEFAULT 'UNASSISTED'
        CHECK(assistance_status IN ('UNASSISTED','ASSISTED','ANSWER_EXPOSED')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    started_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    submitted_at TEXT,
    graded_at TEXT,
    CHECK(
        (status IN ('IN_PROGRESS','ABANDONED','INVALIDATED') AND graded_at IS NULL)
        OR status IN ('SUBMITTED','GRADED')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_assessment_per_node
ON assessment_sessions(workspace_id,node_id) WHERE status='IN_PROGRESS';

CREATE INDEX IF NOT EXISTS idx_assessment_session_history
ON assessment_sessions(workspace_id,node_id,started_at);

CREATE TRIGGER IF NOT EXISTS validate_assessment_session_context
BEFORE INSERT ON assessment_sessions
WHEN NOT EXISTS(
    SELECT 1 FROM assessment_blueprint_versions AS blueprint
    JOIN learning_workspaces AS workspace ON workspace.id=blueprint.workspace_id
    WHERE blueprint.id=NEW.blueprint_id
      AND blueprint.status='FROZEN'
      AND blueprint.workspace_id=NEW.workspace_id
      AND blueprint.owner_user_id=NEW.owner_user_id
      AND blueprint.course_id=NEW.course_id
      AND blueprint.node_id=NEW.node_id
      AND workspace.owner_user_id=NEW.owner_user_id
)
BEGIN
    SELECT RAISE(ABORT, 'Assessment session does not match its frozen blueprint');
END;

CREATE TABLE IF NOT EXISTS assessment_question_attempts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES assessment_sessions(id) ON DELETE RESTRICT,
    blueprint_item_id TEXT NOT NULL
        REFERENCES assessment_blueprint_items(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'UNANSWERED' CHECK(status IN (
        'UNANSWERED','ANSWERED','SUBMITTED','GRADED','NEEDS_REVIEW'
    )),
    answer_json TEXT CHECK(answer_json IS NULL OR json_valid(answer_json)),
    assistance TEXT NOT NULL DEFAULT 'NONE'
        CHECK(assistance IN ('NONE','HINT','TEACHING','ANSWER_REVEALED')),
    awarded_marks REAL CHECK(awarded_marks IS NULL OR awarded_marks >= 0),
    feedback TEXT,
    grading_version INTEGER CHECK(grading_version IS NULL OR grading_version >= 1),
    answered_at TEXT,
    graded_at TEXT,
    UNIQUE(session_id,blueprint_item_id)
);

CREATE TRIGGER IF NOT EXISTS validate_assessment_question_attempt
BEFORE INSERT ON assessment_question_attempts
WHEN NOT EXISTS(
    SELECT 1 FROM assessment_sessions AS session
    JOIN assessment_blueprint_items AS item ON item.blueprint_id=session.blueprint_id
    WHERE session.id=NEW.session_id AND item.id=NEW.blueprint_item_id
)
BEGIN
    SELECT RAISE(ABORT, 'Assessment attempt item is outside the frozen session');
END;

CREATE TABLE IF NOT EXISTS assessment_exposure_events (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    session_id TEXT NOT NULL REFERENCES assessment_sessions(id) ON DELETE RESTRICT,
    question_revision_id TEXT NOT NULL
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    family_id TEXT NOT NULL,
    exposure_kind TEXT NOT NULL CHECK(exposure_kind IN (
        'ANSWER_REVEALED','TEACHING_HELP','PROBLEM_SOLUTION_SEEN'
    )),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(workspace_id,session_id,question_revision_id,exposure_kind)
);

CREATE TABLE IF NOT EXISTS performance_evidence (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    assessment_session_id TEXT NOT NULL
        REFERENCES assessment_sessions(id) ON DELETE RESTRICT,
    question_attempt_id TEXT NOT NULL
        REFERENCES assessment_question_attempts(id) ON DELETE RESTRICT,
    question_revision_id TEXT NOT NULL
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    criterion_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    spec_version INTEGER NOT NULL CHECK(spec_version >= 1),
    item_id TEXT NOT NULL,
    dimension TEXT NOT NULL CHECK(dimension IN (
        'CONCEPT','TERMINOLOGY','METHOD_REASONING','CALCULATION','DERIVATION',
        'CODE_APPLICATION','CLARITY'
    )),
    awarded_marks REAL NOT NULL CHECK(awarded_marks >= 0),
    max_marks REAL NOT NULL CHECK(max_marks > 0 AND awarded_marks <= max_marks),
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    independent_eligible INTEGER NOT NULL CHECK(independent_eligible IN (0,1)),
    performance_band TEXT NOT NULL CHECK(performance_band IN (
        'STRONG','DEVELOPING','WEAK','NEEDS_REVIEW'
    )),
    evidence_locator TEXT NOT NULL CHECK(length(trim(evidence_locator)) > 0),
    source_kind TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK(
        length(content_hash)=64 AND content_hash NOT GLOB '*[^0-9a-f]*'
    ),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(question_attempt_id,criterion_id),
    FOREIGN KEY(question_revision_id,criterion_id)
        REFERENCES assessment_rubric_criteria(question_revision_id,criterion_id)
        ON DELETE RESTRICT,
    FOREIGN KEY(node_id,spec_version,item_id)
        REFERENCES teaching_items(node_id,spec_version,item_id) ON DELETE RESTRICT
);

CREATE TRIGGER IF NOT EXISTS validate_performance_evidence_context
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

CREATE TRIGGER IF NOT EXISTS immutable_performance_evidence_update
BEFORE UPDATE ON performance_evidence
BEGIN
    SELECT RAISE(ABORT, 'Performance evidence is immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_performance_evidence_delete
BEFORE DELETE ON performance_evidence
BEGIN
    SELECT RAISE(ABORT, 'Performance evidence is immutable');
END;

CREATE TABLE IF NOT EXISTS learning_replan_triggers (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    trigger_kind TEXT NOT NULL CHECK(trigger_kind IN (
        'ASSESSMENT_WEAKNESS','NEW_MATERIAL','SPEC_CHANGED','GOAL_CHANGED',
        'MODULE_COMPLETED','USER_REQUEST'
    )),
    source_assessment_session_id TEXT
        REFERENCES assessment_sessions(id) ON DELETE RESTRICT,
    performance_evidence_ids_json TEXT NOT NULL CHECK(
        json_valid(performance_evidence_ids_json)
        AND json_type(performance_evidence_ids_json)='array'
        AND json_array_length(performance_evidence_ids_json) >= 1
    ),
    reason_summary TEXT NOT NULL CHECK(length(trim(reason_summary)) BETWEEN 1 AND 1000),
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK(status IN ('PENDING','APPLIED','DISMISSED')),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    applied_at TEXT,
    UNIQUE(workspace_id,node_id,source_assessment_session_id,trigger_kind)
);

CREATE TRIGGER IF NOT EXISTS immutable_replan_trigger_identity
BEFORE UPDATE OF id,workspace_id,node_id,trigger_kind,source_assessment_session_id,
    performance_evidence_ids_json,reason_summary,created_at
ON learning_replan_triggers
BEGIN
    SELECT RAISE(ABORT, 'Learning replan trigger identity is immutable');
END;

CREATE TABLE IF NOT EXISTS teaching_unit_remediations (
    trigger_id TEXT NOT NULL REFERENCES learning_replan_triggers(id) ON DELETE RESTRICT,
    teaching_unit_id TEXT NOT NULL REFERENCES teaching_units(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(trigger_id,teaching_unit_id)
);

CREATE TABLE IF NOT EXISTS teaching_plan_performance_triggers (
    plan_version_id TEXT NOT NULL
        REFERENCES teaching_plan_versions(id) ON DELETE RESTRICT,
    trigger_id TEXT NOT NULL REFERENCES learning_replan_triggers(id) ON DELETE RESTRICT,
    PRIMARY KEY(plan_version_id,trigger_id)
);

CREATE TRIGGER IF NOT EXISTS immutable_teaching_plan_performance_trigger_update
BEFORE UPDATE ON teaching_plan_performance_triggers
BEGIN
    SELECT RAISE(ABORT, 'Teaching plan performance trigger links are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_teaching_plan_performance_trigger_delete
BEFORE DELETE ON teaching_plan_performance_triggers
BEGIN
    SELECT RAISE(ABORT, 'Teaching plan performance trigger links are immutable');
END;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(17,'frozen assessments attempts performance evidence and replan triggers');
