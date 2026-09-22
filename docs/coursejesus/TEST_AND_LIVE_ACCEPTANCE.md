# TEST AND LIVE ACCEPTANCE (CourseJesus work)

**State of this document.** Round-46 inventory of what is actually measured, on which revision,
and what remains for the live gate. It is written so a later round can tell a re-run from an
inherited number, and so no module is reported as passing because another module passed.

## 1. Local gates, with the revision each one describes

| Gate | Result | Revision / evidence |
|---|---|---|
| Backend regression (rag-api) | **1324 passed / 2 skipped / 0 failed** (1660 s) | frozen `bf31474`, `work/current-change/full_run_round44.log`. The two skips are the optional-SDK constants test and the symlink case (Windows privileges) |
| Canvas adapter suite (new) | **31 passed / 0 failed** | `tests/test_canvas_read_adapter.py`, mock transport; the full-suite run for this revision is in progress (`full_run_round46.log`) |
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
capability selection, a wrong tool intent, and Jev-disconnected fallback. The import wizard's own
journeys (two entry points, school-not-configured state, selection, progress, cancel) also do not
exist yet because the UI does not exist yet.

## 5. Honest limits

* The newest full-suite run (round 46) is in progress while this document is written; the number for
  it is recorded in `COURSEJESUS_EXECUTION_STATE.md` when it lands.
* No live or production acceptance has been attempted, so no row above claims one.
* The 27 journeys from earlier rounds describe earlier revisions; treating them as current would be
  exactly the substitution this project forbids.
