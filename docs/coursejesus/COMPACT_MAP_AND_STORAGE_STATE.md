# CourseJesus compact-map and storage implementation state

Status date: 2026-09-28 (Asia/Shanghai)

## Current verified baseline

- Working tree: `work/auto-knowledge-map-20260927/candidate`
- Branch: `feature/compact-map-oss-20260928`
- Source baseline: `b80d803bef52671676236647f6ee3326cc4db74b`
- Application release candidate: `5a3c1070c2753083a1a9032de96d136c28eda6d7`
- First compact-map commit: `7da442c`
- Preserved user-owned untracked path: `apps/web/public/downloads/`
- Production application host was identified from host key, ECS metadata,
  active units, release symlink, and live database—not from the SSH alias name.
- Verified production host: ECS `47.114.34.175`, `cn-hangzhou-k`, active
  `coursemate-rag` and `coursemate-agent`, release symlink ending in `b80d803`.
- Verified production database before the pause: schema 55 at
  `/srv/coursemate/data/releases/20260919T202006Z/rag.sqlite3`.
- At `2026-09-27T19:31:05Z`, the production root filesystem reported
  41,882,943,488 bytes total and 971,333,632 bytes available. The required
  reserve is 10,737,418,240 bytes before any task peak or outstanding
  reservation. The pre-task shortfall is therefore 9,766,084,608 bytes.
- No private OSS bucket, OSS application settings, attached ECS RAM role, or
  OSS command-line credential path was available to the production runtime.
  Production storage migration and application deployment were not attempted.

## Paid-work boundary pause

The legacy automatic map worker is safely paused:

1. The one RUNNING job and ten QUEUED jobs were marked `SUPERSEDED` with
   `SUPERSEDED_FOR_COMPACT_POLICY`; immutable job receipts retain the reason,
   frozen source snapshot, and model ledger.
2. The in-flight `SEND_INTENT` was not killed. Its response and repair artifact
   were allowed to persist, and no next source shard was started.
3. The attempt ledger was checked until there were no `SEND_INTENT` or
   `RESPONSE_UNKNOWN` rows.
4. `AUTO_KNOWLEDGE_MAP_ALLOW_BILLABLE=false` was written atomically to the
   active non-secret environment file. A root-only pre-change copy remains at
   `/etc/coursemate/rag.2d11587.env.pre-compact-20260927T163549Z`.
5. Only `coursemate-rag` was restarted; health returned `ok`. The learner read
   path and agent service remain available.

The pause does not claim that old jobs are migrated. It prevents additional
legacy granularity and spend while preserving every existing artifact and
UNKNOWN boundary.

## Source implemented

Schema 56 and the application enforce a product-wide limit of 50 stored
members in a materialized knowledge-tree version. Every COMPOSITE chapter,
ATOMIC unit, and explicitly stored root consumes one slot. Source chunks,
citations, pages, questions, and document locators do not.

The database also prevents an over-limit historical tree from newly becoming a
published, personalized-active, or auto-active learner default. Historical
versions remain readable until controlled compaction and lineage mapping are
complete.

The release candidate also contains:

- a V5 whole-course outline planner that freezes the corpus, assigns one
  course-wide node budget, maps every readable segment, and compiles Specs only
  for final ATOMIC units;
- schema 58 immutable old-node/objective lineage, progress evidence projection,
  one-primary-Pair selection, associated-history preservation, and active
  assessment version pinning;
- resolvers that prefer the activated compact successor while retaining legacy
  versions for history;
- schema 57/59 storage object, upload-session, orphan, migration, restore, and
  document-version linkage ledgers;
- local and Aliyun OSS `StorageBackend` implementations, quarantine direct
  upload, canonical promotion, full SHA-256/size/version verification, Range
  reads, capacity admission, dual-read migration, and backup archive restore;
- administrator streaming ingestion that sends file paths directly to OSS and
  retains an auditable orphan receipt if database admission loses a race.

The following boundary checks are covered by local tests:

