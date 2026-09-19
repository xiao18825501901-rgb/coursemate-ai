# Recovery gate and limited remaining work

## Latest limited-scope closure — long course names, 2026-09-20

Application/tested code now `73b7049ee3204d5c213ad70c67db9b892aa306bf`. The long-name creation500 previously excluded under sidebar-only scope is now explicitly authorized and fixed, with independent bounded IDs, preserved display names and no new migration. Integrated focused19 passed; final frozen browser14 passed, Web60/Agent66 and typecheck/build passed. Fresh full backend regression: **676 passed, 0 failures/errors/skips, 2 existing dependency warnings, 755.03s** (`long-name-release-regression.xml`/log), not reused657.

The recovery/PREPARING/sidebar code is byte-identical to `dcfd322` (verified by Git path diff); prior Windows/PREPARING/Linux evidence below is retained and not rerun merely to change its date. Linux ext47 remains an earlier real runtime result; DrvFS unsupported, historical embedding UNKNOWN, original Windows denial attribution UNKNOWN. This current continuation does not reopen those investigations.

Application/source, local fake-provider integration and browser evidence are separate from live models/accounts/production, all of which remain NOT_RUN/NOT_AUTHORIZED. [LONG_COURSE_NAME_FIX.md](LONG_COURSE_NAME_FIX.md) is the current candidate/test ledger; [PRE_DEPLOYMENT_ACCESS_AND_APPROVALS.md](PRE_DEPLOYMENT_ACCESS_AND_APPROVALS.md) supplies granular A–K cards. Earlier CURRENT_CODE_SHA/657/13 fields below refer only to that prior frozen implementation.

## Baseline and execution plan

2026-09-19. Source: D:/CourseMate_COMPLETE_ARCHIVE_20260918/01_SOURCE_REPOSITORY.
Branch fix/codex-dsh-audit-20260919, initial HEAD 84d6ee2edf99998237eb6d5ef7a8882faf23461e; clean worktree.
Authority: COURSEMATE_CODEX_RECOVERY_GATE_AND_REMAINING_WORK.md. Local synthetic work only.

1. Preserve original XML; reproduce Windows publication in a new directory; audit application/test resources; add bounded, observable handling only with regression evidence. Gate: fresh top-level restore and retained safe-failure/resume/no-overwrite/hash assertions.
2. Inspect PREPARING recovery; add only controlled frozen-snapshot recovery with exclusion of active workers. Gate: interrupted subprocess and replay tests, no incomplete ready or duplicate notices/course.
3. Execute Linux native no-overwrite and recovery tests in the existing Ubuntu-24.04 WSL environment, no installation or production access. Gate: actual Linux kernel and filesystem evidence, not mocks.
4. Read-only embedding provenance evidence; retain UNKNOWN without recorded lineage. Fix sidebar display only, with browser evidence and unchanged IDs.
5. Freeze final code, run related tests and final regression, review and update reports. External gates remain explicit.

## Original evidence (preserved)

`work/codex-audit/full-regression3.xml`: 645 passed, 2 failed.
Node IDs: `tests.test_backup_ui_extension::test_backup_and_restore_include_the_refreshed_shell_unit` and `tests.test_backup_ui_extension::test_backup_without_the_extension_still_produces_the_original_unit`.
Failures at assertions on lines 102 and 132: child restore returned 2 after WinError 5 from final `os.rename(staging,target)`.
Original staging siblings under `full-regression3/test_backup_and_restore_includ0` and `test_backup_without_the_extens0` ended in `13ada3f11abe467186503598aef5ee2e.partial` and `c12d4454ffc349ff89594b062d99c888.partial` respectively. Previous explicit resume already renamed these to `restored`; those resulting directories and original XML remain preserved. No original staging is falsely claimed still present.

