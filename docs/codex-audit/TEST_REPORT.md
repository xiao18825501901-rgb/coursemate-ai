# Local test report — 2026-09-19

## 2026-09-20 recovery continuation

Frozen source `dcfd3221ce12170521807e4b1c52fcc2003cbd0b`; earlier runs below remain historical.

| New evidence | Actual result | Artifact under work/codex-audit |
|---|---|---|
| Independent original Windows reproduction |3 passed /1 failed |recovery-gate-baseline1.xml; staging retained |
| Bounded policy RED |1 passed /3 failed |recovery-policy-red.xml |
| Fresh original restore tests |4 passed |recovery-fresh-green1.xml |
| Owned resources + real fresh CLI |32 passed /1 failed (raw immediate OS diagnostic) |recovery-resources-green.xml; actual0.1s retry logged |
| Final application recovery tests |33 passed |recovery-root-final.xml; corrected post-close application contract, raw held-handle denials retained |
| PREPARING abrupt exit / corruption / cancellation |9 passed |preparing-final.xml; owned-worker PID artifacts |
| All-task shutdown cancellation RED |1 passed /1 failed |shutdown-red.xml |
| Independent final cancellation review |3 passed /6 deselected |review-shutdown-fix.xml |
| Real Linux ext4 |7 passed |linux-ext4-review-02/result.json; actual native renameat2 |
| Real Linux DrvFS |4 passed /3 failed |linux-runtime-review-01; unsupported filesystem EINVAL |
| Final browser on frozen commit |13 passed in49.6s;0 skip/failure/flaky |browser-1789833896259-8312/playwright-report.json |
| Web / Node / typecheck / build |60 passed /66 passed /PASS /PASS |Local execution after final UI edits; no later web/Node edits |
| Full backend on frozen commit |**657 passed**,0 failed/0 skipped,2 dependency warnings,596.29s |recovery-final-regression.xml; prior knowledge consistency fix included |

Original full-regression3.xml remains645 pass/2 fail, not rewritten. Current details, exact commands, code-state boundaries and external NOT_RUN statuses are in [RECOVERY_GATE_AND_REMAINING_STATUS.md](RECOVERY_GATE_AND_REMAINING_STATUS.md). No live provider/model/account/production evidence was generated.

## Historical audit runs

Repository baseline `9104b5a`, audit working tree. No remote/model/production
acceptance is implied by any result here. Every DB and upload in these executions
was generated in a new project-owned synthetic test directory.

## Consolidated runs

| Run | Observed result | Evidence / code state |
|---|---|---|
| Backend full first diagnostic |550 pass,32 fail,13 errors | Earlier state before explicit campus fixture/implementation fixes |
| Backend full second |620 pass,2 fail | `work/codex-audit/full-regression2.xml`; legacy history gate later fixed; Windows rename retained |
| Backend full third |**645 pass,2 fail**,2 dependency warnings,571.11s | `work/codex-audit/full-regression3.xml`; both failures restore final Windows publication |
| Web unit regression |**60 pass** | npm test,16 files; after rich-content and UI fixes |
| Node Task Agent regression |**66 pass** | npm test,10 files; actual existing tool/state tests |
| Typecheck |PASS | both workspaces |
| Standard build |PASS | both workspaces; absent public Clerk key can tree-shake auth-dependent UI, so this alone is not UI runtime evidence |
| Initial production-build browser |7 pass | `browser-1789816803671-32652/playwright-report.json` |
| Expanded browser |**12 pass**,50.4s; zero skips/failures/flaky | `browser-1789819169152-31448/playwright-report.json`, production bundle `ui-VDr1B3ig.js`; actual isolated V3+Node |

The full third run started before the knowledge-export read-transaction review
fix. That last one-line backend change and its new regression passed separately
(`test_codex_snapshot_review.py`:1 pass). Therefore this report does not claim
that one immutable final commit passed the entire backend suite. The two failing
tests remain failures in their original XML.

