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
| Gate **on this round's revision** | **1434 passed / 2 skipped / 0 failed** in 1361.67 s (22:41) on frozen revision `7b6316a`, exit 0 (`work/current-change/full_run_round53.log`) — the +16 are the worker failure-decision tests; `git diff 7b6316a -- services benchmarks scripts` is empty |
| Previous round's gate | **1418 passed / 2 skipped / 0 failed** in 1350.74 s on frozen revision `19e09d2` (`work/current-change/full_run_round50.log`) — the +10 there were the job-repository tests. Schema is **31**; connections, jobs and per-file rows have a repository, and a failure now has a recorded decision |
| Running jobs at the start | none (no pytest / Playwright / mypy process was live) |
| Instruction pack | `D:\UserData\Downloads\CourseJesus_Domain_Canvas_Campus_DSH_Pack\CourseJesus_Domain_Canvas_Campus_Plan`, **SHA-256 verified 6/6** against its own `SHA256_MANIFEST.json` (a first PowerShell check wrongly reported one failure because the shell decoded the CJK filename as GBK and hashed the wrong file — measured with Python before trusting it) |
| Production | **not contacted in this round at all** — no deploy, no DNS, no Clerk, no database |
| Model spend | **0** — no provider call was made |

Per the pack's §1, the append happened at this safety point: no reset, no checkout, no overwrite of
uncommitted work, and the running cwd was not renamed.

## 1. Status codes (evidence per item, no aggregate PASS)

