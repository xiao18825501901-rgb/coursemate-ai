# CourseMate — independent DSH audit and completion report

## Long-course-name closure — 2026-09-20 (current)

Application candidate / tested code: **`73b7049ee3204d5c213ad70c67db9b892aa306bf`**, branch `fix/codex-dsh-audit-20260919`. Start HEAD `20b45fb`, clean; local commit only. The explicit long-name creation defect below is now **FIXED**, not still excluded from scope. Names retain the UI's existing validation and full display text; new private-course IDs are independent 39-character ASCII UUID identifiers with at most 3 transactional collision attempts. Existing IDs and deterministic share/recipient mappings are unchanged. No new Schema migration.

Real integrated HTTP RED: 10 pass / 8 fail; real browser form RED: 500 instead of201 for100-character name. Final focused tests:19 passed, with 422 invalid inputs, concurrent same names, private isolation, bounded collisions/no leftover pins, quota propagation and long-name snapshot original/copied file bytes. Same frozen code: **676 backend passed (755.03s, 0 failures/errors/skips, 2 existing dependency deprecation warnings), 14 browser passed (48.2s, no skips/failures/flaky), Web60, Agent66, typecheck/build PASS**. These are fresh final-version executions, not borrowed historical counts.

Windows bounded restore, explicit resume, new-protocol PREPARING and sidebar implementations are unchanged; native WSL ext4 evidence remains valid for unchanged code, not a new ECS/Linux execution. Original Windows attribution and historical embedding provenance stay UNKNOWN; DrvFS stays unsupported. Original failure XML and all RED runs remain intact. No new confirmed in-scope application defect is left open; this is not a fresh whole-system audit or a claim of zero possible bugs.

**SOURCE IMPLEMENTED / OFFLINE CONTRACT VERIFIED / REAL LOCAL V3 INTEGRATION VERIFIED / BROWSER VERIFIED. LIVE MODEL, REAL CLERK/QUALIFICATIONS/MESSAGES/SHARES, PRODUCTION ACCESS AND DEPLOYMENT: NOT RUN / NOT AUTHORIZED.** Local build is not a production-configured publish artifact. No push, reembedding, deployment or real-account operations were performed.

Full commands, SHA/doc identity and results: [LONG_COURSE_NAME_FIX.md](docs/codex-audit/LONG_COURSE_NAME_FIX.md). Separate A–K permission cards: [PRE_DEPLOYMENT_ACCESS_AND_APPROVALS.md](docs/codex-audit/PRE_DEPLOYMENT_ACCESS_AND_APPROVALS.md). Next owner decision: confirm existing domains and optionally approve **A only (fixed unauthenticated HTTPS reads)**; no secrets in chat.

## Recovery-gate continuation — 2026-09-20 (prior frozen-code record)

Frozen implementation: `dcfd3221ce12170521807e4b1c52fcc2003cbd0b` on the same D-drive audit branch. Local checkpoints: `3879274` Windows bounded publication/Linux tests, `bab5683` sidebar display, `dcfd322` controlled interrupted-send recovery. No push or deployment.

Windows fresh top-level recovery now passes local tests with bounded WinError 5/32 handling (5 attempts, 1.5 seconds total waiting, every denial logged). Persistent denial still preserves staging and requires explicit verified resume. One actual fresh invocation logged denial then success after 0.1s; application-resource closure is independently tested. **The original OS denial's cause/locker is UNKNOWN**, not proved antivirus or an external process. Original 645-pass/2-fail XML and recovered original directories remain preserved. The historical body below is not rewritten as all-green.

Controlled PREPARING recovery validates frozen files/indexes/recipients under OS-owned exclusion, never re-reads latest source, publishes ready/notices atomically and refuses incomplete or unsupported legacy snapshots. Dedicated HTTP-worker abrupt exits plus repeated/all-task cancellation tests pass; only owned synthetic workers exit. No Schema migration was added. Sidebar name/code wrapping is browser-verified without ID changes.

Real local Linux ext4: **7 passed**; WSL DrvFS: **4 passed / 3 failed (EINVAL)**, retained and not presented as supported. Historical embedding lineage remains UNKNOWN: read-only local main-file metadata inspection found 1,937 chunks without recorded source metadata. No live/production inference.

