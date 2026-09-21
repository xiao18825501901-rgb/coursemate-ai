-- Course-scope semantic entity relations (proposals only, never mutations).
--
-- ``CourseEntityResolution`` returns pairwise relations between semantic objects
-- the deterministic backend has already authorized for one course/workspace. A
-- relation is a proposal: it never merges, deletes, renames or reorders anything
-- on the retrieval/generation path. The deterministic backend owns the decision
-- to accept or reject a proposal, so this table stores the relation, its evidence
-- and its status separately from the Jev call receipt (``jev_decision_receipts``).
--
-- Columns:
--   left_id / right_id          the two authorized object ids (canonical order)
--   left_source_version         the left object's source version at compare time
--   right_source_version        the right object's source version at compare time
--   course_id / material_revision  the scope the relation was resolved in
--   relation                    one of the ``entity.relation.v1`` Choice labels
--   evidence                    why the pair was compared (exact_id | version |
--                               content_hash | alias | title | similarity)
--   status                      PROPOSED by default (the semantic layer never
--                               ACCEPTs/REJECTs; only the backend does)
--   receipt_id                  the Jev receipt id when a call decided this relation
--   used_jev                    whether a Jev call (mode "on") decided the relation

CREATE TABLE IF NOT EXISTS entity_relations (
    id TEXT PRIMARY KEY,
    left_id TEXT NOT NULL,
    right_id TEXT NOT NULL,
    left_source_version TEXT,
    right_source_version TEXT,
    course_id TEXT NOT NULL,
    material_revision TEXT,
    relation TEXT NOT NULL,
    evidence TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PROPOSED'
        CHECK(status IN ('PROPOSED', 'ACCEPTED', 'REJECTED')),
    receipt_id TEXT,
    used_jev INTEGER NOT NULL DEFAULT 0 CHECK(used_jev IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(left_id, right_id, relation)
);

CREATE INDEX IF NOT EXISTS idx_entity_relations_course
ON entity_relations(course_id, material_revision, relation);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(29, 'entity relations');
