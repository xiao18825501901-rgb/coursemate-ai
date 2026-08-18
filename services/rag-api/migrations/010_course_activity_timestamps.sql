-- Operations-readable record for schema version 10.
-- Database.initialize() creates these triggers idempotently on existing and new databases.

CREATE TRIGGER IF NOT EXISTS course_activity_document_ai AFTER INSERT ON documents BEGIN
    UPDATE courses SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE id = new.course_id;
END;

CREATE TRIGGER IF NOT EXISTS course_activity_document_au AFTER UPDATE ON documents BEGIN
    UPDATE courses SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE id = new.course_id;
END;

CREATE TRIGGER IF NOT EXISTS course_activity_document_ad AFTER DELETE ON documents BEGIN
    UPDATE courses SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE id = old.course_id;
END;

CREATE TRIGGER IF NOT EXISTS course_activity_conversation_ai AFTER INSERT ON conversations BEGIN
    UPDATE courses SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE id = new.course_id;
END;

CREATE TRIGGER IF NOT EXISTS course_activity_conversation_au AFTER UPDATE ON conversations BEGIN
    UPDATE courses SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE id = new.course_id;
END;

CREATE TRIGGER IF NOT EXISTS course_activity_conversation_ad AFTER DELETE ON conversations BEGIN
    UPDATE courses SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE id = old.course_id;
END;

CREATE TRIGGER IF NOT EXISTS course_activity_profile_ai
AFTER INSERT ON course_teaching_profiles BEGIN
    UPDATE courses SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE id = new.course_id;
END;

CREATE TRIGGER IF NOT EXISTS course_activity_profile_ad
AFTER DELETE ON course_teaching_profiles BEGIN
    UPDATE courses SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE id = old.course_id;
END;

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES (10, 'course activity timestamps');
