# CHATGPT REVIEW — CURRENT STATUS AND BLOCKERS

Single self-contained status report for the CourseMate (DeepSeek + TypeSafe Jev) recovery round.
Everything below names its revision, its command and its log path. Nothing here is a percentage, a
"PASS total", or a claim that a shadow receipt is a business effect.

**Audited at:** 2026-09-22 (local, +08:00), branch `fix/codex-dsh-audit-20260919`.
**Companion documents:** `docs/recovery/CURRENT_BLOCKER_LEDGER.md` (one row per open item with its
status class) and `docs/recovery/OWNER_ACTIONS_ONLY.md` (the four things only the owner can do).

---

## 1. Repository identity

| Item | Value |
|---|---|
| Git root | `D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY` |
| Branch | `fix/codex-dsh-audit-20260919` |
| HEAD at audit start | `7e2e4db7cf99d85f92a82c9f97d72729fdaa5162` ("Record round 30's final revision and correct three stale deliverable claims", 2026-09-22 13:31 +08:00) |
| Revision this round produced | `6ba70b0` — the reference-solution gate's result now renders in the shipped shell (apps/web + the E2E spec only; `git diff HEAD -- services` is empty, so the backend regression below still describes the backend) |
| Working tree | clean at audit start |
| Remote | **42 commits ahead of `origin`, nothing pushed** (no push without approval) |
| Application SHA in production | `4ef5064` — **untouched by this work**; production has only ever been read |
| Schema | source `LATEST_V3_SCHEMA_VERSION = 30`; production live DB is **25** (026–030 not applied) |

This round's changes are committed on the same branch (see §6 for the exact SHAs and the evidence run
on each). No history was rewritten, nothing was reset, and no earlier failure evidence was deleted.

## 2. Report set read for this audit, and which version wins

24 report files were read in full and inventoried (path, internal date, named SHAs, modules, what each
supersedes, what each explicitly does not cover). The load-bearing facts:

| Question | Winning document | Note |
|---|---|---|
| What is the current revision? | `FINAL_COURSEMATE_JEV_DEEPSEEK_PRODUCTION_REPORT.md` §2 | It names the revision the release would ship; older `b8104d9`/`5be2d0a` references in it were corrected in round 30 |
| What is wired? | `JEV_CALLSITE_MATRIX.md` table 2 + `FINAL_COURSEMATE_JEV_STRUCTURED_ENHANCEMENT_REPORT.md` §5 | 12 case call sites + 13th (extraction field grounding) + all six modules + P2 |
| What is production? | `FINAL_COURSEMATE_JEV_DEEPSEEK_PRODUCTION_REPORT.md` §4 + `docs/jev-structured/MIGRATION_AND_ROLLBACK.md` | read-only verification 2026-09-22T01:59Z |
| What is the budget state? | `MINIMAL_OWNER_ACTION_CARD.md` §1b | **every figure is proposed, none approved**; USD left to the owner |

Historical documents (kept, not deleted, and now dated in place): `DSH_JEV_DEEPSEEK_PAUSE_AND_HANDOFF_REPORT.md`
(frozen at `6b85df7`, schema 28, production `5ba6a3a` — superseded), `FINAL_COURSEMATE_JEV_DEEPSEEK_RELEASE_REPORT.md`
(same era), `JEV_ABLATION_AND_PRODUCTION_ACCEPTANCE.md` (A/B/C/D only, 200/40/30 dataset *plan*).

Two files were found to be **internally inconsistent** and were corrected this round rather than
reconciled silently: `FINAL_COURSEMATE_JEV_STRUCTURED_ENHANCEMENT_REPORT.md` §7 quoted a stale mypy
count (1068/38) against its own §5 table (1074/39), and `LEARNING_AND_ASSESSMENT_STATE_SPEC.md` §2.5
implied the production migration target was 026–028 when `029` and `030` now exist.

## 3. What is actually finished (with the evidence that says so)

Claimed **finished and verified on a named revision**:

1. **12 case call sites wired and reachable** — single shared `SemanticDecisionService` threaded
   through `main.py` → orchestrator → UI extension mount → cm_update → adapter, plus the two internal
   APIs. Pinned by `test_jev_orchestrator_wiring.py`.
2. **All six structured modules wired with a consumer** — A extraction (query-side exact locator),
   B entity resolution (proposal-only relations + per-concept query expansion), C evidence consistency
   (per-source signal + conflict note into the teaching prompt), D claim/citation audit (pre-generation
   bundle + post-generation card audit), E capability router (consumes `skill_id` → `teaching_flow`),
   F tool-intent gate (opt-in, default `off`). Per-module entry points, authority boundaries and tests
   are tabulated in `JEV_CALLSITE_MATRIX.md`.
3. **P2 user feedback** — durable queue (migration 030), consent enforced by a schema CHECK, admin
   reader + own-list endpoint, shell entry.
4. **Local gates**: full backend regression and the four browser suites, re-run on the revisions this
   round produced — see §6 for the numbers and log paths.
5. **Frozen measurement assets preserved**: the 310-sample dataset and its split manifest are asserted
   unchanged by test (`content_hash 2af0f40d…`).

## 4. What is NOT finished, and why — by status class

The ledger carries 40 rows (B-01 … B-40) with full detail; the summary:

| Status | Count | Representative items |
|---|---|---|
| `RESOLVED_WITH_EVIDENCE` | 27 | module-D resolver type errors; missing QA-stream evidence bundle; `is_definitive` having no caller; the five module metrics being uncomputable; the companion dataset's missing split manifest; six documentation claims that did not match the code; the reference-gate note now reaching the shipped UI; the DeepSeek switch-window configuration refusals now pinned by test; the V1↔V2 template-parity question closed by measurement; an owner instruction that named an environment variable no code reads; a production marker that was written for an artifact set the verifier had just rejected; the call-site matrix now pinned to the catalog; the service that could not read the TypeSafe credential at all; the live adapter verified against the real SDK wheel; an ablation CLI that produced a fake run labelled `live`; a calibration artifact that could not say where its model evidence came from; and **a rollback check that read the assessment pool filter from one tree, so it could not have reported a changed one** |
| `LOCAL_IMPLEMENTATION_GAP` (open, mine) | **0** | none — every local gap this audit found is closed with code and a test |
| `WAITING_CREDENTIAL` | 2 | live Jev validation; live DeepSeek validation |
| `WAITING_BUDGET` | 1 | a real token/USD ceiling (all current figures are proposals) |
| `WAITING_PLATFORM_ACCESS` | 1 | one real sign-in for production acceptance |
| `WAITING_OWNER_DECISION` | 3 | document-side extraction surface; backup timer; Netlify publish method |
| `WAITING_PRODUCTION_APPROVAL` | 4 | boot-enable the two service units; the model switch; the migration/backup rehearsal; the push |
| `QUALITY_NOT_DEMONSTRATED` | 1 | no definition may leave `shadow` until a measured quality gate exists |
| `LIVE_PROVIDER_FAILED` | 0 | no live call has failed, because none has been attempted |
| `UPSTREAM_UNAVAILABLE` | 1 | the V2 visual render check: the source 16-template Word pack is not on this machine and there is no renderer (no LibreOffice, no `soffice`) |

Distinctions the ledger keeps explicit, because collapsing them is how a report lies:

* **not implemented** vs **implemented but not verified** — e.g. the Jev adapter exists and fails typed
  without a key; that is not the same as a provider contract being verified.
* **provider call succeeded** vs **the business uses the result** — the six modules consume their
  decisions in code; none of that has been exercised against a live model.
* **shadow receipt** vs **`effect_applied`** — every deployment so far is `shadow`, so `used_jev` is
  `false` everywhere and the deterministic value is what the learner sees.
* **missing data** vs **a model that failed** — until this round five module arms had *no labels at
  all*; that is now fixed, and it was never evidence about model quality.
* **account lacks permission** vs **a wrong SDK call** — nothing suggests an SDK defect; no credential
  exists to test with.

## 5. What this round actually closed (the local work, not the report)

