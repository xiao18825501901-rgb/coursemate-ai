# COURSEJESUS_EXECUTION_STATE

Run state for the appended CourseJesus work (brand + domain, Canvas private import, campus course
expansion). This file is written so a later round resumes without re-doing the reconnaissance.
It does not replace `docs/recovery/CURRENT_BLOCKER_LEDGER.md`; the DeepSeek/Jev work keeps its own
record there.

## 0. Where this run started (verified, not assumed)

| Fact | Value |
|---|---|
| Work tree | `D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY` (unchanged, not moved) |
| Branch | `fix/codex-dsh-audit-20260919` |
| HEAD at the start of this round | `552e809` — working tree clean, 76 commits ahead of `origin`, nothing pushed |
| Last full backend gate before this round | **1314 passed / 1 skipped / 0 failed** in 1534.25 s on frozen revision `2fd532b` (`work/current-change/full_run_round42b.log`) |
| Running jobs at the start | none (no pytest / Playwright / mypy process was live) |
| Instruction pack | `D:\UserData\Downloads\CourseJesus_Domain_Canvas_Campus_DSH_Pack\CourseJesus_Domain_Canvas_Campus_Plan`, **SHA-256 verified 6/6** against its own `SHA256_MANIFEST.json` (a first PowerShell check wrongly reported one failure because the shell decoded the CJK filename as GBK and hashed the wrong file — measured with Python before trusting it) |
| Production | **not contacted in this round at all** — no deploy, no DNS, no Clerk, no database |
| Model spend | **0** — no provider call was made |

Per the pack's §1, the append happened at this safety point: no reset, no checkout, no overwrite of
uncommitted work, and the running cwd was not renamed.

## 1. Status codes (evidence per item, no aggregate PASS)

| Code | Status | Evidence / reason |
|---|---|---|
| `BRAND_UI` | **NOT_STARTED** (baseline measured) | Old name still on 31 user-visible files; scan in `docs/coursejesus/BRAND_REPLACEMENT_MATRIX.md` (481 `CourseMate` + 515 `coursemate` + 62 `COURSEMATE`). Nothing changed yet |
| `LOGO_ASSETS` | **PENDING_ASSET** | No artwork supplied. Scan also found `apps/web/public/manifest.json` **absent**, so the PWA manifest has to be created, not edited |
| `REPOSITORY_RENAME` | **NOT_STARTED** (target identified) | `git remote -v` → `https://github.com/xiao18825501901-rgb/coursemate-ai.git`. Renaming to `coursejesus` is a platform action; see `OWNER_ACTIONS_ONLY_COURSEJESUS.md` |
| `DOMAIN_DNS_TLS` | **RECON_DONE (read-only)** | `coursejesus.com` is delegated to **Aliyun HiChina DNS** (`dns17/dns18.hichina.com`) with **no** `www` or apex records yet; the current `qqttai.com` zone is on **Cloudflare**, apex → Netlify, `www` CNAME → `coursemate-ai-qqtt.netlify.app` (the site to reuse), `rag`/`agent` → `47.114.34.175`. Front end 200 and www→apex 301 live; the API host resets the TLS handshake from this machine and answers `403 Server: Beaver` (Aliyun WAF) on HTTP. Details and the honest limits: `docs/coursejesus/DOMAIN_AND_CLERK_MIGRATION.md` |
| `CLERK_DOMAIN_AND_USER_CONTINUITY` | **NOT_INSPECTED** | No Clerk instance has been read yet; requirement is the same Production instance and same user subject |
| `OLD_DOMAIN_COMPATIBILITY` | **NOT_STARTED** | 30-day compatibility window is the plan; nothing configured |
| `CANVAS_SKILL_REUSE` | **RECON_DONE, ADAPTATION_NOT_STARTED** | Local checkout `D:\Hp\Documents\canvas-study-assistant-skill` at `f05ffae8` (2026-09-20) with **one local modification: `canvas_study/runtime.py`**, which must be preserved; 16 Python files; `LICENSE` present, `NOTICE` absent; `README.md`/`SKILL.md`/`SECURITY.md` present |
| `CANVAS_OAUTH_PER_INSTITUTION` | **NOT_STARTED** (design fixed) | Institution registry targets `https://canvas.cityu.edu.hk` and `https://cityu-dg.instructure.com`; callback to freeze at `https://rag.coursejesus.com/api/integrations/canvas/oauth/callback`; no public PAT input will be built |
| `CANVAS_LOCAL_UPLOAD_FALLBACK` | **NOT_STARTED** | Becomes the real path while no institution Developer Key exists |
| `CANVAS_PRIVATE_IMPORT` | **NOT_STARTED** | No import job, worker or UI entry point yet |
| `CANVAS_READ_ONLY_AND_ISOLATION` | **NOT_STARTED** | Design fixed (GET-only, no global state, per-connection context); no code yet |
| `CAMPUS_LIBRARY_SCAN` | **DONE (read-only)** | `scripts/scan_campus_inventory.py` + `docs/coursejesus/LOCAL_CAMPUS_INVENTORY.csv` + `docs/coursejesus/CAMPUS_SOURCE_AND_PUBLICATION_MATRIX.md`: 1919 manifest rows reconciled against disk with 0 missing, 0 size mismatches, 0 unlisted files, 8.26 GiB, SHA-256 for every file |
| `CAMPUS_FILES_INGESTED` | **NOT_STARTED** | Nothing uploaded or ingested; `publishable_now` is 0 by construction |
| `CAMPUS_CONTENT_PUBLISHED` | **NOT_STARTED** | Requires the rights decision for 21 restricted + 13 training files and the real `IngestionService` path |
| `EXISTING_COURSE_PRESERVATION` | **OK (untouched)** | CS3481 (`630`) and GE2324 (`629`) found locally as Summer Term 2026 offerings; production `course_id`, trees, history, grades and bindings untouched; no re-download |
| `DEEPSEEK_JEV_EXISTING_SCOPE` | **UNCHANGED** | The three appended tasks did not modify the DeepSeek/Jev work; its gate is still the 1314-pass run above |
| `BACKUP_RESTORE` | **NOT_STARTED for this work** | Production backup/restore belongs to the release sequence, after the local work |
| `PRODUCTION_ACCEPTANCE` | **NOT_STARTED** | Nothing production-facing has been changed by this work |

