-- Campus material records: one row per source file, with the rights metadata that decides whether
-- it may ever be published.
--
-- Task C3 of the CourseJesus pack. Three deliberate choices, because the schema is where they can
-- actually be enforced:
--
--   1. The external unique key is `institution_origin + canvas_course_id + relative_path`. The pack
--      fixes the course's key as institution origin plus Canvas course id; a course's files are
--      distinguished by their path inside the export, because the manifests frequently carry no
--      Canvas file id at all. Names are display-only and are never the key.
--   2. `review_status` is NOT NULL with no default. Every row says where it stands, so there is no
--      such thing as a material row whose review state was forgotten.
--   3. `publication_basis` and `usage_rights` are recorded per file, not per course: the inventory
--      shows a single course mixing textbook copies, lecture slides and personal files, and a
--      course-level flag could not express that.
--
-- Publication is not recorded here as a state this table can advance to on its own: a course is
-- published by the existing course publication flow, and this table only says what the file is and
-- what is known about its rights.

CREATE TABLE IF NOT EXISTS campus_material_records (
    id TEXT PRIMARY KEY,
    institution_origin TEXT NOT NULL,
    canvas_course_id TEXT NOT NULL,
    course_code TEXT NOT NULL DEFAULT '',
    source_root TEXT NOT NULL DEFAULT '',
    relative_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL DEFAULT '',
    bytes_disk INTEGER NOT NULL DEFAULT 0,
    parse_class TEXT NOT NULL DEFAULT '',
    classification TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL
        CHECK(decision IN ('INGESTABLE','DOWNLOAD_ONLY','BLOCKED')),
    decision_reason TEXT NOT NULL DEFAULT '',
    usage_rights TEXT NOT NULL DEFAULT 'UNVERIFIED',
    license_note TEXT NOT NULL DEFAULT '',
    source_notice TEXT NOT NULL DEFAULT '',
    publication_basis TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL
        CHECK(review_status IN ('NEEDS_REVIEW','BLOCKED_NEEDS_OWNER_DECISION','NOT_FOR_PUBLICATION')),
    target_course_id TEXT,
    document_id TEXT,
    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(institution_origin, canvas_course_id, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_campus_material_course
    ON campus_material_records(institution_origin, canvas_course_id, decision);
CREATE INDEX IF NOT EXISTS idx_campus_material_review
    ON campus_material_records(review_status);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(32, 'campus material records and rights metadata');