1. **Two real type errors, one of them a genuine bug shape** — `app/jev/citation_evidence.py` passed a
   plain `str` where `RetrievalAccess` requires `Literal["official","mine"]`, and returned `Any` from
   three functions. Fixed; the file is now mypy-clean (`mypy app/jev/citation_evidence.py` → no issues).
2. **`is_definitive` had no caller, and the API conflated two different things** — the assessment
   reference-solution gate returned `verified: true` when only layer 1 (existence/authorization) had
   run. With no credential layer 3 never runs, so **every** reference solution looked verified. It now
   reports `verified` (layer 1 clean) and `definitive` (a real `SUPPORTED`/`CONTRADICTED` verdict)
   separately, using `citation_audit.is_definitive` as the single source of that rule.
3. **Module D reached its second shipped path** — `QaService.stream` (`POST /api/qa/chat`, a live
   endpoint) produced citations with no evidence-bundle annotation. It now runs the same bundle
   (≤2 calls: select one span, judge that span) and marks the selected card. With the layer genuinely
   absent the cards are byte-identical; with a configured-but-uncredentialed layer they carry
   `UNVERIFIED`/`false` — the same honest shape the UI path has used since round 25.
4. **The five module metrics were not merely "data-poor" — they were uncomputable.** Investigating why
   `INSUFFICIENT_SAMPLES` persisted led to the real cause: the runner had **no result collection** for
   those definition families, so `extraction_false_acceptance`, `extraction_false_rejection`,
   `entity_false_merge`, `entity_missed_alias`, `entity_conflict_false_positive`,
   `condition_distinction`, `capability_misroute`, `tool_false_allow` and `tool_false_block` could not
   be produced for **any** dataset. All ten metrics (plus two for P2 feedback) are now implemented,
   each with its population stated in the docstring and its denominator published next to the rate, so
   a `0.0` with an empty denominator cannot be mistaken for a clean result.
5. **A companion labelled dataset removes the data gap without touching the frozen one** — 49 samples,
   7 per definition, for exactly the seven definitions that had none: 6 `OBJECTIVE_VERIFIED` (each
   naming a deterministic rule verified in the code, e.g. `entity_resolution._classify_pair` and
   `evidence_consistency._narrow_pairs`), 41 `SOURCE_REVIEWED`, 2 `DISPUTED` with both readings
   recorded, **0 `SILVER_DEEPSEEK`** because no model was called. ~73% negative/edge cases, 33 en / 16 zh.
   The frozen dataset and its split manifest are asserted unchanged by test.
6. **Six documentation claims that contradicted the code were corrected where they stood** — module C
   described as `MODULE_ONLY`/"no call site" though it was wired in round 24; entity relations
   introduced as an unwired stub; "pending catalog registration" stated as current for two definitions
   that are registered; three module status lines stale in the existing→new mapping; plus the two
   internal inconsistencies in §2. Two *suspected* defects were checked and found **not** to be
   defects, and that is recorded too: `image_transcription.v1` is a deliberately supported non-catalog
   case set (the harness validates it separately), and the capability catalog's `handler` strings are
   documented metadata, not dispatch.
7. **The DeepSeek switch-window configuration refusals were pinned by no test — now they are.** This
   is the class of gap that hides best: the code was *correct*, so nothing failed. `Settings.validate()`
   refuses a DeepSeek environment with a non-`api.deepseek.com` host, a `/v1` or region path, a
   non-HTTPS URL, an embedded credential, a missing backend key, or any model other than
   `deepseek-flash`; and it requires the three preflight pricing values in production. The Qwen
   equivalents were pinned by `test_production_budget_config.py`; the DeepSeek branch had **no** test
   at all — zero hits for all four error strings across the test tree, and the single test that built a
   `provider_mode="deepseek"` settings object used valid values, so no rejection path had ever run.
   Loosening the host allowlist or the model pin would have passed the entire suite. 33 new tests pin
   every rejection by exact message, plus two positive controls (a valid DeepSeek environment both
   validates and boots through `create_app`), and two ordering facts that were previously assumed:
   validation happens **before** the database is opened and before any provider is chosen, so a bad
   switch-window environment fails at boot and leaves no half-initialised data directory. I checked the
   tests are not vacuous by measurement rather than assertion: with the DeepSeek validator replaced by
   a no-op, a Qwen host is *accepted* — so the allowlist is genuinely what rejects it.
8. **A parity question I opened last round was closed by measuring, and the answer was "add no test".**
   V1 template bodies show 11 `第N步` markers and V2 shows 1, which looked like a lost section. Across
   all 14 professional templates the top-level section numbers are **identical** in both versions
   (`5,6,7,8,9,10`), the `第N步` drop is **uniform** the whole way down, and each surviving V2
   occurrence is a prose mention inside a sentence rather than a heading; V2 additionally *adds* a
   subsection (`5.6`) and renumbers the step flow into `10.x`. The versions are deliberately
   non-parallel, so a parity test would have encoded a false invariant — and a version loose enough to
   pass would still pass with every section body emptied. None was added, and the measurement is
   recorded instead.

One item was recorded rather than substituted: the V2 templates have never been **rendered**, only
checked structurally and by marker (`visual_render_validation_performed_this_turn: false`). That is now
carried as `UPSTREAM_UNAVAILABLE` with its two concrete reasons — the original 16-template Word pack is
not on this machine (only `CS3481(1).doc` remains, under `02_ORIGINAL_DSH_DELIVERY/reference/` and
`work/ui-refresh-inputs/`) and there is no renderer (no LibreOffice, no `soffice` on `PATH`). Replacing a
render check with a structural one and calling it validation is precisely the substitution this project
forbids, so the flag stays `false`.

9. **The owner instruction I wrote in the previous round was not executable, and this is the most
   consequential thing I fixed.** Action 2 of `docs/recovery/OWNER_ACTIONS_ONLY.md` told the owner to put
   `DEEPSEEK_API_KEY` into the protected env. **No code in the repository reads that name.** Checking it
   against the three services turned up three *different* naming schemes that the switch must satisfy:
   the UI backend reads `CMUI_PROVIDER_MODE` / `CMUI_DEEPSEEK_API_KEY` through `os.getenv`; the RAG
   service's pydantic settings read bare uppercased field names, so the V3 teaching path needs
   `V3_MODEL=deepseek-flash` plus `V3_MODEL_API_KEY`, and the grounded QA role needs
   `DEEPSEEK_CHAT_API_KEY`; the TypeScript agent reads `AGENT_MODEL_NAME` plus `AGENT_MODEL_API_KEY`. The
   dangerous part was the failure mode: that pydantic model sets `extra="ignore"`, so a misspelled
   variable is **silently ignored** — the owner would have typed the line, seen nothing happen, and had
   no error to report. I also corrected a second misleading claim in the same section: "no DeepSeek
   variable exists in production" is true only of the *credential* variable; the variables that will
   carry the switch already exist holding the Qwen path, so the action is a **re-pointing, not an
   addition**. A second prerequisite was missing from the same instruction: `CMUI_ALLOW_BILLABLE=true`,
   without which five UI generation endpoints answer `402` and the provider raises
   `BILLING_NOT_AUTHORIZED` — so even a perfectly named key would have generated nothing. That variable
   is the project's deliberate money switch, and the document now says so. The document carries a
   verified per-service table. The reassuring half, also verified
   in code rather than assumed: every wrong *combination* fails loudly instead of generating on the
   wrong provider — `503 MODEL_ENDPOINT_INVALID` for a DeepSeek model with a Model Studio URL,
   `503 MODEL_LIVE_BLOCKED` when `V3_MODEL_API_KEY` is missing, the agent's refusal to start without an
   allowlisted endpoint, and the UI backend's refusal to boot (pinned by the 33 new tests above).

