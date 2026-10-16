-- Forward-only new-policy metadata and wider item ordinals. Historical raw
-- questions/answers/marks/scores and frozen JSON are copied unchanged.
-- The legacy reader/policy retains 5-30; only a complete private point plan
-- permits 1..2K independently scored items. No RUNNING or quota rewrite.
PRAGMA foreign_keys=OFF;
PRAGMA legacy_alter_table=ON;
BEGIN IMMEDIATE;

ALTER TABLE assessment_configurations ADD COLUMN policy_version TEXT NOT NULL
    DEFAULT 'legacy.configurable.v1'
    CHECK(policy_version IN ('legacy.configurable.v1','cj.assessment.points.v1'));

CREATE TABLE assessment_point_configuration_plans (
    configuration_id TEXT PRIMARY KEY
        REFERENCES assessment_configurations(id) ON DELETE RESTRICT,
    plan_json TEXT NOT NULL CHECK(COALESCE(json_valid(plan_json)
        AND json_type(plan_json,'$.items')='array'
        AND json_array_length(plan_json,'$.items') BETWEEN 1 AND 10000
        AND json_extract(plan_json,'$.policy_version')='cj.assessment.points.v1',0)),
    content_hash TEXT NOT NULL CHECK(length(content_hash)=64
        AND content_hash NOT GLOB '*[^0-9a-f]*'),
    catalog_hash TEXT NOT NULL CHECK(length(catalog_hash)=64
        AND catalog_hash NOT GLOB '*[^0-9a-f]*'),
    source_snapshot TEXT NOT NULL CHECK(length(source_snapshot)=64
        AND source_snapshot NOT GLOB '*[^0-9a-f]*'),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TRIGGER validate_point_configuration_plan
BEFORE INSERT ON assessment_point_configuration_plans
WHEN NOT EXISTS (
    SELECT 1 FROM assessment_configurations AS config
    WHERE config.id=NEW.configuration_id AND config.status='DRAFT'
      AND config.policy_version='cj.assessment.points.v1'
      AND config.content_hash=NEW.content_hash
      AND json_extract(NEW.plan_json,'$.content_hash')=NEW.content_hash
      AND json_extract(NEW.plan_json,'$.catalog_hash')=NEW.catalog_hash
      AND json_extract(NEW.plan_json,'$.source_snapshot')=NEW.source_snapshot
      AND json_extract(NEW.plan_json,'$.scope.source_snapshot')=NEW.source_snapshot
      AND json_extract(NEW.plan_json,'$.scope.owner_id')=config.owner_user_id
      AND json_extract(NEW.plan_json,'$.scope.course_id')=config.course_id
      AND json_extract(NEW.plan_json,'$.scope.node_id')=config.node_id
      AND json_extract(NEW.plan_json,'$.scope.spec_version')=CAST(config.spec_version AS TEXT)
      AND json_extract(NEW.plan_json,'$.content_language')=config.language
)
BEGIN SELECT RAISE(ABORT,'Point configuration original scope or hash mismatch'); END;

CREATE TRIGGER immutable_point_configuration_plan_update
BEFORE UPDATE ON assessment_point_configuration_plans
BEGIN SELECT RAISE(ABORT,'Private point plans are immutable'); END;
CREATE TRIGGER immutable_point_configuration_plan_delete
BEFORE DELETE ON assessment_point_configuration_plans
BEGIN SELECT RAISE(ABORT,'Private point plans are immutable'); END;
CREATE TRIGGER immutable_assessment_configuration_policy
BEFORE UPDATE OF policy_version ON assessment_configurations
WHEN NEW.policy_version!=OLD.policy_version
BEGIN SELECT RAISE(ABORT,'Assessment policy versions are immutable'); END;

CREATE TRIGGER validate_point_configuration_initial_status
BEFORE INSERT ON assessment_configurations
WHEN NEW.policy_version='cj.assessment.points.v1' AND NEW.status!='DRAFT'
BEGIN SELECT RAISE(ABORT,'Point configurations must freeze their original private plan'); END;

CREATE TRIGGER immutable_bound_point_configuration_identity
BEFORE UPDATE ON assessment_configurations
WHEN EXISTS (SELECT 1 FROM assessment_point_configuration_plans
             WHERE configuration_id=OLD.id) AND (
    NEW.workspace_id IS NOT OLD.workspace_id OR NEW.owner_user_id IS NOT OLD.owner_user_id
    OR NEW.course_id IS NOT OLD.course_id OR NEW.node_id IS NOT OLD.node_id
    OR NEW.spec_version IS NOT OLD.spec_version OR NEW.language IS NOT OLD.language
    OR NEW.content_hash IS NOT OLD.content_hash OR NEW.series_id IS NOT OLD.series_id
    OR NEW.revision IS NOT OLD.revision OR NEW.policy_version IS NOT OLD.policy_version
)
BEGIN SELECT RAISE(ABORT,'Original point configuration identity is immutable'); END;

DROP TRIGGER IF EXISTS freeze_valid_assessment_configuration;
DROP TRIGGER IF EXISTS immutable_frozen_assessment_configuration_slot_update;
DROP TRIGGER IF EXISTS immutable_assessment_configuration_slot_delete;
DROP TRIGGER IF EXISTS immutable_assessment_configuration_question;
DROP TRIGGER IF EXISTS immutable_assessment_configuration_question_delete;

CREATE TABLE assessment_configuration_slots_v78 (
    configuration_id TEXT NOT NULL REFERENCES assessment_configurations(id) ON DELETE RESTRICT,
    slot_id TEXT NOT NULL CHECK(length(trim(slot_id)) BETWEEN 1 AND 100),
    ordinal INTEGER NOT NULL CHECK(ordinal>=1),
    question_type TEXT NOT NULL CHECK(question_type IN (
        'MCQ_SINGLE','NUMERIC','SHORT_TEXT','EXPLANATION','CODE')),
    task_form TEXT NOT NULL CHECK(task_form IN (
        'concept','definition','calculation','analysis','evaluation','code')),
    objective_text TEXT NOT NULL CHECK(length(trim(objective_text)) BETWEEN 1 AND 500),
    marks_basis_points INTEGER NOT NULL CHECK(marks_basis_points BETWEEN 1 AND 10000),
    primary_point_id TEXT,
    point_slot_json TEXT CHECK(point_slot_json IS NULL OR json_valid(point_slot_json)),
    PRIMARY KEY(configuration_id,slot_id), UNIQUE(configuration_id,ordinal)
);
INSERT INTO assessment_configuration_slots_v78(
    configuration_id,slot_id,ordinal,question_type,task_form,objective_text,marks_basis_points)
SELECT configuration_id,slot_id,ordinal,question_type,task_form,objective_text,marks_basis_points
FROM assessment_configuration_slots;
DROP TABLE assessment_configuration_slots;
ALTER TABLE assessment_configuration_slots_v78 RENAME TO assessment_configuration_slots;

CREATE TRIGGER validate_assessment_configuration_slot_policy
BEFORE INSERT ON assessment_configuration_slots
WHEN NOT EXISTS (
    SELECT 1 FROM assessment_configurations AS config
    WHERE config.id=NEW.configuration_id AND config.status='DRAFT' AND (
        (config.policy_version='legacy.configurable.v1' AND NEW.ordinal<=30
         AND NEW.primary_point_id IS NULL AND NEW.point_slot_json IS NULL)
        OR (config.policy_version='cj.assessment.points.v1' AND EXISTS (
            SELECT 1 FROM assessment_point_configuration_plans AS plan,
                json_each(plan.plan_json,'$.items') AS item
            WHERE plan.configuration_id=config.id
              AND json_extract(item.value,'$.slot_key')=NEW.slot_id
              AND json_extract(item.value,'$.ordinal')=NEW.ordinal
              AND json_extract(item.value,'$.primary_point_id')=NEW.primary_point_id
              AND json_extract(item.value,'$.question_type')=NEW.question_type
              AND json_extract(item.value,'$.task_form')=NEW.task_form
              AND json_extract(item.value,'$.marks_basis_points')=NEW.marks_basis_points
              AND json_extract(item.value,'$.independently_scored_parts')=1
              AND json(NEW.point_slot_json)=json(item.value)
              AND (SELECT COUNT(*) FROM assessment_configuration_slots AS slot
                   WHERE slot.configuration_id=config.id
                     AND slot.primary_point_id=NEW.primary_point_id)<2
        ))
    )
)
BEGIN SELECT RAISE(ABORT,'Assessment slot does not match its original policy plan'); END;

CREATE TRIGGER freeze_valid_assessment_configuration
BEFORE UPDATE OF status ON assessment_configurations
WHEN NEW.status='FROZEN' AND OLD.status='DRAFT' AND (
    (SELECT COALESCE(SUM(marks_basis_points),0) FROM assessment_configuration_slots
        WHERE configuration_id=OLD.id)!=10000
    OR (OLD.policy_version='legacy.configurable.v1' AND (
        (SELECT COUNT(*) FROM assessment_configuration_slots WHERE configuration_id=OLD.id)<5
        OR (SELECT COUNT(*) FROM assessment_configuration_slots WHERE configuration_id=OLD.id)>30))
    OR (OLD.policy_version='cj.assessment.points.v1' AND NOT EXISTS (
        SELECT 1 FROM assessment_point_configuration_plans AS plan
        WHERE plan.configuration_id=OLD.id
          AND plan.content_hash=NEW.content_hash
          AND json_extract(plan.plan_json,'$.content_language')=NEW.language
          AND json_extract(plan.plan_json,'$.scope.owner_id')=NEW.owner_user_id
          AND json_extract(plan.plan_json,'$.scope.course_id')=NEW.course_id
          AND json_extract(plan.plan_json,'$.scope.node_id')=NEW.node_id
          AND json_extract(plan.plan_json,'$.scope.spec_version')=CAST(NEW.spec_version AS TEXT)
          AND (SELECT COUNT(*) FROM assessment_configuration_slots WHERE configuration_id=OLD.id)
              =json_array_length(plan.plan_json,'$.items')
          AND NOT EXISTS (
              SELECT 1 FROM json_each(plan.plan_json,'$.items') AS item
              WHERE NOT EXISTS (SELECT 1 FROM assessment_configuration_slots AS slot
                WHERE slot.configuration_id=OLD.id
                  AND slot.slot_id=json_extract(item.value,'$.slot_key')
                  AND slot.ordinal=json_extract(item.value,'$.ordinal')
                  AND slot.primary_point_id=json_extract(item.value,'$.primary_point_id')
                  AND slot.marks_basis_points=json_extract(item.value,'$.marks_basis_points')
                  AND json(slot.point_slot_json)=json(item.value)))
    ))
)
BEGIN SELECT RAISE(ABORT,'Assessment needs its complete policy slots totaling 100.00'); END;

CREATE TRIGGER immutable_frozen_assessment_configuration_slot_update
BEFORE UPDATE ON assessment_configuration_slots
WHEN (SELECT status FROM assessment_configurations WHERE id=OLD.configuration_id)='FROZEN'
BEGIN SELECT RAISE(ABORT,'Frozen Assessment configuration slots are immutable'); END;
CREATE TRIGGER validate_assessment_configuration_slot_policy_update
BEFORE UPDATE ON assessment_configuration_slots
WHEN (SELECT policy_version FROM assessment_configurations WHERE id=OLD.configuration_id)
        ='cj.assessment.points.v1'
  OR NOT EXISTS (
    SELECT 1 FROM assessment_configurations AS config
    WHERE config.id=NEW.configuration_id AND config.status='DRAFT'
      AND config.policy_version='legacy.configurable.v1' AND NEW.ordinal<=30
      AND NEW.primary_point_id IS NULL AND NEW.point_slot_json IS NULL
  )
BEGIN SELECT RAISE(ABORT,'Assessment slot updates cannot bypass the original policy'); END;
CREATE TRIGGER immutable_assessment_configuration_slot_delete
BEFORE DELETE ON assessment_configuration_slots
BEGIN SELECT RAISE(ABORT,'Assessment configuration slots are immutable'); END;

CREATE TABLE assessment_configuration_questions_v78 (
    configuration_id TEXT NOT NULL REFERENCES assessment_configurations(id) ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    slot_id TEXT NOT NULL, ordinal INTEGER NOT NULL CHECK(ordinal>=1),
    question_revision_id TEXT NOT NULL REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    family_id TEXT NOT NULL CHECK(length(trim(family_id)) BETWEEN 1 AND 100),
    blueprint_id TEXT NOT NULL CHECK(length(trim(blueprint_id)) BETWEEN 1 AND 100),
    objective_id TEXT NOT NULL CHECK(length(trim(objective_id)) BETWEEN 1 AND 100),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    primary_point_id TEXT,
    point_validation_receipt_id TEXT REFERENCES generic_llm_calls(id) ON DELETE RESTRICT,
    PRIMARY KEY(configuration_id,slot_id), UNIQUE(configuration_id,ordinal),
    UNIQUE(configuration_id,question_revision_id), UNIQUE(configuration_id,family_id),
    FOREIGN KEY(configuration_id,slot_id)
        REFERENCES assessment_configuration_slots(configuration_id,slot_id) ON DELETE RESTRICT
);
INSERT INTO assessment_configuration_questions_v78(
    configuration_id,workspace_id,slot_id,ordinal,question_revision_id,family_id,
    blueprint_id,objective_id,created_at)
SELECT configuration_id,workspace_id,slot_id,ordinal,question_revision_id,family_id,
    blueprint_id,objective_id,created_at FROM assessment_configuration_questions;
DROP TABLE assessment_configuration_questions;
ALTER TABLE assessment_configuration_questions_v78 RENAME TO assessment_configuration_questions;

CREATE TRIGGER validate_assessment_configuration_question_policy
BEFORE INSERT ON assessment_configuration_questions
WHEN NOT EXISTS (
    SELECT 1 FROM assessment_configurations AS config
    JOIN assessment_configuration_slots AS slot
      ON slot.configuration_id=config.id AND slot.slot_id=NEW.slot_id
    JOIN assessment_question_revisions AS question ON question.id=NEW.question_revision_id
    WHERE config.id=NEW.configuration_id AND config.status='FROZEN'
      AND config.workspace_id=NEW.workspace_id AND slot.ordinal=NEW.ordinal
      AND question.course_id=config.course_id AND question.question_type=slot.question_type
      AND (question.owner_user_id IS NULL OR question.owner_user_id=config.owner_user_id)
      AND question.family_id=NEW.family_id AND question.validation_status='VALIDATED'
      AND question.verification_method!='MODEL_ONLY' AND (
        (config.policy_version='legacy.configurable.v1' AND NEW.ordinal<=30
         AND NEW.primary_point_id IS NULL AND NEW.point_validation_receipt_id IS NULL)
        OR (config.policy_version='cj.assessment.points.v1'
          AND NEW.primary_point_id=slot.primary_point_id AND EXISTS (
            SELECT 1 FROM generic_llm_calls AS receipt
            JOIN assessment_point_configuration_plans AS plan ON plan.configuration_id=config.id
            WHERE receipt.id=NEW.point_validation_receipt_id AND receipt.status='COMPLETED'
              AND receipt.role='LLM_REVIEW'
              AND receipt.operation_family='ASSESSMENT_POINT_QUESTION_REVIEW'
              AND receipt.template_version='assessment-point-question-review.v1'
              AND receipt.schema_version='assessment-point-question-review.v1'
              AND json_extract(receipt.audit_json,'$.returned_model')='qwen3.8-max'
              AND json_extract(receipt.audit_json,'$.usage_status')='REPORTED'
              AND json_type(receipt.audit_json,'$.input_tokens')='integer'
              AND json_type(receipt.audit_json,'$.output_tokens')='integer'
              AND json_extract(receipt.audit_json,'$.input_tokens')>=0
              AND json_extract(receipt.audit_json,'$.output_tokens')>=0
              AND receipt.input_tokens=json_extract(receipt.audit_json,'$.input_tokens')
              AND receipt.output_tokens=json_extract(receipt.audit_json,'$.output_tokens')
              AND receipt.owner_user_id=config.owner_user_id AND receipt.course_id=config.course_id
              AND receipt.content_language=config.language
              AND json_extract(receipt.output_json,'$.configuration_id')=config.id
              AND json_extract(receipt.output_json,'$.plan_hash')=plan.content_hash
              AND json_extract(receipt.output_json,'$.source_snapshot')=plan.source_snapshot
              AND json_extract(receipt.output_json,'$.question_revision_id')=NEW.question_revision_id
              AND json_extract(receipt.output_json,'$.primary_point_id')=NEW.primary_point_id
              AND json_extract(receipt.output_json,'$.independently_scored_items')=1
              AND json_extract(receipt.output_json,'$.supported')=1
              AND json_extract(receipt.output_json,'$.conditions_preserved')=1
              AND json_extract(receipt.output_json,'$.variation_valid')=1
          ))
      )
)
BEGIN SELECT RAISE(ABORT,'Assessment question lacks its original policy/review binding'); END;

CREATE TRIGGER immutable_assessment_configuration_question
BEFORE UPDATE ON assessment_configuration_questions
BEGIN SELECT RAISE(ABORT,'Assessment configuration question bindings are immutable'); END;
CREATE TRIGGER immutable_assessment_configuration_question_delete
BEFORE DELETE ON assessment_configuration_questions
BEGIN SELECT RAISE(ABORT,'Assessment configuration question bindings are immutable'); END;

DROP TRIGGER IF EXISTS validate_assessment_blueprint_item;
DROP TRIGGER IF EXISTS freeze_valid_assessment_blueprint;
DROP TRIGGER IF EXISTS immutable_frozen_assessment_blueprint_item_update;
DROP TRIGGER IF EXISTS immutable_assessment_blueprint_item_delete;
CREATE TABLE assessment_blueprint_items_v78 (
    id TEXT PRIMARY KEY,
    blueprint_id TEXT NOT NULL REFERENCES assessment_blueprint_versions(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK(ordinal>=1),
    question_revision_id TEXT NOT NULL REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    family_id TEXT NOT NULL CHECK(length(family_id) BETWEEN 1 AND 100),
    marks INTEGER NOT NULL CHECK(marks BETWEEN 0.01 AND 100),
    marks_basis_points INTEGER NOT NULL CHECK(marks_basis_points BETWEEN 1 AND 10000),
    source_kind TEXT NOT NULL CHECK(source_kind IN (
        'OFFICIAL','WORKSPACE_PRIVATE','MODEL_GENERATED','EXTERNAL_INSPIRED')),
    verification_method TEXT NOT NULL CHECK(verification_method IN (
        'OFFICIAL','OWNER_AUTHORED','DETERMINISTIC','HUMAN_REVIEWED','AI_REVIEWED')),
    UNIQUE(blueprint_id,ordinal), UNIQUE(blueprint_id,question_revision_id), UNIQUE(blueprint_id,family_id)
);
INSERT INTO assessment_blueprint_items_v78
SELECT * FROM assessment_blueprint_items;
DROP TABLE assessment_blueprint_items;
ALTER TABLE assessment_blueprint_items_v78 RENAME TO assessment_blueprint_items;

CREATE TRIGGER validate_assessment_blueprint_item
BEFORE INSERT ON assessment_blueprint_items
WHEN NOT EXISTS (
    SELECT 1 FROM assessment_blueprint_versions AS blueprint
    JOIN assessment_question_revisions AS question ON question.id=NEW.question_revision_id
    JOIN assessment_rubric_criteria AS criterion
      ON criterion.question_revision_id=question.id AND criterion.node_id=blueprint.node_id
     AND criterion.spec_version=blueprint.spec_version
    WHERE blueprint.id=NEW.blueprint_id AND blueprint.status='BUILDING'
      AND question.course_id=blueprint.course_id
      AND (question.owner_user_id IS NULL OR question.owner_user_id=blueprint.owner_user_id)
      AND question.validation_status='VALIDATED' AND question.verification_method!='MODEL_ONLY'
      AND question.family_id=NEW.family_id AND question.source_kind=NEW.source_kind
      AND question.verification_method=NEW.verification_method AND (
        (COALESCE(json_extract(blueprint.selection_policy_json,'$.policy_version'),'legacy.configurable.v1')
            ='legacy.configurable.v1' AND NEW.ordinal<=30
         AND (SELECT COUNT(*) FROM assessment_blueprint_items WHERE blueprint_id=NEW.blueprint_id)<30)
        OR (json_extract(blueprint.selection_policy_json,'$.policy_version')='cj.assessment.points.v1'
          AND EXISTS (
            SELECT 1 FROM assessment_configurations AS config
            JOIN assessment_point_configuration_plans AS plan ON plan.configuration_id=config.id
            JOIN assessment_configuration_questions AS bound ON bound.configuration_id=config.id
            JOIN assessment_configuration_slots AS slot
              ON slot.configuration_id=config.id AND slot.slot_id=bound.slot_id
            WHERE config.id=json_extract(blueprint.selection_policy_json,'$.configuration_id')
              AND config.status='FROZEN' AND config.policy_version='cj.assessment.points.v1'
              AND config.workspace_id=blueprint.workspace_id AND config.owner_user_id=blueprint.owner_user_id
              AND config.course_id=blueprint.course_id AND config.node_id=blueprint.node_id
              AND config.spec_version=blueprint.spec_version
              AND plan.content_hash=json_extract(blueprint.selection_policy_json,'$.point_plan_hash')
              AND bound.ordinal=NEW.ordinal AND bound.question_revision_id=NEW.question_revision_id
              AND bound.family_id=NEW.family_id AND slot.marks_basis_points=NEW.marks_basis_points
              AND NEW.marks=slot.marks_basis_points/100.0
          ))
      )
)
BEGIN SELECT RAISE(ABORT,'Assessment blueprint item is invalid or lacks its policy binding'); END;

CREATE TRIGGER freeze_valid_assessment_blueprint
BEFORE UPDATE OF status ON assessment_blueprint_versions
WHEN NEW.status='FROZEN' AND OLD.status='BUILDING' AND (
    json_type(NEW.selection_policy_json,'$.question_count') IS NOT 'integer'
    OR COALESCE(json_extract(NEW.selection_policy_json,'$.policy_version'),'legacy.configurable.v1')
        NOT IN ('legacy.configurable.v1','cj.assessment.points.v1')
    OR (SELECT COALESCE(SUM(marks_basis_points),0) FROM assessment_blueprint_items WHERE blueprint_id=OLD.id)!=10000
    OR (SELECT COUNT(*) FROM assessment_blueprint_items WHERE blueprint_id=OLD.id)
        !=json_extract(NEW.selection_policy_json,'$.question_count')
    OR (COALESCE(json_extract(NEW.selection_policy_json,'$.policy_version'),'legacy.configurable.v1')
          ='legacy.configurable.v1' AND (
        (SELECT COUNT(*) FROM assessment_blueprint_items WHERE blueprint_id=OLD.id)<5
        OR (SELECT COUNT(*) FROM assessment_blueprint_items WHERE blueprint_id=OLD.id)>30))
    OR (json_extract(NEW.selection_policy_json,'$.policy_version')='cj.assessment.points.v1'
        AND NOT EXISTS (
          SELECT 1 FROM assessment_point_configuration_plans AS plan
          WHERE plan.configuration_id=json_extract(NEW.selection_policy_json,'$.configuration_id')
            AND plan.content_hash=json_extract(NEW.selection_policy_json,'$.point_plan_hash')
            AND json_array_length(plan.plan_json,'$.items')=
                (SELECT COUNT(*) FROM assessment_blueprint_items WHERE blueprint_id=OLD.id)))
)
BEGIN SELECT RAISE(ABORT,'Assessment blueprint needs its complete policy items totaling 100.00'); END;

CREATE TRIGGER validate_assessment_blueprint_initial_status
BEFORE INSERT ON assessment_blueprint_versions
WHEN NEW.status!='BUILDING'
BEGIN SELECT RAISE(ABORT,'New Assessment blueprints must freeze their complete policy items'); END;

CREATE TRIGGER immutable_frozen_assessment_blueprint_item_update
BEFORE UPDATE ON assessment_blueprint_items
WHEN (SELECT status FROM assessment_blueprint_versions WHERE id=OLD.blueprint_id)!='BUILDING'
BEGIN SELECT RAISE(ABORT,'Frozen Assessment blueprint items are immutable'); END;
CREATE TRIGGER immutable_assessment_blueprint_item_delete
BEFORE DELETE ON assessment_blueprint_items
BEGIN SELECT RAISE(ABORT,'Assessment blueprint items are immutable'); END;

CREATE TABLE assessment_configuration_recovery_receipts_v78 (
    id TEXT PRIMARY KEY,
    preparation_id TEXT NOT NULL REFERENCES assessment_configuration_preparations(id) ON DELETE RESTRICT,
    configuration_id TEXT NOT NULL REFERENCES assessment_configurations(id) ON DELETE RESTRICT,
    prior_status TEXT NOT NULL CHECK(prior_status IN ('PREPARING','BLOCKED','CANCELLED')),
    reason TEXT NOT NULL CHECK(reason IN ('COMPATIBLE_POOL_COMPLETE','SAVED_RESPONSE_RECONCILED')),
    prepared_slots INTEGER NOT NULL CHECK(prepared_slots>=1),
    model_calls_added INTEGER NOT NULL DEFAULT 0 CHECK(model_calls_added=0),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(preparation_id,reason,prepared_slots)
);
INSERT INTO assessment_configuration_recovery_receipts_v78
SELECT * FROM assessment_configuration_recovery_receipts;
DROP TABLE assessment_configuration_recovery_receipts;
ALTER TABLE assessment_configuration_recovery_receipts_v78 RENAME TO assessment_configuration_recovery_receipts;
CREATE TRIGGER validate_assessment_configuration_recovery_count
BEFORE INSERT ON assessment_configuration_recovery_receipts
WHEN NOT EXISTS (
    SELECT 1 FROM assessment_configurations AS config
    JOIN assessment_configuration_preparations AS prep ON prep.configuration_id=config.id
    WHERE config.id=NEW.configuration_id AND prep.id=NEW.preparation_id AND (
        (config.policy_version='legacy.configurable.v1' AND NEW.prepared_slots>=5)
        OR (config.policy_version='cj.assessment.points.v1' AND NEW.prepared_slots=
            (SELECT COUNT(*) FROM assessment_configuration_slots WHERE configuration_id=config.id))
    )
)
BEGIN SELECT RAISE(ABORT,'Recovered Assessment count must match its original policy'); END;

-- Check all restored foreign keys before committing the migration. A failure
-- leaves the previous schema/rows/ledger intact in the enclosing transaction.
CREATE TEMP TABLE point_migration_fk_guard(ok INTEGER NOT NULL CHECK(ok=1));
INSERT INTO point_migration_fk_guard
SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM pragma_foreign_key_check) THEN 1 ELSE 0 END;
DROP TABLE point_migration_fk_guard;
INSERT INTO schema_migrations(version,name) VALUES(78,'original receipt point assessment plans');
COMMIT;
PRAGMA legacy_alter_table=OFF;
PRAGMA foreign_keys=ON;
