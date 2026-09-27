# CourseJesus compact-map and storage implementation state

Status date: 2026-09-28 (Asia/Shanghai)

## Current verified baseline

- Working tree: `work/auto-knowledge-map-20260927/candidate`
- Branch: `feature/compact-map-oss-20260928`
- Source baseline: `b80d803bef52671676236647f6ee3326cc4db74b`
- First compact-map commit: `7da442c`
- Preserved user-owned untracked path: `apps/web/public/downloads/`
- Production application host was identified from host key, ECS metadata,
  active units, release symlink, and live database—not from the SSH alias name.
- Verified production host: ECS `47.114.34.175`, `cn-hangzhou-k`, active
  `coursemate-rag` and `coursemate-agent`, release symlink ending in `b80d803`.
- Verified production database before the pause: schema 55 at
  `/srv/coursemate/data/releases/20260919T202006Z/rag.sqlite3`.
- The production filesystem had about 927 MiB free. This is below the new
  reserve policy, so no bulk extraction, database copy, full-library staging,
  or resumed automatic generation is allowed yet.
- The public apex resolved to Netlify at the check time. The `rag` and `agent`
  subdomains did not resolve from the checking machine and remain a separate
  deployment fact to reconcile before release acceptance.

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

## Implemented so far

Schema 56 and the application now enforce a product-wide limit of 50 stored
members in a materialized knowledge-tree version. Every COMPOSITE chapter,
ATOMIC unit, and explicitly stored root consumes one slot. Source chunks,
citations, pages, questions, and document locators do not.

The database also prevents an over-limit historical tree from newly becoming a
published, personalized-active, or auto-active learner default. Historical
versions remain readable until controlled compaction and lineage mapping are
complete.

Verification attached to commit `7da442c`:

- exact 50-member personalized tree: accepted;
- 51-member personalized tree: rejected with `TREE_NODE_LIMIT_EXCEEDED`;
- direct 51st membership insert: rejected by SQLite trigger;
- official plan containing 7 chapters plus 44 units: rejected before model use;
- `test_knowledge_registry.py` plus
  `test_official_knowledge_course_builder.py`: 20 passed.

## Ordered implementation slices

1. Replace the per-shard micro-node planner with one frozen course outline and
   node budget, map every readable source segment into that outline, and compile
   Teaching Specs only for the final ATOMIC units.
2. Add versioned compaction lineage, frozen legacy-to-unit mappings, progress
   evidence projection, primary Pair selection, and active-assessment pinning.
3. Make every resolver and learning/problem/assessment entry point consume the
   same activated unit, objective, and tree version.
4. Add `StorageBackend`, a local implementation, private Aliyun OSS
   implementation, scoped direct-upload sessions, verified promotion, ranged
   reads, cache reservations, and recovery receipts.
5. Migrate old objects by dual-read and per-object verification. Never delete a
   local canonical copy until immutable OSS, references, backup restore, and
   fallback have all passed.
6. Rehearse and deploy schema/application changes; then compact and reconcile
   each eligible production course. Resume paused campus work only under the
   new planner and capacity rules.

## Current stop conditions

- Do not resume billable legacy builder version V4.
- Do not use the sub-gigabyte production disk for bulk copies or extraction.
- Do not purchase or create OSS resources without verifying an existing
  authorized bucket/role or obtaining the narrowly required resource approval.
- Do not delete WAL, the only recovery point, user originals, or Owner copies
  under `D:\Canvas` and `D:\Canvas-DG`.
