# CourseMate V3 — Migration and Rollback

Version: Stage 1 migration rehearsal evidence, 2026-09-12.
No production or real local database migration is authorized or claimed by this document.

## 1. Known migration reality

| Location | Last verified versions | Evidence | Status |
|---|---:|---|---|
| repository V2 base | 1–10 | `app/db.py`, existing tests | current stable baseline |
| repository V3 files | 011/012/013 written, uncommitted | SQL source + automated tests | source implemented through Stage 1 |
| pytest/E2E databases | 1–13 when `v3_enabled=True` | temporary synthetic runs | disposable local evidence |
| isolated real-data copy | 1–13 | `work/v3-migration-rehearsal-03/migration-evidence.json` | local copy only; private, never commit/share |
| local real `data/rag.sqlite3` | 1–10, integrity ok | SQLite read-only audit | deliberately unchanged |
| production database | UNKNOWN | no current access/evidence | manual verification required |

011 creates owner×course workspaces and hidden private corpora. 012 creates the current minimal journey/problem/bridge/operation tables. 013 adds immutable source versions, derived artifacts and chunk-to-source-version bindings, and backfills every existing document/chunk without rewriting original bytes. Earlier disposable copies may contain an early 011 `CASCADE` variant while the current file uses `RESTRICT`; therefore version number alone is not enough to prove exact shape. Do not edit/delete/re-number applied history to hide that fact. Migrations 011–013 are now frozen; correct forward with 014+.

## 2. Activation rule

`SUPPLEMENTAL_ENGINEERING_DECISION`: V3 Schema activation follows the server-side `V3_ENABLED` setting.

- `V3_ENABLED=false`: initialization and readiness require versions 1–10; no V3 table is referenced by V2 course/publication paths.
- `V3_ENABLED=true`: initialization applies 011/012/013 and readiness requires the complete set 1–13.
- Web `VITE_V3_ENABLED` controls navigation only and never authorizes a Schema migration.
- Future 014+ migrations must be included only after their corresponding feature slice, idempotency and copy rehearsal pass.

The rule has focused local evidence in `test_database.py` and `test_learning_workspace.py`. Production remains unverified.

## 3. Additive migration plan

Actual table/column names are finalized test-first; numbers below are allocation intent, not yet-existing migrations.

| Migration range | Intended additive scope | Backfill rule |
|---|---|---|
| 013 (implemented) | DocumentVersion, DerivedArtifact and chunk source provenance | one immutable version per existing document; bind every existing chunk without rewriting bytes/chunks |
| 014 | MaterialEvidence, Knowledge Registry, aliases and private overlay | no global name merge; existing minimal node IDs preserved |
| 015 | TreeVersion/Membership and prerequisite edges | start as drafts; no automatic “official” publication |
| 016 | normalized Teaching Spec items/plan versions/cache and stronger delivery evidence | retain JSON Spec and old journeys; explicit pinned-version conversion only |
| 017 | Problem revisions/images/knowledge links/attempt exposure and hardened Bridge | preserve current problem/solution/step IDs through mapping columns |
| 018 | Assessment pool/blueprint/session/attempt/performance | no legacy grade inference; all users begin `NOT_ASSESSED` |
| 019 | GradePolicy/GradeSnapshot | missing A-/thresholds stored null/unconfigured; no default official policy |
| 020 | Publication review snapshots/grants/out Bots/audit hardening | no existing private data auto-published |

Migrations may be split further to keep each reviewable and recoverable. They must not be collapsed into a destructive “V3 rebuild.”

## 4. Preflight before any real-data copy

Record without exposing content or secrets:

```text
release/branch/HEAD
source database absolute resolved path and filesystem
upload root absolute resolved path and size/file count
Task Agent database path if included in a consistent release snapshot
schema_migrations rows and sqlite_schema hashes
PRAGMA integrity_check and foreign_key_check
database page count/WAL state/free disk
service write/quiesce plan
backup destination resolved path, outside live notebooks/uploads
feature flag state and old/new frontend compatibility
```

Stop if paths are unresolved, point at a workspace/repository root, backup space is insufficient, integrity is already bad, an unknown write process is active, or production version does not match the expected source.

## 5. Local isolated rehearsal

The repository script refuses an absent source, an existing target, or a target outside `work/`. It uses SQLite online backup for the database copy, then initializes V3 twice and compares old-table row counts/hashes plus integrity and foreign keys.

Example from repository root, using an unused target name:

```powershell
services/rag-api/.venv/Scripts/python.exe scripts/rehearse_v3_migration.py `
  --source data/rag.sqlite3 `
  --target work/v3-migration-rehearsal-04
```

