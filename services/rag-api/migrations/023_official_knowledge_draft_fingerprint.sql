-- Additive corpus-fingerprint column for the M6D1 official knowledge draft builder.
-- The builder derives a stable fingerprint from the course's current OFFICIAL
-- document versions plus the generation configuration, and stores it on the
-- OFFICIAL DRAFT tree it creates so an identical corpus rerun reuses the draft
-- instead of stacking duplicate canonical nodes and trees.
--
-- initialize() replays every V3 migration file, and SQLite cannot ADD COLUMN
-- conditionally, so the ALTER and the partial index are applied in db.py with a
-- column-existence guard (the same pattern as the chunk metadata columns). This
-- file records the migration intent and its ledger entry.

INSERT OR IGNORE INTO schema_migrations(version, name)
VALUES(23, 'official knowledge draft corpus fingerprint');
