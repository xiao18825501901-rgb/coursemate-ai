-- CourseJesus learning-loop metadata and durable practice-submission outbox.
--
-- Existing question, source, rubric, grade, Pair, conversation and Task Agent
-- authorities remain authoritative.  These tables keep references, ordering
-- facts and immutable receipts.  The one deliberate exception is
-- practice_submission_revisions: it is the canonical answer revision that must
-- be durable before asynchronous feedback is requested.

CREATE TABLE IF NOT EXISTS learning_loop_course_flags (
    course_id TEXT PRIMARY KEY REFERENCES courses(id) ON DELETE RESTRICT,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
    enabled_by_user_id TEXT,
    enabled_at TEXT,
    history_complete_from TEXT,
    CHECK(
        (enabled=0 AND enabled_at IS NULL)
        OR (enabled=1 AND enabled_at IS NOT NULL AND enabled_by_user_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS learning_loop_actor_classifications (
    owner_user_id TEXT PRIMARY KEY,
    internal INTEGER NOT NULL DEFAULT 0 CHECK(internal IN (0,1)),
    source TEXT NOT NULL CHECK(source IN ('ADMIN_ID','TEST_ENV','OWNER_REVIEW')),
    classified_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS learning_loop_pack_revisions (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    offering_id TEXT NOT NULL CHECK(length(trim(offering_id)) BETWEEN 1 AND 200),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    source_manifest_hash TEXT NOT NULL CHECK(
        length(source_manifest_hash)=64 AND source_manifest_hash NOT GLOB '*[^0-9a-f]*'
    ),
    source_refs_json TEXT NOT NULL CHECK(
        json_valid(source_refs_json) AND json_type(source_refs_json)='array'
    ),
    rights_status TEXT NOT NULL CHECK(rights_status IN (
        'OWNER_PRIVATE','CAMPUS_AUTHORIZED','OPEN_LICENSE','UNKNOWN'
    )),
    review_status TEXT NOT NULL CHECK(review_status IN (
        'SOURCE_VERIFIED','HUMAN_REVIEWED','AI_ORGANIZED','WAITING_SOURCE','WITHDRAWN'
    )),
    status TEXT NOT NULL CHECK(status IN ('DRAFT','ACTIVE','RETIRED','WITHDRAWN')),
    created_by_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(course_id, offering_id, revision)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_learning_loop_active_pack
ON learning_loop_pack_revisions(course_id, offering_id) WHERE status='ACTIVE';

CREATE TABLE IF NOT EXISTS learning_loop_pack_targets (
    pack_revision_id TEXT NOT NULL
        REFERENCES learning_loop_pack_revisions(id) ON DELETE RESTRICT,
    node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    spec_version INTEGER NOT NULL CHECK(spec_version >= 1),
    objective_id TEXT NOT NULL CHECK(length(trim(objective_id)) BETWEEN 1 AND 100),
    terminology_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(terminology_json)),
    rubric_refs_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(rubric_refs_json)),
    intervention_refs_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(intervention_refs_json)),
    PRIMARY KEY(pack_revision_id,node_id,spec_version,objective_id),
    FOREIGN KEY(node_id,spec_version,objective_id)
        REFERENCES teaching_items(node_id,spec_version,item_id) ON DELETE RESTRICT
);

CREATE TRIGGER IF NOT EXISTS validate_learning_loop_pack_target
BEFORE INSERT ON learning_loop_pack_targets
WHEN NOT EXISTS(
    SELECT 1 FROM learning_loop_pack_revisions AS pack
    JOIN knowledge_nodes AS node ON node.id=NEW.node_id
    WHERE pack.id=NEW.pack_revision_id AND node.course_id=pack.course_id
)
BEGIN
    SELECT RAISE(ABORT,'Learning-loop pack target does not match its course');
END;

CREATE TABLE IF NOT EXISTS learning_loop_cycles (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    offering_id TEXT NOT NULL,
    pair_ref TEXT NOT NULL CHECK(length(trim(pair_ref)) BETWEEN 1 AND 200),
    node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE RESTRICT,
    spec_version INTEGER NOT NULL CHECK(spec_version >= 1),
    objective_id TEXT NOT NULL CHECK(length(trim(objective_id)) BETWEEN 1 AND 100),
    pack_revision_id TEXT NOT NULL
        REFERENCES learning_loop_pack_revisions(id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK(state IN (
        'STARTED','DIAGNOSING','DIRECT_PRACTICE','PRACTICING',
        'SAVED_AWAITING_EVALUATION','INTERVENTION_DELIVERED','TRANSFER_READY',
        'COMPLETED','PAUSED'
    )),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    diagnostic_status TEXT NOT NULL DEFAULT 'NOT_STARTED' CHECK(diagnostic_status IN (
        'NOT_STARTED','AVAILABLE','COMPLETED','SKIPPED'
    )),
    diagnostic_questions_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(diagnostic_questions_json)),
    diagnostic_responses_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(diagnostic_responses_json)),
    internal INTEGER NOT NULL DEFAULT 0 CHECK(internal IN (0,1)),
    history_complete INTEGER NOT NULL DEFAULT 0 CHECK(history_complete IN (0,1)),
    completion_submission_ref TEXT,
    closure_initial_submission_ref TEXT,
    closure_feedback_ref TEXT,
    started_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    completed_at TEXT,
    FOREIGN KEY(node_id,spec_version,objective_id)
        REFERENCES teaching_items(node_id,spec_version,item_id) ON DELETE RESTRICT,
    CHECK(completed_at IS NULL OR state='COMPLETED')
);

CREATE INDEX IF NOT EXISTS idx_learning_loop_cycles_owner
ON learning_loop_cycles(owner_user_id,course_id,started_at);

CREATE TABLE IF NOT EXISTS learning_loop_commands (
    owner_user_id TEXT NOT NULL,
    operation_id TEXT NOT NULL CHECK(length(trim(operation_id)) BETWEEN 8 AND 120),
    action TEXT NOT NULL CHECK(length(trim(action)) BETWEEN 1 AND 100),
    input_hash TEXT NOT NULL CHECK(
        length(input_hash)=64 AND input_hash NOT GLOB '*[^0-9a-f]*'
    ),
    result_json TEXT NOT NULL CHECK(json_valid(result_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(owner_user_id,operation_id)
);

CREATE TABLE IF NOT EXISTS learning_loop_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    owner_user_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    cycle_id TEXT REFERENCES learning_loop_cycles(id) ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK(length(trim(kind)) BETWEEN 1 AND 100),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_learning_loop_events_cycle
ON learning_loop_events(cycle_id,sequence);

CREATE TABLE IF NOT EXISTS learning_loop_assignments (
    id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL REFERENCES learning_loop_cycles(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    question_revision_id TEXT NOT NULL
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    family_id TEXT NOT NULL,
    question_content_hash TEXT NOT NULL CHECK(length(question_content_hash)=64),
    family_evidence_ref TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK(purpose IN ('INITIAL','DIAGNOSTIC','TRANSFER','RECHECK')),
    assigned_sequence INTEGER NOT NULL REFERENCES learning_loop_events(sequence),
    history_complete INTEGER NOT NULL CHECK(history_complete IN (0,1)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(cycle_id,question_revision_id,purpose)
);

CREATE INDEX IF NOT EXISTS idx_learning_loop_assignment_cycle
ON learning_loop_assignments(cycle_id,assigned_sequence);

CREATE TABLE IF NOT EXISTS learning_loop_exposures (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    owner_user_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    question_revision_id TEXT NOT NULL
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    family_id TEXT NOT NULL,
    question_content_hash TEXT NOT NULL CHECK(length(question_content_hash)=64),
    kind TEXT NOT NULL CHECK(kind IN (
        'STEM','HINT_REQUEST','HINT','DETAIL','SOLUTION','TARGETED_TEACHING'
    )),
    channel TEXT NOT NULL CHECK(channel IN (
        'QUESTION','TEACHING_PANE','PROBLEM_PANE','DETAIL_WINDOW','HISTORY','AUTHORIZED_SHARE'
    )),
    assignment_id TEXT REFERENCES learning_loop_assignments(id) ON DELETE RESTRICT,
    ordering TEXT NOT NULL CHECK(ordering IN ('SERVER_ORDERED','LATE_UNORDERED')),
    receipt TEXT NOT NULL CHECK(length(trim(receipt)) BETWEEN 1 AND 300),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(owner_user_id,receipt)
);

CREATE INDEX IF NOT EXISTS idx_learning_loop_exposure_novelty
ON learning_loop_exposures(owner_user_id,workspace_id,family_id,sequence);

CREATE TABLE IF NOT EXISTS practice_submission_revisions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES learning_workspaces(id) ON DELETE RESTRICT,
    question_revision_id TEXT NOT NULL
        REFERENCES assessment_question_revisions(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    answer_revision INTEGER NOT NULL DEFAULT 1 CHECK(answer_revision >= 1),
    submitted_answer TEXT NOT NULL CHECK(length(trim(submitted_answer)) BETWEEN 1 AND 6000),
    answer_hash TEXT NOT NULL CHECK(
        length(answer_hash)=64 AND answer_hash NOT GLOB '*[^0-9a-f]*'
    ),
    rubric_revision TEXT NOT NULL CHECK(length(trim(rubric_revision)) BETWEEN 1 AND 100),
    assistance TEXT NOT NULL CHECK(assistance IN ('NONE','HINT','ANSWER_REVEALED','UNKNOWN')),
    exposure_sequence INTEGER NOT NULL CHECK(exposure_sequence >= 0),
    substantive INTEGER NOT NULL CHECK(substantive IN (0,1)),
    transcription_confirmed INTEGER NOT NULL DEFAULT 1 CHECK(transcription_confirmed IN (0,1)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(workspace_id,operation_id),
    FOREIGN KEY(workspace_id,operation_id)
        REFERENCES practice_interaction_operations(workspace_id,operation_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS practice_evaluation_jobs (
    submission_id TEXT PRIMARY KEY
        REFERENCES practice_submission_revisions(id) ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','COMPLETED','FAILED','UNKNOWN')),
    lease_owner TEXT,
    lease_expires_at TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(workspace_id,operation_id)
        REFERENCES practice_interaction_operations(workspace_id,operation_id) ON DELETE RESTRICT,
    CHECK(
        (status='RUNNING' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR status!='RUNNING'
    )
);

CREATE INDEX IF NOT EXISTS idx_practice_evaluation_jobs_status
ON practice_evaluation_jobs(status,updated_at);

CREATE TABLE IF NOT EXISTS learning_loop_submission_links (
    id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL REFERENCES learning_loop_cycles(id) ON DELETE RESTRICT,
    assignment_id TEXT NOT NULL REFERENCES learning_loop_assignments(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    canonical_submission_id TEXT NOT NULL UNIQUE
        REFERENCES practice_submission_revisions(id) ON DELETE RESTRICT,
    frozen_exposure_sequence INTEGER NOT NULL CHECK(frozen_exposure_sequence >= 0),
    independent_at_submission INTEGER NOT NULL CHECK(independent_at_submission IN (0,1)),
    eligibility_reasons_json TEXT NOT NULL CHECK(json_valid(eligibility_reasons_json)),
    saved_sequence INTEGER NOT NULL REFERENCES learning_loop_events(sequence),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS learning_loop_evaluation_links (
    id TEXT PRIMARY KEY,
    submission_link_id TEXT NOT NULL
        REFERENCES learning_loop_submission_links(id) ON DELETE RESTRICT,
    canonical_evaluation_id TEXT NOT NULL UNIQUE
        REFERENCES practice_question_attempts(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('CORRECT','PARTIAL','INCORRECT','NEEDS_REVIEW')),
    status TEXT NOT NULL CHECK(status IN ('VALID','NEEDS_REVIEW')),
    evaluation_sequence INTEGER NOT NULL REFERENCES learning_loop_events(sequence),
    supersedes_id TEXT REFERENCES learning_loop_evaluation_links(id) ON DELETE RESTRICT,
    correction_ref TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS learning_loop_feedback_deliveries (
    id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL REFERENCES learning_loop_cycles(id) ON DELETE RESTRICT,
    submission_link_id TEXT NOT NULL
        REFERENCES learning_loop_submission_links(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    canonical_feedback_ref TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    diagnosis_ref TEXT,
    delivered_sequence INTEGER NOT NULL REFERENCES learning_loop_events(sequence),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(owner_user_id,canonical_feedback_ref)
);

CREATE TABLE IF NOT EXISTS learning_loop_diagnosis_candidates (
    id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL REFERENCES learning_loop_cycles(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    submission_link_id TEXT NOT NULL
        REFERENCES learning_loop_submission_links(id) ON DELETE RESTRICT,
    answer_span_hash TEXT NOT NULL CHECK(length(answer_span_hash)=64),
    criterion_ref TEXT NOT NULL,
    source_rule_ref TEXT NOT NULL,
    alternative_refs_json TEXT NOT NULL CHECK(json_valid(alternative_refs_json)),
    proof_receipt_ref TEXT,
    status TEXT NOT NULL CHECK(status IN ('CANDIDATE','SUPPORTED','NEEDS_REVIEW','WITHDRAWN')),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS learning_loop_interventions (
    id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL REFERENCES learning_loop_cycles(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    diagnosis_id TEXT REFERENCES learning_loop_diagnosis_candidates(id) ON DELETE RESTRICT,
    strategy_version TEXT NOT NULL,
    delivery_ref TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS learning_loop_followups (
    id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL REFERENCES learning_loop_cycles(id) ON DELETE RESTRICT,
    owner_user_id TEXT NOT NULL,
    due_at TEXT NOT NULL,
    timezone TEXT NOT NULL,
    consent_revision INTEGER NOT NULL DEFAULT 1 CHECK(consent_revision >= 1),
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'PENDING','CREATING','BOUND','CANCELLED','UNKNOWN','RECONFIRMATION_REQUIRED'
    )),
    task_ref TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(owner_user_id,idempotency_key)
);

CREATE TABLE IF NOT EXISTS learning_loop_corrections (
    id TEXT PRIMARY KEY,
    actor_user_id TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    reason_ref TEXT NOT NULL,
    affected_refs_json TEXT NOT NULL CHECK(json_valid(affected_refs_json)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS learning_loop_reliability_facts (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    cycle_id TEXT REFERENCES learning_loop_cycles(id) ON DELETE RESTRICT,
    operation_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK(stage IN (
        'FIRST_RENDER','SAVE','GRADE','SOURCE','RECOVERY','TASK_AGENT'
    )),
    status TEXT NOT NULL CHECK(status IN (
        'STARTED','SUCCEEDED','FAILED','IN_FLIGHT','CANCELLED','UNKNOWN'
    )),
    latency_ms INTEGER CHECK(latency_ms IS NULL OR latency_ms >= 0),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(operation_id,stage,status)
);

CREATE TRIGGER IF NOT EXISTS immutable_learning_loop_assignment_update
BEFORE UPDATE ON learning_loop_assignments BEGIN
    SELECT RAISE(ABORT,'Learning-loop assignments are immutable');
END;
CREATE TRIGGER IF NOT EXISTS immutable_learning_loop_assignment_delete
BEFORE DELETE ON learning_loop_assignments BEGIN
    SELECT RAISE(ABORT,'Learning-loop assignments are immutable');
END;
CREATE TRIGGER IF NOT EXISTS immutable_learning_loop_exposure_update
BEFORE UPDATE ON learning_loop_exposures BEGIN
    SELECT RAISE(ABORT,'Learning-loop exposures are immutable');
END;
CREATE TRIGGER IF NOT EXISTS immutable_learning_loop_exposure_delete
BEFORE DELETE ON learning_loop_exposures BEGIN
    SELECT RAISE(ABORT,'Learning-loop exposures are immutable');
END;
CREATE TRIGGER IF NOT EXISTS immutable_practice_submission_update
BEFORE UPDATE ON practice_submission_revisions BEGIN
    SELECT RAISE(ABORT,'Practice submission revisions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS immutable_practice_submission_delete
BEFORE DELETE ON practice_submission_revisions BEGIN
    SELECT RAISE(ABORT,'Practice submission revisions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS immutable_learning_loop_submission_link_update
BEFORE UPDATE ON learning_loop_submission_links BEGIN
    SELECT RAISE(ABORT,'Learning-loop submission links are immutable');
END;
CREATE TRIGGER IF NOT EXISTS immutable_learning_loop_submission_link_delete
BEFORE DELETE ON learning_loop_submission_links BEGIN
    SELECT RAISE(ABORT,'Learning-loop submission links are immutable');
END;
CREATE TRIGGER IF NOT EXISTS immutable_learning_loop_evaluation_link_update
BEFORE UPDATE ON learning_loop_evaluation_links BEGIN
    SELECT RAISE(ABORT,'Learning-loop evaluation links are immutable');
END;
CREATE TRIGGER IF NOT EXISTS immutable_learning_loop_evaluation_link_delete
BEFORE DELETE ON learning_loop_evaluation_links BEGIN
    SELECT RAISE(ABORT,'Learning-loop evaluation links are immutable');
END;
CREATE TRIGGER IF NOT EXISTS immutable_learning_loop_feedback_update
BEFORE UPDATE ON learning_loop_feedback_deliveries BEGIN
    SELECT RAISE(ABORT,'Learning-loop feedback deliveries are immutable');
END;
CREATE TRIGGER IF NOT EXISTS immutable_learning_loop_feedback_delete
BEFORE DELETE ON learning_loop_feedback_deliveries BEGIN
    SELECT RAISE(ABORT,'Learning-loop feedback deliveries are immutable');
END;
CREATE TRIGGER IF NOT EXISTS immutable_learning_loop_correction_update
BEFORE UPDATE ON learning_loop_corrections BEGIN
    SELECT RAISE(ABORT,'Learning-loop corrections are immutable');
END;
CREATE TRIGGER IF NOT EXISTS immutable_learning_loop_correction_delete
BEFORE DELETE ON learning_loop_corrections BEGIN
    SELECT RAISE(ABORT,'Learning-loop corrections are immutable');
END;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(60,'learning loop evidence ordering async practice and followups');