Nothing above is marked complete on the strength of a helper existing, a fake transport, a
localhost screenshot or a `health=200`.

## 2. What this round actually did

1. **Verified the instruction pack** (6/6 SHA-256) and read all four documents in full before
   acting, including `CANVAS_ADMIN_OAUTH_REQUEST.md` and `OWNER_MINIMAL_ACTIONS.md`.
2. **Appended the three tasks to the goal** without clearing the existing objectives.
3. **Reconnaissance (read-only)** of `D:\Canvas`, `D:\Canvas-DG` and the upstream skill checkout,
   using the real filesystem rather than the numbers in the pack: the reported "201 + 1718 = 1919
   files, ~8.4 GB" measured as **1919 rows, 8,868,856,230 bytes (8.26 GiB)**; DG has 29 courses
   with files (the pack's report said 33 courses, 29 with files); the main root's information
   boards measured 170 files (154 announcement + 16 scholarship), matching the report.
4. **Built the campus inventory tool** `scripts/scan_campus_inventory.py`: joins both manifests to
   the disk, streams SHA-256, classifies each file, groups duplicates and same-name/different-id
   pairs, and writes a committed inventory (personal names redacted) plus a full working copy.
5. **Tested it**: `services/rag-api/tests/test_campus_inventory_scan.py` — **10 passed, 1 skipped**
   (the skip is symlink creation, which needs Windows privileges), and **5 of 5 mutations caught**
   (`work/current-change/mutation-check-campus-scan.py`, tool restored byte-for-byte).
6. **Found and fixed three real classifier defects by running it on the real roots** — `Grader.java`
   / `IGrade.java` and "personality" were false positives from substring matching, and a student
   grouping list was filed as training material because the training check ran before the privacy
   check. All three are pinned by tests so they cannot return.
7. **Measured the brand surface** for task A1 and wrote the replacement matrix (which surfaces
   must change, which must survive, which need a per-case decision), including the finding that no
   PWA manifest exists yet.
8. **Read-only domain reconnaissance** (no writes anywhere): authoritative providers for both
   domains, the live site's Netlify subdomain, the API host address, and the fact that the API
   endpoints cannot be reached from this machine (TLS reset; `403 Server: Beaver` on HTTP). The
   API result is recorded as an observation with its limits — it is not proof the API is down for
   real users, and it is not a licence to route around it via the old domain.

## 3. Next steps, in order

1. **Brand config source (A1)**: one module providing name/中文名/canonical+API origins/logo
   path/support name; wire the shell, `index.html`, package metadata and the visible pages to it;
   add the missing PWA manifest; keep Class B names intact. Then a test that fails if a *new*
   user-visible file hard-codes the old name.
2. **Canvas read-only adapter (B)**: port the skill's discovery/pagination/file logic into a
   stateless adapter with injected connection context and token provider, preserving the upstream
   licence and the owner's local patch; add context-injection tests and negative tests for the
   forbidden operations.
3. **OAuth design freeze (B)**: institution registry + state handling + credential storage with a
   key id, then the mock-OAuth journey and the "school not connected" + local-upload fallback.
4. **Import job (B)**: persistent job table/worker with the frozen state machine and per-file
   checkpoint; private course creation through the existing course service and `IngestionService`.
5. **Campus ingestion (C3)**: one small qualifying course end to end (the pack's requirement),
   then batches; rights/publication decision for the 40 review-list files first.
6. **Domain/Clerk/GitHub (A2/A3)**: read-only inventory of DNS, Clerk, Netlify and the GitHub repo
   before any change; then the switch order in the pack's §6.

## 4. Owner-blocked (see `OWNER_ACTIONS_ONLY_COURSEJESUS.md`)

School Canvas Developer Key, the owner's MFA/real-name/ICP filings, the logo asset, the
publication-rights decision for the review list, and any spend above the existing approved policy.
Everything else in §3 is local implementation work and continues without those.

## 5. Honest limits of this state file

* No user-visible string, DNS record, Clerk setting, Netlify setting, GitHub repository name,
  database row or production service has been changed.
* The campus scan reads **names, paths, sizes and hashes**, never file contents, so its
  classification is a review work list, not a rights decision.
* `CAMPUS_LIBRARY_SCAN` is done; `CAMPUS_FILES_INGESTED` and `CAMPUS_CONTENT_PUBLISHED` are not,
  and no report here should be read as saying the campus library has grown.
