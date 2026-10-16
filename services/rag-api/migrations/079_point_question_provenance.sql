-- Additive provenance for a genuinely multi-target point question. The existing
-- question/private answer/rubric/reference/history tables remain authoritative.
-- No old question, score, session, operation, UNKNOWN or qualification is rewritten.
BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS assessment_point_question_provenance (
    question_revision_id TEXT PRIMARY KEY
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    configuration_id TEXT NOT NULL REFERENCES assessment_configurations(id) ON DELETE RESTRICT,
    slot_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    spec_version INTEGER NOT NULL CHECK(spec_version>=1),
    policy_version TEXT NOT NULL CHECK(policy_version='cj.assessment.points.v1'),
    point_input_hash TEXT NOT NULL CHECK(length(point_input_hash)=64
        AND point_input_hash NOT GLOB '*[^0-9a-f]*'),
    question_revision_hash TEXT NOT NULL CHECK(length(question_revision_hash)=64
        AND question_revision_hash NOT GLOB '*[^0-9a-f]*'),
    point_input_json TEXT NOT NULL CHECK(COALESCE(json_valid(point_input_json)
        AND json_type(point_input_json,'$.targets')='array'
        AND json_array_length(point_input_json,'$.targets')>=1,0)),
    candidate_json TEXT NOT NULL CHECK(json_valid(candidate_json)),
    blind_receipt_json TEXT NOT NULL CHECK(json_valid(blind_receipt_json)),
    review_receipt_json TEXT NOT NULL CHECK(json_valid(review_receipt_json)),
    structure_report_json TEXT NOT NULL CHECK(COALESCE(json_valid(structure_report_json)
        AND json_extract(structure_report_json,'$.status')='PASS',0)),
    qualification_receipts_json TEXT NOT NULL CHECK(json_valid(qualification_receipts_json)),
    author_receipt_id TEXT NOT NULL REFERENCES generic_llm_calls(id) ON DELETE RESTRICT,
    blind_receipt_id TEXT NOT NULL REFERENCES generic_llm_calls(id) ON DELETE RESTRICT,
    review_receipt_id TEXT NOT NULL REFERENCES generic_llm_calls(id) ON DELETE RESTRICT,
    publication_status TEXT NOT NULL CHECK(publication_status='READY'),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(workspace_id,question_revision_hash), UNIQUE(configuration_id,slot_id),
    FOREIGN KEY(configuration_id,slot_id)
        REFERENCES assessment_configuration_slots(configuration_id,slot_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS assessment_point_question_targets (
    question_revision_id TEXT NOT NULL
        REFERENCES assessment_point_question_provenance(question_revision_id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK(ordinal>=1),
    node_id TEXT NOT NULL,
    spec_version INTEGER NOT NULL CHECK(spec_version>=1),
    item_id TEXT NOT NULL,
    evidence_pack_hash TEXT NOT NULL CHECK(length(evidence_pack_hash)=64
        AND evidence_pack_hash NOT GLOB '*[^0-9a-f]*'),
    evidence_pack_json TEXT NOT NULL CHECK(json_valid(evidence_pack_json)),
    PRIMARY KEY(question_revision_id,item_id), UNIQUE(question_revision_id,ordinal),
    FOREIGN KEY(node_id,spec_version,item_id)
        REFERENCES teaching_items(node_id,spec_version,item_id) ON DELETE RESTRICT
);

CREATE TRIGGER IF NOT EXISTS validate_point_question_provenance
BEFORE INSERT ON assessment_point_question_provenance
WHEN NOT EXISTS (
    SELECT 1 FROM assessment_question_revisions question
    JOIN assessment_configurations config ON config.id=NEW.configuration_id
    JOIN assessment_configuration_slots slot
      ON slot.configuration_id=config.id AND slot.slot_id=NEW.slot_id
    JOIN assessment_point_configuration_plans plan ON plan.configuration_id=config.id
    JOIN learning_workspaces workspace ON workspace.id=NEW.workspace_id
    JOIN generic_llm_calls author ON author.id=NEW.author_receipt_id
    JOIN generic_llm_calls blind ON blind.id=NEW.blind_receipt_id
    JOIN generic_llm_calls review ON review.id=NEW.review_receipt_id
    WHERE question.id=NEW.question_revision_id
      AND question.id='pointqe_'||NEW.question_revision_hash
      AND question.owner_user_id=workspace.owner_user_id AND question.course_id=workspace.course_id
      AND question.validation_status='VALIDATED' AND question.verification_method='AI_REVIEWED'
      AND question.source_kind='MODEL_GENERATED' AND question.question_type=slot.question_type
      AND config.workspace_id=workspace.id AND config.owner_user_id=workspace.owner_user_id
      AND config.course_id=workspace.course_id AND config.node_id=NEW.node_id
      AND config.spec_version=NEW.spec_version AND config.status='FROZEN'
      AND config.policy_version=NEW.policy_version
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
      AND json_extract(NEW.structure_report_json,'$.point_input_hash')=NEW.point_input_hash
      AND json_extract(NEW.structure_report_json,'$.question_revision')=NEW.question_revision_hash
      AND author.status='COMPLETED' AND author.role='ASSESSMENT_AUTHOR'
      AND author.operation_family='ASSESSMENT_POINT_QUESTION_AUTHOR'
      AND author.id='point-question-author:'||NEW.point_input_hash
      AND blind.status='COMPLETED' AND blind.role='BLIND_SOLVER'
      AND blind.operation_family='ASSESSMENT_POINT_QUESTION_BLIND'
      AND blind.id='point-question-blind:'||NEW.point_input_hash
      AND review.status='COMPLETED' AND review.role='LLM_REVIEW'
      AND review.operation_family='ASSESSMENT_POINT_QUESTION_REVIEW'
      AND review.id='point-question-review:'||NEW.point_input_hash
      AND author.owner_user_id=config.owner_user_id AND blind.owner_user_id=config.owner_user_id
      AND review.owner_user_id=config.owner_user_id
      AND author.course_id=config.course_id AND blind.course_id=config.course_id
      AND review.course_id=config.course_id
      AND author.content_language=config.language AND blind.content_language=config.language
      AND review.content_language=config.language
      AND json_extract(review.output_json,'$.question_revision_id')=question.id
      AND json_extract(review.output_json,'$.answer_agreement')=1
      AND json_extract(review.output_json,'$.private_boundary_clear')=1
      AND json_extract(review.output_json,'$.supported')=1
      AND json_extract(review.output_json,'$.conditions_preserved')=1
      AND json_extract(review.output_json,'$.variation_valid')=1
      AND json_extract(review.output_json,'$.independently_scored_items')=1
)
BEGIN SELECT RAISE(ABORT,'Point question lacks original scoped pipeline provenance'); END;

CREATE TRIGGER IF NOT EXISTS validate_point_question_original_target
BEFORE INSERT ON assessment_point_question_targets
WHEN NOT EXISTS (
    SELECT 1 FROM assessment_point_question_provenance provenance,
        json_each(provenance.point_input_json,'$.targets') target
    WHERE provenance.question_revision_id=NEW.question_revision_id
      AND provenance.node_id=NEW.node_id AND provenance.spec_version=NEW.spec_version
      AND CAST(target.key AS INTEGER)+1=NEW.ordinal
      AND json_extract(target.value,'$.item_id')=NEW.item_id
      AND json(json_extract(target.value,'$.evidence'))=json(NEW.evidence_pack_json)
)
BEGIN SELECT RAISE(ABORT,'Point question target is not the exact original target'); END;

-- An owner-authored historical pool revision remains legal under 078. Only a
-- newly generated point revision must also have complete multi-target proof.
CREATE TRIGGER IF NOT EXISTS validate_bound_point_question_complete_provenance
BEFORE INSERT ON assessment_configuration_questions
WHEN NEW.question_revision_id LIKE 'pointqe_%' AND NOT EXISTS (
    SELECT 1 FROM assessment_point_question_provenance provenance
    WHERE provenance.question_revision_id=NEW.question_revision_id
      AND provenance.workspace_id=NEW.workspace_id
      AND provenance.configuration_id=NEW.configuration_id AND provenance.slot_id=NEW.slot_id
      AND provenance.review_receipt_id=NEW.point_validation_receipt_id
      AND NEW.objective_id=json_extract(provenance.point_input_json,'$.point_slot.primary_point_id')
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

CREATE TRIGGER IF NOT EXISTS immutable_point_question_provenance_update
BEFORE UPDATE ON assessment_point_question_provenance
BEGIN SELECT RAISE(ABORT,'Point question provenance is immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_point_question_provenance_delete
BEFORE DELETE ON assessment_point_question_provenance
BEGIN SELECT RAISE(ABORT,'Point question provenance is immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_point_question_target_update
BEFORE UPDATE ON assessment_point_question_targets
BEGIN SELECT RAISE(ABORT,'Point question original targets are immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_point_question_target_delete
BEFORE DELETE ON assessment_point_question_targets
BEGIN SELECT RAISE(ABORT,'Point question original targets are immutable'); END;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(79,'multi-target point question provenance');
COMMIT;
