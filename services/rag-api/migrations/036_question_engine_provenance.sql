-- Question Engine Stage 7: provenance for one immutable assessment question revision.
--
-- The actual question, private answer, rubric and reference solution continue to live in the
-- existing Assessment tables.  This additive table stores only the missing pipeline binding:
-- exact blueprint/evidence identities, author/blind call receipts and the validation report.
-- It is deliberately not a second question pool and contains no grade or learning-progress state.

CREATE TABLE IF NOT EXISTS question_engine_provenance (
    question_revision_id TEXT PRIMARY KEY
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL
        REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    blueprint_id TEXT NOT NULL CHECK(length(trim(blueprint_id)) BETWEEN 1 AND 100),
    blueprint_hash TEXT NOT NULL CHECK(
        length(blueprint_hash)=64 AND blueprint_hash NOT GLOB '*[^0-9a-f]*'
    ),
    evidence_pack_hash TEXT NOT NULL CHECK(
        length(evidence_pack_hash)=64 AND evidence_pack_hash NOT GLOB '*[^0-9a-f]*'
    ),
    question_revision_hash TEXT NOT NULL CHECK(
        length(question_revision_hash)=64 AND question_revision_hash NOT GLOB '*[^0-9a-f]*'
    ),
    node_id TEXT NOT NULL,
    spec_version INTEGER NOT NULL CHECK(spec_version >= 1),
    objective_id TEXT NOT NULL CHECK(length(trim(objective_id)) BETWEEN 1 AND 100),
    blueprint_json TEXT NOT NULL CHECK(json_valid(blueprint_json)),
    evidence_ids_json TEXT NOT NULL CHECK(
        json_valid(evidence_ids_json) AND json_type(evidence_ids_json)='array'
    ),
    author_run_json TEXT NOT NULL CHECK(json_valid(author_run_json)),
    blind_input_hash TEXT NOT NULL CHECK(
        length(blind_input_hash)=64 AND blind_input_hash NOT GLOB '*[^0-9a-f]*'
    ),
    blind_output_json TEXT NOT NULL CHECK(json_valid(blind_output_json)),
    blind_run_json TEXT NOT NULL CHECK(json_valid(blind_run_json)),
    validation_report_json TEXT NOT NULL CHECK(json_valid(validation_report_json)),
    publication_status TEXT NOT NULL
        CHECK(publication_status IN ('READY','NEEDS_REVIEW','REJECTED')),
    readiness_reason TEXT NOT NULL CHECK(length(trim(readiness_reason)) BETWEEN 1 AND 200),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(workspace_id, question_revision_hash),
    FOREIGN KEY(node_id, spec_version, objective_id)
        REFERENCES teaching_items(node_id, spec_version, item_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_question_engine_workspace_node
ON question_engine_provenance(workspace_id, node_id, spec_version, publication_status);

CREATE TRIGGER IF NOT EXISTS validate_question_engine_provenance
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
           AND question.verification_method!='MODEL_ONLY')
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

CREATE TRIGGER IF NOT EXISTS immutable_question_engine_provenance_update
BEFORE UPDATE ON question_engine_provenance
BEGIN
    SELECT RAISE(ABORT, 'Question Engine provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_question_engine_provenance_delete
BEFORE DELETE ON question_engine_provenance
BEGIN
    SELECT RAISE(ABORT, 'Question Engine provenance is immutable');
END;

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(36, 'question engine provenance');