Final same-commit browser: **13 passed in 49.6s**, zero failures/skips/flaky; Web **60 passed**, Agent **66 passed**, typechecks/builds passed. Full frozen-version backend regression: **657 passed, 0 failed, 0 skipped**, 2 dependency deprecation warnings, 596.29s (`work/codex-audit/recovery-final-regression.xml`). The final code includes the prior knowledge-export consistency fix.

Disposition: **local limited-scope work complete with documented limitations; not production accepted**. No new local administrator/install action is needed. Await separately scoped external authority rather than repeatedly rerunning unchanged tests. Original Windows denial attribution and historical embedding provenance remain UNKNOWN; DrvFS and the separate long-name creation defect are not represented as fixed.

Detailed commands, retained evidence, controlled recovery operator card, migrations/rollback, provenance policy and remaining boundaries: [RECOVERY_GATE_AND_REMAINING_STATUS.md](docs/codex-audit/RECOVERY_GATE_AND_REMAINING_STATUS.md).

Real Qwen, Clerk sync, qualification writes, real messages/shares and production remain **NOT RUN / NOT AUTHORIZED**. Separate scope finding: direct course creation with a long accepted name can generate an overlong ID and return 500; retained as an out-of-scope defect, not hidden or called fixed.

## Historical completion snapshot (retained)

2026-09-19 · **Local implementation delivered; Windows first-attempt recovery gate remains open. Not production accepted.**

## Scope and factual baseline

Source root: `D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY`.
Branch: `fix/codex-dsh-audit-20260919`.
Retained DSH HEAD: `9104b5ae5cc767a57d804131b01b925728552cb5`.
Local recoverable implementation checkpoints (not pushed): backend `7126a05`,
web/browser `99f0d0a`, backup/restore `1227d6a`. These commits preserve the tested
working-tree implementation; they do not create new live/production evidence.
Original DSH feature and follow-up commits were not reset, rebased or overwritten.
The owner explicitly confirmed DSH stopped editing. No claim is made that unrelated
processes on the machine were terminated. The old C: repository was not modified.

Authoritative audit specification: `COURSEMATE_CODEX_AUDIT_AND_FINISH_PROMPT.md`,
SHA256 `CB2F0F4766676329B8F6C51DFC431DC1A3B6F5678597DBEEFA08E54BCADD5753`,
plus the latest continuation attachment. Original Word resources were read only.
The Downloads `粘贴的文本 (1).txt` is an older September 12 requirements document,
not assumed to be a current DSH report. DSH claims were instead located in
`COURSEMATE_MODIFICATION_REPORT.md` and `docs/current-change/`.

Current online source, provider/account, data and deployment state: **UNKNOWN**.
This authorization excluded production access, real model costs, Clerk sync,
actual qualification changes/messages/shares, Git push and website deployment.
None was performed. Historical canary budgets were not reused.

## What changed

- Integrated sharing now freezes authorized file versions, original bytes and
  parsed indexes, verifies hashes, imports through the V3 ingestion service and
  persists recipient-owned document/version/chunk mappings. Actual V3 retrieval,
  preview and download use the recipient course; sender deletion does not remove
  the copied files. Course/private corpora stay separate, including equal bytes.
- Durable import receipts preserve one course per share/recipient through partial
  failure, concurrent joins and quota-boundary retries. History imports remap
  citations, attachments, exercises, answer/reveal versions and cached step
  explanations; unmappable references are unavailable, not sender-private URLs.
- Knowledge nodes/specifications/tree membership/prerequisites and classification
  versions copy independently of grades and teaching coverage. History and
  knowledge export use stable read transactions. Invalid/missing specifications
  remain unavailable/DRAFT; sharing does not invent completed learning.
- Send replay rejects changed payloads, resumes caught failures against the frozen
  manifest, and publishes ready status with recipient notices transactionally.
  Selected history requires valid bound Pairs; unbound history belongs to “all”.
- Authorized parsed bodies and version evidence drive bounded classification.
  Persisted claims reject stale worker results; newest pending work is retained;
  manual choices win. Same-name changed-body integration was tested.