New baseline: `recovery-gate-baseline1.xml`, 3 passed / 1 failed (legacy-unit restore WinError 5). Its staging `.restored.388f4e3940d240e898dd97361774ce43.partial` is retained. The exact origin of the denial is UNKNOWN; neither Defender nor another external process is established. Restore SQLite/tar/file resources have explicit close paths. A test's post-success SQLite query lacks explicit close, but occurs after the failed assertion and cannot explain that failure.

## Current gates

CURRENT_CODE_SHA: dcfd3221ce12170521807e4b1c52fcc2003cbd0b (frozen implementation; later report-only commit may follow)
ORIGINAL_WINDOWS_FAILURES: FAILED, retained
WINDOWS_FAILURE_ROOT_CAUSE: HISTORICAL_UNKNOWN (denied OS publication proved; original locker/cause not identified)
FRESH_WINDOWS_RESTORE: VERIFIED locally, bounded publication handling; not an OS root-cause claim
EXPLICIT_RESUME: VERIFIED with controlled faults and unchanged validation
PREPARING_SEND_RECOVERY: VERIFIED locally for new frozen-intent protocol on abrupt-exit synthetic workers and cancellation regressions; legacy missing-intent recovery refused
LINUX_RUNTIME_RESTORE: VERIFIED on WSL ext4; FAILED on DrvFS, explicitly unsupported in this rehearsal
HISTORICAL_EMBEDDING_PROVENANCE: HISTORICAL_UNKNOWN
SIDEBAR_VISUAL_FIX: VERIFIED, final same-commit browser 13 passed / 0 skipped
FINAL_REGRESSION: VERIFIED — 657 backend passed / 0 failed / 0 skipped, 2 deprecation warnings; final browser 13 passed; Web60, Agent66, typecheck/build PASS
REAL_QWEN: NOT_RUN, not authorized
LIVE_CLERK_SYNC: NOT_RUN, not authorized
REAL_STUDENT_QUALIFICATION_CHANGES: NOT_RUN, not authorized
PRODUCTION_DEPLOYMENT: NOT_RUN, not authorized
NEXT_CONCRETE_USER_ACTION: No required local installation/admin action. External model/account/production actions require a separately scoped approval; no credentials should be pasted into chat.

## Windows diagnosis and acceptance

Original backup sources are `full-regression3/test_backup_and_restore_includ0/backups/coursemate-v2-20260919T114509.280375Z` and `full-regression3/test_backup_without_the_extens0/backups/coursemate-v2-20260919T114511.015625Z`; targets are each parent's `restored`. All paths here are relative to `work/codex-audit/` unless stated otherwise. Original XML retains complete failure text and staging UUIDs above.

Application resource audit now observes every restore SQLite connection, Path-opened file, and tar archive before native publication; all are closed in both original and extended recovery units. The tests use independent tmp directories and synchronous, waited child commands, with no cleanup of the original evidence. The unused post-restore test DB connection is now explicitly closed, a real hygiene correction but not a claimed cause of an earlier failure. Destination races are tested with actual no-overwrite publication. Persistent permissions/locks are not bypassed; no ACL, scanner or system change was made.

The original Windows error remains unattributed. Evidence supports a transient denial in at least one new fresh run, not a named external process: `recovery-resources-green/test_fresh_top_level_command_r0/restore-stderr.txt` records `attempt=1 winerror=5 retry_delay_seconds=0.1`, then `succeeded attempt=2` in the same top-level invocation. The sibling extended-unit run needed no retry. Fresh originals: `recovery-fresh-green1.xml`, 4 passed. No manual resume was used for these successes.

Policy in `ops/restore_v2.py`: retry only native WinError 5/32, at most 5 attempts and 0.1+0.2+0.4+0.8 = 1.5 seconds of total waiting (not a guarantee on total OS-call duration). Every denied attempt is logged. Before each attempt the target must still be absent, and native no-overwrite rename remains authoritative against races. Other errors are not retried. Sustained denial returns failure and retains staging; explicit resume revalidates all bytes/trees/DBs. No copying, repairs, manifest generation or paid calls are replayed by this retry loop.

