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
| Gate **on this round's revision** | **1570 passed / 3 skipped / 0 failed** in 2520.02 s (42:00) on this round's frozen revision, exit 0 (`work/current-change/full_run_round78.log`) — the +9 are `tests/test_campus_ingest_cli.py`, which is the first test to drive the campus ingest CLI itself. The run shared the machine with the whole-library ingestion, which is why it took longer than the 1578 s baseline |
| Previous round's gate | **1561 passed / 3 skipped / 0 failed** in 2711.57 s on frozen revision `3b0ebea`, exit 0 (`work/current-change/full_run_round77.log`) — the +5 were the campus refusal-mapping tests |
| Running jobs at the start | none (no pytest / Playwright / mypy process was live) |
| Instruction pack | `D:\UserData\Downloads\CourseJesus_Domain_Canvas_Campus_DSH_Pack\CourseJesus_Domain_Canvas_Campus_Plan`, **SHA-256 verified 6/6** against its own `SHA256_MANIFEST.json` (a first PowerShell check wrongly reported one failure because the shell decoded the CJK filename as GBK and hashed the wrong file — measured with Python before trusting it) |
| Production | **not contacted in this round at all** — no deploy, no DNS, no Clerk, no database |
| Model spend | **0** — no provider call was made |
| Whole-library ingestion | **all 28 offerings with material, 58.5 min, 0 failed** — `work/current-change/full_run_round78_library.log`, database read back by `inspect-library.py`; only local files were read and only local `work/` artifacts were written |

Per the pack's §1, the append happened at this safety point: no reset, no checkout, no overwrite of
uncommitted work, and the running cwd was not renamed.

## 1. Status codes (evidence per item, no aggregate PASS)