10. **A number I had reported as "unchanged" was wrong, and re-measuring it exposed two real defects.**
    Both this report and the ledger stated that the whole-app mypy count was unchanged, without
    re-running it since round 30. I ran it: **1077 errors in 38 files**, not 1074/39 — my own round-31
    module-metric collectors had added **+7** to `app/evaluation/jev_semantic_ablation.py` while the
    resolver fix removed 4. The seven were not cosmetic. `run_jev_semantic_ablation` reused a single
    variable `predicted` for two different payloads: the image branch assigns the answer **string**
    returned by `image_predictor` (`Callable[..., str | None]`), while every other family assigns a
    prediction **mapping** from `_predict` (`dict[str, Any] | None`). Because the string assignment came
    first, mypy pinned the name to `str | None` and **21 mapping uses** — `.get`, `_choice_prediction`,
    `_coverage_bool`, `_criterion_grade` — were never type-checked at all; a wrong payload there would
    have surfaced as a runtime crash in a measurement run. Renamed that branch to `predicted_answer`,
    matching the `ImageResult` field it feeds (behaviour-free: the branch appends and `continue`s). The
    second defect is in `recall_at_k`/`mrr`, which declared `relevant_ids: Sequence[str]` while every
    caller passes the `frozenset` the case objects store — only `returned_ids` is order-sensitive (it is
    sliced to the top *k* and ranked), so the label parameter is now `Iterable[str]` with the asymmetry
    documented. Net effect at that point: **1077 → 1010 errors in 35 files**, with
    `jev_semantic_ablation.py` (23 → 0), `jev_ablation.py` (40 → 0) and `receipt_store.py` (1 → 0) all
    clean — and the six errors still open then were closed in the next round, which is item 13 below.
    The ablation harness's 40 were
    the same defect class — twelve loops in one function reused the single name `case` across seven
    unrelated dataclasses — and since that file underpins every future calibration claim, I proved the
    rename behaviour-free instead of asserting it: the ablation CLI was run before and after, the raw
    outputs differ only in `latency_summary`, **a control run of the unmodified code differs from itself
    by exactly the same 12 lines**, and with the timings stripped all three runs canonicalise to one
    identical hash. One thing I am deliberately *not* claiming: the remaining debt is not "gone" — 728
    of the 1004 sit in `app/cm_update/app.py`.

11. **One more claim of mine was wrong, and checking it is what caught it.** The `app/jev/gateway.py`
    error looked like a latent crash: `authorized = set((criteria or {}).keys())` would raise
    `AttributeError` for a list, and the surrounding handler catches only `JevInvalidResponseError`, so
    the decision path would fail untyped. I wrote two tests asserting that a list of candidate ids is
    accepted — **both failed**, because `_build_question` already rejects a non-mapping for a Choice
    primitive with a typed `JevRequestError`; the list never reaches that line. I deleted both tests
    rather than adjusting them to pass, and what is committed is type-narrowing with the invariant named
    in the comment, which for an unreachable non-mapping degrades to the typed `invalid_response` instead
    of an untyped `AttributeError`. The `receipt_store.py` change was plain accuracy: `invalidate()`
    declared `-> int` and returned `cursor.rowcount`, which the sqlite3 stubs type as `Any`. This is the
    third time this round that re-measuring something I had already reported changed the answer, which is
    the reason the evidence table above names its command, its log path and its revision for every row.

12. **A required gate had no evidence at all, and is now measured: the agent service.** The task's gate
    list includes "Agent tests" and "Agent build", and the evidence table in this report covered the
    backend, the browser, the web app, the measurement suites, ruff and mypy — but never
    `services/agent-api`, even though the tool-intent guard (the thing that blocks a wrong side-effecting
    tool call) lives there and is cited by the call-site matrix. It has 12 test files: **92 vitest passed
    / 0 failed**, `tsc -p tsconfig.json --noEmit` exit 0, production build exit 0, and the 14 intent-gate
    tests are exactly the pair the matrix points at. I also verified the §18 deliverable set rather than
    assuming it: all 16 documents exist and none is a stub (the smallest is 51 lines, the largest 465).
    Verification, not construction, is the honest headline here — the round's *new* code is small; what
    changed is that four defects it found are fixed and three previously-unmeasured gates now have
    numbers.

13. **The whole Jev layer is now type-clean, and I fixed the last six errors instead of carrying them.**
    `app/jev/` and `app/evaluation/` report **zero** mypy errors (whole app 1010 → 1004 in 32 files, ruff
    unchanged at 1815). Each was a real type defect, not noise: `JevQuestion.criteria` is declared for all
    three primitives, so the Choice branch calls `Choice(criteria=dict(...))` on a value mypy can only see
    as a union — it now names the mapping first; the cache path assigns a concrete `JevAnswer` while the
    invalid-response path assigns `None`, so the binding is annotated optional; a SCORE definition's
    criteria is named locally because the catalog rejects a SCORE definition without it; `best_t` in
    `fit_temperature` returns `float(None)` to the checker even though the non-empty-grid check above the
    loop makes that unreachable, so the invariant is asserted; and a sixth error appeared only once those
    were gone — `deepseek_canary.py` indexing `["json_schema"]["schema"]` on a constant whose untyped
    nested literal made mypy join its array values to `Collection[str]`, now annotated. **One trade-off is
    stated rather than buried:** I removed the `# type: ignore` on the `typesafe_sdk` import because the
    documented gate (`mypy app --ignore-missing-imports`) flags it as unused, but a stricter invocation
    without that flag reports `[import-not-found]` — the SDK is genuinely not installed in the venv. That
    is a fact about this environment, not a defect: the import is guarded by `try/except ImportError`
    raising `JevUnavailableError`, which the suite exercises.

14. **The one gate item that was still resting on historical evidence now has a current answer — including
    the rollback check against the real production release.** The §12 gate list ends with migration,
    backup/restore and rollback compatibility, and my evidence for it was a script output recorded on
    `6e65396`. Two things are now measured rather than inherited. First, the suites themselves: **67
    passed / 0 failed** on the frozen revision, and the upgrade path is exercised from a genuinely older
    schema — `test_document_versions.py` builds a **V2** database with rows, initialises it with
    `v3_enabled=True` **twice**, and asserts the resulting `schema_migrations`, which proves the additive
    backfill and the idempotent replay in one test. Second, and more usefully, I produced **local rollback
    evidence against the actual production release**: `scripts/verify_rollback_compat.py` takes a
    `--release-tree`, so I made a temporary git worktree of `4ef5064` (which exists in this repository
    and declares `LATEST_V3_SCHEMA_VERSION = 25`, matching production) and pointed the tool at it. It
    builds a database with the current code, then runs the **old release's own code** against that
    migrated file. Verdict: **`ROLLBACK_SAFE_WITH_MIGRATED_DB`**, exit 0 — the old release imports and
    opens the schema-30 database with `integrity=ok`, zero foreign-key violations, no missing tables or
    columns, no retyped columns, no narrowed CHECK enums, and an unchanged assessment pool filter. (That
    last clause was **not** actually measured when this paragraph was written — round 42 found the field was
    read from this tree only, so it could not have reported a difference; see item 24. The re-run against
    the same release export still gives `UNCHANGED`, now by comparing both trees.) So if
    the migration has to be undone, the code-only path is viable; the pre-migration backup stays the
    primary path regardless. Nothing touched production: the worktree was under the system temp directory
    and has been removed. This is the kind of item that looks like it "needs the release window" and in
    fact had a locally executable half, which is the pattern this round was looking for.

    The same reasoning then produced the rehearsal itself. `scripts/rehearse_v3_migration.py` needs a
    `--source` database, which I had assumed meant the production snapshot — but the requirement is only
    that it be a database *at the older schema*, and the old release's own code can build one. So I used
    the `4ef5064` worktree to create a schema-25 database (its own `Database(settings)` API, one course,
    document and chunk seeded through the columns that schema actually requires), removed the worktree,
    and ran the rehearsal from the current tree. It copies the file, applies the real migration files
    001–030 and calls `initialize()` **twice**. Result: **`old_rows_unchanged: true`** — every
    fingerprinted table is byte-identical before and after by SHA-256, which is what "additive migration"
    is supposed to mean and is stronger than checking that the DDL ran; `integrity=ok`;
    `foreign_key_violations=0`; `v3_invariants_ok=true` with 52 counters at zero and only the four
    expected seeds/backfills non-zero (`document_versions=1` backfilled from the seeded document,
    `documents=1`, `grade_policy_versions=1`, `requirements_grade_policy_seed=1`). Evidence:
    `work/current-change/rehearsal-25-to-30.clean.json`. **The limitation is stated, not glossed:** the
    source is synthetic and has one row per table, so this proves the *schema* upgrade path and the
    invariant set, not that the real corpus has no awkward rows — the rehearsal against the production
    dump is still a release-window step and is listed as such.