Root recovery tests: `recovery-root-final.xml`, 33 passed, including resource closure, fresh CLI, bounded persistent failure, target races and all prior hash/resume constraints. The original low-level diagnostic's assertion “closing our handle guarantees immediate raw OS rename succeeds” itself failed again in `recovery-resources-green.xml` (32 pass/1 fail). Its held-handle raw denial assertions are retained; after close it now tests the bounded application publication contract. No safety assertion or original failure record was removed. This is a documented correction of an unproved OS assumption, not evidence that Windows can never deny a later rename.

## PREPARING send recovery and boundaries

New `services/rag-api/app/cm_update/share_recovery.py` supplies a local operator command, default inspection only. It does not initialize a DB, call a provider, read sender source files or create recipient courses. It validates the frozen manifest/archived file set, original-byte SHA/size and integrated index SHA before publishing. The same ready+recipient+notice transaction serves ordinary send and recovery. Existing notice uniqueness and import receipts remain intact.

New sends persist resolved recipient intent and notice text in the existing manifest (`send_recovery.version=1`), before copying. A coarse per-UI-data-directory OS lock excludes another sender/recovery worker; it releases on actual process exit, never because a timestamp expired. A busy sender gets a retryable 503. All processes must run the lock-aware version; do not run the CLI alongside an old binary that ignores the protocol. Legacy PREPARING without the frozen intent is refused for manual offline review, not silently upgraded. Incomplete/invalid archives become `failed` only on explicit apply; no notification is created. The ordinary authenticated same-request retry may still use its pinned version, but this offline recovery tool never fetches a replacement from live source.

Review reproduced two early cancellation defects: repeated caller cancellation and cancellation of all owned asyncio tasks could release exclusion while an OS file thread was still active. Final code drains a shielded executor Future (not a cancellable `to_thread` Task); the lock remains held until I/O actually completes. `shutdown-red.xml` preserves the 1 failed/1 passed reproduction, `preparing-final.xml` has 9 passed, and independent `review-shutdown-fix.xml` has 3 passed/6 deselected. Fault workers call `os._exit(73)` only on themselves; each records PID, parent PID, phase, exact synthetic root and exit code in `owned-worker.json`. No unrelated process was terminated. Actual module CLI inspection was also executed against the completed synthetic share and returned exit0 / status ready / applied false.

The four actual mounted V3 HTTP interruption points are manifest freeze, partial copy, all copies before publication, and after committed publication. Later sender bytes are changed in the synthetic source before recovery; completed archives still publish frozen content, incomplete ones do not. Repeated apply produces one notice/recipient row, no duplicate course/import. A corrupted frozen index is refused. The operator must retain backups before applying this to any real data; none was applied here.

### Local operator card (no production authorization implied)

Target: a verified isolated UI recovery copy, explicitly selected `ui.sqlite3` and share ID. From `services/rag-api`, use the project audit Python:

```powershell
& ../../work/codex-audit/venv/Scripts/python.exe -m app.cm_update.share_recovery --database '<ISOLATED_UI_DB>' --share '<SHARE_ID>'
```

Expected: JSON action `ready` only for complete validated archives, otherwise `failed`, or exit 2 for busy/unsupported legacy state. Default inspection does not change application rows (it may create the lock file). Save the result privately. To apply to the SAME verified isolated copy, append `--apply`. This only publishes that frozen send or marks incomplete PREPARING failed; no fees, no UAC, no source fetch. Stop on unexpected DB path, legacy protocol, active worker or hash failure; do not remove the lock file to bypass exclusion. Production use requires separately approved backup/rehearsal/write scope. No current user action is required for the completed synthetic runs.

## Linux runtime evidence

Existing Ubuntu-24.04 WSL2, Python 3.12.3, kernel `6.18.33.1-microsoft-standard-WSL2`, `/dev/sdd ext4`. Command:

```text
wsl.exe -d Ubuntu-24.04 -- python3 /mnt/d/CourseMate_COMPLETE_ARCHIVE_20260918/01_SOURCE_REPOSITORY/tests/test_recovery_linux_runtime.py --artifact-root /home/austumn/CourseMate-recovery-gate-20260919/linux-runtime-review-02
```

`linux-ext4-review-02/{environment.json,result.json,unittest.log}`: 7 passed, 0 failures/errors, including three separate fresh CLI targets, real renameat2 against empty/nonempty existing targets, two-thread single-winner publication, fault preservation, explicit resume and hash/manifest refusal. Restore script SHA256 `ff8eb1156e424239116866973f8ee58635c33122fb978805a4ed82d939d76410` matches final source. Only synthetic artifacts were created in the dedicated Linux project folder and copied to D-drive evidence; no components installed, sudo, production host or account access.

`linux-runtime-review-01` deliberately remains FAILED (4 passed, 3 failed): WSL Windows-mounted 9p/DrvFS returns EINVAL 22 for RENAME_NOREPLACE when publishing an absent target. Existing-target refusals pass. Do not deploy/rehearse on that filesystem or replace this atomic primitive with overwrite-capable rename. Local WSL ext4 evidence is not actual ECS/production verification.

## Historical embedding provenance (read-only)

Observed current code: `app/db.py` chunks store embedding/metadata but no dedicated generation provider/model/preprocessing receipt. `app/services/ingestion.py` persists parsed chunk metadata and vectors, not the actual embedding request receipt. Migration 013 freezes source file/version/hash/ownership, not vector generation identity. `app/ui_extension/domain.py` labels exported snapshots with CURRENT configuration; `import_snapshot` rejects a different configured label but cannot establish historical identity when labels happen to match.

Bounded local read-only SQLite inspection used `mode=ro&immutable=1`, schema/aggregate metadata keys only, no course content/vector values/secrets. `data/rag.sqlite3` main file contains 1,937 chunks with no metadata keys; the retained September-15 local canary DB main file contains 0 chunks. Immutable inspection intentionally does not incorporate active WAL; these counts are local main-file evidence, not a live production census. Existing related audit reports contain no independent historical generation receipt. No database was rewritten or re-embedded.

- PROVEN_MATCH: none established for those historical vectors in this bounded audit.
- PROVEN_INCOMPATIBLE: no actual historical provenance proving incompatibility was found; a configured-label mismatch is a refusal condition, not historical proof.
- UNKNOWN: the inspected historical vector lineage; equal dimensions/configuration or retrieval hits cannot upgrade this.

Current runtime has no provenance-specific user badge or automatic UNKNOWN quarantine. Hybrid retrieval still embeds queries and combines keyword/vector ranks; this audit does not claim verified historical vector compatibility. Existing authorized structured locator/keyword and original preview/download capabilities do not need historical embedding identity, but ordinary hybrid retrieval is not an implemented lexical-only failover. Owner-facing notice: “历史向量来源未记录，语义检索兼容性未验收；原文与权限隔离不因此失效。” This is an operational release warning, not a claim that a new UI warning was installed.

Any later rebuild must be separately approved: select explicit corpus/counts, freeze source versions, estimate embedding tokens/price/cap, build a new isolated index with model/account/region/dimension/preprocessing/receipt evidence, compare authorized keyword/semantic retrieval and tenant isolation, then approve switching the index pointer; retain the old index for rollback. No fee or rebuild is authorized by this report.

## Final code-state evidence

Implementation was frozen before the final full backend command at `dcfd3221ce12170521807e4b1c52fcc2003cbd0b`. Only reports were subsequently edited; `git diff --name-only dcfd322 -- apps services ops tests` is empty. This includes the previous knowledge-export read-transaction fix. The original failed XML SHA256 is `7DE38BB892A4672F068584F7F1D4A2F32CF510D9ACE636102228E9C2BEB124FD`.

