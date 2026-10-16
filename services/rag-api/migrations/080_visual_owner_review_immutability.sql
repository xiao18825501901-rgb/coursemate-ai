-- Human decisions are new append-only events, not edits of AI or old approvals.
BEGIN IMMEDIATE;
CREATE TRIGGER IF NOT EXISTS immutable_visual_owner_review_update
BEFORE UPDATE ON visual_job_events
WHEN OLD.event_type='OWNER_VISUAL_ASSET_REVIEW' OR NEW.event_type='OWNER_VISUAL_ASSET_REVIEW'
BEGIN SELECT RAISE(ABORT,'Owner visual asset review is immutable'); END;

CREATE TRIGGER IF NOT EXISTS immutable_visual_owner_review_delete
BEFORE DELETE ON visual_job_events
WHEN OLD.event_type='OWNER_VISUAL_ASSET_REVIEW'
BEGIN SELECT RAISE(ABORT,'Owner visual asset review is immutable'); END;

INSERT OR IGNORE INTO schema_migrations(version,name)
VALUES(80,'immutable Owner visual asset reviews');
COMMIT;
