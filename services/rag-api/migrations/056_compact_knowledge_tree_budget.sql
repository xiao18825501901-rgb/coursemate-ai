-- Product-wide hard limit for materialized course knowledge views.
-- Every stored membership counts: COMPOSITE chapters, ATOMIC learning units,
-- and any explicitly stored root. Source chunks and citations remain outside
-- the tree and are deliberately not counted.

CREATE TRIGGER IF NOT EXISTS limit_tree_membership_insert
BEFORE INSERT ON knowledge_tree_memberships
WHEN (
    SELECT COUNT(*)
    FROM knowledge_tree_memberships
    WHERE tree_version_id = NEW.tree_version_id
) >= 50
BEGIN
    SELECT RAISE(ABORT, 'A knowledge tree may contain at most 50 members');
END;

CREATE TRIGGER IF NOT EXISTS limit_tree_membership_move
BEFORE UPDATE OF tree_version_id ON knowledge_tree_memberships
WHEN NEW.tree_version_id != OLD.tree_version_id AND (
    SELECT COUNT(*)
    FROM knowledge_tree_memberships
    WHERE tree_version_id = NEW.tree_version_id
) >= 50
BEGIN
    SELECT RAISE(ABORT, 'A knowledge tree may contain at most 50 members');
END;

-- Historical over-limit versions remain readable while compaction is staged,
-- but no such version may newly become the default learner view.
CREATE TRIGGER IF NOT EXISTS limit_tree_status_activation
BEFORE UPDATE OF status ON knowledge_tree_versions
WHEN NEW.status IN ('PUBLISHED','ACTIVE') AND (
    SELECT COUNT(*)
    FROM knowledge_tree_memberships
    WHERE tree_version_id = NEW.id
) > 50
BEGIN
    SELECT RAISE(ABORT, 'An active knowledge tree may contain at most 50 members');
END;

CREATE TRIGGER IF NOT EXISTS limit_auto_tree_activation_insert
BEFORE INSERT ON auto_course_tree_activations
WHEN NEW.status = 'ACTIVE' AND (
    SELECT COUNT(*)
    FROM knowledge_tree_memberships
    WHERE tree_version_id = NEW.tree_version_id
) > 50
BEGIN
    SELECT RAISE(ABORT, 'An active automatic knowledge tree may contain at most 50 members');
END;

CREATE TRIGGER IF NOT EXISTS limit_auto_tree_activation_update
BEFORE UPDATE OF tree_version_id,status ON auto_course_tree_activations
WHEN NEW.status = 'ACTIVE' AND (
    SELECT COUNT(*)
    FROM knowledge_tree_memberships
    WHERE tree_version_id = NEW.tree_version_id
) > 50
BEGIN
    SELECT RAISE(ABORT, 'An active automatic knowledge tree may contain at most 50 members');
END;

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(56, 'compact knowledge tree budget');