- exact 50-member personalized tree: accepted;
- 51-member personalized tree: rejected with `TREE_NODE_LIMIT_EXCEEDED`;
- direct 51st membership insert: rejected by SQLite trigger;
- official plan containing 7 chapters plus 44 units: rejected before model use;
- old progress is projected as evidence but does not synthesize `LEARNED` or a
  grade for a merged unit;
- separate Pair transcripts remain separate while one Pair is selected primary;
- an active assessment stays pinned to its original tree and Spec;
- direct upload and migration reject hash/size mismatches and cannot use a
  multipart ETag as content integrity evidence;
- Range preview does not hydrate the full object or consume the parse cache;
- low-space admission leaves the configured reserve intact;
- backup archive rejects any unmanifested artifact and restore verifies every
  byte in an isolated directory.

## Production inventory requiring compaction

The read-only production inventory contains 14 effective trees over the cap.
The largest are 1,515, 1,171, 988, 979, and 935 nodes. The three historical
Database System private trees contain 979, 536, and 310 nodes. Exact tree IDs,
course IDs, chapter/unit/Spec counts, and the explicit `NOT_RUN` result are in
`LEGACY_NODE_AND_OBJECTIVE_MAPPING.jsonl`.

No production compact successor exists yet. Consequently, production after
counts, lineage rows, Spec reuse rates, and model usage are `NOT RUN`, not zero.

The preserved legacy ledger contains 3,844 `ACCEPTED`, 268
`BUSINESS_REJECTED`, and 163 `CONTRACT_REJECTED` attempts; it contains no
`SEND_INTENT` or `RESPONSE_UNKNOWN` row at the observation point. Existing job
rows report 3,564 base model calls and 33 repairs, with 2,465 section-map and
1,380 Teaching-Spec artifacts. These are historical V4 facts, not V5 spend.
Production has zero compact/V5 jobs and zero compact/V5 model calls; the reuse
rate remains `NOT RUN` until a safe canary compaction is executed.

## Deployment order after the external gate is cleared

1. Expand the system disk or otherwise provide enough working space so
   `free - outstanding reservations - task peak >= 10 GiB`.
2. Create/identify a private `cn-hangzhou` OSS bucket and attach a prefix-scoped
   ECS RAM role; do not send long-lived access keys through chat or env files.
3. Create a fresh consistent backup, archive and isolated-restore it to OSS,
   then rehearse schemas 56–59 on the restored copy.
4. Deploy code with billable auto-map work still disabled; verify local and OSS
   dual-read, Range preview, direct upload, and rollback health.
5. Migrate one immutable original and one backup recovery unit, verify full
   hashes and references, then expand the batch gradually. Keep server copies.
6. Compact one non-active canary tree, validate mapping/coverage/history, and
   only then atomically activate per course. Resume campus work after all gates.

## Current stop conditions

- Do not resume billable legacy builder version V4.
- Do not use the sub-gigabyte production disk for backup creation, bulk copies,
  extraction, database migration rehearsal, cache hydration, or deployment.
- Do not switch `STORAGE_BACKEND` to OSS until a same-region private bucket,
  scoped instance role, object restore proof, and local fallback are verified.
- Do not delete WAL, the only recovery point, user originals, or Owner copies
  under `D:\Canvas` and `D:\Canvas-DG`.
- Do not describe this candidate as production deployed or production accepted.

## Frozen local verification

Application SHA `5a3c1070c2753083a1a9032de96d136c28eda6d7` passed:

- backend: 1,958 passed, 3 skipped, 4 warnings;
- Web: 31 files / 138 tests;
- Agent: 13 files / 98 tests;
- browser: 4 tests;
- TypeScript typecheck, production build, PAT bundle scan, Python compile, and
  scoped Ruff fatal/error checks.

Rollback compatibility with production source `b80d803` is
`ROLLBACK_SAFE_WITH_MIGRATED_DB`; a verified pre-migration backup is still the
primary rollback path.
