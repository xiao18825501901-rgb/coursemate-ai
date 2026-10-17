-- Zero-HTTP, source-bound questions for the four audited graph-degree targets.
-- This is an additive path through the existing point configuration/question
-- tables.  It does not relax or rewrite the AI-reviewed provenance contract.
BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS assessment_point_deterministic_provenance (
    question_revision_id TEXT PRIMARY KEY
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    configuration_id TEXT NOT NULL REFERENCES assessment_configurations(id) ON DELETE RESTRICT,
    slot_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    spec_version INTEGER NOT NULL CHECK(spec_version>=1),
    point_input_hash TEXT NOT NULL CHECK(length(point_input_hash)=64
        AND point_input_hash NOT GLOB '*[^0-9a-f]*'),
    question_revision_hash TEXT NOT NULL CHECK(length(question_revision_hash)=64
        AND question_revision_hash NOT GLOB '*[^0-9a-f]*'),
    point_input_json TEXT NOT NULL CHECK(COALESCE(json_valid(point_input_json)
        AND json_type(point_input_json,'$.targets')='array'
        AND json_array_length(point_input_json,'$.targets')=1,0)),
    content_json TEXT NOT NULL CHECK(json_valid(content_json)),
    proof_json TEXT NOT NULL CHECK(json_valid(proof_json)),
    method TEXT NOT NULL CHECK(method='finite-loop-free-graph-degree-assessment.v1'),
    publication_status TEXT NOT NULL CHECK(publication_status='READY'),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(configuration_id,slot_id),
    FOREIGN KEY(configuration_id,slot_id)
        REFERENCES assessment_configuration_slots(configuration_id,slot_id) ON DELETE RESTRICT
);

CREATE TRIGGER validate_deterministic_point_provenance
BEFORE INSERT ON assessment_point_deterministic_provenance
WHEN NOT EXISTS (
    SELECT 1 FROM assessment_question_revisions question
    JOIN assessment_configurations config ON config.id=NEW.configuration_id
    JOIN assessment_configuration_slots slot
      ON slot.configuration_id=config.id AND slot.slot_id=NEW.slot_id
    JOIN assessment_point_configuration_plans plan ON plan.configuration_id=config.id
    JOIN learning_workspaces workspace ON workspace.id=NEW.workspace_id
    WHERE question.id=NEW.question_revision_id
      AND question.id='pointdet_'||NEW.question_revision_hash
      AND question.owner_user_id=workspace.owner_user_id
      AND question.course_id=workspace.course_id
      AND question.source_kind='WORKSPACE_PRIVATE'
      AND question.validation_status='VALIDATED'
      AND question.verification_method='DETERMINISTIC'
      AND question.question_type=slot.question_type
      AND question.content_hash=NEW.question_revision_hash
      AND question.prompt_text=json_extract(NEW.content_json,'$.question_text')
      AND json_extract(question.answer_json,'$.reference_answer')
          =json_extract(NEW.content_json,'$.reference_answer')
      AND json(json_extract(question.answer_json,'$.deterministic_proof'))
          =json(NEW.proof_json)
      AND config.workspace_id=workspace.id
      AND config.owner_user_id=workspace.owner_user_id
      AND config.course_id=workspace.course_id
      AND config.node_id=NEW.node_id
      AND config.spec_version=NEW.spec_version
      AND config.status='FROZEN'
      AND config.policy_version='cj.assessment.points.v1'
      AND json_extract(NEW.point_input_json,'$.configuration_id')=config.id
      AND json_extract(NEW.point_input_json,'$.workspace_id')=workspace.id
      AND json_extract(NEW.point_input_json,'$.owner_user_id')=workspace.owner_user_id
      AND json_extract(NEW.point_input_json,'$.course_id')=workspace.course_id
      AND json_extract(NEW.point_input_json,'$.node_id')=NEW.node_id
      AND json_extract(NEW.point_input_json,'$.spec_version')=NEW.spec_version
      AND json_extract(NEW.point_input_json,'$.plan_hash')=plan.content_hash
      AND json_extract(NEW.point_input_json,'$.source_snapshot')=plan.source_snapshot
      AND json_extract(NEW.point_input_json,'$.content_language')=config.language
      AND json(json_extract(NEW.point_input_json,'$.point_slot'))=json(slot.point_slot_json)
      AND json_extract(NEW.content_json,'$.schema_version')='deterministic-graph-point-content.v1'
      AND json_extract(NEW.content_json,'$.method')=NEW.method
      AND json_extract(NEW.content_json,'$.point_input_hash')=NEW.point_input_hash
      AND json_extract(NEW.content_json,'$.source_snapshot')=plan.source_snapshot
      AND json_extract(NEW.proof_json,'$.schema_version')='deterministic-graph-point-proof.v1'
      AND json_extract(NEW.proof_json,'$.method')=NEW.method
      AND json_extract(NEW.proof_json,'$.model_http')=0
      AND json_extract(NEW.proof_json,'$.degree_sum')=8
      AND json_extract(NEW.proof_json,'$.edge_count')=4
      AND json_extract(NEW.proof_json,'$.twice_edge_count')=8
      AND json_extract(NEW.proof_json,'$.odd_degree_count')=2
      AND json_array_length(NEW.proof_json,'$.vertices')=4
      AND json_array_length(NEW.proof_json,'$.edges')=4
      AND (SELECT COUNT(*) FROM assessment_rubric_criteria rubric
           WHERE rubric.question_revision_id=question.id)=1
      AND (SELECT SUM(max_fraction) FROM assessment_rubric_criteria rubric
           WHERE rubric.question_revision_id=question.id)=100
      AND EXISTS (
          SELECT 1 FROM assessment_rubric_criteria rubric
          WHERE rubric.question_revision_id=question.id
            AND rubric.criterion_id='point_target_1'
            AND rubric.node_id=NEW.node_id
            AND rubric.spec_version=NEW.spec_version
            AND rubric.item_id=json_extract(
                NEW.point_input_json,'$.targets[0].item_id')
            AND json(rubric.deterministic_rule_json)=json(NEW.proof_json)
      )
      AND EXISTS (
          SELECT 1 FROM assessment_reference_solutions solution
          WHERE solution.question_revision_id=question.id
            AND solution.prompt_version=NEW.method
            AND json_extract(solution.answer_json,'$')
                =json_extract(NEW.content_json,'$.reference_answer')
            AND json(solution.source_refs_json)
                =json(json_extract(NEW.proof_json,'$.source_refs'))
      )
)
BEGIN SELECT RAISE(ABORT,'Deterministic point question lacks exact host proof'); END;