Final browser after the last cancellation fix: `browser-1789833896259-8312/playwright-report.json`, **13 passed in49.6s**, zero skipped/unexpected/flaky, no test retries. HEAD verified unchanged before/after. Source-specific earlier checks remain valid because their tested files are byte-identical to this commit (Linux restore hash above, root recovery33, sidebar production bundle `ui-Bm6ig1d2.js` / `ui-dO-H8oqS.css`). Web60/Agent66/typecheck/build ran after final UI edits; later changes only affect Python share cancellation.

Commands (fresh artifact roots, no production configuration):

```powershell
# Repository root; existing installed dependencies, no new package install
npm test
npm run typecheck
npm run build
npm exec -- playwright test --config playwright.codex-audit.config.ts
& work/codex-audit/venv/Scripts/python.exe -m pytest tests/test_recovery_gate.py tests/test_codex_backup_publication.py -q --tb=short --basetemp=work/codex-audit/recovery-root-final --junitxml=work/codex-audit/recovery-root-final.xml
# From services/rag-api; final immutable code full run
$env:CMUI_ALLOW_BILLABLE='false'
$env:CMUI_ENV='test'
$env:CMUI_DATA_DIR=''
& ../../work/codex-audit/venv/Scripts/python.exe -m pytest -q --tb=short --basetemp=../../work/codex-audit/recovery-final-regression --junitxml=../../work/codex-audit/recovery-final-regression.xml
```

Full backend actual result: **657 passed / 0 failed / 0 skipped**, 2 existing Starlette/httpx/AnyIO dependency deprecation warnings, **596.29s**. XML: `recovery-final-regression.xml`. This one frozen-code run includes original restore cases, PREPARING tests and the previous knowledge-export transaction fix; it does not merge earlier partial runs into a fabricated full PASS. npm workspaces have no separate lint script; typecheck/build and changed-diff review were run. This is a limited local recovery handoff, not a full new production security/performance audit.

## UI and bounded scope

Course name is now the primary sidebar label, code secondary; both wrap and expose focus/title. ID, routing and sharing identity unchanged. Original browser RED: `browser-1789833138641-25296`; at 768px the code's 190px content exceeded its 123px box. GREEN: `browser-1789833412115-276`, then 13 passed in 52.7s under `browser-1789833446035-16312`; zero skips/failures/flaky. At 1100/768px both labels fit 145/123px and screenshots were inspected; 390px and unchanged-ID assertions passed. Final post-cancellation-fix browser run: 13 passed in49.6s, as recorded in the final code-state evidence above.

Out-of-scope finding, not silently fixed: creating a course directly with a long legal name can generate an ID over the 50-character limit and return 500 (`domain.py:_create_course`). Browser fixture used normal short-name creation then authorized rename to isolate the requested sidebar issue. Earlier failed setup evidence is retained (`browser-1789833031141-30516` and the following setup attempt). This is not a claimed sidebar defect or production observation.

## Migration, rollback and external boundaries

No schema migration added; RAG migration 025 and UI schema 11 remain unchanged. Recovery metadata is additive in existing manifest JSON; the advisory lock is process-owned and never a row-age lease. Old snapshots and all user data are preserved. Reverting this local code must not be combined with running a new recovery command beside old send workers; quiesce writes and change the whole worker set together. Already published notices are not “undone” by code rollback. Real DB rollback still needs a verified complete recovery unit and reconciliation of later writes.

Real Qwen budget, live Clerk reads/sync, real qualification writes, real recipients/messages/shares, production inventory/backup/migration, push and deployment each remain separate unapproved actions. Historical provenance cannot be recreated merely by granting access. No installation/admin-diagnostic permission is currently needed; if native restore still persistently fails on a future target, request an exact-path read-only handle investigation rather than ACL/security changes or broad Full Access.

Final disposition: local limited-scope work complete with limitations; external acceptance NOT RUN. All original and new failure artifacts remain available. No further unchanged full-suite rerun or deployment is scheduled. Report-only changes follow frozen implementation `dcfd322`; no application/test source changed during final regression.
