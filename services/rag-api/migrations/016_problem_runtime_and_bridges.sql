-- Stage 4 is additive. Legacy problem JSON is retained and explicitly labelled instead
-- of being silently promoted to the normalized, server-validated runtime contract.

CREATE TABLE IF NOT EXISTS problem_index_entries (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    document_version_id TEXT NOT NULL
        REFERENCES document_versions(id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL UNIQUE REFERENCES chunks(id) ON DELETE CASCADE,
    question_number TEXT NOT NULL CHECK(length(trim(question_number)) BETWEEN 1 AND 40),
    question_part TEXT CHECK(
        question_part IS NULL OR length(trim(question_part)) BETWEEN 1 AND 40
    ),
    heading_path TEXT,
    parent_key TEXT,
    locator_type TEXT NOT NULL CHECK(length(trim(locator_type)) > 0),
    locator_value TEXT NOT NULL CHECK(length(trim(locator_value)) > 0),
    question_text TEXT NOT NULL CHECK(length(trim(question_text)) > 0),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_problem_index_lookup
ON problem_index_entries(
    course_id, document_version_id, question_number, question_part, locator_type,
    locator_value
);

INSERT OR IGNORE INTO problem_index_entries(
    id, course_id, document_version_id, chunk_id, question_number, question_part,
    heading_path, parent_key, locator_type, locator_value, question_text, created_at
)
SELECT
    'pqi_' || chunks.id,
    chunks.course_id,
    chunk_source_versions.document_version_id,
    chunks.id,
    json_extract(chunks.metadata_json, '$.question_number'),
    json_extract(chunks.metadata_json, '$.question_part'),
    json_extract(chunks.metadata_json, '$.heading_path'),
    chunks.parent_key,
    chunks.locator_type,
    chunks.locator_value,
    chunks.content,
    chunks.created_at
FROM chunks
JOIN chunk_source_versions ON chunk_source_versions.chunk_id = chunks.id
WHERE json_type(chunks.metadata_json, '$.question_number') = 'text'
  AND length(trim(json_extract(chunks.metadata_json, '$.question_number'))) > 0;

CREATE TRIGGER IF NOT EXISTS index_structured_problem_chunk
AFTER INSERT ON chunks
WHEN json_type(NEW.metadata_json, '$.question_number') = 'text'
 AND length(trim(json_extract(NEW.metadata_json, '$.question_number'))) > 0
BEGIN
    INSERT OR IGNORE INTO problem_index_entries(
        id, course_id, document_version_id, chunk_id, question_number, question_part,
        heading_path, parent_key, locator_type, locator_value, question_text, created_at
    )
    SELECT
        'pqi_' || NEW.id,
        NEW.course_id,
        document_versions.id,
        NEW.id,
        json_extract(NEW.metadata_json, '$.question_number'),
        json_extract(NEW.metadata_json, '$.question_part'),
        json_extract(NEW.metadata_json, '$.heading_path'),
        NEW.parent_key,
        NEW.locator_type,
        NEW.locator_value,
        NEW.content,
        NEW.created_at
    FROM document_versions
    WHERE document_versions.document_id = NEW.document_id
    ORDER BY document_versions.version DESC
    LIMIT 1;
END;

CREATE TABLE IF NOT EXISTS problem_revisions (
    id TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    input_kind TEXT NOT NULL CHECK(input_kind IN ('TEXT','INDEXED','IMAGE')),
    question_text TEXT NOT NULL CHECK(length(trim(question_text)) > 0),
    question_transcription TEXT,
    transcription_status TEXT NOT NULL CHECK(transcription_status IN (
        'NOT_APPLICABLE','USER_HINT','MODEL_PROPOSED','UNCERTAIN'
    )),
    visual_uncertainties_json TEXT NOT NULL DEFAULT '[]'
        CHECK(json_valid(visual_uncertainties_json)),
    problem_index_entry_id TEXT
        REFERENCES problem_index_entries(id) ON DELETE SET NULL,
    input_document_version_id TEXT
        REFERENCES document_versions(id) ON DELETE SET NULL,
    input_source_sha256 TEXT CHECK(
        input_source_sha256 IS NULL OR
        (length(input_source_sha256) = 64
         AND input_source_sha256 NOT GLOB '*[^0-9a-f]*')
    ),
    source_locator_json TEXT NOT NULL DEFAULT '{}'
        CHECK(json_valid(source_locator_json)),
    content_hash TEXT CHECK(
        content_hash IS NULL OR
        (length(content_hash) = 64 AND content_hash NOT GLOB '*[^0-9a-f]*')
    ),
    validation_status TEXT NOT NULL
        CHECK(validation_status IN ('VALIDATED','LEGACY_PRESERVED')),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(problem_id, revision),
    FOREIGN KEY(problem_id, workspace_id)
        REFERENCES learning_problems(id, workspace_id) ON DELETE RESTRICT,
    CHECK(
        (validation_status = 'VALIDATED' AND content_hash IS NOT NULL)
        OR (validation_status = 'LEGACY_PRESERVED' AND content_hash IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_problem_revisions_workspace
ON problem_revisions(workspace_id, created_at, problem_id, revision);

CREATE TRIGGER IF NOT EXISTS immutable_problem_revisions_update
BEFORE UPDATE OF id, problem_id, workspace_id, revision, input_kind, question_text,
    question_transcription, transcription_status, visual_uncertainties_json,
    input_source_sha256, source_locator_json, content_hash, validation_status,
    created_at
ON problem_revisions
BEGIN
    SELECT RAISE(ABORT, 'Problem revisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS revoke_problem_revision_source_only
BEFORE UPDATE OF problem_index_entry_id, input_document_version_id
ON problem_revisions
WHEN NOT (
    (NEW.problem_index_entry_id IS OLD.problem_index_entry_id
     OR (OLD.problem_index_entry_id IS NOT NULL AND NEW.problem_index_entry_id IS NULL))
    AND
    (NEW.input_document_version_id IS OLD.input_document_version_id
     OR (OLD.input_document_version_id IS NOT NULL
         AND NEW.input_document_version_id IS NULL))
)
BEGIN
    SELECT RAISE(ABORT, 'Problem source identity may only be revoked');
END;

CREATE TRIGGER IF NOT EXISTS immutable_problem_revisions_delete
BEFORE DELETE ON problem_revisions
BEGIN
    SELECT RAISE(ABORT, 'Problem revisions are immutable');
END;

CREATE TABLE IF NOT EXISTS problem_attempts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    problem_revision_id TEXT NOT NULL REFERENCES problem_revisions(id) ON DELETE RESTRICT,
    assistance TEXT NOT NULL CHECK(assistance IN ('ANSWER_EXPOSED','ASSESSMENT_HIDDEN')),
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK(status IN ('ACTIVE','COMPLETED','CANCELLED')),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(workspace_id, problem_revision_id, id)
);

CREATE TRIGGER IF NOT EXISTS validate_problem_attempt_workspace
BEFORE INSERT ON problem_attempts
WHEN NOT EXISTS(
    SELECT 1 FROM problem_revisions
    WHERE problem_revisions.id = NEW.problem_revision_id
      AND problem_revisions.workspace_id = NEW.workspace_id
)
BEGIN
    SELECT RAISE(ABORT, 'Problem attempt does not match its private workspace');
END;

CREATE TABLE IF NOT EXISTS solution_revisions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    solution_id TEXT NOT NULL REFERENCES learning_solutions(id) ON DELETE RESTRICT,
    problem_revision_id TEXT NOT NULL REFERENCES problem_revisions(id) ON DELETE RESTRICT,
    attempt_id TEXT NOT NULL REFERENCES problem_attempts(id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    answer_origin TEXT NOT NULL CHECK(answer_origin IN (
        'OFFICIAL','INDEPENDENTLY_VERIFIED_MODEL','MODEL_PROPOSED'
    )),
    verification TEXT NOT NULL CHECK(verification IN (
        'OFFICIAL','INDEPENDENTLY_VERIFIED','NOT_INDEPENDENTLY_VERIFIED'
    )),
    content_hash TEXT CHECK(
        content_hash IS NULL OR
        (length(content_hash) = 64 AND content_hash NOT GLOB '*[^0-9a-f]*')
    ),
    validation_status TEXT NOT NULL
        CHECK(validation_status IN ('VALIDATED','LEGACY_PRESERVED')),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(solution_id, revision),
    CHECK(
        (validation_status = 'VALIDATED' AND content_hash IS NOT NULL)
        OR (validation_status = 'LEGACY_PRESERVED' AND content_hash IS NULL)
    )
);

CREATE TRIGGER IF NOT EXISTS validate_solution_revision_context
BEFORE INSERT ON solution_revisions
WHEN NOT EXISTS(
    SELECT 1
    FROM learning_solutions AS solution
    JOIN learning_problems AS problem ON problem.id = solution.problem_id
    JOIN problem_revisions AS problem_revision
      ON problem_revision.problem_id = problem.id
     AND problem_revision.workspace_id = problem.workspace_id
    JOIN problem_attempts AS attempt
      ON attempt.problem_revision_id = problem_revision.id
     AND attempt.workspace_id = problem.workspace_id
    WHERE solution.id = NEW.solution_id
      AND problem.workspace_id = NEW.workspace_id
      AND problem_revision.id = NEW.problem_revision_id
      AND attempt.id = NEW.attempt_id
)
BEGIN
    SELECT RAISE(ABORT, 'Solution revision does not match its problem attempt');
END;

CREATE TRIGGER IF NOT EXISTS immutable_solution_revisions_update
BEFORE UPDATE ON solution_revisions
BEGIN
    SELECT RAISE(ABORT, 'Solution revisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_solution_revisions_delete
BEFORE DELETE ON solution_revisions
BEGIN
    SELECT RAISE(ABORT, 'Solution revisions are immutable');
END;

CREATE TABLE IF NOT EXISTS step_knowledge_links (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    solution_revision_id TEXT NOT NULL REFERENCES solution_revisions(id) ON DELETE RESTRICT,
    step_id TEXT NOT NULL REFERENCES learning_steps(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 1),
    resolution_status TEXT NOT NULL
        CHECK(resolution_status IN ('VALIDATED','UNRESOLVED','LEGACY_PRESERVED')),
    node_id TEXT REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    spec_version INTEGER,
    item_id TEXT,
    question_text TEXT NOT NULL CHECK(length(trim(question_text)) > 0),
    reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
    unresolved_reason TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(step_id, ordinal),
    UNIQUE(step_id, node_id),
    FOREIGN KEY(node_id, spec_version, item_id)
        REFERENCES teaching_items(node_id, spec_version, item_id) ON DELETE RESTRICT,
    CHECK(
        (resolution_status = 'VALIDATED'
         AND node_id IS NOT NULL AND spec_version IS NOT NULL AND item_id IS NOT NULL
         AND unresolved_reason IS NULL)
        OR
        (resolution_status = 'UNRESOLVED'
         AND node_id IS NULL AND spec_version IS NULL AND item_id IS NULL
         AND unresolved_reason IS NOT NULL)
        OR
        (resolution_status = 'LEGACY_PRESERVED'
         AND node_id IS NOT NULL AND spec_version IS NULL AND item_id IS NULL
         AND unresolved_reason IS NOT NULL)
    )
);

CREATE TRIGGER IF NOT EXISTS validate_step_knowledge_link_context
BEFORE INSERT ON step_knowledge_links
WHEN NOT EXISTS(
    SELECT 1
    FROM solution_revisions AS revision
    JOIN learning_steps AS step ON step.solution_id = revision.solution_id
    WHERE revision.id = NEW.solution_revision_id
      AND revision.workspace_id = NEW.workspace_id
      AND step.id = NEW.step_id
)
OR (
    NEW.resolution_status = 'VALIDATED' AND NOT EXISTS(
        SELECT 1
        FROM learning_workspaces AS workspace
        JOIN knowledge_nodes AS node
          ON node.course_id = workspace.course_id
         AND node.id = NEW.node_id
         AND node.kind = 'ATOMIC'
        JOIN teaching_spec_metadata AS spec
          ON spec.node_id = node.id
         AND spec.version = NEW.spec_version
        WHERE workspace.id = NEW.workspace_id
          AND (
            (node.owner_user_id = workspace.owner_user_id
             AND node.status = 'PRIVATE' AND spec.status = 'PRIVATE_ACTIVE')
            OR
            (node.owner_user_id IS NULL
             AND node.status = 'PUBLISHED' AND spec.status = 'PUBLISHED')
          )
    )
)
BEGIN
    SELECT RAISE(ABORT, 'Step knowledge link is not authorized for this workspace');
END;

CREATE TRIGGER IF NOT EXISTS immutable_step_knowledge_links_update
BEFORE UPDATE ON step_knowledge_links
BEGIN
    SELECT RAISE(ABORT, 'Step knowledge links are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_step_knowledge_links_delete
BEFORE DELETE ON step_knowledge_links
BEGIN
    SELECT RAISE(ABORT, 'Step knowledge links are immutable');
END;

CREATE TABLE IF NOT EXISTS learning_bridge_contexts (
    bridge_id TEXT PRIMARY KEY REFERENCES learning_bridges(id) ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    problem_revision_id TEXT NOT NULL REFERENCES problem_revisions(id) ON DELETE RESTRICT,
    attempt_id TEXT NOT NULL REFERENCES problem_attempts(id) ON DELETE RESTRICT,
    solution_revision_id TEXT NOT NULL REFERENCES solution_revisions(id) ON DELETE RESTRICT,
    source_step_id TEXT NOT NULL REFERENCES learning_steps(id) ON DELETE RESTRICT,
    knowledge_link_id TEXT REFERENCES step_knowledge_links(id) ON DELETE RESTRICT,
    knowledge_node_ids_json TEXT NOT NULL CHECK(
        json_valid(knowledge_node_ids_json)
        AND json_array_length(knowledge_node_ids_json) >= 1
    ),
    node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    spec_version INTEGER,
    item_id TEXT,
    reason_for_learning TEXT NOT NULL CHECK(length(trim(reason_for_learning)) > 0),
    selected_question TEXT NOT NULL CHECK(length(trim(selected_question)) > 0),
    target_learning_session TEXT NOT NULL
        REFERENCES learning_journeys(id) ON DELETE RESTRICT,
    return_problem_id TEXT NOT NULL REFERENCES learning_problems(id) ON DELETE RESTRICT,
    return_step_id TEXT NOT NULL REFERENCES learning_steps(id) ON DELETE RESTRICT,
    return_anchor TEXT NOT NULL CHECK(length(trim(return_anchor)) > 0),
    idempotency_key TEXT NOT NULL CHECK(length(trim(idempotency_key)) > 0),
    validation_status TEXT NOT NULL
        CHECK(validation_status IN ('VALIDATED','LEGACY_PRESERVED')),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(workspace_id, knowledge_link_id),
    UNIQUE(workspace_id, idempotency_key),
    FOREIGN KEY(node_id, spec_version, item_id)
        REFERENCES teaching_items(node_id, spec_version, item_id) ON DELETE RESTRICT,
    CHECK(
        (validation_status = 'VALIDATED'
         AND knowledge_link_id IS NOT NULL
         AND spec_version IS NOT NULL AND item_id IS NOT NULL)
        OR
        (validation_status = 'LEGACY_PRESERVED'
         AND spec_version IS NULL AND item_id IS NULL)
    )
);

CREATE TRIGGER IF NOT EXISTS validate_learning_bridge_context
BEFORE INSERT ON learning_bridge_contexts
WHEN NEW.validation_status = 'VALIDATED' AND NOT EXISTS(
    SELECT 1
    FROM learning_bridges AS bridge
    JOIN learning_workspaces AS workspace ON workspace.id = bridge.workspace_id
    JOIN step_knowledge_links AS link ON link.id = NEW.knowledge_link_id
    JOIN solution_revisions AS solution_revision
      ON solution_revision.id = link.solution_revision_id
    JOIN problem_revisions AS problem_revision
      ON problem_revision.id = solution_revision.problem_revision_id
    JOIN problem_attempts AS attempt ON attempt.id = solution_revision.attempt_id
    WHERE bridge.id = NEW.bridge_id
      AND bridge.workspace_id = NEW.workspace_id
      AND workspace.owner_user_id = NEW.owner_user_id
      AND workspace.course_id = NEW.course_id
      AND link.workspace_id = NEW.workspace_id
      AND link.step_id = NEW.source_step_id
      AND link.node_id = NEW.node_id
      AND link.spec_version = NEW.spec_version
      AND link.item_id = NEW.item_id
      AND link.question_text = NEW.selected_question
      AND link.reason = NEW.reason_for_learning
      AND solution_revision.id = NEW.solution_revision_id
      AND solution_revision.workspace_id = NEW.workspace_id
      AND problem_revision.id = NEW.problem_revision_id
      AND problem_revision.workspace_id = NEW.workspace_id
      AND attempt.id = NEW.attempt_id
      AND attempt.workspace_id = NEW.workspace_id
      AND bridge.step_id = NEW.source_step_id
      AND bridge.node_id = NEW.node_id
      AND bridge.journey_id = NEW.target_learning_session
      AND problem_revision.problem_id = NEW.return_problem_id
      AND NEW.return_step_id = NEW.source_step_id
)
BEGIN
    SELECT RAISE(ABORT, 'LearningBridge context does not match its authorized revisions');
END;

CREATE TRIGGER IF NOT EXISTS immutable_learning_bridge_context
BEFORE UPDATE OF bridge_id, workspace_id, owner_user_id, course_id,
    problem_revision_id, attempt_id, solution_revision_id, source_step_id,
    knowledge_link_id, knowledge_node_ids_json, node_id, spec_version, item_id,
    reason_for_learning, selected_question, target_learning_session,
    return_problem_id, return_step_id, return_anchor, idempotency_key,
    validation_status, created_at
ON learning_bridge_contexts
BEGIN
    SELECT RAISE(ABORT, 'LearningBridge context identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS touch_learning_bridge_context_status
AFTER UPDATE OF status ON learning_bridges
BEGIN
    UPDATE learning_bridge_contexts
    SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
    WHERE bridge_id = NEW.id;
END;

INSERT OR IGNORE INTO problem_revisions(
    id, problem_id, workspace_id, revision, input_kind, question_text,
    question_transcription, transcription_status, visual_uncertainties_json,
    problem_index_entry_id, input_document_version_id, input_source_sha256,
    source_locator_json, content_hash, validation_status
)
SELECT
    'pr_' || id, id, workspace_id, version, 'TEXT', question, NULL,
    'NOT_APPLICABLE', '[]', NULL, NULL, NULL, '{}', NULL, 'LEGACY_PRESERVED'
FROM learning_problems;

INSERT OR IGNORE INTO problem_attempts(
    id, workspace_id, problem_revision_id, assistance
)
SELECT
    problem.attempt_id,
    problem.workspace_id,
    problem_revision.id,
    problem.assistance
FROM learning_problems AS problem
JOIN problem_revisions AS problem_revision
  ON problem_revision.problem_id = problem.id
 AND problem_revision.revision = problem.version;

INSERT OR IGNORE INTO solution_revisions(
    id, workspace_id, solution_id, problem_revision_id, attempt_id, revision,
    answer_origin, verification, content_hash, validation_status
)
SELECT
    'sr_' || solution.id,
    problem.workspace_id,
    solution.id,
    problem_revision.id,
    problem.attempt_id,
    solution.version,
    COALESCE(json_extract(solution.content_json, '$.answer_origin'), 'MODEL_PROPOSED'),
    COALESCE(
        json_extract(solution.content_json, '$.verification'),
        'NOT_INDEPENDENTLY_VERIFIED'
    ),
    NULL,
    'LEGACY_PRESERVED'
FROM learning_solutions AS solution
JOIN learning_problems AS problem ON problem.id = solution.problem_id
JOIN problem_revisions AS problem_revision
  ON problem_revision.problem_id = problem.id
 AND problem_revision.revision = problem.version;

INSERT OR IGNORE INTO step_knowledge_links(
    id, workspace_id, solution_revision_id, step_id, ordinal,
    resolution_status, node_id, spec_version, item_id, question_text, reason,
    unresolved_reason
)
SELECT
    'skl_' || step.id || '_' || link.key,
    problem.workspace_id,
    solution_revision.id,
    step.id,
    CAST(link.key AS INTEGER) + 1,
    'LEGACY_PRESERVED',
    json_extract(link.value, '$.node_id'),
    NULL,
    NULL,
    json_extract(link.value, '$.question_text'),
    json_extract(link.value, '$.reason'),
    'MIGRATION_016_MISSING_TEACHING_ITEM_ID'
FROM learning_steps AS step
JOIN learning_solutions AS solution ON solution.id = step.solution_id
JOIN learning_problems AS problem ON problem.id = solution.problem_id
JOIN solution_revisions AS solution_revision
  ON solution_revision.solution_id = solution.id
 AND solution_revision.revision = solution.version,
json_each(json_extract(step.content_json, '$.knowledge_links')) AS link
WHERE json_type(link.value, '$.node_id') = 'text'
  AND json_type(link.value, '$.question_text') = 'text'
  AND json_type(link.value, '$.reason') = 'text';

INSERT OR IGNORE INTO learning_bridge_contexts(
    bridge_id, workspace_id, owner_user_id, course_id, problem_revision_id,
    attempt_id, solution_revision_id, source_step_id, knowledge_link_id,
    knowledge_node_ids_json, node_id, spec_version, item_id,
    reason_for_learning, selected_question, target_learning_session,
    return_problem_id, return_step_id, return_anchor, idempotency_key,
    validation_status
)
SELECT
    bridge.id,
    bridge.workspace_id,
    workspace.owner_user_id,
    workspace.course_id,
    problem_revision.id,
    problem.attempt_id,
    solution_revision.id,
    bridge.step_id,
    link.id,
    json_array(bridge.node_id),
    bridge.node_id,
    NULL,
    NULL,
    COALESCE(
        json_extract(bridge.snapshot_json, '$.reason_for_learning'),
        'Legacy LearningBridge reason'
    ),
    COALESCE(link.question_text, 'Legacy knowledge question'),
    bridge.journey_id,
    problem.id,
    bridge.step_id,
    COALESCE(
        json_extract(bridge.snapshot_json, '$.return_anchor'),
        'step-' || bridge.step_id
    ),
    bridge.id,
    'LEGACY_PRESERVED'
FROM learning_bridges AS bridge
JOIN learning_workspaces AS workspace ON workspace.id = bridge.workspace_id
JOIN learning_steps AS step ON step.id = bridge.step_id
JOIN learning_solutions AS solution ON solution.id = step.solution_id
JOIN learning_problems AS problem ON problem.id = solution.problem_id
JOIN problem_revisions AS problem_revision
  ON problem_revision.problem_id = problem.id
 AND problem_revision.revision = problem.version
JOIN solution_revisions AS solution_revision
  ON solution_revision.solution_id = solution.id
 AND solution_revision.revision = solution.version
LEFT JOIN step_knowledge_links AS link
  ON link.step_id = bridge.step_id AND link.node_id = bridge.node_id;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(16,'problem index revisions step knowledge links and LearningBridge contexts');
