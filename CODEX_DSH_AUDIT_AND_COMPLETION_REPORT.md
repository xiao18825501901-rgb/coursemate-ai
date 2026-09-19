# CourseMate — independent DSH audit and completion report

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
  publication remains subject to an observed external lock/permission failure.

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
