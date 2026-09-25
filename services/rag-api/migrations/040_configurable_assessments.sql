-- Versioned, content-free Assessment configurations and N-question blueprints.
-- Existing five-question sessions remain byte-for-byte addressable; their marks
-- are backfilled into integer hundredths so new N-way allocations can total
-- exactly 100.00 without floating-point policy decisions.

PRAGMA foreign_keys=OFF;
PRAGMA legacy_alter_table=ON;

DROP TRIGGER IF EXISTS validate_assessment_blueprint_item;
DROP TRIGGER IF EXISTS freeze_valid_assessment_blueprint;
DROP TRIGGER IF EXISTS immutable_frozen_assessment_blueprint_item_update;
DROP TRIGGER IF EXISTS immutable_assessment_blueprint_item_delete;

CREATE TABLE assessment_blueprint_items_v40 (
    id TEXT PRIMARY KEY,
    blueprint_id TEXT NOT NULL
        REFERENCES assessment_blueprint_versions(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 30),
    question_revision_id TEXT NOT NULL
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    family_id TEXT NOT NULL CHECK(length(family_id) BETWEEN 1 AND 100),
    -- Keep the legacy declared type so the previously deployed application can still
    -- read this rebuilt table during a code rollback. Exact scoring is governed by the
    -- additive marks_basis_points column; SQLite can still represent a fractional display
    -- value in this compatibility column when N does not divide 100.
    marks INTEGER NOT NULL CHECK(marks BETWEEN 0.01 AND 100),
    marks_basis_points INTEGER NOT NULL CHECK(marks_basis_points BETWEEN 1 AND 10000),
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

INSERT INTO assessment_blueprint_items_v40(
    id,blueprint_id,ordinal,question_revision_id,family_id,marks,marks_basis_points,
    source_kind,verification_method
)
SELECT id,blueprint_id,ordinal,question_revision_id,family_id,marks,
       CAST(round(marks*100) AS INTEGER),source_kind,verification_method
FROM assessment_blueprint_items;

DROP TABLE assessment_blueprint_items;
ALTER TABLE assessment_blueprint_items_v40 RENAME TO assessment_blueprint_items;

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
) >= 30
BEGIN
    SELECT RAISE(ABORT, 'Assessment blueprint item is invalid or unauthorized');
END;

CREATE TRIGGER freeze_valid_assessment_blueprint
BEFORE UPDATE OF status ON assessment_blueprint_versions
WHEN NEW.status='FROZEN' AND OLD.status='BUILDING' AND (
    (SELECT COUNT(*) FROM assessment_blueprint_items WHERE blueprint_id=OLD.id) < 5
    OR (SELECT COUNT(*) FROM assessment_blueprint_items WHERE blueprint_id=OLD.id) > 30
    OR (SELECT COUNT(*) FROM assessment_blueprint_items WHERE blueprint_id=OLD.id)
       != CAST(json_extract(OLD.selection_policy_json,'$.question_count') AS INTEGER)
    OR (SELECT COALESCE(SUM(marks_basis_points),0) FROM assessment_blueprint_items
        WHERE blueprint_id=OLD.id) != 10000
)
BEGIN
    SELECT RAISE(ABORT, 'Assessment blueprint needs its configured slots totaling 100.00');
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

CREATE TABLE IF NOT EXISTS assessment_configurations (
    id TEXT PRIMARY KEY,
    series_id TEXT NOT NULL CHECK(length(trim(series_id)) BETWEEN 1 AND 100),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    spec_version INTEGER NOT NULL CHECK(spec_version >= 1),
    language TEXT NOT NULL DEFAULT 'auto',
    source_scope_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_scope_json)),
    quality_policy TEXT NOT NULL DEFAULT 'highest-no-application-usd-cap',
    status TEXT NOT NULL CHECK(status IN ('DRAFT','FROZEN','CANCELLED')),
    content_hash TEXT NOT NULL CHECK(
        length(content_hash)=64 AND content_hash NOT GLOB '*[^0-9a-f]*'
    ),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(series_id,revision),
    UNIQUE(workspace_id,content_hash)
);

