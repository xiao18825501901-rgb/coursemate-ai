# CourseMate V3 — Migration and Rollback

Version: Stage 4 migration rehearsal evidence, 2026-09-12.
No production migration or real-local migration 016 is authorized or claimed by this document.

## 1. Known migration reality

| Location | Last verified versions | Evidence | Status |
|---|---:|---|---|
| repository V2 base | 1–10 | `app/db.py`, existing tests | current stable baseline |
| repository V3 files | 011–016 committed on the V3 feature branch | SQL source + automated tests | source implemented through Stage 4 |
| pytest/E2E databases | 1–16 when `v3_enabled=True` | temporary synthetic runs | disposable local evidence |
| isolated real-data copy | 1–16 | `work/v3-migration-rehearsal-07/migration-evidence.json` | local copy only; private, never commit/share |
| local real `data/rag.sqlite3` | 1–15, integrity ok | 2026-09-12 17:25 SQLite read-only audit | not changed by the 016 rehearsal; origin/time of 11–15 UNKNOWN |
| production database | UNKNOWN | no current access/evidence | manual verification required |

011 creates owner×course workspaces and hidden private corpora. 012 creates the current minimal journey/problem/bridge/operation tables. 013 adds immutable source versions, derived artifacts and chunk-to-source-version bindings. 014 adds the Registry, aliases/lineage/material evidence, normalized Spec metadata/items, tree versions/memberships and separate prerequisite edges. 015 adds learning-preference/TeachingPlan versions, normalized Plan links, exact TeachingDeliveryEvidence and safe model-run evidence. 016 adds the structural problem index and immutable Problem/Solution revisions, Attempts, StepKnowledgeLinks and LearningBridgeContexts; old rows remain and are explicitly marked `LEGACY_PRESERVED`. Earlier applied copies may differ in exact historical shape; version number alone is not enough to prove it. Do not edit/delete/re-number applied history. Migrations 011–016 are frozen; correct forward with 017+.

## 2. Activation rule

`SUPPLEMENTAL_ENGINEERING_DECISION`: V3 Schema activation follows the server-side `V3_ENABLED` setting.

- `V3_ENABLED=false`: initialization and readiness require versions 1–10; no V3 table is referenced by V2 course/publication paths.
- `V3_ENABLED=true`: initialization applies 011–016 and readiness requires the complete set 1–16.
- Web `VITE_V3_ENABLED` controls navigation only and never authorizes a Schema migration.
- Future 017+ migrations must be included only after their corresponding feature slice, idempotency and copy rehearsal pass.

The rule has focused local evidence in `test_database.py` and `test_learning_workspace.py`. Production remains unverified.

## 3. Additive migration plan

Actual table/column names are finalized test-first; numbers below are allocation intent, not yet-existing migrations.

| Migration range | Intended additive scope | Backfill rule |
|---|---|---|
| 013 (implemented) | DocumentVersion, DerivedArtifact and chunk source provenance | one immutable version per existing document; bind every existing chunk without rewriting bytes/chunks |
| 014 (implemented) | MaterialEvidence, Registry/aliases/lineage, normalized Spec items, TreeVersion/Membership and prerequisite edges | preserve existing node/Spec IDs; draft official trees stay invisible; no global name merge or automatic publication |
| 015 (implemented) | TeachingPlan/preference versions, cache identity, normalized Plan units/links, exact delivery evidence and safe model-run evidence | retain JSON Spec and old journeys; old coverage becomes `LEGACY_PRESERVED`, never silently reclassified as validated |
| 016 (implemented) | Problem index/revisions/images/knowledge links/attempt exposure and hardened Bridge context | preserve current problem/solution/step/bridge IDs; backfill as `LEGACY_PRESERVED`, never silently validate |
| 017 | Assessment pool/blueprint/session/attempt/performance | no legacy grade inference; all users begin `NOT_ASSESSED` |
| 018 | GradePolicy/GradeSnapshot | missing A-/thresholds stored null/unconfigured; no default official policy |
| 019+ | Publication review snapshots/grants/outbox/audit hardening | no existing private data auto-published |

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
  --target work/v3-migration-rehearsal-08
```

This command creates a private local copy and therefore must not be run in a directory that is synced/published. The target must be a fresh name; `-08` is only the next example after the retained `-07` evidence. Do not paste `migration-evidence.json` if future revisions include identifiers; inspect its schema first. The existing rehearsal does not copy uploads and is not a full-site restore drill.

The 2026-09-12 Stage 4 `v3-migration-rehearsal-07` run opened the current source database through SQLite read-only URI mode, copied it with SQLite online backup, initialized twice and reported:

```text
old_rows_unchanged=true
integrity=ok
foreign_key_violations=0
schema_versions=1..16
documents=69
document_versions=69
chunks_without_source_version=0 of 1937
invalid_source_owners=0
problem_index_entries=0; invalid_problem_index_sources=0
learning problems/revisions=2/2
learning solutions/revisions=2/2
learning steps/normalized links=2/2
learning bridges/contexts=2/2
all missing-normalization counters=0
v3_invariants_ok=true
```

The zero problem-index count is an honest source fact: the current 1,937 legacy chunks contain no `question_number` structural metadata, so the migration did not manufacture question identity. The nonzero 2/2 runtime counts prove the legacy normalization assertions were not vacuous. These remain aggregate local-copy facts only. Upload bytes were not copied and no application smoke was run against the copy. The source hash was unchanged across rehearsal and the source remained at versions 1–15; who previously applied 11–15 is unknown.

The same fresh `-07` copy then ran `scripts/validate_v3_cs3481_subset.py`. It bound two existing CS3481 Chunk/version references to a three-node DRAFT fixture, kept reviewer fields null, separated two hierarchy edges from one prerequisite edge, and confirmed that the learner view still returned `NO_REVIEWED_TREE`. This validation makes zero model calls and refuses database paths outside ignored `work/`. It is a Schema/provenance rehearsal, not approval of the fixture as official course content.

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
SOURCE MIGRATIONS REVIEWED: 011–016 for the current Stage 1–4 slices
SYNTHETIC MIGRATION VERIFIED: 011–016, including repeat initialization
REAL-DATA COPY MIGRATION VERIFIED: current source 1–15 to isolated copy 1–16; must rerun for every later final Schema
ISOLATED FULL RESTORE VERIFIED: not yet
PRODUCTION MIGRATION VERIFIED: not verified
PRODUCTION ROLLBACK DRILL VERIFIED: not verified
```