15. **Running the publish path locally found a defect in its own safety net.** The same "does this really
    need the window?" question applies to the frontend publish, and the answer is that its *build and
    verification* half is local: `netlify.toml` runs
    `preflight_release_build.mjs && build && verify_release_build.mjs`, and both scripts are gated on
    `RELEASE_BUILD=1`/`CONTEXT=production`, so I could run the exact command with production-shaped
    configuration. The preflight passes, the build passes, and the verifier passes writing
    `build-info.json`. Then I ran the **negative** control — the same command against the real
    browser-acceptance dist — and it exited 1 listing seven forbidden markers, which is the safety net
    working. But it also **wrote `build-info.json` anyway**, with `context: production` and
    `not_for_production: false`, because the write happened before the failure check. That field is
    precisely what the backend's production gate reads to refuse the offline verification runtime, so the
    artifact set the verifier had just rejected carried a marker asserting it was production-ready. Impact,
    stated honestly: in the Netlify pipeline the non-zero exit fails the deploy, so nothing gets published
    and production was protected by the *pipeline*, not by the marker — the defect is that the marker is
    self-contradictory and any consumer of it is told the opposite of the verdict. Fixed by writing the
    marker only after a clean scan (and saying so on the failure path), then verified in both directions:
    contaminated dist → exit 1 and **no marker**; production-shaped build → exit 0 and a marker whose
    fields are actually populated. Two things this does *not* prove, and I am not claiming them: the
    Clerk **application** is unverified because my key is only shape-valid (`pk_live_…`), so a real sign-in
    remains a release-window check; and the local build ran through `pnpm --filter @coursemate/web run
    build` rather than `npm run build --workspace @coursemate/web`, because npm is not installed in this
    environment (the repo does declare npm workspaces). The gates themselves are the same files.

16. **A whole browser suite was missing from my evidence, and running it passed.** The task's gate list
    says to run the existing `coursemate`, `learning`, `ui-refresh` **and audit** journeys. I had been
    citing four suites and 32 journeys; `tests/e2e/codex-audit.spec.ts` — 14 journeys — had never
    appeared in any evidence table of mine. It is the most isolated suite in the repository: its
    Playwright config builds its own web bundle into a per-run directory, starts its own fixtures on
    its own ports (8200/8201/5373), runs with a deliberately stripped environment that excludes
    credentials and provider endpoints, and drives real Chrome. Result on the current revision:
    **14 passed in 1.9 minutes, exit 0**, with its report recording 14 expected / 0 unexpected /
    0 flaky / 0 skipped — and it covers journeys nothing else in the set does (normal vs Thinking
    routing through the integrated services, the late-Pair race, campus auto-access, the calendar's
    Node task store, keyboard reachability of the composer and upload actions, non-modal step windows,
    cross-account sharing, and a 100-character course name). My browser evidence is therefore
    **46 journeys across five suites**, and the repo's own `apps/web/dist` was untouched by the run
    (verified by digest, since the suite builds elsewhere).

17. **Two more deliverables carried stale "current state" numbers and are corrected.** Having found
    this pattern in the status report last round, I swept the other §18 deliverables for it rather than
    assuming they were fine. The genuinely stale ones were
    `DSH_JEV_DEEPSEEK_EXECUTION_STATE.md` — the file the task tells a resuming round to read first —
    whose gate table still read 1235 passed, 1074/39 mypy, 68 web tests on `6e65396`, and
    `FINAL_COURSEMATE_JEV_DEEPSEEK_PRODUCTION_REPORT.md`, whose "frozen revision and its evidence"
    table claimed the same revision and the same wrong mypy sentence. Both now carry a dated block with
    the current numbers, the earlier values kept beside them, and an explicit note that the mypy
    "none in a file this revision changed" claim was disproven by re-measurement. The remaining
    documents that mention `MODULE_ONLY`, "not wired" or "pending catalog registration" are **not**
    stale: each already carries a dated correction banner, which is exactly what the audit checks were
    for, so they were left alone.

    Sweeping further, the same pattern turned up somewhere that actually matters for the owner: three
    documents still prescribe a **Qwen canary with a CNY 5.00 budget**, which is doubly superseded — the
    architecture is now DeepSeek for all generation with Qwen auto-fallback forbidden, and the task
    specification says explicitly not to inherit old budgets. Two are actionable rather than historical:
    `docs/ui-refresh/RELEASE_CLOSURE_CHECKLIST.md` lists "approve CNY 5.00" as a **step for the owner**
    and its canary section is titled around 千问, and `DSH_EXECUTION_STATE.md` — which calls itself the
    sole resume reference for a later session — names "approve a Qwen two-stage canary (CNY 5.00
    suggested)" as the minimum unblocking action. A third, `docs/ui-refresh/QWEN_LIVE_TWO_STAGE_REPORT.md`,
    still says the amount to put in the authorisation box is CNY 5.00. Each now carries a dated banner
    naming what was superseded and pointing at the current sources
    (`MINIMAL_OWNER_ACTION_CARD.md`, `docs/recovery/OWNER_ACTIONS_ONLY.md`: **≤1,700 paid calls / ≤7.0M
    tokens**, USD set by the owner, proposed 15 + 10 + 2 = 27), with the original text kept for
    traceability. What those documents still get right — the approval channel, the ordered
    read-only/backup/deploy sequence, and "no execution without approval" — is stated in the banner so
    nothing useful is thrown away with the stale parts.

18. **The deliverable that proves the twelve call sites are real had no test, and the test found a
    defect on its first run.** `JEV_CALLSITE_MATRIX.md` is what the task asks for in place of "a helper
    exists": one row per definition saying where it is really called from, what state it reads, what it
    changes and what happens when Jev is absent. Nothing connected that file to the repository — the only
    reference to it in the whole test tree was a comment inside an E2E spec. It was accurate when I
    measured it (all 19 catalog definitions present, no phantom ids, Table 1 numbering the twelve, the
    count and version matching), but a drift would have been invisible. `tests/test_jev_callsite_matrix.py`
    now pins coverage, absence of phantoms, Table 1's contents, the stated count and catalog version, and
    the "all `shadow`" claim *through `JevGateway.mode_for`* so it follows from code. Two things worth
    reporting about writing it: my first draft asserted the table's row order matched the task's list, the
    test failed, and the right fix was to **drop the assertion** — the matrix deliberately numbers by
    pipeline position, and enforcing the task's order would have been a false invariant dressed as
    rigour. And non-vacuity is measured: five mutations of a copy of the matrix (row removed, phantom
    added, count changed, numbered row dropped, id misspelled) are each caught, 0 missed.

19. **The live Jev gate was not one credential away from working, and the owner was told it was.** This is
    the most consequential thing this round found. `SdkTransport` accepts the key **only** as a
    constructor argument — `def __init__(self, *, api_key: str | None = None, model: str = "jev")` — and
    `call()` raises the typed `JevNotConfiguredError` when it is falsy. The gateway constructs it as
    `SdkTransport()`, with **no arguments**. So nothing in the service ever read `TYPESAFE_API_KEY`: the
    owner could have placed the key in `/etc/coursemate/rag.env` exactly as instructed, restarted, and
    the live path would still have refused every call. And the same document said the SDK was "already a
    dependency, vendored under `services/rag-api`", which is false — `requirements.txt` carries
    `#   typesafe-sdk==0.7.0` **commented out** as an optional extra, and `find_spec("typesafe_sdk")` is
    `None`. So the gate needed three things, not one, and two of them were missing. I found it by writing
    the invariant the previous round's defect implied — *every variable the owner document names must be
    read by real code*, where "read" means an actual env accessor or settings field, so a name that
    appears only in a docstring counts as unread. Fixed in code: the adapter resolves the credential from
    the environment, an explicitly passed key still wins, and `TYPESAFE_MODEL` overrides the default model
    id. Proven by running it rather than by reading it: with the variable set, `SdkTransport()` passes the
    guard and the next failure is only `JevUnavailableError: typesafe-sdk is not installed`; unset, the
    typed `JevNotConfiguredError` still fires; `TYPESAFE_MODEL=jev-2` shows up in `transport.model`. The
    mutation proof includes the pre-fix file read from git: it *mentions* `TYPESAFE_API_KEY` in a
    docstring and does **not** read it, which is precisely the failure the new test would have reported.

