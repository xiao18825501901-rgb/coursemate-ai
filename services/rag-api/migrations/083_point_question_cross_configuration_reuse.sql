-- Bind an unchanged, fully qualified READY point question into a later frozen
-- configuration without copying the question, changing its original receipts,
-- or contacting a model again. The reuse receipt is immutable and is valid only
-- for the same workspace/course/node/spec/language/source and the same semantic
-- point slot (the catalog validation receipt identity may advance).

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS assessment_point_question_reuse_receipts (
    id TEXT PRIMARY KEY CHECK(length(trim(id)) BETWEEN 1 AND 100),
    configuration_id TEXT NOT NULL REFERENCES assessment_configurations(id) ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    slot_id TEXT NOT NULL,
    original_configuration_id TEXT NOT NULL
        REFERENCES assessment_configurations(id) ON DELETE RESTRICT,
    question_revision_id TEXT NOT NULL
        REFERENCES assessment_point_question_provenance(question_revision_id) ON DELETE RESTRICT,
    original_review_receipt_id TEXT NOT NULL
        REFERENCES generic_llm_calls(id) ON DELETE RESTRICT,
    semantic_hash TEXT NOT NULL CHECK(length(semantic_hash)=64
        AND semantic_hash NOT GLOB '*[^0-9a-f]*'),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(configuration_id,slot_id),
    FOREIGN KEY(configuration_id,slot_id)
        REFERENCES assessment_configuration_slots(configuration_id,slot_id) ON DELETE RESTRICT
);

CREATE TRIGGER validate_point_question_reuse_receipt
BEFORE INSERT ON assessment_point_question_reuse_receipts
WHEN NOT EXISTS (
    SELECT 1
    FROM assessment_configurations current_config
    JOIN assessment_point_configuration_plans current_plan
      ON current_plan.configuration_id=current_config.id
    JOIN assessment_configuration_slots current_slot
      ON current_slot.configuration_id=current_config.id AND current_slot.slot_id=NEW.slot_id
    JOIN assessment_point_question_provenance original
      ON original.question_revision_id=NEW.question_revision_id
    JOIN assessment_configurations original_config
      ON original_config.id=original.configuration_id
    JOIN assessment_point_configuration_plans original_plan
      ON original_plan.configuration_id=original_config.id
    JOIN assessment_configuration_slots original_slot
      ON original_slot.configuration_id=original_config.id AND original_slot.slot_id=original.slot_id
    JOIN assessment_question_revisions question ON question.id=original.question_revision_id
    JOIN generic_llm_calls review ON review.id=original.review_receipt_id
    WHERE current_config.id=NEW.configuration_id
      AND current_config.workspace_id=NEW.workspace_id
      AND current_config.status='FROZEN'
      AND current_config.policy_version='cj.assessment.points.v1'
      AND original.configuration_id=NEW.original_configuration_id
      AND original.workspace_id=NEW.workspace_id
      AND original.slot_id=NEW.slot_id
      AND original.review_receipt_id=NEW.original_review_receipt_id
      AND original.publication_status='READY'
      AND original.policy_version='cj.assessment.points.v1'
      AND original_config.status='FROZEN'
      AND original_config.workspace_id=current_config.workspace_id
      AND original_config.owner_user_id=current_config.owner_user_id
      AND original_config.course_id=current_config.course_id
      AND original_config.node_id=current_config.node_id
      AND original_config.spec_version=current_config.spec_version
      AND original_config.language=current_config.language
      AND original.node_id=current_config.node_id
      AND original.spec_version=current_config.spec_version
      AND original_plan.source_snapshot=current_plan.source_snapshot
      AND json_extract(original.point_input_json,'$.source_snapshot')=current_plan.source_snapshot
      AND current_slot.ordinal=original_slot.ordinal
      AND current_slot.question_type=original_slot.question_type
      AND current_slot.task_form=original_slot.task_form
      AND current_slot.marks_basis_points=original_slot.marks_basis_points
      AND current_slot.primary_point_id=original_slot.primary_point_id
      AND json(json_remove(current_slot.point_slot_json,
            '$.verified_point.validation_receipt_id'))
          =json(json_remove(json_extract(original.point_input_json,'$.point_slot'),
            '$.verified_point.validation_receipt_id'))
      AND question.course_id=current_config.course_id
      AND question.owner_user_id=current_config.owner_user_id
      AND question.validation_status='VALIDATED'
      AND question.verification_method='AI_REVIEWED'
      AND review.status='COMPLETED'
      AND review.role='LLM_REVIEW'
      AND review.operation_family='ASSESSMENT_POINT_QUESTION_REVIEW'
      AND json_extract(review.output_json,'$.question_revision_id')=question.id
      AND json_extract(review.output_json,'$.supported')=1
      AND json_extract(review.output_json,'$.conditions_preserved')=1
      AND json_extract(review.output_json,'$.variation_valid')=1
      AND json_extract(review.output_json,'$.answer_agreement')=1
      AND json_extract(review.output_json,'$.private_boundary_clear')=1
      AND (SELECT COUNT(*) FROM assessment_point_question_targets target
           WHERE target.question_revision_id=question.id)
          =json_array_length(original.point_input_json,'$.targets')
      AND (SELECT SUM(max_fraction) FROM assessment_rubric_criteria rubric
           WHERE rubric.question_revision_id=question.id)=100
)
BEGIN SELECT RAISE(ABORT,'Point question reuse is not semantically identical and qualified'); END;

