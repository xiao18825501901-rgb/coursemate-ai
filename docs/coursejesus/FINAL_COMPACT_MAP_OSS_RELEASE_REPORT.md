# CourseJesus compact-map and OSS release report

Report date: 2026-09-28 (Asia/Shanghai)

Branch: `feature/compact-map-oss-20260928`

Application release SHA: `5a3c1070c2753083a1a9032de96d136c28eda6d7`

Production deployment: **BLOCKED — NOT DEPLOYED**

## Executive result

The source release candidate implements the requested whole-course compact map,
hard 50-node enforcement, old-node/history lineage, immutable object storage,
direct OSS upload, capacity gates, dual-read migration, and verified backup
archive/restore. It does not merely hide or truncate old nodes.

Production acceptance is not claimed. The verified production server remains on
`b80d803` / schema 55, has only 971,333,632 bytes available, and exposes no
usable private OSS runtime role/configuration. The required reserve alone is
10,737,418,240 bytes. Deploying, copying a new backup, rehearsing migration, or
resuming model work on that filesystem would violate the release policy.

## Source implementation

### Maximum 50 materialized nodes

- Schema 56 rejects the 51st membership, movement into a full tree, and new
  official/personalized/automatic activation over 50.
- All COMPOSITE chapters, ATOMIC learning units, and any stored root count.
- Effective official, AI campus, private, shared-snapshot, and overlay views use
  the same limit.
- The V5 builder freezes the complete readable corpus, plans one whole-course
  outline and quota, maps all source segments, then compiles Specs only for
  final ATOMIC units.
- Source documents, chunks, pages, citations, examples, questions, and detail
  remain in evidence/RAG/Specs and do not become hidden navigation nodes.
- Empty/unreadable/partial courses surface explicit waiting/exception states;
  they do not receive fake “chapter 1” nodes.

### Legacy preservation and learner behavior

- Schema 58 records immutable `EXACT`, `MERGED_INTO`, `RELATED`, or `UNMAPPED`
  lineage and a per-tree reconciliation receipt.
- Exact compatible nodes/Specs and prior paid artifacts can be reused; merged
  units receive a new bounded objective contract rather than one hundred copied
  micro-objectives.
- Old tree versions remain readable. Activation is atomic only after count,
  source coverage, provenance, permission, hierarchy, Spec, and mapping checks.
- Old learning-start evidence may project to the successor. `LEARNED` is never
  synthesized unless every new REQUIRED objective has valid coverage; grades
  are not averaged or fabricated.
- All old Pairs/transcripts remain separate. One deterministic Pair becomes
  primary and the rest remain associated history.
- Active assessments remain pinned to their original questions, tree, Spec,
  and grading contract.
- Teaching, `做一题`, and N-question assessment resolve the compact unit,
  objective, and tree version together.

### 100 GiB-class object path

- `StorageBackend` has local and Aliyun OSS implementations.
- Web uploads use short-lived, object-scoped quarantine grants when OSS is
  active; local deployments receive an explicit successful fallback descriptor
  rather than a noisy expected 409.
- Backend promotion validates actual full SHA-256, size, version identity, and
  authorization. Browser claims and multipart ETag are never trusted as MD5.
- Admin/campus file paths stream to OSS and still reuse the existing ingestion
  service. A sealed multi-file batch triggers one compact build.
- Upload, preview/Range, download, citation reads, Canvas import, share
  snapshots, problem/assessment attachments, migration, and backups are wired
  through durable object/version identities.
- Remote Range preview avoids full-object cache hydration. Full parsing is
  capacity-admitted against the 10 GiB / 20% reserve formula.
- Existing local originals remain dual-readable. Moving storage does not change
  source hashes, re-Embed content, or trigger a course rebuild.
- Backup archival requires complete manifests and an isolated byte-for-byte
  restore before it can justify any later cleanup.

## Production inventory and reconciliation status

Read-only production inventory found 14 effective over-limit trees containing
9,427 materialized nodes: 2,280 COMPOSITE and 7,147 ATOMIC. They also contain
7,147 assigned Specs. Largest before counts are:

| Course/tree | Before nodes | Before Specs | After nodes | Status |
|---|---:|---:|---:|---|
| PHY1201 auto campus | 1,515 | 1,167 | — | NOT RUN |
| GE2340 auto campus | 1,171 | 878 | — | NOT RUN |
| GE2248 auto campus | 988 | 729 | — | NOT RUN |
| Database System private | 979 | 733 | — | NOT RUN |
| MA1200 auto campus | 935 | 750 | — | NOT RUN |

