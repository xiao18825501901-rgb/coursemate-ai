-- The student entry path may publish a source-bound model question after the
-- trusted host has revalidated authorization, exact evidence, required public
-- and private fields, rubric, answer isolation and immutable identities.
-- MODEL_ONLY remains explicit audit truth: no blind/human/OpenJEV review is
-- fabricated. Existing rows, scores and historical qualification evidence are
-- untouched.

DROP TRIGGER IF EXISTS validate_question_engine_provenance;

CREATE TRIGGER validate_question_engine_provenance
BEFORE INSERT ON question_engine_provenance
WHEN NOT EXISTS(
    SELECT 1
    FROM assessment_question_revisions AS question
    JOIN learning_workspaces AS workspace ON workspace.id=NEW.workspace_id
    JOIN knowledge_nodes AS node ON node.id=NEW.node_id
    WHERE question.id=NEW.question_revision_id
      AND question.course_id=workspace.course_id
      AND question.owner_user_id=workspace.owner_user_id
      AND node.course_id=workspace.course_id
      AND (
          (NEW.publication_status='READY'
           AND question.validation_status='VALIDATED'
           AND (
               question.verification_method IN (
                   'AI_REVIEWED','DETERMINISTIC','HUMAN_REVIEWED',
                   'OWNER_AUTHORED','OFFICIAL'
               )
               OR (question.verification_method='MODEL_ONLY'
                   AND NEW.readiness_reason='SOURCE_BOUND_AUTHOR_COMPLETE')
           ))
          OR
          (NEW.publication_status='NEEDS_REVIEW'
           AND question.validation_status='NEEDS_REVIEW'
           AND question.verification_method='MODEL_ONLY')
          OR
          (NEW.publication_status='REJECTED'
           AND question.validation_status='REJECTED'
           AND question.verification_method='MODEL_ONLY')
      )
)
BEGIN
    SELECT RAISE(ABORT, 'Question Engine provenance does not match its scoped revision');
END;

DROP TRIGGER IF EXISTS validate_assessment_configuration_question_policy;

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
      AND (
        (config.policy_version='legacy.configurable.v1'
         AND question.verification_method!='MODEL_ONLY' AND NEW.ordinal<=30
         AND NEW.primary_point_id IS NULL AND NEW.point_validation_receipt_id IS NULL)
        OR (config.policy_version='cj.assessment.points.v1'
          AND NEW.primary_point_id=slot.primary_point_id AND (
            EXISTS (
              SELECT 1 FROM generic_llm_calls AS receipt
              JOIN assessment_point_configuration_plans AS plan
                ON plan.configuration_id=config.id
              WHERE question.verification_method='AI_REVIEWED'
                AND receipt.id=NEW.point_validation_receipt_id AND receipt.status='COMPLETED'
                AND receipt.role='LLM_REVIEW'
                AND receipt.operation_family='ASSESSMENT_POINT_QUESTION_REVIEW'
                AND receipt.template_version='assessment-point-question-review.v1'
                AND receipt.schema_version='assessment-point-question-review.v1'
                AND json_extract(receipt.audit_json,'$.returned_model')='qwen3.8-max'
                AND json_extract(receipt.audit_json,'$.usage_status')='REPORTED'
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
            ) OR EXISTS (
              SELECT 1 FROM assessment_point_question_reuse_receipts reuse
              WHERE question.verification_method='AI_REVIEWED'
                AND reuse.configuration_id=config.id AND reuse.workspace_id=NEW.workspace_id
                AND reuse.slot_id=NEW.slot_id
                AND reuse.question_revision_id=NEW.question_revision_id
                AND reuse.original_review_receipt_id=NEW.point_validation_receipt_id
            ) OR EXISTS (
              SELECT 1 FROM assessment_point_deterministic_provenance deterministic
              JOIN assessment_point_configuration_plans plan
                ON plan.configuration_id=config.id
              WHERE question.verification_method='DETERMINISTIC'
                AND NEW.point_validation_receipt_id IS NULL
                AND deterministic.configuration_id=config.id
                AND deterministic.workspace_id=NEW.workspace_id
                AND deterministic.slot_id=NEW.slot_id
                AND deterministic.question_revision_id=NEW.question_revision_id
                AND deterministic.publication_status='READY'
                AND json_extract(deterministic.point_input_json,'$.plan_hash')=plan.content_hash
                AND json_extract(deterministic.point_input_json,'$.source_snapshot')=plan.source_snapshot
                AND json_extract(deterministic.point_input_json,
                    '$.point_slot.primary_point_id')=NEW.primary_point_id
            ) OR EXISTS (
              SELECT 1 FROM question_engine_provenance entry
              JOIN assessment_point_configuration_plans plan
                ON plan.configuration_id=config.id
              WHERE question.verification_method='MODEL_ONLY'
                AND NEW.point_validation_receipt_id IS NULL
                AND entry.question_revision_id=NEW.question_revision_id
                AND entry.workspace_id=NEW.workspace_id
                AND entry.publication_status='READY'
                AND entry.readiness_reason='SOURCE_BOUND_AUTHOR_COMPLETE'
                AND json_extract(entry.blueprint_json,'$.point_input.configuration_id')=config.id
                AND json_extract(entry.blueprint_json,'$.point_input.plan_hash')=plan.content_hash
                AND json_extract(entry.blueprint_json,'$.point_input.source_snapshot')=plan.source_snapshot
                AND json_extract(entry.blueprint_json,
                    '$.point_input.point_slot.primary_point_id')=NEW.primary_point_id
                AND json_extract(entry.blueprint_json,
                    '$.point_input.point_slot.independently_scored_parts')=1
            )
          ))
      )
)
BEGIN SELECT RAISE(ABORT,'Assessment question lacks its original policy/review binding'); END;