20. **The live adapter had been verified against documentation, so I downloaded the package and verified
    it against the artifact.** The adapter's own docstring said its signatures were "verified against
    `docs.typesafe.ai`" — verified against prose, not against the thing that will actually be imported at
    the live gate. The pinned package turned out to resolve from the configured index
    (`typesafe_sdk-0.7.0-py3-none-any.whl`, 35 KB), so I downloaded and read it — **without installing
    it**, so no virtualenv was changed. That converted an assumption into a check and found **two real
    defects**, both introduced or missed while fixing the credential wiring the round before:
    the model override read `TYPESAFE_MODEL`, and the SDK's own constant is
    `DEFAULT_MODEL_ENV = "TYPESAFE_DEFAULT_MODEL"` — a name **no code and no SDK version reads**; and the
    adapter pinned its default model to `"jev"` when the SDK's default is `DEFAULT_MODEL = "jev-latest"`,
    so a live call would have asked for a model id the SDK does not default to. Both are fixed in the
    code and in the owner document. The other half is worth stating too, because it is the half that did
    not need changing: `Choice`/`Noul`/`Score`/`TypeSafeClient` are all exported; `TypeSafeClient.__init__`
    takes `api_key`/`model`/`base_url`/`timeout`; `Config.resolve` reads `API_KEY_ENV = "TYPESAFE_API_KEY"`,
    the exact variable my guard now reads, so guard and SDK agree; `system_one(state, questions)` is
    positional as called; `SystemOneResponse.choices/scores/nouls` are real cached properties over
    `answers`, and the fields the adapter reads — `ChoiceAnswer.choice`, `ScoreAnswer.score`,
    `NoulAnswer.noul` — all exist; and `DEFAULT_TIMEOUT = 10.0` matches the gateway's 10-second bound.
    A test now pins our names and default to the SDK's own constants whenever the package is installed
    (it skips here, which is honest: the package is deliberately optional). **A caveat on my own test**:
    the owner-document check cannot know which names the *SDK* reads, only that our code reads the names
    the document gives — which is exactly how `TYPESAFE_MODEL` slipped past it last round. The skip-aware
    test above closes that gap where it can be closed.

21. **The six component-ablation arms now have offline numbers, and the reason they sometimes look
    unmeasured is a pairing rule nobody had written down.** Running
    `scripts/run_jev_semantic_ablation.py --arm all-components --transport fake` against the companion
    dataset makes five of the six arms report **MEASURED** values with denominators — extraction false
    acceptance 1.0 over 4 and false rejection 0.0 over 2; entity false merge 1.0 over 4, missed alias 1.0
    over **1**, conflict false positive 0.0 over 4; condition distinction 0.0 over 4; capability misroute
    0.2 over 5; tool false allow 1.0 over 3 and false block 0.0 over 2 — all tagged
    `NON_INTERPRETABLE_PLUMBING_ONLY`, because the transport is the fake one. The sixth, `M-CITATION`,
    reports `INSUFFICIENT_SAMPLES` against that file **by design**: its definitions' labels (42 + 16
    samples) live in the frozen dataset, while the companion holds the seven definitions that had none.
    So no single dataset covers all six arms, and an operator who ran one file would read "unmeasured"
    for arms that are in fact measurable. That pairing rule, the union accounting (310 + 49 = 359 samples
    = the 19 catalog definitions plus the deliberate non-catalog `image_transcription.v1`) and the
    measured table are now in `JEV_CALIBRATION_AND_ABLATION_REPORT.md` §6.3. Two column meanings are
    stated there because they disagree on purpose and are easy to confuse: the number of labels for the
    decision a metric reads (7) versus the denominator its rate divides by (3 for `tool_false_allow`).
    And one number is deliberately flagged as thin rather than quoted: `entity_missed_alias` divides by
    **1**, so its value carries almost no information yet. I also checked the obvious suspicion that the
    two numbers meant a mis-mapping in the metric-to-decision table — they do not: each metric is mapped
    to the definition it reads, which is exactly what the docstring says.

22. **A `live` ablation run was produced by the fake transport, and the artefact said `live`.** Following the
    same "check the path the live gate will actually take" thread, I read the sibling CLI that runs the six
    component arms. Its `--transport live` branch called the runner with `FakeJevTransport()`, justified by a
    comment saying the branch was "unreachable after `_live_preflight`". That is true only while the
    credentials are **absent**: `_live_preflight` passes when both `TYPESAFE_API_KEY` and `DEEPSEEK_API_KEY`
    are set and `--allow-billable` is given — precisely the situation the owner is being asked to create.
    Reproduced before touching anything, with dummy keys set and no call made: the CLI exited **0**, ran the
    fake transport, and wrote a 6,594-byte artefact whose top-level `transport` field said **`live`** while
    each arm line said `deterministic_fake`. That is the substitution this project forbids, sitting on the
    exact path the live gate would take. Fixed three ways, because the fix should not depend on one guard:
    the live branch refuses with exit 3 and a named reason and writes nothing; the payload records
    `transport_used` beside the requested `transport`; and the CLI refuses to write at all if those two
    disagree. Verified by running both paths — live now exits 3 with no file, offline exits 0 and records
    `transport: fake` / `transport_used: deterministic_fake` — and mutation-proved against the pre-fix script
    read from git, which returns 0 and writes the artefact claiming `live`, so the new test fails on it.
    **The reason it survived is worth stating:** nothing ran this CLI. Four suites reference the ablation
    module and all of them import it rather than the command line, so the file had no coverage at all.
    `tests/test_jev_semantic_ablation_cli.py` now drives `main()` directly (3 tests), covering both
    refusals and the recorded transport. The sibling A–E CLI was checked and does **not** share the defect.

23. **The calibration artefact could not say where its model evidence came from.** Checking the remaining
    artefact-producing tools on the live path, the calibration CLI pins its dataset by content hash and its
    split by name, and records the input *paths* — but the predictions file itself, which is the only model
    evidence it consumes, was represented by nothing but a path string. A synthetic predictions file
    therefore produced an artefact that reads exactly like a fitted result: buckets, `n_calibration`, ECE
    before and after, a dataset hash. Nothing in the file said the numbers came from a stub — I had to say
    so in **prose** in the last round's report ("demonstrates the plumbing, and is not a calibration
    result"), which is exactly the situation where the artefact should speak for itself, because this is
    the artefact a promotion decision would lean on. Fixed by recording two fields: `predictions_sha256`
    pins the exact model evidence the way the datasets are already pinned by content hash, and
    `predictions_provenance` carries an explicit statement from a new optional
    `--predictions-provenance` flag that defaults to **`UNSTATED`** and prints a note telling the operator
    that the numbers are only as real as the predictions file. The flag is optional so existing callers
    keep working, and the existing test was **strengthened** rather than adjusted to assert both fields.
    Verified by running the CLI twice: without the flag the artefact records `UNSTATED` and the note is
    printed; with it the text is recorded verbatim; both artefacts' `predictions_sha256` equal the
    predictions file's own digest. No new lint debt — the file still reports the same 2 pre-existing E402
    as its pre-change version taken from git.

    The same sweep produced a **negative** result worth recording, because a clean check is also evidence:
    the DeepSeek canary CLI is already correct. Its preflight **returns** (it does not fall through), and it
    is followed by an explicit refusal chain — missing key, missing `--max-cost`, non-finite or
    non-positive cost, missing prices, cost ceiling exceeded, existing output or checkpoint — before it
    ever builds the real `httpx` transport. I ran those refusals rather than reading them:
    `--allow-billable` without a key exits **2** ("Missing credential environment variable"), with a dummy
    key but no `--max-cost` exits **2** ("--max-cost is required for a billable run"), and with no
    `--allow-billable` it exits **0** after printing the ten per-role token ceilings *before* any call.
    No network was contacted and nothing was spent.