## Windows recovery evidence

Full-run failures:

- `test_backup_and_restore_include_the_refreshed_shell_unit`
- `test_backup_without_the_extension_still_produces_the_original_unit`

Both backups completed with checksums; restore extracted and verified data, then
Windows denied final directory publication with WinError5. Restore returned2 and
kept its hidden partial directory. No tests were skipped, no assertions weakened,
and no automatic retry/sleep or system-security change was used.

After the full run, each exact preserved synthetic staging directory was supplied
to RESTORE_RESUME_PARTIAL with the same source and target. Both explicit invocations
returned0 and “Isolated restore ready”; the restore code revalidated every staged
DB and archive-derived byte/tree before publication. This proves the recovery
path on those two artifacts, **not** reliable first-attempt publication or a fixed
underlying Windows locking process.

New publication/resume diagnostics: first23 pass; expanded final24 pass/1 fail
(a low-level post-handle-close Windows publication diagnostic). Compatibility
run34 pass/3 fail, all three in original backup publication. XML files are
`backup-publication-resume-green3.xml` and `backup-resume-compatibility1.xml`.
Linux renameat2 branch has mocked call/error-contract coverage, not native Linux
execution. Platform rehearsal remains a release gate.

## Focused independent evidence

- Sharing/knowledge/identity combination:29 pass before later share additions.
- Send resume + sharing:17 pass,45.83s, including frozen original2 files after a
  later third upload, same request/course identity, zero successful notices on
  failed send, real recipient file import.
- History consistency + explanation restart:18 pass,36.50s.
- Classification:4 pass,5.93s; same filename/body change traverses real upload,
  parsed chunks and provider bundle, plus stale revision/manual precedence.
- Action idempotency/cancellation/current-change:19 pass; final5 action tests
  reexecuted on exact helper source. `action-final.xml`, `action-final-replay.xml`.
- Full original template content:18 checks;14 professional+3 task normalized body
  hashes and OTHER required contract; no source-template edits.
- Standalone shared file bytes/chunks/owned-ID/replay:1 pass after1 genuine RED.
- Safe step rich-content DOM:1 pass after missing pre/code RED; no script element
  is created from model content.

## Reproduction

From `services/rag-api`, use the project-owned Python interpreter:

```powershell
$env:CMUI_ALLOW_BILLABLE='false'
$env:CMUI_ENV='test'
$env:CMUI_DATA_DIR=''
& '../../work/codex-audit/venv/Scripts/python.exe' -m pytest -q --tb=short --basetemp=../../work/codex-audit/NEW_UNIQUE_RUN
```

From repository root: `npm test`, `npm run typecheck`, `npm run build`.
Browser: `npm exec -- playwright test --config playwright.codex-audit.config.ts`.
Publication diagnostics: project Python `-m pytest tests/test_codex_backup_publication.py`.

The browser harness builds into a fresh isolated directory, uses actual FastAPI
V3 and Node servers on loopback, and a production Vite bundle with synthetic
authentication. It suppresses inherited credentials at child-process boundaries,
does not copy a real database, and does not use fixture replies in place of V3.
The deliberate delayed Pair response is the actual fetched response, held only
to exercise the browser race. Live model/Clerk/production tests are NOT RUN.

Final browser coverage includes normal/Thinking, exact Pair reload, pre-reveal
network surfaces, supplied problem answer/explanation, paginated directory,
campus denials, actual Node task create/reload/complete, held old-Pair response,
keyboard/divider/fullscreen/mobile controls, both file pickers, nonmodal pointer
and keyboard step windows, and sender-to-recipient frozen sharing. Sharing asserts
explicit join before directory presence, no-reload navigation, file preview,
byte-exact download, distinct document IDs, sender access denial and persistence
after source deletion/recipient reload. Desktop/mobile screenshots were inspected.
Math/code window rendering is DOM component evidence, not a math browser canary.