CREATE TRIGGER immutable_deterministic_point_provenance_update
BEFORE UPDATE ON assessment_point_deterministic_provenance
BEGIN SELECT RAISE(ABORT,'Deterministic point provenance is immutable'); END;
CREATE TRIGGER immutable_deterministic_point_provenance_delete
BEFORE DELETE ON assessment_point_deterministic_provenance
BEGIN SELECT RAISE(ABORT,'Deterministic point provenance is immutable'); END;

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
            ) OR EXISTS (
              SELECT 1 FROM assessment_point_deterministic_provenance deterministic
              JOIN assessment_point_configuration_plans plan
                ON plan.configuration_id=config.id
              WHERE NEW.point_validation_receipt_id IS NULL
                AND deterministic.configuration_id=config.id
                AND deterministic.workspace_id=NEW.workspace_id
                AND deterministic.slot_id=NEW.slot_id
                AND deterministic.question_revision_id=NEW.question_revision_id
                AND deterministic.publication_status='READY'
                AND deterministic.point_input_hash=json_extract(
                    deterministic.content_json,'$.point_input_hash')
                AND json_extract(deterministic.point_input_json,'$.plan_hash')=plan.content_hash
                AND json_extract(deterministic.point_input_json,'$.source_snapshot')=plan.source_snapshot
                AND json_extract(deterministic.point_input_json,
                    '$.point_slot.primary_point_id')=NEW.primary_point_id
            )
          ))
      )
)
BEGIN SELECT RAISE(ABORT,'Assessment question lacks its original policy/review binding'); END;

CREATE TRIGGER validate_bound_deterministic_point_provenance
BEFORE INSERT ON assessment_configuration_questions
WHEN NEW.question_revision_id LIKE 'pointdet_%' AND NOT EXISTS (
    SELECT 1 FROM assessment_point_deterministic_provenance provenance
    WHERE provenance.question_revision_id=NEW.question_revision_id
      AND provenance.workspace_id=NEW.workspace_id
      AND provenance.configuration_id=NEW.configuration_id
      AND provenance.slot_id=NEW.slot_id
      AND NEW.point_validation_receipt_id IS NULL
      AND NEW.objective_id=json_extract(
          provenance.point_input_json,'$.point_slot.primary_point_id')
      AND (SELECT SUM(max_fraction) FROM assessment_rubric_criteria rubric
           WHERE rubric.question_revision_id=provenance.question_revision_id)=100
)
BEGIN SELECT RAISE(ABORT,'Deterministic READY binding requires exact host proof'); END;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(84,'source-bound deterministic graph point questions');

COMMIT;