Two of my own first-draft claims were wrong and were corrected in place rather than left standing: I
first recorded the retrieval re-rank as "40 calls per page, fixable by batching" — it is bounded at
**16**, and the batching I proposed is not available for that shape (`JevCall` shares one state across
its questions, and per-candidate scoring has a different state per candidate). And I first asserted the
QA stream would be byte-identical without a credential — `create_app` **always** builds a service, so
"no credential" is not "no layer"; only `jev=None` is byte-identical.

24. **The rollback check could not report a changed pool filter, so "unchanged" was never measured.**
    Item 14 above says the rollback verdict includes "an unchanged assessment pool filter". Reading the
    tool rather than its output, that field was `report["pool_filter_unchanged"] =
    bool(current_pool_filter())` — the **current** tree's own filter, extracted from this worktree, with
    the release tree never consulted — while the module docstring promised "is the assessment pool filter
    unchanged, so old and new code select the same pool?". The field therefore read `true` for every
    release tree that could ever be passed, whatever that release's filter was; it would have read `false`
    only if *this* tree lost its own filter, a condition with nothing to do with the release. So the clause
    in item 14 was **accidentally correct rather than verified** — the predicate does turn out to be
    byte-identical between the two trees (checked with the tool's own regex against
    `git show 4ef5064:services/rag-api/app/learning/assessments.py`: raw equal), and it is now measured
    instead of assumed. Fixed by a `compare_pool_filters(release_root, current_root)` that extracts the
    predicate from **both** trees and reports `UNCHANGED`, `CHANGED` or `UNDETERMINED` with both extracted
    strings and the reason; `pool_filter_unchanged` is `true` only for `UNCHANGED`, and anything else goes
    into a new `rollback_concerns` list that deliberately does **not** change the database verdict — a
    changed pool filter means the rollback changes behaviour, not that the database must be restored, so
    folding it into `reasons` would have made the tool lie in the other direction. The artefact's note now
    says exactly that. A second defect came out of the same reading: `run_old_release` passed `text=True`
    with no encoding, so the release's output was decoded with this machine's locale codec (cp936) — one
    byte the locale cannot decode kills `subprocess`'s reader thread and the tool reports "the previous
    release printed nothing" instead of the release's real failure. A third, smaller defect in the same
    function was fixed with the test that pins it: its `json.loads(...)` result was returned unchecked, so
    a release whose output parsed as JSON but was not an object handed `main()` a list and the first
    `old.get(...)` died with an opaque `AttributeError: 'list' object has no attribute 'get'`; the probe
    output is now checked and the cause named, which also cleared the file's one pre-existing mypy error
    (`no-any-return` — measured with `work/current-change/check_mypy_rollback_tool.py` to exist before this
    round and to surface only under the service's stricter config, since from the repo root the same file
    reported success). Verified by running it on the real
    artefact: a fresh export of `4ef5064` gives `pool_filter_verdict: UNCHANGED` with detail
    "byte-identical predicate" and empty `rollback_concerns`, and the **same export with one clause added
    to its pool filter** gives `CHANGED` with `rollback_concerns` populated while the database verdict and
    exit code stay as before — a state the old code could not express at all. The corrected tool was also
    re-run against `b05fd294` (own schema 26), the release whose pool filter the earlier Schema-26 report
    asserted was identical: `UNCHANGED`, "byte-identical predicate", empty `rollback_concerns`, verdict
    `ROLLBACK_SAFE_WITH_MIGRATED_DB` — so that older claim is measured for that pair too. Nine new tests, and
    the suite was mutation-proved: restoring the pre-fix comparison, hardcoding the field, removing the
    explicit encoding, dropping the release-absent branch, or removing the probe-output check each fails it
    (5 of 5 caught). No test had **ever** run this tool before — `tests/test_schema_rollback_compat.py`
    mentions it only in a docstring, which is how a field that could not say no survived four rounds of
    being cited as evidence. Honest limits: the comparison is **source text**, not runtime behaviour; two
    different texts that select the same rows are reported `CHANGED`, and a change made identically in both
    trees is invisible to it. The probe subprocess also runs without a timeout, so a release that hangs
    blocks the tool instead of being reported. The sibling rehearsal tool
    (`scripts/rehearse_v3_migration.py`) was checked for the same shape and is genuinely comparison-based —
    `old_rows_unchanged` is `before == after` around the migration and `v3_invariants_ok` is a 25-term
    conjunction — so the defect was confined to this one field.

    **Why this one matters for the release:** it was in the evidence I would have handed to whoever runs
    the migration window. The verdict itself (can the old release open the migrated database?) was always
    real — it comes from running the old release's code — but the reassurance sitting next to it was not.
    All three cited artefacts were also re-produced by the shipped revision after the probe guard was
    added, and they are field-for-field identical (`work/current-change/rollback-compat-*.rerun.json`), so
    the evidence describes the code as committed rather than an earlier revision of the tool.

## 6. Evidence for this round