- Generated answers remain server-side until reveal, including split markers,
  malformed responses, run reads, SSE/replayed legacy events and history. Plan
  events/errors use closed public projections. No perfect model anti-extraction
  claim is made.
- Exercise creation targets the explicit current Pair and real node. First node
  teaching has one durable claim. Legacy lane creation no longer guesses a Pair.
  Browser restore guards prevent late responses replacing newly selected history.
- Supplied problems persist answer/step versions with reveal already granted.
  Explanations enforce reveal, cache by version, validate action payload replay,
  coalesce concurrent requests, support scoped follow-ups and silent cancellation,
  and reconcile terminal run status after restart without overwriting newer runs.
- Directory browsing supports empty/one-character search and pagination with
  opaque IDs. A backend-only paginated Clerk client and protected old-user cutoff
  application have fake-HTTP contracts, not live sync evidence.
- Campus authorization covers original/legacy and refreshed content paths, not
  only file/add buttons. Verification storage no longer logically persists raw
  seven-digit codes; existing tombstones and leading zeros are preserved.
- Inbox tabs now actually switch, lists paginate beyond item 100, attachment
  actions and step movement/resize are keyboard accessible. Step windows use the
  existing safe rich-content renderer. No UI redesign or new agent framework.
- Backups include share archives. Restore publication preserves failed staging,
  refuses overwriting, and supports explicitly verified resume. Windows directory
  publication was subject to an observed denial whose original cause is unknown.

## Verification levels — do not merge these

| Level | Evidence status |
|---|---|
| Source implemented | Listed changes implemented and independently reviewed; limitations below |
| Offline upstream contract verified | Deterministic/fake HTTP provider and directory contracts; no real credentials |
| Real V3 integrated verified | Isolated actual FastAPI/V3 DB/storage/retrieval paths with fake external providers |
| Browser verified | Final expanded12 passed in50.4s, zero skips/failures/flaky; actual local V3/Node and production frontend bundle |
| Real model verified | **NOT RUN / NOT AUTHORIZED** |
| Production deployed | **NOT RUN / NOT AUTHORIZED** |

Final Web tests: **60 passed**; Agent: **66 passed**; typecheck and builds passed.
Backend full third run: **645 passed,2 failed**, both Windows restore-publication
failures. Both exact preserved staging units later completed explicit verified
resume. Their original failures remain in the XML. A subsequent independent
knowledge-export consistency regression passed after its read-transaction fix.
See TEST_REPORT.md for precise code-state qualifications and local artifact paths.

## Review and evidence index

- [Requirement matrix](docs/codex-audit/REQUIREMENT_EVIDENCE_MATRIX.md)
- [Findings and fixes](docs/codex-audit/FINDINGS_AND_FIXES.md)
- [Full Word-template integrity](docs/codex-audit/TEMPLATE_AUDIT.md)
- [Identity storage evidence](docs/codex-audit/IDENTITY_FINDINGS.md)
- [Directory HTTP contracts](docs/codex-audit/DIRECTORY_UPSTREAM_FINDINGS.md)
- [Pair lifecycle regressions](docs/codex-audit/PAIR_LIFECYCLE_FINDINGS.md)
- [Migration and rollback](docs/codex-audit/MIGRATION_AND_ROLLBACK.md)
- [Test report](docs/codex-audit/TEST_REPORT.md)
- [External actions](docs/codex-audit/EXTERNAL_ACTIONS.md)

Raw local XML/browser traces and screenshots stay under the ignored project-owned
`work/codex-audit/` directory. They contain synthetic data only and are not deployed.

## Remaining boundaries

Do not approve production until the recovery gate is resolved and external
actions are independently approved. Windows backup/restore publication can fail
with WinError 5; the original locking process is unidentified. Tests preserve
that failure rather than bypass it. Linux no-overwrite publication is contract-
tested here, not Linux-runtime-tested. Historical embedding provenance cannot be
proved from a configured model label. A process killed during a PREPARING send
needs controlled stuck-build recovery; no incomplete send is announced as ready.
A minor visual issue remains: long generated shared-course codes clip in the
narrow sidebar; this does not prevent opening or using the copied course.

No real learning data was used to test migrations, no production schema version
is inferred, no code/DB rollback was performed on actual users, and no success
was manufactured by removing tests or globally granting campus access.
