# Compact-map and OSS migration / rollback evidence

Status date: 2026-09-28

Production mutation status: **NOT RUN**

## Additive schema sequence

| Schema | Purpose | Existing-data behavior |
|---|---|---|
| 56 | 50-member insert/move and activation guards | Existing over-limit trees remain readable; they cannot be newly activated |
| 57 | storage objects, direct-upload sessions, capacity reservations, migration receipts | Existing `documents.stored_path` remains valid; local is still the default backend |
| 58 | compact old→new lineage, primary Pair choice, per-tree receipt | Does not rewrite old nodes, Pairs, transcripts, progress, grades, or assessments |
| 59 | immutable document-version linkage for object and migration rows | Additive nullable linkage with unique canonical/migration indexes |

Database initialization contains guarded ALTER handling for the columns that
SQLite cannot add idempotently via a replayed SQL file. Migration files already
applied are not renumbered or rewritten.

## Local evidence

The source test suite covers:

- exact 50 accepted, 51 rejected in service and SQLite activation paths;
- whole-course outline budgeting and final-unit-only Spec compilation;
- same-corpus over-limit targets receiving a compact builder identity;
- exact/many-to-one/unmapped lineage and compact receipt counts;
- old progress projection without fabricated `LEARNED` or grade;
- primary Pair selection with all other histories retained separately;
- active assessment tree/Spec pinning;
- direct upload with SHA/size verification, duplicate/race behavior, and orphan
  receipt preservation;
- OSS Range preview, parse hydration capacity, immutable migration, dual-read,
  isolated restore, and manifest-complete backup archive.

Final backend regression for the frozen application SHA completed with 1,958
passed, 3 platform/optional-dependency skips, and 4 deprecation warnings in
1,706.60 seconds. Web tests passed 138, Agent tests passed 98, and browser tests
passed 4. TypeScript typecheck and the production web build also passed.

The final counts and SHA are recorded in
`FINAL_COMPACT_MAP_OSS_RELEASE_REPORT.md`. Local synthetic evidence is not
production evidence and does not populate the production mapping JSONL.

The previous production source `b80d803` was exported and checked against a
fresh database migrated by the current candidate. The old release imported,
opened, read, and wrote schema 59 successfully; integrity was `ok`, foreign-key
violations were `0`, no expected table/column/type/check enum was incompatible,
and the assessment pool predicate was byte-identical. Verdict:
`ROLLBACK_SAFE_WITH_MIGRATED_DB`. Machine-readable evidence is in
`evidence/ROLLBACK_COMPAT_B80D803.json`. This does not replace the required
pre-migration backup.

## Production preflight evidence

Read-only verification found:

- application release: `/srv/coursemate/releases/b80d803`;
- live database: `/srv/coursemate/data/releases/20260919T202006Z/rag.sqlite3`;
- schema: 55; integrity check `ok`; foreign-key violations `0`;
- automatic model work disabled with
  `AUTO_KNOWLEDGE_MAP_ALLOW_BILLABLE=false`;
- 14 effective knowledge trees over 50 members;
- root filesystem available: 971,333,632 bytes;
- no usable production OSS configuration or attached runtime role evidence.

No schema, file, object, model, service, or application write was performed as
part of this release attempt. The former trees remain the effective learner
views. Production compact-map after counts and object migration totals are
therefore `NOT RUN`.

## Required migration rehearsal

After capacity and OSS prerequisites are satisfied:

1. Drain writes and preserve model/ingestion receipts.
2. Create a consistent pre-migration recovery unit; archive and isolated-
   restore it according to `OSS_STORAGE_AND_UPLOAD_RUNBOOK.md`.
3. Rehearse schemas 56–59 against the restored copy. Run integrity, foreign-key,
   50/51, local-read, OSS-read, and rollback-compatibility checks.
4. Deploy application code with billable auto-map work disabled and local
   reads still available.
5. Migrate one explicit immutable document version; verify full SHA-256, size,
   OSS version identity, references, Range preview, download, and isolated
   restore. Do not delete its local copy.
6. Compact one non-active canary. Verify source denominator, mapping totals,
   Spec reuse/recompile decisions, Pair/progress/grade/assessment semantics,
   then activate atomically.
7. Expand in bounded batches. Reconcile every course before resuming the paused
   campus/import queue under builder V5.

## Rollback boundaries

### Before schema application

Stop and retain the current production release/database. No rollback action is
needed because this candidate has not touched production.

### After additive schema, before activation

Stop workers and direct-upload issuance, select the prior immutable application
release, and keep the upgraded database. Old trees and local `stored_path`
remain readable. Schema 56 intentionally prevents new over-limit activation;
do not remove this safety trigger merely to run old builder V4.

### After object copy, before local deletion

Set `STORAGE_BACKEND=local`, restart only after configuration validation, and
continue using local originals. Preserve OSS objects and receipts for audit;
object copy does not alter chunks or trigger re-Embedding/compaction.

### After compact activation

Atomically restore the previously effective tree activation. Existing Pairs,
transcripts, grades, and assessment pins still reference their immutable old
versions. Do not delete the compact version; retire it and retain lineage for
audit.

### Database restore

Use only a pre-verified recovery unit and a maintenance window. Restoring an old
database after accepting new uploads/messages would discard those writes, so
first drain and separately preserve/replay the new immutable receipts. Restore
into isolation, verify hashes, integrity, foreign keys, document/object
references, and application compatibility, then switch paths atomically.

## Explicitly prohibited rollback shortcuts

- editing or deleting applied migration numbers;
- dropping the 50-member guard to reactivate a legacy graph;
- treating ETag as MD5 or HTTP 200 as restore proof;
- deleting local originals before object and recovery verification;
- clearing WAL/backups/staging to manufacture free space;
- touching Owner sources under `D:\Canvas` or `D:\Canvas-DG`;
- retrying an `UNKNOWN` paid operation with the same identity.