| Code | Status | Evidence / reason |
|---|---|---|
| `BRAND_UI` | **DONE (web, agent, backend and operations), guarded** | One brand source per runtime: `apps/web/src/brand.ts` and `app/brand.py`. Both HTML entries and the PWA manifest are generated from the front-end source (the manifest did not exist before); 17 front-end files and the agent service's prompt/log render the new name; the backend's user-visible identity reads the brand source (the tutor persona a student's answer comes from, the Chinese teacher instruction, the default display name in four use sites, both FastAPI titles, three guard messages, the canary's persona line); and round 73 converted the **operations half** — the console messages, CLI help, recovery docstrings and the model persona in `ops/` and `scripts/`, while every production identifier stayed (`/etc/coursemate/*.env`, `/srv/coursemate/**`, the `coursemate-rag`/`coursemate-agent` units, the `coursemate` service user, `COURSEMATE_API_PROXY`, the `coursemate-v2-*` backup prefix, `User-Agent: CourseMateMonitor/2`, the synthetic Clerk user's name) — each with its reason recorded in `BRAND_REPLACEMENT_MATRIX.md` §6. Guards: `apps/web/tests/brand.test.ts` (8 tests) and `services/rag-api/tests/test_brand_identity.py` (**11 tests**, structural, mutation-proven). Verified on the built bundle and with 21/21 real-Chrome journeys. Remaining, by decision: `docs/` history and the historical `m6f_*` admin-walk payloads. Renaming the production identifiers is a coordinated migration, not a branding edit, and is listed for the owner |
| `LOGO_ASSETS` | **PENDING_ASSET** | No artwork supplied. The interim mark is the repository's existing `favicon.svg`; `BRAND.logoStatus` says `PENDING_ASSET` in code rather than implying a final logo. The manifest had to be created, not edited |
| `REPOSITORY_RENAME` | **NOT_STARTED** (target identified) | `git remote -v` → `https://github.com/xiao18825501901-rgb/coursemate-ai.git`. Renaming to `coursejesus` is a platform action; see `OWNER_ACTIONS_ONLY_COURSEJESUS.md` |
| `DOMAIN_DNS_TLS` | **RECON_DONE (read-only)** | `coursejesus.com` is delegated to **Aliyun HiChina DNS** (`dns17/dns18.hichina.com`) with **no** `www` or apex records yet; the current `qqttai.com` zone is on **Cloudflare**, apex → Netlify, `www` CNAME → `coursemate-ai-qqtt.netlify.app` (the site to reuse), `rag`/`agent` → `47.114.34.175`. Front end 200 and www→apex 301 live; the API host resets the TLS handshake from this machine and answers `403 Server: Beaver` (Aliyun WAF) on HTTP. Details and the honest limits: `docs/coursejesus/DOMAIN_AND_CLERK_MIGRATION.md` |
| `CLERK_DOMAIN_AND_USER_CONTINUITY` | **NOT_INSPECTED** | No Clerk instance has been read yet; requirement is the same Production instance and same user subject |
| `OLD_DOMAIN_COMPATIBILITY` | **NOT_STARTED** | 30-day compatibility window is the plan; nothing configured |
| `CANVAS_SKILL_REUSE` | **IMPLEMENTED (mock-verified)** | `services/rag-api/app/canvas/` — stateless `CanvasReadAdapter`, institution registry, `http_safety`; `UPSTREAM_NOTICE.md` records the MIT licence, baseline commit `f05ffae8` **and the owner's `runtime.py` patch**. 31 tests + **8/8 mutations caught**. Not yet verified against a school (no key exists) |
| `CANVAS_OAUTH_PER_INSTITUTION` | **ROUTES, ENCRYPTED STORAGE AND A SHARED STATE STORE (mock-verified)** | `app/canvas/oauth.py` (documented authorisation URL with the frozen `redirect_uri`; one-time, short-lived `state` bound to (subject, institution, nonce), consumed on success **and** failure; forged/expired/replayed states refused before any outbound request; denial reported as `ACCESS_DENIED`; `POST login/oauth2/token` exchange and refresh with `expires_in`; serialised per-connection refresh; `DELETE` revocation that clears the local credential even when the school endpoint fails — 22 tests) and `app/api/canvas.py` + `app/canvas/credentials.py`: nine routes under `/api/integrations/canvas` (institutions, connections, connect, callback, courses, imports create/status/cancel, disconnect), with **39 route tests** running the real `create_app` wiring against a simulated school and **13 credential tests**. The token is stored with AES-256-GCM under `CANVAS_CREDENTIAL_KEY`, bound to version + key id + connection id, in files outside the database; **with no key the routes report `NO_CREDENTIAL_KEY` instead of storing anything in the clear**. 6 of 6 route/credential guards proven by mutation (`mutation-check-canvas-routes.py`). **Round 80 closed the multi-worker gap**: `SqlStateStore` (migration 034) keeps the one-time state as a SHA-256 hash in shared storage, claimed by `UPDATE … WHERE consumed_at IS NULL`, and `create_app` wires it instead of the process-local store. `tests/test_canvas_oauth_state_store.py` (9 tests) proves the property that matters — worker A issues the state, **worker B completes the callback over the same database** and the connection exists, with a replay refused — and the negative control (wiring the in-memory store instead) makes that same journey end in `canvas=failed`, which is the user-visible failure the shared store removes. Still missing: any real school key |
| `CANVAS_LOCAL_UPLOAD_FALLBACK` | **SCREEN AND FALLBACK DONE (browser-verified)** | Both entry points exist as real underlined buttons (dashboard dashed card's last row, all-courses create area) and open one wizard. With no Developer Key — this deployment's actual state — the screen reads "等待学校开通 Canvas 连接", lists each school with the server's reason, and offers 上传本地资料, which opens the existing create-course form. The revision added the school picker (both schools plus "其他 Canvas 学校" with an address field), the primary `连接 Canvas` button, and the local-token route behind the secondary entry `无法连接？查看本地 Token 导入方式`. There is **no credential input anywhere**: the browser journey asserts the dialog contains **zero** `input` elements before and after opening the tutorial. Verified in real Chrome by two journeys (2/2 pass on the revised screen, `work/current-change/browser_ui_canvas_round79.log`), including 390px and the dark theme, and by 17 client unit tests. The connect/select/progress steps remain covered by the route tests and the simulated school, not by a browser, because no school is connectable here |
| `CANVAS_LOCAL_PAT_BRIDGE` | **SERVER AND UI IMPLEMENTED (mock-verified); the local tool is the owner-verified skill** | `docs/coursejesus/CANVAS_LOCAL_BRIDGE.md` is the protocol. `migrations/033_canvas_local_bridge.sql` + `app/canvas/local_bridge.py` + `app/api/canvas_local.py` implement a short-lived, single-use session (30 min, one code, one user, one institution) with ten routes; the bridge signs in as the user, sends course metadata, then uploads file bytes that are checked against the declared size and digest. **29 tests** drive the real application (real routes, real DB, real `IngestionService`), covering replay, cross-user use, expiry, an unknown school, an unselected course, a forged digest, a path-shaped filename, idempotent retries and the real private-course quota. Two defects were found and fixed by writing them: `get_job` answers `JOB_NOT_FOUND` for a private user course unless the owner is named, and `REJECTED` was missing from the file-status CHECK so the first refused format raised a 500. The PAT never reaches this service: the schema has no column for one (a test reads `PRAGMA table_info`), every request model is `extra="forbid"` so a posted token is a 422, and the page has no field for one. Local side: the owner-verified `canvas-study-assistant` skill (Windows Credential Manager, hidden `getpass`, active+completed enrolments) is reused — no second CLI was written |
| `CANVAS_TOKEN_SECURITY` | **ENFORCED AND SCANNED** | `scripts/scan_web_bundle_for_pat.mjs` runs on every web build and **fails it** if the built output or the sources contain an input named like a token, a token written to `localStorage`/`sessionStorage`, or if the notice "本站不接收个人访问令牌" has gone; its negative control (a planted `<input name="canvas_token" />`) is caught and exits 1. Wired into `apps/web/package.json` `build`, so a production build cannot ship one. On the OAuth route the token lives in the encrypted store only (`app/canvas/credentials.py`), never in a response, a log or the database |
| `CANVAS_MULTI_CONNECTION` | **PER-INSTITUTION AND PER-USER (mock-verified)** | A registry entry per school with its own origin, key reference and download hosts; a connection is unique per (user, institution, canvas user); a local session belongs to one user and one institution, and the second-user test proves a session cannot be taken over. There is no global "current Canvas": the connection id (or session id) scopes every operation. Still unverified against a real second school |
| `CANVAS_PRIVATE_IMPORT` | **LOOP IMPLEMENTED AND TESTED (mock-verified), no HTTP route yet** | `app/canvas/job.py` (states, legal transitions, frozen-selection fingerprint, per-file records, earned verdict), `migrations/031_canvas_import.sql` + `app/canvas/store.py` (idempotent creation, lease-based claiming, per-file checkpoints) and now `app/canvas/worker.py`: claim → re-check the selection against the student's own live enrolments → list files → download → verify → ingest through the real `IngestionService` → checkpoint → earned terminal state. The private course is created by the real course service (`course_type='user'`, private, owner-scoped, quota-respecting) and its id is stored in `target_course_id`. **148 Canvas tests pass** in 60.29 s (26 of them new worker tests, which run the real adapter, the real migrated schema and the real ingestion path — only the school's HTTP surface is simulated). Two worker defects were found by those tests and fixed: the `NEEDS_REAUTH` branch released the lease instead of writing the verdict, and a cancel result reported the state constant instead of the outcome. Still missing: the HTTP routes, the wizard entries, and any real school call. **Round 81 added the post-import half**: `tests/test_canvas_imported_course_lifecycle.py` (6 tests) imports through the local bridge and then uses the result like any private course — listed for its owner as `user`/`private`/indexed with `isOwner`, invisible and untouchable to another account (list, read, documents, rename, delete all refused), renameable, extendable through the ordinary upload route (quota-respecting, ingested), **answerable with a citation to the imported file**, and deletable in a way that removes its documents and chunks while keeping the import receipts as history. A mutation (creating the imported course as an admin course instead) is caught by the isolation test, and the module is restored byte-for-byte |
| `CANVAS_READ_ONLY_AND_ISOLATION` | **ENFORCED IN CODE (mock-verified)** | GET-only single request path; exact-pattern endpoint allow-list (`/assignments`, `/submissions`, `/messages` and a generic `/read_api` are refused); token only in the `Authorization` header; per-hop download validation with a token-free client; two adapters demonstrably do not share tokens or state. Proven by mutations that remove each guard |
| `CAMPUS_LIBRARY_SCAN` | **DONE (read-only)** | `scripts/scan_campus_inventory.py` + `docs/coursejesus/LOCAL_CAMPUS_INVENTORY.csv` + `docs/coursejesus/CAMPUS_SOURCE_AND_PUBLICATION_MATRIX.md`: 1919 manifest rows reconciled against disk with 0 missing, 0 size mismatches, 0 unlisted files, 8.26 GiB, SHA-256 for every file |
| `CAMPUS_FILES_INGESTED` | **THE WHOLE LIBRARY INGESTED (measured), nothing published** | `scripts/plan_campus_ingestion.py` decided all 1919 files (1479 `INGESTABLE`, 186 `DOWNLOAD_ONLY`, 254 `BLOCKED`). Round 71 did the pack's single verification course — 社会实践 (`628`, CityU (DG)); round 76 a batch of six; **round 78 the remaining 22, so all 28 offerings with material are now in one database** (`work/current-change/full_run_round78_library.log`, read back from `campus-library.sqlite3` by `inspect-library.py`): **28 courses, 831 documents (754 with readable text), 21,056 chunks, 1728 material rows — 783 `INGESTABLE`, 876 `DOWNLOAD_ONLY`, 69 `BLOCKED` — 0 `FAILED`, 0 offerings failed, every course `private/private`, 0 published**, in 3514 s. All of them are labelled `display_type='campus'` with `requires_student_verification=1` (round 74). Migration 032 records one row per file with its decision, reason and rights metadata. **The plan's `INGESTABLE` count is an upper bound, and the difference is now measured file by file** (`explain-plan-gap.py` joins every row back to its plan entry: 1919 joined, 0 unmatched): of the 696 planned-`INGESTABLE` files that were not indexed, **575 are source code and web assets whose extension is outside the upload allow-list** (`.java` 244, `.html` 209, `.css` 90, `.cpp` 13, `.h` 7, `.c` 4, `.js` 3, `.py` 3, `.sql` 1, `.rtf` 1), 42 are over the 20 MB limit, and ~78 have no extractable text (scanned PDFs, one malformed DOCX, one file that claims to be a PDF and is not). Extending what may be parsed is a **decision, not a cleanup**: those extensions are refused by the shared upload allow-list, so teaching the campus path to read them means deciding what the platform will parse — recorded for the owner, not changed unilaterally. **36 tests** (27 policy/ingestion + 9 CLI); a re-run reports `SKIPPED_IDENTICAL` (29 across the library) instead of duplicating a document; a `pending`/`published` course is refused rather than written into. Two defects this work found: round 76's refusal mapping (a file-scoped refusal recorded as `FAILED`, fixed with an allow-list and 4/4 mutations caught) and round 78's ordering (the staleness check ran *after* the course was created, so a refused plan could leave an empty private course behind; everything that can refuse a plan is now checked before anything is written, and the CLI refuses an ambiguous course id under two institutions instead of taking the first match — 4/4 mutations caught, `mutation-check-campus-cli-guards.py`) |
| `CAMPUS_CONTENT_PUBLISHED` | **NOT_STARTED (and cannot start here)** | 1715 rows are listed in `docs/coursejesus/CAMPUS_RIGHTS_REVIEW_LIST.csv` waiting for one owner decision (46 of them belong to the first six offerings); every campus course stays private until then, and the whole-library run changed nothing about that — `courses not private: 0`. Publication needs the rights declaration, not code |
| `EXISTING_COURSE_PRESERVATION` | **OK (untouched)** | CS3481 (`630`) and GE2324 (`629`) found locally as Summer Term 2026 offerings; production `course_id`, trees, history, grades and bindings untouched; no re-download |
| `DEEPSEEK_JEV_EXISTING_SCOPE` | **UNCHANGED** | The three appended tasks did not modify the DeepSeek/Jev work; its gate is still the 1314-pass run above |
| `BACKUP_RESTORE` | **NOT_STARTED for this work** | Production backup/restore belongs to the release sequence, after the local work |
| `PRODUCTION_ACCEPTANCE` | **NOT_STARTED** | Nothing production-facing has been changed by this work |

### The revision's own status codes (Canvas identity), each with its own evidence

| Code | Status | Evidence |
|---|---|---|
| `CANVAS_OAUTH_CODE` | **IMPLEMENTED (mock-verified)** | the authorisation-code flow, state handling, token exchange, refresh, revocation and encrypted storage described in `CANVAS_OAUTH_PER_INSTITUTION`; 39 route tests + 22 flow tests + 13 credential tests; 6/6 route guards mutation-proven |
| `CANVAS_OAUTH_LIVE` | **WAITING_INSTITUTION** | no school Developer Key exists, so no real authorisation has run and none can. This is **not** a PASS, and nothing below is allowed to stand in for it |
| `LOCAL_PAT_BRIDGE` | **IMPLEMENTED (mock-verified)** | `CANVAS_LOCAL_PAT_BRIDGE` above: 29 tests, 10 routes, migration 033, and the page's local route in a real browser journey |
| `CANVAS_IMPORT_ENGINE` | **IMPLEMENTED (mock-verified on the OAuth route; live on the bridge route)** | OAuth: worker claim → discovery → download → verify → ingest → checkpoint → earned terminal state (148 Canvas tests). Bridge: the user's own machine downloads and uploads bytes; this service verifies and ingests them through the same `IngestionService` |
| `CANVAS_MULTI_CONNECTION` | **IMPLEMENTED (mock-verified)** | see the row above; two connections per user and two users on one school are both covered by tests |
| `TOKEN_SECURITY` | **ENFORCED AND SCANNED** | see `CANVAS_TOKEN_SECURITY`: build-time scan with a negative control, no credential column, `extra="forbid"` request models, encrypted store on the OAuth route |
| `PRIVATE_COURSE_IMPORT` | **DONE for both routes (measured)** | the bridge's own tests assert `course_type='user'`, `visibility='private'`, `publication_status='private'`, owner = caller, real quota, and that a second user gets a different course for the same Canvas course id |
| `HISTORICAL_COURSES` | **COVERED IN CODE (mock-verified)** | the adapter asks for both `active` and `completed` enrolments and distinguishes enrolment state from course workflow state (26 adapter tests); the local tool enumerates the same two sets on the user's own account. Real history has not been read through OAuth because there is no key |
| `PRODUCTION_ACCEPTANCE` | **NOT_STARTED** | unchanged: nothing production-facing has been changed, and `CANVAS_OAUTH_LIVE = WAITING_INSTITUTION` means the OAuth route cannot be called production-verified today |

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
13. **The Canvas wizard and its fallback (round 70)**: both entry points the pack names (dashboard
   dashed card's last row, all-courses create area) now open one wizard driven entirely by the
   server's answers, and the screen a real user sees today — no Developer Key — says
   "学校连接尚未开通", gives each school's reason, and offers the local-upload path. **No credential
   input exists anywhere.** Verified in real Chrome (21/21 ui-refresh journeys, the two new ones
   covering both entry points by keyboard, the fallback, 390px and the dark theme) and by 9 client
   unit tests. Building it also forced a server fix: the post-callback redirect pointed at a path
   the hash-routed shell does not serve, so the target is now the configured `CANVAS_RETURN_PATH`
   with the outcome appended *before* the fragment — two tests pin that it is configuration and that
   no request parameter can steer it. One honest gap found and recorded rather than half-fixed: the
   shell's forms had no associated labels, and only the create-course form (the one the fallback
   opens) has been corrected.
14. **Campus ingestion, decided and verified (round 71)**: `app/campus_ingestion.py` +
   `scripts/plan_campus_ingestion.py` decide all 1919 inventory files (1479 ingestable, 186
   download-only, 254 blocked) and write one review list; `scripts/ingest_campus_course.py` +
   migration 032 ingest the first offering — 社会实践 (`628`) — through the real `IngestionService`
   into a **private** campus course (1 document, 2 chunks, nothing published). Running the planner on
   the real inventory is what found the three defects a unit test could not: the policy expected the
   disk status `OK` where the scanner writes `PRESENT`, so it blocked all 1919 files; the assessment
   rule's `\b` boundaries missed `Final2023.pdf` and `cs3334_final_problem_set.pdf`; and the plan
   file was too lossy to re-derive its own decisions. Two more came from running the ingestion: the
   campus course must be created `private` — `pending` is a *frozen* release under migration 019, so
   the import's own insert aborts — and a copy whose filename names a shadow library
   (`(z-library.sk, 1lib.sk, z-lib.sk)`) is not merely "rights unclear" and is now blocked.
15. **Backend brand identity (round 72)**: `app/brand.py` is the backend's brand and URL source,
   replacing the literals the state file had listed as remaining — both FastAPI titles, the Chinese
   teacher instruction, the default display name in four use sites, three developer-facing guard
   messages, the canary's persona line, and the tutor persona a student's answer comes from (prompt
   and its pinned test moved together, as the pack requires). `tests/test_brand_identity.py` guards
   it **structurally** — it reads string literals from the AST, so a docstring or a comment cannot
   mask a regression — and refuses an old-name identifier nobody recorded; it found
   `coursemate_internal_token` on its first run. Mutation-proven 3/3, and running the same mutation
   against the UI-extension suites showed the *runtime* half of the compatibility rule is already
   protected there: renaming `cmui_users` at a use site fails them with 6 failures / 16 errors. One
   judgment call is recorded rather than hidden: `coursemate-dev-verification-secret` and
   `coursemate-ui-update` keep their spelling because they are a credential default and a status
   contract, not visible names.
16. **Course display type and the student-verification gate (round 74)**: a probe found that a course
   created *after* migration 025 kept `display_type=NULL` and `requires_student_verification=0`,
   while that migration's own header states "official courses display as campus courses and require
   verification" — its backfill only touched rows that existed when the column was added. **Measured
   first, and it was not an access-control hole:** every gate ORs the flag with
   `display_type=='campus'` (`ui_extension/domain.py` reports campus for an official course with an
   empty column; `ui_extension/mount.py`'s authorizer adds `course_type=='official'`; the shell's
   `isCampusUnverified` and the cmui share creation do the same), so nothing was ever let through.
   What was wrong was the *column* disagreeing with the policy — which a future reader of the flag
   alone would inherit — so `create_course` now writes both values explicitly, with no backfill and
   no change to existing rows. 8 tests pin the created values, the effect the shell sees, the
   no-backfill rule, the non-V3 case and the very fallback that kept the legacy rows gated; 4 of 4
   mutations caught (`work/current-change/mutation-check-course-gate.py`). **Two consequences are
   recorded rather than quietly repaired:** the campus course ingested in round 71 predates this
   change and still reads `display_type=NULL, requires_student_verification=0` (measured in
   `work/current-change/campus-ingest.sqlite3`), so its gate holds through the fallback alone — a
   backfill of pre-existing rows is a data-migration decision, not something to slip into an
   importer that deliberately does not rewrite the courses it reuses; and the first attempt named
   those two columns unconditionally, which the **full suite caught** (54 failures,
   `table courses has no column named display_type`, because the columns arrive with the V3 schema)
   and which is now itself a mutation-proofed test.

## 3. Next steps, in order

**Resume point (round 71).** Task C's reading half is now executable end to end: the scan exists,
the planner decides every file, and one offering has been ingested into a private campus course.
What remains on this stream is **scale and the owner's decision**: running the same two commands
for the remaining 27 offerings with material (28 in total, ~1479 files) once the owner has decided
rights for the 1715 listed rows, and wiring the campus display/verification path so a published
campus course appears as `display_type='campus'`.

The other two open items are unchanged: the brand remainder in §3 item 1 (ops/scripts, templates,
and the backend identity strings), and the wizard's remaining steps for a real school, which wait on
the school Developer Key. Everything else in §3 is executable locally without an owner decision.

Two constraints the remaining work has to respect, both enforced in code: no school connection
exists without the school's own OAuth flow (there is no token input anywhere), and no campus
material is published without a recorded rights decision — the material records cannot advance
their own review status.

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
   with a key id), the HTTP routes in round 69, and the **shared state store in round 80** —
   `SqlStateStore` (migration 034) replaced the process-local one in `create_app`, so a callback may
   land on any worker. The credential store is the encrypted file store, shared by construction.
   What remains on this line is only the real school key.