| Gate | Result |
|---|---|
| Full backend regression | **1314 passed / 1 skipped / 0 failed** in 1534.25s (exit 0) — `work/current-change/full_run_round42b.log`, run on the **frozen** revision `2fd532b`, with `git diff 2fd532b -- services benchmarks scripts` empty so the run describes the code as shipped. The delta from 1305 is exactly the **9** rollback-tool tests added this round (the tool had none); the one skip is the skip-aware SDK-constants test |
| Calibration artefact provenance (new this round) | Run twice on a synthetic predictions file for the companion dataset: without the flag the artefact records `predictions_provenance: 'UNSTATED'` and the CLI prints the note; with `--predictions-provenance "…"` the text is recorded verbatim; in both cases `predictions_sha256` equals the predictions file's own digest (`d06b9961…`). `scripts/calibrate_jev.py` reports the same 2 pre-existing E402 as its pre-change version from git, so no lint debt was added |
| DeepSeek canary CLI guards (verified this round, no defect) | Run rather than read: `--allow-billable` with no key → **exit 2** "Missing credential environment variable: DEEPSEEK_API_KEY"; `--allow-billable` with a dummy key and no `--max-cost` → **exit 2** "Refusing provider calls: --max-cost is required for a billable run"; without `--allow-billable` → **exit 0** after printing the ten per-role token ceilings *before* any call. Its preflight returns rather than falling through, and the refusals precede the real `httpx` transport. No network was contacted |
| Ablation CLI coverage (new this round) | `tests/test_jev_semantic_ablation_cli.py` (3 tests) is the first coverage this entry point has ever had: it asserts the live branch refuses (exit 3, no artefact), that the preflight still refuses without authorization (exit 2, no artefact), and that an offline run records `transport: fake` with `transport_used: deterministic_fake`. Mutation-proved against the pre-fix script read from git, which exits 0 and writes an artefact claiming `live` |
| Two invariant suites added this round | `tests/test_jev_callsite_matrix.py` (5) pins the §3 deliverable to `app/jev/catalog.py` and `JevGateway.mode_for`; `tests/test_owner_actions_name_real_variables.py` (3) fails if any variable the owner document names is not read through a real mechanism. Both carry a measured mutation proof (5/5 and 3/3 respectively, including the pre-fix gateway read from git) |
| Rollback-tool comparison (new this round) | `tests/test_rollback_compat_tool.py` (**9 tests**) is the first coverage this tool has ever had: it pins the three pool-filter states, that the field is `false` whenever the two trees were not actually compared, that `main()` still reaches `ROLLBACK_REQUIRES_DB_RESTORE`, that a release printing non-locale bytes is analysed rather than crashing subprocess's reader thread, and that a probe output which parses but is not an object is named instead of returned. Mutation-proved **5 of 5** (`work/current-change/mutation-check-rollback.py`, tool restored byte-for-byte), and run against real exports: `4ef5064` and `b05fd294` both give `pool_filter_verdict: UNCHANGED` with detail "byte-identical predicate" and empty `rollback_concerns`, while the `4ef5064` export with one clause added to its pool filter gives `CHANGED` and lists the concern without changing the database verdict |
| Browser journeys (real Chrome, real three services, injected identity) | **46 journeys / 0 failed** — `ui-refresh` 19, `jev-structured` 6, `coursemate` 4, `learning` 3 (re-run on `6ba70b0`) **plus `codex-audit` 14** (round 37, on `d656bf7`). The audit suite is isolated: its own fixtures, its own ports (8200/8201/5373), its own web bundle built into the run directory, and a stripped environment ("do not forward account credentials, provider endpoints, or live environment files" is in its config); its Playwright report records **14 expected / 0 unexpected / 0 flaky / 0 skipped**. It had never been part of this report's evidence before, which is itself the finding — the task's gate list asks for the audit journeys and I had been citing four suites, not five |
| Web app | `tsc --noEmit` exit 0, **73 vitest passed** (18 → 19 files), production build exit 0 |
| Agent service (`services/agent-api`, TypeScript) | **92 vitest passed / 0 failed** (12 files), `tsc -p tsconfig.json --noEmit` exit 0, production build exit 0 with `dist/src/server.js` emitted — run this round on `cfd0ef1`; the 14 intent-gate tests are `executor-intent-gate.test.ts` (6) + `intent-gate.test.ts` (8), exactly the pair the call-site matrix cites for tool misexecution |
| Measurement / module-metric suites | **121 passed** (`test_jev_module_metrics.py` 13, `test_jev_module_split_calibration.py` 8) |
| Six component ablation arms, run offline (this round) | `scripts/run_jev_semantic_ablation.py --arm all-components --transport fake` now produces **MEASURED** metrics with published denominators for five of the six arms, over the companion dataset: `M-EXTRACT` (false acceptance 1.0 over 4, false rejection 0.0 over 2), `M-ENTITY` (false merge 1.0 over 4, missed alias 1.0 over **1**, conflict false positive 0.0 over 4), `M-CONSISTENCY` (condition distinction 0.0 over 4), `M-CAPABILITY` (misroute 0.2 over 5), `M-TOOL` (false allow 1.0 over 3, false block 0.0 over 2). Every number is tagged `NON_INTERPRETABLE_PLUMBING_ONLY` — it shows the arms compute where labels exist, not that quality is good. The sixth, `M-CITATION`, correctly reports `INSUFFICIENT_SAMPLES` **against the companion** because citation labels live in the frozen dataset; the pairing rule (which dataset each arm needs, and why no single file covers all six) is now written into `JEV_CALIBRATION_AND_ABLATION_REPORT.md` §6.3 having been absent before |
| Migration, backup/restore and rollback gate (run this round) | **67 passed / 0 failed** across `test_document_versions.py`, `test_four_change_migration.py`, `test_assessment_runtime.py`, `test_backup_restore.py`, `test_backup_ui_extension.py`, `test_monitor_v2.py`, `test_knowledge_registry.py`, `test_database.py` and `test_codex_snapshot_backup.py`. The upgrade path is not just asserted: `test_document_versions.py` builds a **V2** database with course/document/chunk rows, then initialises the same file with `v3_enabled=True` **twice** and asserts the resulting `schema_migrations`, so the additive backfill and the idempotent replay are proven together |
| The 25 → 30 upgrade rehearsed end to end (run this round, locally) | `scripts/rehearse_v3_migration.py` on a source database built by the **old release's own code** (`4ef5064`, schema 25, one course/document/chunk seeded): real migrations 001–030 applied to a copy with `initialize()` called **twice** → **`old_rows_unchanged: true`** (every fingerprinted table byte-identical before and after by SHA-256, so the upgrade is strictly additive), `integrity=ok`, `foreign_key_violations=0`, `v3_invariants_ok=true` with **52** counters at zero and only the four expected seeds/backfills non-zero (`document_versions=1` backfilled from the seeded document, `documents=1`, `grade_policy_versions=1`, `requirements_grade_policy_seed=1`). Evidence: `work/current-change/rehearsal-25-to-30.clean.json`. **Not covered:** the source is synthetic and one row per table, so the same rehearsal against the real production dump remains a release-window step |
| Production frontend build, local half (run this round) | The exact Netlify command from `netlify.toml` — `preflight → build → verify` — with production-shaped configuration (`pk_live`-shaped Clerk key, `VITE_UI_API_BASE=https://rag.qqttai.com/ui-extension/api/ui/v1`, `VITE_RAG_API_URL`/`VITE_AGENT_API_URL` on the two documented hosts, `VITE_V3_ENABLED=true`, `VITE_AUTH_TEST_TOKEN` **unset**): preflight **exit 0** ("production configuration checks passed"), build **exit 0**, verify **exit 0** writing `build-info.json` with 8 artifact hashes, `context=production`, `not_for_production=false`, the Clerk field present and all three origins recorded. **Negative control on the real browser-acceptance dist: exit 1** listing seven forbidden markers (`test-session-token`, `VITE_AUTH_TEST_TOKEN`, `http://localhost:`, `localhost:8000/8001`) — the safety net demonstrably blocks the build I use for E2E from ever being published. Deviations stated: the local build ran through `pnpm --filter @coursemate/web run build` because npm is not installed in this environment (the repo does configure npm workspaces), and the Clerk **application** is not verified — the key is shape-valid only, so a real sign-in remains the release-window check |
| Rollback compatibility against the production release (run this round, locally) | **`ROLLBACK_SAFE_WITH_MIGRATED_DB`**, exit 0 — `scripts/verify_rollback_compat.py` with `--release-tree` pointed at a git worktree of `4ef5064` (the production release, own schema 25). It builds a database with the current code (all migrations to 30) and runs the **old release's own code** against that file: no import or open error, `max_migration=30` seen by code whose own schema is `25`, `integrity=ok`, 0 foreign-key violations, no missing tables or columns, no retyped columns, no narrowed CHECK enums, assessment pool filter unchanged across the four rebuilt tables. Evidence: `work/current-change/rollback-compat-4ef5064.json`. **Corrected in round 42:** that pool-filter field was read from this tree only and could not have reported a difference (B-41). Re-measured against the same release export: a fresh export of `4ef5064` gives `pool_filter_verdict: UNCHANGED`, detail "byte-identical predicate", both extracted predicates recorded and `rollback_concerns` empty, while the same export with one clause added to its filter gives `CHANGED` with the concern listed and the database verdict unchanged. Evidence: `work/current-change/rollback-compat-4ef5064-{r42,mutated-r42}.json`. The worktree was a temporary checkout under the system temp directory and was removed afterwards; production was not contacted |
| ruff | **1815 errors at the pre-change revision and 1815 after** for app+tests, unchanged even with a 221-line test file added (ruff 0.16.2 from the service venv, run **with `services/rag-api` as the working directory** over `app tests`); the new script is additionally clean under the service config, where its siblings in `scripts/` carry 19 pre-existing E402 and 207 E501. It did rise to **1821** mid-round, when the renamed loop variables pushed six lines past the 100-column limit; those were rewrapped in their own commit, so the total is back to 1815 rather than reported as "unchanged" without measuring |
| mypy | **1004 errors in 32 files** — *not* "unchanged", as my earlier reports claimed: measuring it showed 1077/38 (and 1074/39 at round 30), because my own round-31 work had added 7. Six in-scope defects fixed since, removing 73 errors (1077 → 1004), and **`app/jev/` and `app/evaluation/` now report zero errors**. The remainder is reported by rule, not hidden: 728 of 1004 in `app/cm_update/app.py`, and the bulk are `no-untyped-call` / `no-untyped-def` / `type-arg` |

**A lint trap I fell into and corrected, recorded because it produced a wrong verdict.** The same file
lints *differently* depending on the working directory even when the config is passed explicitly with
`--config`: ruff resolves its project root — and therefore `per-file-ignores` and `src` handling — from
the invocation. Checking the new test file from the repository root reported "All checks passed", so I
accepted an import-sorting autofix; run from `services/rag-api` (the canonical cwd, and the one the
1815 figure comes from) that same autofix had *introduced* one `I001` error. I found it only because I
re-measured the total instead of trusting the single-file result: it read 1816, not 1815. Fixed under
the canonical invocation, file re-verified clean, total back to 1815, and the test file re-run after
the fix (33 passed).

