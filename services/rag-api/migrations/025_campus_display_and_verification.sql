-- Additive display-type / student-verification columns for the campus-course
-- and snapshot-sharing feature round. display_type is a PRESENTATION field
-- (campus/shared/private) kept separate from the access rules that already
-- live in course_type/visibility/ownership; requires_student_verification is
-- the independent access requirement so a shared snapshot of a campus course
-- keeps its gate. Legacy rows: official courses display as campus courses and
-- require verification; user courses display as private. Shared-snapshot
-- courses are inserted with display_type='shared' by the new code.
-- Application rollback stays compatible: older releases ignore both columns.

CREATE TABLE IF NOT EXISTS learning_pairs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    bound_node_id TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_learning_pairs_node_binding
ON learning_pairs(workspace_id, bound_node_id) WHERE bound_node_id IS NOT NULL;

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(25, 'campus display type and verification gate');