4. **Import job (B)**: **loop done in round 68** — `claim` → discovery → download → verify →
   ingest → checkpoint → earned terminal state, with 26 new tests. The private course is created
   through the real course service (`kind=user`, private, owner-scoped) and its id is persisted in
   `target_course_id` so a resumed run reuses it.
5. **Campus ingestion (C3)**: the pack's single qualifying course is done (`628`, round 71) and six
   offerings are ingested as private drafts (round 76); the remaining 27 offerings with material wait
   on the same thing the batch does — the owner's rights/publication decision for the 1715-row
   review list. Ingestion itself is local and needs no key.
6. **Domain/Clerk/GitHub (A2/A3)**: read-only inventory of DNS, Clerk, Netlify and the GitHub repo
   before any change; then the switch order in the pack's §6.

## 4. Owner-blocked (see `OWNER_ACTIONS_ONLY_COURSEJESUS.md`)

School Canvas Developer Key, the owner's MFA/real-name/ICP filings, the logo asset, the
publication-rights decision for the review list, and any spend above the existing approved policy.
Everything else in §3 is local implementation work and continues without those.

Two further decisions this work surfaced, neither of which code should make alone:

* **What the platform may parse.** 575 of the 696 campus files the planner called ingestable are
  source code and web assets (`.java` 244, `.html` 209, `.css` 90, `.cpp` 13, `.h` 7, `.c` 4, `.js` 3,
  `.py` 3, `.sql` 1, `.rtf` 1) whose extensions the **shared upload allow-list** refuses. Reading them
  as plain text in the campus path means deciding, on the record, that source files are teaching
  material the RAG may index — and it touches a validation boundary the student upload path also uses.
* **The 42 files over the 20 MB ingestion limit** (largest 405 MB) are stored originals that no model
  can read. Raising the limit is a cost and safety decision, not a bug fix.

Both are recorded in `work/current-change/ROUND77_PENDING.md`; nothing was widened unilaterally.

## 5. Honest limits of this state file

* No user-visible string, DNS record, Clerk setting, Netlify setting, GitHub repository name,
  database row or production service has been changed.
* The campus scan reads **names, paths, sizes and hashes**, never file contents, so its
  classification is a review work list, not a rights decision.
* `CAMPUS_LIBRARY_SCAN` and `CAMPUS_FILES_INGESTED` are done for all 28 offerings that have material
  — but "ingested" means **stored as private drafts in a local database**, of which 754 files are
  readable text (21,056 chunks) and 876 are stored originals no model can read;
  `CAMPUS_CONTENT_PUBLISHED` is not, and no report here should be read as saying the campus library
  has grown: every campus course is `private/private`, invisible to students, and none of the 41
  documents is readable by an account that has not been verified.