This command creates a private local copy and therefore must not be run in a directory that is synced/published. The target must be a fresh name; `-04` is only the next example after the retained local evidence. Do not paste `migration-evidence.json` if future revisions include identifiers; inspect its schema first. The existing rehearsal does not copy uploads and is not a full-site restore drill.

The 2026-09-12 `v3-migration-rehearsal-03` run opened the source database through SQLite read-only URI mode, copied it with SQLite online backup, initialized twice and reported:

```text
old_rows_unchanged=true
integrity=ok
foreign_key_violations=0
schema_versions=1..13
documents=67
document_versions=67
chunks_without_source_version=0 of 1937
invalid_source_owners=0
v3_invariants_ok=true
```

Those are aggregate local-copy facts only. Upload bytes were not copied, no application smoke was run against the copy, and the source `data/rag.sqlite3` remained at versions 1–10.

Required database assertions:

1. initialization twice produces one row per migration version;
2. pre-existing tables retain row counts and deterministic content hashes;
3. `integrity_check=ok` and `foreign_key_check` is empty;
4. V2 API suite passes with the new code;
5. V3 A/B/Admin/anonymous, journey and assessment suites pass;
6. unsupported/legacy rows produce explicit state rather than inferred LEARNED/grade;
7. a stopped/failed migration rolls back or is safely forward-repairable.

## 6. Consistent release backup

The production backup unit is more than one `.sqlite3` file:

```text
manifest.json
rag.sqlite3 consistent snapshot
agent.sqlite3 consistent snapshot (if deployed by this release)
uploads/ immutable file snapshot or storage generation
release SHA + configuration key names/values redacted
schema/integrity/file-count/hash evidence
```

Preferred sequence:

1. Put public writes into a verified maintenance/drain state; confirm no background ingestion/model finalization remains.
2. Checkpoint WAL as appropriate and use SQLite’s backup API for each database; do not byte-copy a live main file while ignoring `-wal`.
3. Snapshot uploads/object generation while writes remain drained.
4. Write the manifest last with start/end time, release SHA, source and backup summaries.
5. Open backups read-only, run integrity/FK and representative file hashes.
6. Restore into NZ new isolated paths and boot an isolated instance before considering the backup usable.
7. Resume writes only after evidence is retained outside the live directory.

Exact production commands depend on the verified host/service/storage. Historical paths in old reports are not copied here as facts.

## 7. Rollout order

1. Verify production reality and take/test the complete backup unit.
2. Deploy backend code with `V3_ENABLED=false`; run V2 smoke/regression against the compatible Schema.
3. Run the reviewed V3 migration in a maintenance window; validate versions/integrity/counts.
4. Enable backend V3 for an owner-only canary while Web navigation remains hidden.
5. Run authenticated API isolation and minimum live-model canary within explicit budget.
6. Deploy Web with `VITE_V3_ENABLED=true` to preview/canary audience.
7. Run full browser smoke including two users/admin, refresh/relogin and both pane directions.
8. Widen exposure only after monitoring/rollback triggers are confirmed.

If the deployed frontend cannot tolerate a disabled/missing V3 endpoint, deploy backend compatibility first. Never enable the Web flag ahead of a compatible backend/schema.

## 8. Rollback levels

| Trigger | Immediate reversible action | Data handling |
|---|---|---|
| UI or quality defect; Schema healthy | disable Web flag, then backend V3 flag if safe | retain V3 tables/events; V2 remains available |
| provider failure/cost anomaly | disable V3 generation or V3 flag | keep completed/failed operation audit; no automatic paid retry |
| authorization leak | disable affected routes/V3 immediately; preserve security logs | revoke derived links/cache; do not delete evidence before incident review |
| migration invariant failure before exposure | keep service drained; stop rollout | restore only to isolated path, compare, then authorized cutover |
| post-exposure database corruption | stop all writes and preserve live files/WAL | Owner-authorized restore of complete snapshot; separately preserve post-backup deltas |

Rollback normally means code/flag rollback with additive tables retained. Dropping V3 tables or restoring an old database can destroy new journeys/assessments and is a high-risk, Owner-authorized last resort. Never run recursive delete or overwrite the live directory to “clean up.”

## 9. Exit evidence

Migration/restore acceptance is a separate result from source and model quality:

```text
SOURCE MIGRATIONS REVIEWED: 011–013 for the current Stage 1 slice
SYNTHETIC MIGRATION VERIFIED: 011–013, including repeat initialization
REAL-DATA COPY MIGRATION VERIFIED: 011–013 only; must rerun for every later final Schema
ISOLATED FULL RESTORE VERIFIED: not yet
PRODUCTION MIGRATION VERIFIED: not verified
PRODUCTION ROLLBACK DRILL VERIFIED: not verified
```