**A second tooling trap, recorded for the same reason: an editor write silently converted a whole file
to CRLF.** These Python sources are LF-only, and `core.autocrlf=false` is used for every git command
here, so a CRLF rewrite shows up as a whole-file diff. It happened twice: `jev_semantic_ablation.py`
first appeared as a **3545-line** change for a 13-line edit, and later `app/jev/gateway.py` as a
**571-line** change for two one-line edits. Both were caught before the numbers were reported by
checking `git diff --stat` against the intended change rather than trusting it, and both were normalised
back to LF byte-wise, after which the real diffs were 13 and 7 lines. The practical rule this round
adopted: after editing any Python file, compare `git diff --stat` with the size of the change you meant
to make, and audit the line endings of every modified file before committing.

The regression delta is exactly accounted for at every step: 1235 → 1252 (4 QA tests + 13 metric
tests) → 1260 (8 split/calibration tests) → 1293 (33 config-guard tests) → **1301** (5 call-site-matrix
tests + 3 owner-document tests); the web delta 68 → 73 is the 5 reference-note tests. No test was
renamed, skipped or weakened to reach any of these numbers, no threshold was lowered, and the two tests
I drafted for the gateway in an earlier round were **deleted** when they were found to assert a false
contract.

### 6.1 Backend regression

Command: `services\rag-api\.venv\Scripts\python.exe -m pytest -q` (earlier rounds added
`-p no:cacheprovider`; that flag only stops `.pytest_cache` being written and does not affect results)
Log: `work/current-change/full_run_round42b.log` → `1314 passed, 1 skipped, 2 warnings in 1534.25s
(0:25:34)`, exit 0, on the frozen revision `2fd532b`. Only documentation changed after that commit, so
this run still describes the services and scripts in the tree. The two warnings are pre-existing
third-party deprecations (`starlette.testclient` with `httpx`, and an `anyio.abc.BlockingPortal` alias),
not failures. The skip is named in the log (`tests/test_owner_actions_name_real_variables.py:141`) and is
the skip-aware SDK-constants test; it is the only skip in the run.

Evidence hygiene, stated because it tripped me up while re-reading: these logs are **UTF-16LE**
(PowerShell's `Tee-Object`), as are the earlier rounds' logs, so a UTF-8 reader shows them as spaced-out
mojibake. Every log was decoded and diffed before being cited here. Six exist and each carries its own
summary — `full_run_round31.log` `1252` (1681.27s), `round32` `1260` (1589.54s), `round33` `1293`
(1408.76s), `round34` `1293` (1493.21s), `round34b` `1293` (1610.00s) and `round35` `1293`
(1577.08s) — with distinct SHA-256 hashes, which is not something the byte counts alone would show,
since all six happen to be exactly 4832 bytes. Two of them are deliberately superseded and are kept
rather than deleted: `round34` was green, but I then changed `jev_ablation.py` to fix the lint debt the
rename had introduced, and `round34b` was green too until round 35 changed three more files, so I
re-ran the whole suite on the frozen revision and **`round35` is the run the table above cites**. A
green run that no longer describes the tree is not evidence for the tree.

### 6.2 Browser journeys

Command: `pnpm exec playwright test -c playwright.<ui|jev|config|v3>.config.ts` (four suites, real Chrome
via `C:\Program Files\Google\Chrome\Application\chrome.exe`, isolated injected identity — no production
Clerk). Result: 19 + 6 + 4 + 3 = **32 passed, 0 failed**. The journeys that exist, and the ones that
cannot yet exist because they need a live signal, are itemised in `JEV_CALLSITE_MATRIX.md`
§"Browser journeys: what exists, what cannot exist yet, and why".

## 7. External operations and money

* **Live model calls made this round: 0.** Jev live: 0. DeepSeek live: 0. Embeddings: 0.
* **Money spent this round: 0.** The only external contact in this work has been read-only production
  inspection in an earlier round (recorded 2026-09-22T01:59Z, variable *names* only, never values).
* **Approved budget: none.** `MINIMAL_OWNER_ACTION_CARD.md` §1b lists proposed ceilings (≤1,700 paid
  calls / ≤7.0M tokens; USD 15 + 10 + 2 = 27 combined) and explicitly leaves the USD number to the
  owner. I did not treat any of it as approval, and I did not spend anything.
* **Credentials:** no `TYPESAFE_*` or `JEV_*` variable exists in `/etc/coursemate/*.env`; no DeepSeek
  key is present either. Nothing has been requested in chat; only variable names appear in the reports.

## 8. Production: touched? deployed? accepted?

**No / No / No.**

* No deployment, no migration, no service restart, no DNS change, no publish, no production data write.
* Production is still release `4ef5064`, schema 25, Qwen models, and the published CS3481/GE2324 trees
  were not regenerated. SRSZQ is untouched.
* Two production risks remain **recorded and unfixed by design** (they are owner actions): both
  `coursemate-rag` and `coursemate-agent` are `disabled` at boot although they declare
  `WantedBy=multi-user.target` (the next reboot is an outage), and no CourseMate backup timer exists,
  which is why `coursemate-monitor` reports `failed` on a 32-hour-old snapshot.
* Because nothing is live-verified and every definition is still `shadow`, the correct overall verdict
  for the release is **PARTIAL — release-ready locally, unverified in production**, not "deployed and
  accepted".

## 9. What is genuinely left for the owner

Exactly four actions, each with its scope, platform and reversibility spelled out in
`docs/recovery/OWNER_ACTIONS_ONLY.md`:

1. Put a **TypeSafe Jev credential** into the protected backend env (`TYPESAFE_API_KEY`) — unlocks live
   validation, calibration and the ablations.
2. Put a **DeepSeek key** in the same protected env and **confirm one ceiling** (calls / tokens / USD) —
   unlocks the live acceptance run. (One number, not a key, is needed from you.)
3. Approve or defer a **production window** — plus two 10-second decisions inside it: enable the two
   service units at boot, and add a backup timer (or relax the monitor threshold).
4. Answer one **product question** about the document-side extraction surface (leave it unwired / add a
   per-field review slot with a consumer / flag-only), because building an annotation nothing reads is
   the pattern this project refuses to count as integration.

I will not ask for keys, tokens or passwords in chat, for blanket admin rights, or for a production
database copy in a shared location.

## 10. Dependency order from here

1. Owner: action 1 + 2 (one message with a ceiling) → 2. Jev + DeepSeek canaries in `shadow` (bounded,
   logged with call/token counts) → 3. calibration on the calibration split only, thresholds
   pre-registered → 4. the A/B/C/D/E and module arms on the frozen + companion datasets, test split
   touched only once → 5. promotion decisions per definition (retrieval re-rank first, plus at least
   one of context/intent/pedagogy) → 6. owner: action 3 (production window) → 7. read-only production
   re-verification → consistent backup → isolated restore → migration 026–030 rehearsal → rollback check
   against `4ef5064` → immutable release → protected env → frontend build → publish → real acceptance →
   post-release backup and monitoring → 8. push and final report.

Everything in steps 1–2 of that chain is owner-gated; nothing else in the list is.

## 11. Facts I could not confirm

* **Live provider behaviour of any kind** — no credential, so no prompt conformance, no latency, no
  real cost, no failure-mode data. Any statement about how the live Jev or DeepSeek behaves is
  unverified, including that the SDK call shape is accepted by the real service.
* **Production state as of today** — the newest production facts I hold are from the 2026-09-22T01:59Z
  read-only pass; uptime, disk, backup age and service health may have changed since. They will be
  re-verified before any release step.
* **Whether the extended dataset is sufficient for calibration** — 7 samples per definition is a
  starting population. `entity.relation.v1` drew no calibration-split group at all, so its thresholds
  cannot be fitted until it has more groups. I am not claiming the dataset is adequate; I am claiming
  it is real, validated, and no longer empty.
* **Teaching-quality effect of anything** — unmeasurable without the live ablation. No threshold was
  invented, nothing was promoted, and no number in this report should be read as a quality result.
