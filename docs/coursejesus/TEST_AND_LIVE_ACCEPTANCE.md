# TEST AND LIVE ACCEPTANCE (CourseJesus work)

**State of this document.** Round-46 inventory of what is actually measured, on which revision,
and what remains for the live gate. It is written so a later round can tell a re-run from an
inherited number, and so no module is reported as passing because another module passed.

## 0. Update (round 79, Canvas identity revision)

The Canvas identity design changed — OAuth is the production route, the local bridge is the fallback —
so the relevant numbers are re-stated here rather than left to the older table below:

| Gate | Result | Revision / evidence |
|---|---|---|
| Backend regression (rag-api) | **1599 passed / 3 skipped / 0 failed** (1778 s, exit 0) | `work/current-change/full_run_round80.log` on `47bc2e1`; the +29 are the Canvas local-bridge tests. The three skips are the symlink case, the POSIX-permission case and the optional-SDK case |
| Canvas local-bridge suite (new) | **29 passed / 0 failed** — replay, cross-user, expiry, unknown school, unselected course, forged digest, path-shaped name, idempotent retry, real quota, no credential column | `services/rag-api/tests/test_canvas_local_bridge.py`, real `create_app` wiring + real DB + real `IngestionService` |
| Canvas shared state store (round 80) | **9 passed / 0 failed** — one use, expiry, unknown state, no plaintext state at rest, purge, and the **multi-worker callback journey** (worker A issues, worker B completes) | `services/rag-api/tests/test_canvas_oauth_state_store.py`; negative control: wiring the in-memory store makes that journey end in `canvas=failed` |
| Neighbouring Canvas/schema suites | **88 passed / 0 failed** | `test_canvas_api_routes.py`, `test_canvas_import_schema.py`, `test_database.py`, `test_ui_extension_schema_compat.py`, `test_schema_rollback_compat.py`, `test_v3_migration_rehearsal.py`, `test_ingestion_api.py` |
| Web unit tests | **96 passed / 22 files** | round 79; the 6 new ones cover the bridge client, the address matching and the required texts |
| Web typecheck | `tsc -b --pretty false` **exit 0** | round 79 |
| Web production build | **exit 0**, and the build now runs `scripts/scan_web_bundle_for_pat.mjs`, whose negative control (a planted `<input name="canvas_token" />`) fails the build | round 79, wired into `apps/web/package.json` |
| Agent service tests | **92 passed / 12 files** | round 79 |
| Browser journeys, both suites | **21/21 `ui-refresh` and 6/6 `jev-structured`, all passing on `47bc2e1`** in real Chrome against the three real services | `work/current-change/browser_ui_round79c.log` (2.4 m) and `browser_jev_round79c.log` (59.7 s) |
| Browser journeys, Canvas screen | **2/2 pass** on the revised screen (every input is the school radio, the tutorial text, no credential field), including 390px and the dark theme | `work/current-change/browser_ui_canvas_round79b.log` |

## 1. Local gates, with the revision each one describes

| Gate | Result | Revision / evidence |
|---|---|---|
| Backend regression (rag-api) | **1355 passed / 2 skipped / 0 failed** (1689 s, exit 0) | frozen `184d973`, `work/current-change/full_run_round46.log`, `git diff 184d973 -- services benchmarks scripts` empty. The two skips are the optional-SDK constants test and the symlink case (Windows privileges). The run before it was 1324 on `bf31474`, so the delta is exactly the **31** new Canvas adapter tests |
| Canvas adapter suite (new) | **31 passed / 0 failed** | `tests/test_canvas_read_adapter.py`, mock transport; included in the 1355 above |
| Canvas adapter guards | **8 of 8 mutations caught**, module restored byte-for-byte | `work/current-change/mutation-check-canvas.py` |
| Web unit tests | **81 passed / 20 files** | round 45, on the brand rename revision |
| Web typecheck | `tsc -p tsconfig.app.json` and `tsc -p tsconfig.node.json` both **exit 0** | round 45 |
| Web production build | **exit 0**, and the built artifacts were inspected rather than assumed: `dist/index.html` → `<title>CourseJesus</title>`, `dist/ui.html` → `<title>CourseJesus 学习空间</title>`, `dist/manifest.webmanifest` → `CourseJesus`, no placeholder leftovers | round 45 |
| Agent service | **92 tests passed**, `tsc` exit 0, build exit 0 | round 45 |
| Browser journeys | **19/19 `ui-refresh` journeys pass in real Chrome** on the round-45 build | `work/current-change/ui_refresh_round45b.log`, three real services, injected identity |
| Other browser suites | `jev-structured` 6, `coursemate` 4, `learning` 3, `codex-audit` 14 = 27 journeys, all passing **on their own older revisions** | rounds 37–44; they have not been re-run since the brand rename, and this table says so rather than adding them to the 19 |
| `ruff` / `mypy` | `ruff` clean on the new code; **`mypy app` 1004 errors in 32 files, unchanged** — the Canvas package contributes none | round 46 measurements |
| Campus inventory tool | **10 passed / 1 skipped**, **5 of 5 mutations caught** | round 44 |