CREATE TRIGGER immutable_point_question_reuse_receipt_update
BEFORE UPDATE ON assessment_point_question_reuse_receipts
BEGIN SELECT RAISE(ABORT,'Point question reuse receipts are immutable'); END;
CREATE TRIGGER immutable_point_question_reuse_receipt_delete
BEFORE DELETE ON assessment_point_question_reuse_receipts
BEGIN SELECT RAISE(ABORT,'Point question reuse receipts are immutable'); END;

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
      AND question.verification_method!='MODEL_ONLY' AND (
        (config.policy_version='legacy.configurable.v1' AND NEW.ordinal<=30
         AND NEW.primary_point_id IS NULL AND NEW.point_validation_receipt_id IS NULL)
        OR (config.policy_version='cj.assessment.points.v1'
          AND NEW.primary_point_id=slot.primary_point_id AND (
            EXISTS (
              SELECT 1 FROM generic_llm_calls AS receipt
              JOIN assessment_point_configuration_plans AS plan
                ON plan.configuration_id=config.id
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
            ) OR EXISTS (
              SELECT 1 FROM assessment_point_question_reuse_receipts reuse
              WHERE reuse.configuration_id=config.id AND reuse.workspace_id=NEW.workspace_id
                AND reuse.slot_id=NEW.slot_id
                AND reuse.question_revision_id=NEW.question_revision_id
                AND reuse.original_review_receipt_id=NEW.point_validation_receipt_id
            )
          ))
      )
)
BEGIN SELECT RAISE(ABORT,'Assessment question lacks its original policy/review binding'); END;

DROP TRIGGER IF EXISTS validate_bound_point_question_complete_provenance;
CREATE TRIGGER validate_bound_point_question_complete_provenance
BEFORE INSERT ON assessment_configuration_questions
WHEN NEW.question_revision_id LIKE 'pointqe_%' AND NOT EXISTS (
    SELECT 1 FROM assessment_point_question_provenance provenance
    WHERE provenance.question_revision_id=NEW.question_revision_id
      AND provenance.workspace_id=NEW.workspace_id
      AND provenance.review_receipt_id=NEW.point_validation_receipt_id
      AND NEW.objective_id=json_extract(provenance.point_input_json,'$.point_slot.primary_point_id')
      AND (
        (provenance.configuration_id=NEW.configuration_id AND provenance.slot_id=NEW.slot_id)
        OR EXISTS (
          SELECT 1 FROM assessment_point_question_reuse_receipts reuse
          WHERE reuse.configuration_id=NEW.configuration_id
            AND reuse.workspace_id=NEW.workspace_id AND reuse.slot_id=NEW.slot_id
            AND reuse.original_configuration_id=provenance.configuration_id
            AND reuse.question_revision_id=provenance.question_revision_id
            AND reuse.original_review_receipt_id=provenance.review_receipt_id
        )
      )
      AND (SELECT COUNT(*) FROM assessment_point_question_targets target
           WHERE target.question_revision_id=provenance.question_revision_id)
          =json_array_length(provenance.point_input_json,'$.targets')
      AND (SELECT SUM(max_fraction) FROM assessment_rubric_criteria rubric
           WHERE rubric.question_revision_id=provenance.question_revision_id)=100
      AND NOT EXISTS (
          SELECT 1 FROM assessment_point_question_targets target
          WHERE target.question_revision_id=provenance.question_revision_id AND NOT EXISTS (
              SELECT 1 FROM assessment_rubric_criteria rubric
              WHERE rubric.question_revision_id=target.question_revision_id
                AND rubric.node_id=target.node_id AND rubric.spec_version=target.spec_version
                AND rubric.item_id=target.item_id))
)
BEGIN SELECT RAISE(ABORT,'Point READY binding requires every original target and rubric'); END;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(83,'qualified point question cross-configuration reuse');

COMMIT;