| Code | Status | Evidence / reason |
|---|---|---|
| `BRAND_UI` | **IN_PROGRESS (web + agent done, guarded)** | One brand source `apps/web/src/brand.ts`; both HTML entries and the PWA manifest are generated from it (the manifest did not exist before); 17 front-end files and the agent service's prompt/log now render the new name; `apps/web/tests/brand.test.ts` (8 tests) fails if any source file outside an explicit remainder list prints the old name. Verified on the **built bundle**: `dist/index.html` → `<title>CourseJesus</title>`, `dist/ui.html` → `<title>CourseJesus 学习空间</title>`, `manifest.webmanifest` → `CourseJesus`, no placeholder leftovers, and the only `CourseMate` strings left in the bundle are the compatibility identifiers. **Real Chrome: 19/19 ui-refresh journeys pass** on that build. Still old, and listed: `ops/` + scripts (37), `docs/` (history by decision), and the **backend identity strings** — the two FastAPI titles, the Chinese teacher prompts in `app/cm_update/provider.py`, the default display name `CourseMate 同学`, two DB-guard messages, and the tutor prompt pinned by `tests/test_tutor_prompt.py` (prompt and test must change together). Notification/e-mail templates do not exist yet |
| `LOGO_ASSETS` | **PENDING_ASSET** | No artwork supplied. The interim mark is the repository's existing `favicon.svg`; `BRAND.logoStatus` says `PENDING_ASSET` in code rather than implying a final logo. The manifest had to be created, not edited |
| `REPOSITORY_RENAME` | **NOT_STARTED** (target identified) | `git remote -v` → `https://github.com/xiao18825501901-rgb/coursemate-ai.git`. Renaming to `coursejesus` is a platform action; see `OWNER_ACTIONS_ONLY_COURSEJESUS.md` |
| `DOMAIN_DNS_TLS` | **RECON_DONE (read-only)** | `coursejesus.com` is delegated to **Aliyun HiChina DNS** (`dns17/dns18.hichina.com`) with **no** `www` or apex records yet; the current `qqttai.com` zone is on **Cloudflare**, apex → Netlify, `www` CNAME → `coursemate-ai-qqtt.netlify.app` (the site to reuse), `rag`/`agent` → `47.114.34.175`. Front end 200 and www→apex 301 live; the API host resets the TLS handshake from this machine and answers `403 Server: Beaver` (Aliyun WAF) on HTTP. Details and the honest limits: `docs/coursejesus/DOMAIN_AND_CLERK_MIGRATION.md` |
| `CLERK_DOMAIN_AND_USER_CONTINUITY` | **NOT_INSPECTED** | No Clerk instance has been read yet; requirement is the same Production instance and same user subject |
| `OLD_DOMAIN_COMPATIBILITY` | **NOT_STARTED** | 30-day compatibility window is the plan; nothing configured |
| `CANVAS_SKILL_REUSE` | **IMPLEMENTED (mock-verified)** | `services/rag-api/app/canvas/` — stateless `CanvasReadAdapter`, institution registry, `http_safety`; `UPSTREAM_NOTICE.md` records the MIT licence, baseline commit `f05ffae8` **and the owner's `runtime.py` patch**. 31 tests + **8/8 mutations caught**. Not yet verified against a school (no key exists) |
| `CANVAS_OAUTH_PER_INSTITUTION` | **ROUTES AND ENCRYPTED STORAGE IMPLEMENTED (mock-verified)** | `app/canvas/oauth.py` (documented authorisation URL with the frozen `redirect_uri`; one-time, short-lived `state` bound to (subject, institution, nonce), consumed on success **and** failure; forged/expired/replayed states refused before any outbound request; denial reported as `ACCESS_DENIED`; `POST login/oauth2/token` exchange and refresh with `expires_in`; serialised per-connection refresh; `DELETE` revocation that clears the local credential even when the school endpoint fails — 22 tests) and now `app/api/canvas.py` + `app/canvas/credentials.py`: nine routes under `/api/integrations/canvas` (institutions, connections, connect, callback, courses, imports create/status/cancel, disconnect), with **39 route tests** running the real `create_app` wiring against a simulated school and **13 credential tests**. The token is stored with AES-256-GCM under `CANVAS_CREDENTIAL_KEY`, bound to version + key id + connection id, in files outside the database; **with no key the routes report `NO_CREDENTIAL_KEY` instead of storing anything in the clear**. 6 of 6 route/credential guards proven by mutation (`mutation-check-canvas-routes.py`). Still missing: the two UI entries, the local-upload fallback screen, a shared state store for multi-worker, and any real school key |
| `CANVAS_LOCAL_UPLOAD_FALLBACK` | **NOT_STARTED (the state it falls back from now exists)** | Becomes the real path while no institution Developer Key exists. `GET /institutions` now reports per school why it cannot be connected (`NO_DEVELOPER_KEY`, `NO_CREDENTIAL_KEY`, `SCHEMA_NOT_READY`), which is what the fallback screen renders; the screen itself and the two "从 Canvas 导入" entries are the next increment |
| `CANVAS_PRIVATE_IMPORT` | **LOOP IMPLEMENTED AND TESTED (mock-verified), no HTTP route yet** | `app/canvas/job.py` (states, legal transitions, frozen-selection fingerprint, per-file records, earned verdict), `migrations/031_canvas_import.sql` + `app/canvas/store.py` (idempotent creation, lease-based claiming, per-file checkpoints) and now `app/canvas/worker.py`: claim → re-check the selection against the student's own live enrolments → list files → download → verify → ingest through the real `IngestionService` → checkpoint → earned terminal state. The private course is created by the real course service (`course_type='user'`, private, owner-scoped, quota-respecting) and its id is stored in `target_course_id`. **148 Canvas tests pass** in 60.29 s (26 of them new worker tests, which run the real adapter, the real migrated schema and the real ingestion path — only the school's HTTP surface is simulated). Two worker defects were found by those tests and fixed: the `NEEDS_REAUTH` branch released the lease instead of writing the verdict, and a cancel result reported the state constant instead of the outcome. Still missing: the HTTP routes, the wizard entries, and any real school call |
| `CANVAS_READ_ONLY_AND_ISOLATION` | **ENFORCED IN CODE (mock-verified)** | GET-only single request path; exact-pattern endpoint allow-list (`/assignments`, `/submissions`, `/messages` and a generic `/read_api` are refused); token only in the `Authorization` header; per-hop download validation with a token-free client; two adapters demonstrably do not share tokens or state. Proven by mutations that remove each guard |
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
9. **The visible brand rename (round 45)**: one brand source plus the build-time wiring described
   in the `BRAND_UI` row, verified on the built bundle and with 19/19 real-Chrome journeys. Two
   defects in the conversion script itself were caught by running the checks rather than trusting
   the edit (a wrong relative import depth, and an import inserted inside a comment block that
   broke a file's syntax); the damaged files were restored from git and re-converted.
10. **Re-verification (round 51)**: the two mutation proofs were re-run on the current revision
   rather than trusted from the rounds that introduced them — the Canvas guards **8/8 caught**
   (`mutation-check-canvas.py`) and the campus-scan guards **5/5 caught**
   (`mutation-check-campus-scan.py`), with both tools restored byte-for-byte and the working tree
   clean afterwards. This confirms the security and evidence guards still bite after migration 031
   and the job repository were added; no new code was written this round.
11. **The worker loop (round 68)**: `app/canvas/worker.py`, plus the checkpoint writes it needed
   (`store.list_files`, `record_file_result`, `touch`, `set_target_course`/`target_course_of`) and
   one adapter method (`course_file_download_url`, read from the file's own metadata record so a URL
   can never belong to a different file). 26 new tests drive the real adapter, the real migrated
   schema and the real `IngestionService`; the school's HTTP surface is the only thing simulated.
   The tests found two real worker defects — the `NEEDS_REAUTH` branch released the lease instead of
   writing the verdict, and the cancel path reported the state constant as the stop reason — and
   reviewing my own first draft found three more before it ever ran: a wrong import for
   `CanvasCourse`, a `raise None` path in the enrolment check, and a hole where files deferred in
   one run could let a half-finished job report `COMPLETED`. `mypy app` stayed at exactly the
   baseline (1004 errors / 32 files) with **zero** errors in `app/canvas`.
12. **OAuth routes and encrypted credential storage (round 69)**: `app/api/canvas.py` (nine routes,
   wired into `create_app` with one shared registry and one shared OAuth client) and
   `app/canvas/credentials.py` (AES-256-GCM, key id, atomic writes, nothing in the clear without a
   key). 39 route tests run the real application factory against a simulated school; 13 credential
   tests inspect what is actually written to disk. Running them found four real defects a review
   would not have: the callback looked up the *new* Canvas account to decide whether a different
   account was replacing an existing connection — so the guard never fired and one person's courses
   could be filed under another's; the status route reported the JSON string length as the number of
   courses; a client with no credential store would have completed a flow and silently dropped the
   token; and mounting the router unconditionally meant a deployment without migration 031 would
   answer with a missing-table 500 instead of `SCHEMA_NOT_READY`. A mutation run then showed that the
   last two guards were themselves untested, so each got a test that fails without it (6 of 6
   caught), and reviewing the credential store for that run exposed a claim in its own docstring
   that was false — a copied record *did* open for another connection — which is now a check with a
   test behind it.

## 3. Next steps, in order

**Resume point (round 69).** What is left of task B is the **wizard UI**: the two underlined
"从 Canvas 导入" entry points (the dashboard dashed create card's last row and the all-courses top
create area), the "school connection is not open yet" state rendered from
`GET /api/integrations/canvas/institutions`, the course-selection screen from
`GET /api/integrations/canvas/courses`, the job progress view, and the local-upload fallback. The
server side is complete enough for all of it: nine routes exist, a selection becomes a queued job,
and the worker (round 68) imports it into a real private course.

Two constraints the UI work has to respect, both already enforced server-side: no personal-access-token
input exists anywhere (the only authorisation is the school's OAuth flow), and a school that is not
`connectable` must show the fallback rather than a button that fails on click.

The rules the worker obeys are the ones the pack fixed, and they are now tested rather than
described: no retry on `403`, back off on `429` by `Retry-After` and retry that file, leave other
transport failures pending for the next run, end the batch on `EXPIRED_TOKEN`, stop at a checkpoint
on cancel without deleting material, and let the file results — never the caller — decide the
terminal state. Two debts it carries on purpose: the downloaded copy of a file that could not be
parsed stays on disk (it is the only copy CourseMate has), and a `FILE_PENDING` file is re-fetched
rather than reused, because a row that went back to pending still holds the *previous* version's
hash.

1. **Brand completion (A1)**: convert the operations scripts and `ops/` material, write the
   notification/e-mail templates from the same source, and re-run the browser journeys on the new
   build. The web app itself is done and guarded.
2. **Canvas read-only adapter (B)**: **done in round 46** — see the `CANVAS_SKILL_REUSE` and
   `CANVAS_READ_ONLY_AND_ISOLATION` rows and `docs/coursejesus/CANVAS_SKILL_ADAPTATION.md` §7.
3. **OAuth design freeze (B)**: **done in round 47** (registry, state handling, credential storage
   with a key id). What remains is the HTTP routes and the shared stores a multi-worker deployment
   needs: `InMemoryStateStore`/`InMemoryCredentialStore` are single-process by construction, so the
   routes must not be wired to them in production.
4. **Import job (B)**: **loop done in round 68** — `claim` → discovery → download → verify →
   ingest → checkpoint → earned terminal state, with 26 new tests. The private course is created
   through the real course service (`kind=user`, private, owner-scoped) and its id is persisted in
   `target_course_id` so a resumed run reuses it.
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