-- Blueprint freezing is a separate immutable boundary from configuration
-- binding.  Keep MODEL_ONLY visible as audit truth, while permitting it only
-- for the point-policy path whose configuration binding above has already
-- proven the source-bound host receipt.  Legacy configurable assessments keep
-- their historical exclusion unchanged.
PRAGMA foreign_keys=OFF;
PRAGMA legacy_alter_table=ON;

DROP TRIGGER IF EXISTS validate_assessment_blueprint_item;
DROP TRIGGER IF EXISTS immutable_frozen_assessment_blueprint_item_update;
DROP TRIGGER IF EXISTS immutable_assessment_blueprint_item_delete;

CREATE TABLE assessment_blueprint_items_v85 (
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
        'OFFICIAL','OWNER_AUTHORED','DETERMINISTIC','HUMAN_REVIEWED','AI_REVIEWED','MODEL_ONLY')),
    UNIQUE(blueprint_id,ordinal), UNIQUE(blueprint_id,question_revision_id), UNIQUE(blueprint_id,family_id)
);
INSERT INTO assessment_blueprint_items_v85
SELECT * FROM assessment_blueprint_items;
DROP TABLE assessment_blueprint_items;
ALTER TABLE assessment_blueprint_items_v85 RENAME TO assessment_blueprint_items;

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
      AND question.validation_status='VALIDATED'
      AND question.family_id=NEW.family_id AND question.source_kind=NEW.source_kind
      AND question.verification_method=NEW.verification_method AND (
        (COALESCE(json_extract(blueprint.selection_policy_json,'$.policy_version'),'legacy.configurable.v1')
            ='legacy.configurable.v1' AND question.verification_method!='MODEL_ONLY'
         AND NEW.ordinal<=30
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

CREATE TRIGGER immutable_frozen_assessment_blueprint_item_update
BEFORE UPDATE ON assessment_blueprint_items
WHEN (SELECT status FROM assessment_blueprint_versions WHERE id=OLD.blueprint_id)!='BUILDING'
BEGIN SELECT RAISE(ABORT,'Frozen Assessment blueprint items are immutable'); END;

CREATE TRIGGER immutable_assessment_blueprint_item_delete
BEFORE DELETE ON assessment_blueprint_items
BEGIN SELECT RAISE(ABORT,'Assessment blueprint items are immutable'); END;

PRAGMA legacy_alter_table=OFF;
PRAGMA foreign_keys=ON;

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(85,'source-bound student question entry without formal review gate');
