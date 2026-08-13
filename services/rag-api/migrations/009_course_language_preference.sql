-- Operations-readable record for schema version 9.
-- Database.initialize() is the idempotent executable migrator.

ALTER TABLE courses
ADD COLUMN preferred_language TEXT NOT NULL DEFAULT 'auto'
CHECK (preferred_language IN ('auto', 'zh-CN', 'en', 'bilingual'));

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES (9, 'course language preference');
