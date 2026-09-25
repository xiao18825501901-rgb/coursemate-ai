# ADR-003: Skip superseded table rebuilds on migration replay

## Status

Accepted

## Date

2026-09-25

## Context

The RAG database intentionally replays registered V3 migration scripts during initialization. Most
scripts are idempotent and this behavior recreates required indexes, triggers and additive objects.
Some SQLite schema changes, however, require a table rebuild.

Migration 027 rebuilt the two model-call ledgers with the roles and uniqueness rule that existed at
that time. Migration 038 later superseded those exact rebuilds: it added the Question Engine roles
and removed the one-reservation-per-role constraint so five author and five blind-solver calls can be
recorded in one operation. Migration 039 then added the two diagnostic-practice roles to the same
ledgers. Replaying either 027 or 038 on an already-39 database would temporarily restore an obsolete
role constraint before 039 could run, and copying legitimate newer rows would fail during restart.

Historical migration files are immutable evidence of the upgrade that originally ran. Editing 027
to understand a future schema would make that history false.

## Decision

Keep historical SQL unchanged and maintain an explicit `V3_REPLAY_SUPERSEDED_BY` map in
`app/db.py`. A mapped historical migration is skipped during replay only when its superseding
migration version is already recorded in `schema_migrations`.

For the current schema, migration 027 is superseded by 038 and migration 038 is superseded by 039.
Fresh initialization and any pre-39 upgrade still execute the required historical sequence. An
already-39 database skips both older replay-unsafe rebuilds, replays 039 and retains the complete
role set and repeated reservations. All other migration replay behavior is unchanged.

## Alternatives considered

### Edit migration 027

- Pro: one script would replay on the current schema.
- Con: the historical migration would no longer describe or reproduce the version-27 transition.
- Rejected because migration history must remain immutable and auditable.

### Stop replaying every recorded migration

- Pro: conventional migration runners execute each version only once.
- Con: this repository currently relies on idempotent replay for existing schema-object repair; a
  global change would be much broader than the demonstrated defect.
- Rejected for this correction. A future migration-runner redesign needs its own rehearsal and ADR.

### Ignore duplicate-role rows while 027 copies them

- Pro: 027 could finish.
- Con: dropping, merging or rewriting reservation/evidence rows would corrupt the audit ledger.
- Rejected because model-call accounting is append-only evidence.

## Consequences

- Schema-39 databases with repeated Question Engine and metered practice roles restart safely.
- Fresh and pre-39 migration order remains unchanged.
- A future table rebuild that supersedes an older replay-unsafe rebuild must add an explicit map
  entry and a restart regression; it must not silently edit historical SQL.
- The exact-candidate gate must continue testing fresh initialization, upgrade, second
  initialization, integrity and foreign keys.
- If the project later replaces replay with a conventional once-only runner, this decision should be
  superseded rather than deleted.
