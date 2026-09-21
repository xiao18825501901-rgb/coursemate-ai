# MIGRATION_AND_ROLLBACK

How database changes for the Jev layer and the structured-enhancement modules are made, rehearsed and
reversed — and what must never be lost.

---

## 1. Current schema state

| Item | Value |
|---|---|
| Source schema target (RAG) | **28** — `app/db.py::LATEST_V3_SCHEMA_VERSION`, migrations 001–028 |
| Jev receipts | `028_jev_decision_receipts.sql` (executed, historical; never rewritten) |
| UI schema | 13 (unchanged this round) |
| Agent schema | 1 (unchanged) |
| Withdrawn | migration 029 existed only for the cancelled Laya direction; it was removed and is archived under `archive/laya-superseded-20260922/` |
| Production (verified read-only this round) | **25** — the live database is `/srv/coursemate/data/releases/20260919T202006Z/rag.sqlite3`, `integrity_check=ok`, migrations 001–025 |

Production therefore needs **25 → 28** (026 learning start events, 027 assessment preparation, 028 Jev
receipts). There is no 029.

## 2. Rules for new state

1. **Reuse before adding.** New structured-enhancement state extends the existing receipt table or an
   existing service. A new table is added only when a receipt genuinely cannot hold it (for example,
   an accepted entity *relation* that retrieval must later read).
2. **Additive only.** New migrations are appended after 028, keep `LATEST_V3_SCHEMA_VERSION` in sync,
   and never edit an executed file. No migration may drop a column, narrow a CHECK set, or delete a
   row: the previous release must still be able to run against the migrated database.
3. **No parallel stores.** No second knowledge-tree authority, no second grade store, no second user
   store, no second tool executor, no second Jev gateway.
4. **Nothing is deleted.** Published trees and specs, history, marks, files and share snapshots keep
   their bytes; a relation, a review or a receipt is added *around* them.

## 3. Rehearsal (before any production migration)

The rehearsal runs on an isolated copy, never on the production file:

```
python work/current-change/mig_probe.py                      # init + replay on a temp database
python scripts/rehearse_v3_migration.py                      # legacy copy → migrate up, invariants checked
python scripts/verify_rollback_compat.py --release-tree <previous release export>
```

What each must prove:

* **Fresh init and replay**: every declared migration applies, a second `initialize()` is a no-op, no
  `*_new`/`*_old` leftovers, `integrity_check=ok`, `foreign_key_check` empty, and all governance
  objects (including the ten assessment triggers that migration 027 rebuilds) still exist.
* **Legacy upgrade**: an older copy upgrades with its rows preserved (the rehearsal asserts the
  legacy course row and the model-budget invariants).
* **Rollback compatibility**: the *actual* previous release runs against the migrated database —
  import, open, read, enumerate — with no missing or retyped column and no narrowed CHECK
  (verdict `ROLLBACK_SAFE_WITH_MIGRATED_DB`). This was verified for the earlier boundary; it must be
  re-run against the real release being replaced (`4ef5064`) before the production migration.
* Frozen guards in the test suite: `test_schema_rollback_compat.py` pins the pre-027 column/table/enum
  snapshot and `test_v3_migration_rehearsal.py` pins the migration set, so a future migration that
  removes a column or narrows an enum fails the suite instead of shipping.

## 4. Backup and restore

1. Take a consistent copy of all three databases (RAG, UI extension, agent), the uploads, the share
   snapshots and the release's model/provider configuration **before** touching anything, and record
   the release SHA and the schema version alongside them.
2. Restore that copy into an isolated directory and run the rehearsal against it — never against
   production.
3. Keep the pre-migration backup after the release; it is the primary rollback path.

## 5. Rollback

| Situation | Action |
|---|---|
| The new release misbehaves, schema is fine | re-point `current` to the previous immutable release directory. Migrations are additive, so the previous release can read the migrated database; this is the case verified by `verify_rollback_compat.py` |
| Data is wrong or a migration misbehaved | restore the pre-migration backup, then re-point the release. This is the only path that discards new rows, so it requires the owner's explicit decision |
| A single definition misbehaves | switch that definition back to `shadow`/`off` — no schema change, no release change |

Never force-push, never rewrite an executed migration, never "clean up" a backup or an evidence log to
make a report look tidier.

## 6. Verified status

| Item | State |
|---|---|
| Isolated init/replay and leftover checks | verified this session (`integrity=ok`, `fk=0`, max 28, no leftovers) |
| Legacy-upgrade invariants | covered by the rehearsal suite (green) |
| Rollback compatibility against the *previous* release | verified for the earlier boundary; **must be re-run against `4ef5064` before the production migration** |
| Production migration 026–028 | **NOT_RUN** — requires the release window and a fresh backup |
| Post-release backup and monitoring | **NOT_RUN** |