Two habits this table keeps: a number names the revision it came from, and a suite that was not
re-run is listed separately instead of being folded into a total.

## 2. What the canvas adapter's tests actually prove

They drive a mock transport, so they assert **this client's behaviour**: which paths it can reach,
which verbs it can use, where the token can appear, what it does with a redirect, and that two
connections do not share state. That is the correct thing to test without a school key — and it is
**not** evidence that Canvas works. Specifically, they prove:

* every non-`GET` verb is refused at the single request path, and the public surface exposes only
  `profile`, `student_courses`, `course_files`, `download`;
* `/assignments`, `/submissions`, `/messages`, `/accounts` and a generic `/read_api?path=` are
  refused, as is an absolute URL on another host;
* the token appears only in the `Authorization` header (never in a query string), and a download
  runs through a client that sends no Authorization header at all;
* loopback, RFC1918, link-local and metadata targets are refused, including as a redirect hop, as
  are plain HTTP and non-standard ports;
* `active` and `completed` student courses are both discovered, a teacher-role course is not, and
  a completed course keeps its state without being treated as an error;
* a cross-origin pagination link is refused and a chain longer than `max_pages` is refused rather
  than read to the end.

They do **not** prove: that a real school's Canvas returns these shapes; that the OAuth flow works;
that a real download completes; or that the import produces a course.

## 3. Live gate (all owner-blocked, none attempted)

| Item | Blocked on | Why it cannot be worked around |
|---|---|---|
| Real TypeSafe Jev calls | credential + one approved ceiling | the service resolves `TYPESAFE_API_KEY`/`TYPESAFE_DEFAULT_MODEL`, but the optional SDK is not installed and no key exists |
| Real DeepSeek calls | credential + budget | the canary CLI refuses without `--max-cost`, by design |
| Real Canvas authorisation | the school's Developer Key | a student token cannot mint an institution key; the request letter is ready in `CANVAS_ADMIN_REQUEST.md` |
| Production release | window + approvals + one real sign-in | the sequence is in `DOMAIN_AND_CLERK_MIGRATION.md` and the ledger's production rows |

The live acceptance criteria themselves are unchanged from the pack and are not restated as
achieved anywhere in this repository: a provider returning valid JSON is not a quality pass, and
`health=200` is not acceptance.

## 4. What still needs a browser journey (not yet written)

The pack asks for journeys that do not exist yet, and they are listed here so their absence is
visible: extraction verification, alias retrieval, conflicting conditions, an unsupported citation,
capability selection, a wrong tool intent, and Jev-disconnected fallback. Three of those now exist in
`tests/e2e/jev-structured.spec.ts` (capability dispatch, extraction of a named question reference, and
the Jev-unavailable deployment), and the import wizard's own journeys now exist too — two entry
points, the honest "等待学校开通 Canvas 连接" state, the local-token route, the 390px layout and both
themes. The remaining four are recorded as not existing rather than quietly dropped: condition
conflict needs a live decision to produce a real `SAME_CONTEXT_CONTRADICTION`, the semantic half of
citation support needs a live decision, alias retrieval is asserted on the real corpus instead (a
browser cannot discriminate it with stub embeddings), and tool intent is asserted at the agent's real
execution boundary because the E2E agent never proposes a tool call.

## 5. Honest limits

* No live or production acceptance has been attempted, so no row above claims one.
* The 27 journeys from earlier rounds describe earlier revisions; treating them as current would be
  exactly the substitution this project forbids.
* The newest full-suite number (1355 on `184d973`) includes the Canvas adapter, but the adapter is
  still only mock-verified: passing tests do not mean a school's Canvas has been contacted.