CREATE TABLE IF NOT EXISTS assessment_configuration_slots (
    configuration_id TEXT NOT NULL
        REFERENCES assessment_configurations(id) ON DELETE RESTRICT,
    slot_id TEXT NOT NULL CHECK(length(trim(slot_id)) BETWEEN 1 AND 100),
    ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 30),
    question_type TEXT NOT NULL CHECK(question_type IN (
        'MCQ_SINGLE','NUMERIC','SHORT_TEXT','EXPLANATION','CODE'
    )),
    task_form TEXT NOT NULL CHECK(task_form IN (
        'concept','definition','calculation','analysis','evaluation','code'
    )),
    objective_text TEXT NOT NULL CHECK(length(trim(objective_text)) BETWEEN 1 AND 500),
    marks_basis_points INTEGER NOT NULL CHECK(marks_basis_points BETWEEN 1 AND 10000),
    PRIMARY KEY(configuration_id,slot_id),
    UNIQUE(configuration_id,ordinal)
);

CREATE TRIGGER IF NOT EXISTS freeze_valid_assessment_configuration
BEFORE UPDATE OF status ON assessment_configurations
WHEN NEW.status='FROZEN' AND OLD.status='DRAFT' AND (
    (SELECT COUNT(*) FROM assessment_configuration_slots
     WHERE configuration_id=OLD.id) < 5
    OR (SELECT COUNT(*) FROM assessment_configuration_slots
        WHERE configuration_id=OLD.id) > 30
    OR (SELECT COALESCE(SUM(marks_basis_points),0)
        FROM assessment_configuration_slots WHERE configuration_id=OLD.id) != 10000
)
BEGIN
    SELECT RAISE(ABORT, 'Assessment configuration needs 5-30 slots totaling 100.00');
END;

CREATE TRIGGER IF NOT EXISTS immutable_frozen_assessment_configuration
BEFORE UPDATE ON assessment_configurations
WHEN OLD.status='FROZEN' AND NEW.status=OLD.status
BEGIN
    SELECT RAISE(ABORT, 'Frozen Assessment configurations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_frozen_assessment_configuration_slot_update
BEFORE UPDATE ON assessment_configuration_slots
WHEN (SELECT status FROM assessment_configurations WHERE id=OLD.configuration_id)='FROZEN'
BEGIN
    SELECT RAISE(ABORT, 'Frozen Assessment configuration slots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_assessment_configuration_slot_delete
BEFORE DELETE ON assessment_configuration_slots
BEGIN
    SELECT RAISE(ABORT, 'Assessment configuration slots are immutable');
END;

CREATE TABLE IF NOT EXISTS assessment_configuration_preparations (
    id TEXT PRIMARY KEY,
    configuration_id TEXT NOT NULL UNIQUE
        REFERENCES assessment_configurations(id) ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK(status IN ('PREPARING','READY','BLOCKED','CANCELLED')),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS assessment_configuration_questions (
    configuration_id TEXT NOT NULL
        REFERENCES assessment_configurations(id) ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    slot_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 30),
    question_revision_id TEXT NOT NULL
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    family_id TEXT NOT NULL CHECK(length(trim(family_id)) BETWEEN 1 AND 100),
    blueprint_id TEXT NOT NULL CHECK(length(trim(blueprint_id)) BETWEEN 1 AND 100),
    objective_id TEXT NOT NULL CHECK(length(trim(objective_id)) BETWEEN 1 AND 100),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(configuration_id,slot_id),
    UNIQUE(configuration_id,ordinal),
    UNIQUE(configuration_id,question_revision_id),
    UNIQUE(configuration_id,family_id),
    FOREIGN KEY(configuration_id,slot_id)
        REFERENCES assessment_configuration_slots(configuration_id,slot_id)
        ON DELETE RESTRICT
);

CREATE TRIGGER IF NOT EXISTS immutable_assessment_configuration_question
BEFORE UPDATE ON assessment_configuration_questions
BEGIN
    SELECT RAISE(ABORT, 'Assessment configuration question bindings are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_assessment_configuration_question_delete
BEFORE DELETE ON assessment_configuration_questions
BEGIN
    SELECT RAISE(ABORT, 'Assessment configuration question bindings are immutable');
END;

PRAGMA legacy_alter_table=OFF;
PRAGMA foreign_keys=ON;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(40,'versioned configurable N-question assessments');
