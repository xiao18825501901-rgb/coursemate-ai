-- Canvas OAuth authorisation states, stored where every worker can see them.
--
-- `InMemoryStateStore` is correct for one worker and wrong for more than one: the browser starts an
-- authorisation on whichever worker answered `/connect`, and the school's callback can land on a
-- different worker, which would know nothing about the state it is asked to validate. A deployment
-- that runs more than one process therefore needs the state in shared storage, which is what this
-- table is.
--
-- Two properties the schema enforces:
--
--   1. **The state is stored as a hash.** The plaintext value exists in the redirect the browser
--      follows and in nothing else, so a dump of this database cannot be replayed into a callback.
--   2. **One use.** `consumed_at` is written by the same `UPDATE … WHERE consumed_at IS NULL` that
--      claims the row, so two callbacks racing the same state cannot both complete — the database
--      decides, not timing.
--
-- `expires_at` is derived from the store's TTL at issue time and is only an index for purging;
-- expiry is judged against `created_at` so the rule lives in one place (`AuthorizationState`).

CREATE TABLE IF NOT EXISTS canvas_oauth_states (
    state_hash TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    institution_key TEXT NOT NULL,
    origin TEXT NOT NULL,
    return_path TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    consumed_at REAL
);

CREATE INDEX IF NOT EXISTS idx_canvas_oauth_states_expiry
    ON canvas_oauth_states(expires_at);
CREATE INDEX IF NOT EXISTS idx_canvas_oauth_states_subject
    ON canvas_oauth_states(subject, created_at);

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES (34, '034_canvas_oauth_states.sql');
