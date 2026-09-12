-- Grade mapping is independent from Assessment raw score. The requirements seed is
-- intentionally incomplete and must never be presented as an institutional policy.

CREATE TABLE IF NOT EXISTS grade_policy_versions (
    id TEXT PRIMARY KEY,
    scope_type TEXT NOT NULL CHECK(scope_type IN ('PLATFORM','COURSE','NODE')),
    scope_id TEXT NOT NULL CHECK(length(trim(scope_id)) BETWEEN 1 AND 100),
    version INTEGER NOT NULL CHECK(version >= 1),
    status TEXT NOT NULL CHECK(status IN (
        'DRAFT_UNCONFIGURED','DRAFT_VALID','PUBLISHED','RETIRED'
    )),
    display_name TEXT NOT NULL CHECK(length(trim(display_name)) BETWEEN 1 AND 200),
    provenance_label TEXT NOT NULL
        CHECK(length(trim(provenance_label)) BETWEEN 1 AND 500),
    numeric_scale_json TEXT NOT NULL CHECK(
        json_valid(numeric_scale_json) AND json_type(numeric_scale_json)='array'
    ),
    raw_score_bands_json TEXT NOT NULL CHECK(
        json_valid(raw_score_bands_json) AND json_type(raw_score_bands_json)='array'
    ),
    rounding_rule TEXT CHECK(
        rounding_rule IS NULL OR rounding_rule IN ('NEAREST_INTEGER','FLOOR','CEILING')
    ),
    pass_rule TEXT,
    retake_rule TEXT,
    content_hash TEXT NOT NULL CHECK(
        length(content_hash)=64 AND content_hash NOT GLOB '*[^0-9a-f]*'
    ),
    created_by_user_id TEXT NOT NULL,
    supersedes_policy_id TEXT REFERENCES grade_policy_versions(id) ON DELETE RESTRICT,
    published_by_user_id TEXT,
    published_at TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(scope_type,scope_id,version),
    CHECK(
        (status='PUBLISHED' AND published_by_user_id IS NOT NULL AND published_at IS NOT NULL)
        OR (status!='PUBLISHED' AND published_by_user_id IS NULL AND published_at IS NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS one_published_grade_policy_per_scope
ON grade_policy_versions(scope_type,scope_id) WHERE status='PUBLISHED';

CREATE TRIGGER IF NOT EXISTS immutable_grade_policy_content
BEFORE UPDATE OF id,scope_type,scope_id,version,display_name,provenance_label,
    numeric_scale_json,raw_score_bands_json,rounding_rule,pass_rule,retake_rule,
    content_hash,created_by_user_id,supersedes_policy_id,created_at
ON grade_policy_versions
BEGIN
    SELECT RAISE(ABORT, 'Grade policy version content is immutable');
END;

CREATE TRIGGER IF NOT EXISTS validate_grade_policy_transition
BEFORE UPDATE OF status,published_by_user_id,published_at ON grade_policy_versions
WHEN NOT (
    (OLD.status='DRAFT_VALID' AND NEW.status='PUBLISHED'
     AND NEW.published_by_user_id IS NOT NULL AND NEW.published_at IS NOT NULL)
    OR (OLD.status='PUBLISHED' AND NEW.status='RETIRED')
    OR (
        OLD.status=NEW.status
        AND OLD.published_by_user_id IS NEW.published_by_user_id
        AND OLD.published_at IS NEW.published_at
    )
)
BEGIN
    SELECT RAISE(ABORT, 'Invalid GradePolicy transition');
END;

CREATE TRIGGER IF NOT EXISTS immutable_grade_policy_delete
BEFORE DELETE ON grade_policy_versions
BEGIN
    SELECT RAISE(ABORT, 'Grade policy versions are immutable');
END;

INSERT OR IGNORE INTO grade_policy_versions(
    id,scope_type,scope_id,version,status,display_name,provenance_label,
    numeric_scale_json,raw_score_bands_json,rounding_rule,pass_rule,retake_rule,
    content_hash,created_by_user_id
) VALUES(
    'gp_requirements_draft_v1','PLATFORM','platform',1,'DRAFT_UNCONFIGURED',
    'User-supplied learning grade draft',
    'Requirements draft; not an institutional policy',
    '[{"letter":"A+","numeric_value":4.3},{"letter":"A","numeric_value":3.7},{"letter":"A-","numeric_value":null},{"letter":"B+","numeric_value":3.3},{"letter":"B","numeric_value":3.0},{"letter":"B-","numeric_value":2.7},{"letter":"C+","numeric_value":2.3},{"letter":"C","numeric_value":2.0},{"letter":"C-","numeric_value":1.7},{"letter":"D","numeric_value":1.4},{"letter":"E","numeric_value":1.0},{"letter":"F","numeric_value":0.0}]',
    '[]',NULL,NULL,NULL,
    '8e9f11a92e685fbf66d0213ee4eb1ad8dc6ceb7222ae989eeb278ca235efa1d1',
    'REQUIREMENTS_IMPORT'
);

CREATE TABLE IF NOT EXISTS assessment_blueprint_grade_policies (
    blueprint_id TEXT PRIMARY KEY
        REFERENCES assessment_blueprint_versions(id) ON DELETE RESTRICT,
    grade_policy_version_id TEXT NOT NULL
        REFERENCES grade_policy_versions(id) ON DELETE RESTRICT,
    mapping_status TEXT NOT NULL CHECK(mapping_status IN ('CONFIGURED','UNCONFIGURED'))
);

CREATE TRIGGER IF NOT EXISTS immutable_assessment_blueprint_policy_update
BEFORE UPDATE ON assessment_blueprint_grade_policies
BEGIN
    SELECT RAISE(ABORT, 'Frozen Assessment GradePolicy binding is immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_assessment_blueprint_policy_delete
BEFORE DELETE ON assessment_blueprint_grade_policies
BEGIN
    SELECT RAISE(ABORT, 'Frozen Assessment GradePolicy binding is immutable');
END;

CREATE TABLE IF NOT EXISTS grade_snapshots (
    id TEXT PRIMARY KEY,
    assessment_session_id TEXT NOT NULL
        REFERENCES assessment_sessions(id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    grade_policy_version_id TEXT NOT NULL
        REFERENCES grade_policy_versions(id) ON DELETE RESTRICT,
    mapping_status TEXT NOT NULL CHECK(mapping_status IN ('CONFIGURED','UNCONFIGURED')),
    raw_score REAL NOT NULL CHECK(raw_score BETWEEN 0 AND 100),
    grade_label TEXT,
    numeric_value REAL,
    independent_eligible INTEGER NOT NULL CHECK(independent_eligible IN (0,1)),
    criterion_summary_json TEXT NOT NULL CHECK(json_valid(criterion_summary_json)),
    supersedes_snapshot_id TEXT REFERENCES grade_snapshots(id) ON DELETE RESTRICT,
    content_hash TEXT NOT NULL CHECK(
        length(content_hash)=64 AND content_hash NOT GLOB '*[^0-9a-f]*'
    ),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(assessment_session_id,revision),
    CHECK(
        (mapping_status='UNCONFIGURED' AND grade_label IS NULL AND numeric_value IS NULL)
        OR (mapping_status='CONFIGURED' AND grade_label IS NOT NULL
            AND numeric_value IS NOT NULL)
    )
);

CREATE TRIGGER IF NOT EXISTS validate_grade_snapshot_context
BEFORE INSERT ON grade_snapshots
WHEN NOT EXISTS(
    SELECT 1 FROM assessment_sessions AS session
    JOIN assessment_blueprint_grade_policies AS policy
      ON policy.blueprint_id=session.blueprint_id
    WHERE session.id=NEW.assessment_session_id
      AND policy.grade_policy_version_id=NEW.grade_policy_version_id
      AND policy.mapping_status=NEW.mapping_status
)
BEGIN
    SELECT RAISE(ABORT, 'GradeSnapshot does not match the frozen Assessment policy');
END;

CREATE TRIGGER IF NOT EXISTS immutable_grade_snapshot_update
BEFORE UPDATE ON grade_snapshots
BEGIN
    SELECT RAISE(ABORT, 'Grade snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS immutable_grade_snapshot_delete
BEFORE DELETE ON grade_snapshots
BEGIN
    SELECT RAISE(ABORT, 'Grade snapshots are immutable');
END;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(18,'versioned grade policy bindings and immutable grade snapshots');