All 14 exact IDs and before counts are in
`LEGACY_NODE_AND_OBJECTIVE_MAPPING.jsonl`. Every compact successor/mapping field
is deliberately null/`NOT_RUN_PRODUCTION_CAPACITY_BLOCKED`; no fake “after”
value is reported.

Historical V4 evidence remains intact: 3,844 accepted, 268 business-rejected,
and 163 contract-rejected attempts; 3,564 base calls and 33 repairs are recorded
on job rows; 2,465 section-map and 1,380 Spec artifacts remain stored. No
`SEND_INTENT` or `RESPONSE_UNKNOWN` was present at the read-only observation.

This implementation made **zero real model calls**. Production has zero V5/
compact jobs and zero V5/compact model calls. Actual V5 usage, new Spec count,
paid-artifact reuse count, and reuse rate are `NOT RUN`, not zero.

## Verification

| Gate | Result |
|---|---|
| Focused compact-map/storage/migration suite | 130 passed, 1 warning |
| Original five full-suite failures after diagnosis | 30 targeted checks passed, 1 warning |
| Final backend suite | 1,958 passed, 3 skipped, 4 warnings |
| Web unit/component suite | 31 files, 138 passed |
| Agent suite | 13 files, 98 passed |
| Browser suite | 4 passed |
| TypeScript typecheck | passed |
| Production web build + PAT scan | passed |
| Scoped Python Ruff (`F`,`E9`) and compile check | passed |
| Rollback compatibility with `b80d803` | `ROLLBACK_SAFE_WITH_MIGRATED_DB` |

The first browser run exposed a stale Vite executable path and then an expected
local-storage direct-upload 409 that polluted the browser console. The path was
corrected; local storage now advertises an explicit fallback contract; the
unchanged end-to-end scenario then passed 4/4.

The initial full backend run reported 1,952 passed, 3 skipped, and 5 failed.
Those failures were individually reproduced and corrected: local same-size
tampering is hash-checked in detail metadata; prompt manifest hashes normalize
Windows newlines; the optional Jev transport test injects its contract module;
and the Bridge schema test distinguishes an irreversible CourseJesus-issued
verifier hash from a Canvas credential. The final complete rerun completed in
1,706.60 seconds and is authoritative for application SHA
`5a3c1070c2753083a1a9032de96d136c28eda6d7`.

## Rollback evidence

The previous `b80d803` release imported and opened a schema-59 database created
by this candidate, with integrity `ok`, zero foreign-key violations, no missing
or retyped expected fields, no narrowed check enum, and an unchanged assessment
pool predicate. See `evidence/ROLLBACK_COMPAT_B80D803.json`.

Code-only rollback is therefore locally compatible, but the primary production
rollback remains a fresh pre-migration backup. Local storage remains available
during object dual-read. A compact activation can be reversed to its prior tree
without deleting either version, mapping, Pair, transcript, grade, or pinned
assessment.

## Production stop condition and minimum owner action

The current release is stopped before production writes. The owner must use the
Alibaba Cloud console/MFA to:

1. expand instance `i-bp1f0vqhds2341pdqqiy` (`47.114.34.175`, Hangzhou) from
   40 GiB to at least 80 GiB, then ensure the guest filesystem satisfies
   `free - reservations - task peak >= 10 GiB`;
2. create or nominate a private Standard OSS bucket in `cn-hangzhou`, with
   public access blocked, encryption enabled, and non-destructive lifecycle;
3. attach an ECS-trusted, bucket/prefix-scoped RAM role;
4. provide only the non-secret bucket/endpoint/prefix/role identifiers through
   a protected configuration path—never a key, password, code, or token in chat.

After those facts are available, follow `OSS_STORAGE_AND_UPLOAD_RUNBOOK.md`:
fresh backup → OSS archive → isolated restore → schemas 56–59 rehearsal →
code deploy with billable work off → one object canary → one non-active compact
tree canary → gradual migration/activation → per-course reconciliation → only
then resume the paused campus queue under V5.

## Release disposition

- Source implemented: **YES**
- Local/fake-provider verified: **YES — all required local gates green**
- Real compact model verified: **NO — no compact paid call was made**
- OSS migration/restore verified against real production bucket: **NO**
- Production deployed: **NO**
- Production compacted/backfilled: **NO**
- Production accepted: **NO**

This stop is intentional protection of originals, backups, database/WAL, model
receipts, and learner history—not a claim that deployment succeeded.
