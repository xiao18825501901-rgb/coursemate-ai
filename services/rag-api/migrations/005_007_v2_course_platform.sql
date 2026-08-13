-- CourseMate AI V2 migration reference for SQLite schema versions 5-7.
--
-- IMPORTANT: app.db.Database.initialize() is the executable, idempotent migrator.
-- SQLite has no portable `ADD COLUMN IF NOT EXISTS`, so do not apply this file
-- directly to an unknown or partially migrated database. Operators should back up
-- the database and uploads, start the release against a copy, and let initialize()
-- inspect PRAGMA table_info before applying each statement.

-- Version 5: private, owned user courses.
ALTER TABLE courses ADD COLUMN owner_user_id TEXT;
ALTER TABLE courses ADD COLUMN course_type TEXT NOT NULL DEFAULT 'official';
ALTER TABLE courses ADD COLUMN visibility TEXT NOT NULL DEFAULT 'public';
ALTER TABLE courses ADD COLUMN updated_at TEXT;
UPDATE courses
SET updated_at = COALESCE(NULLIF(updated_at, ''), NULLIF(created_at, ''),
                          strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
WHERE updated_at IS NULL OR updated_at = '';
CREATE INDEX IF NOT EXISTS idx_courses_visibility_owner
ON courses(visibility, owner_user_id, updated_at);
INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES (5, 'private user courses and ownership');

-- Version 6: versioned teaching profiles pinned to conversations.
ALTER TABLE conversations ADD COLUMN teaching_profile_version INTEGER;
CREATE TABLE IF NOT EXISTS course_teaching_profiles (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version >= 1),
    created_by_user_id TEXT NOT NULL,
    language TEXT NOT NULL CHECK (language IN ('auto', 'zh-CN', 'en', 'bilingual')),
    student_level TEXT NOT NULL CHECK (student_level IN ('beginner', 'intermediate', 'advanced')),
    learning_goal TEXT NOT NULL,
    teaching_styles_json TEXT NOT NULL CHECK (json_valid(teaching_styles_json)),
    answer_depth TEXT NOT NULL CHECK (answer_depth IN ('concise', 'balanced', 'detailed')),
    example_preference TEXT NOT NULL CHECK (example_preference IN ('minimal', 'when-helpful', 'worked')),
    exercise_policy TEXT NOT NULL CHECK (exercise_policy IN ('none', 'offer', 'always')),
    exam_orientation INTEGER NOT NULL DEFAULT 0 CHECK (exam_orientation IN (0, 1)),
    citation_preference TEXT NOT NULL CHECK (citation_preference IN ('standard', 'detailed')),
    math_detail_level TEXT NOT NULL CHECK (math_detail_level IN ('light', 'standard', 'full')),
    terminology_style TEXT NOT NULL CHECK (terminology_style IN ('plain', 'bilingual', 'formal')),
    custom_requirements TEXT NOT NULL DEFAULT '',
    generated_prompt TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (course_id, version)
);
CREATE INDEX IF NOT EXISTS idx_profiles_course_version
ON course_teaching_profiles(course_id, version DESC);
INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES (6, 'versioned course teaching profiles');

-- Version 7: explicit consent and administrator publication review.
ALTER TABLE courses ADD COLUMN publication_status TEXT NOT NULL DEFAULT 'private';
UPDATE courses SET publication_status = 'published' WHERE course_type = 'official';
ALTER TABLE courses ADD COLUMN published_at TEXT;
UPDATE courses SET published_at = created_at WHERE course_type = 'official';
CREATE TABLE IF NOT EXISTS course_publication_requests (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'withdrawn')),
    share_materials_consent INTEGER NOT NULL CHECK (share_materials_consent = 1),
    rights_confirmation INTEGER NOT NULL CHECK (rights_confirmation = 1),
    consent_version TEXT NOT NULL,
    consented_at TEXT NOT NULL,
    submitted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    reviewed_at TEXT,
    reviewed_by_user_id TEXT,
    review_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_publication_status_submitted
ON course_publication_requests(status, submitted_at);
INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES (7, 'consent based course publication workflow');
