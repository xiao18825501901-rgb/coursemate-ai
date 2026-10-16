-- A bounded retry window for a preparation whose original attempt budget is
-- already exhausted.
--
-- The historical `attempt` counter is the learner-visible retry history and is
-- never rewritten: a legacy row sitting at attempt 24 stays at 24.  A targeted,
-- explicitly allowlisted recovery registers a new *epoch* instead, and the epoch
-- carries its own cap so "make the row runnable again" cannot degrade into
-- unbounded authoring retries.
--
-- SQLite cannot ADD COLUMN IF NOT EXISTS, so this file is registered in
-- V3_REPLAY_SUPERSEDED_BY: its own schema_migrations row is the restart-safe
-- guard that stops the ALTERs from replaying.

BEGIN IMMEDIATE;

ALTER TABLE assessment_configuration_preparations ADD COLUMN retry_epoch_id TEXT;
ALTER TABLE assessment_configuration_preparations ADD COLUMN retry_epoch_attempt INTEGER
    CHECK(retry_epoch_attempt IS NULL OR retry_epoch_attempt >= 0);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(72, 'bounded assessment preparation retry epochs');

COMMIT;
