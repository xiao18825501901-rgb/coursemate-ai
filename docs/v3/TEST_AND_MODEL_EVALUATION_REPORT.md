# CourseMate V3 — Test and Model Evaluation Report

Last updated: 2026-09-12 after Stage 5 implementation, migration rehearsal and browser isolation recovery.

Branch: `feature/coursemate-v3-persistent-learning`

Stage-switch base: `c6158cf34142c311e77a58aa49a3b0b7cbe7fbd8`; Stage 1 commits are `00961ef` through `e9ecd00`; Stage 2 code commits are `6eeff90`, `5a1f9d0`, `0be1a47`, `86032bb` and `5dba760`; Stage 3 code commits are `956d849`, `da1fa2a`, `e5d14d3`, `52514d1` and `2256cf0`; Stage 4 code/evidence commits are `5b88c3e`, `ebe2ffa`, `1eb94ed` and `cf8466b`; Stage 5 implementation and hardening commits run from `141057a` through `a882d36`.
This report is cumulative and must be updated after every behavior change; old PASS does not cover later code.

## 1. Current evidence summary

| Acceptance layer | Result | Meaning |
|---|---|---|
| Source implementation | PARTIAL | Stages 1–5 source slices exist; Stages 6–8 are not complete |
| Python automated tests | PASS for current Stage 5 code | 284 passed; 1 known dependency deprecation plus local pytest-cache ACL warning |
| Web unit tests | PASS | 10 files / 39 tests passed |
| Task Agent unit tests | PASS | 53 passed; V3 did not take over task tools |
| Python lint/type | PASS | Ruff app/tests/scripts; mypy strict app 57 files |
| TS typecheck/build | PASS | both workspaces typecheck; production bundles built locally |
| Browser regression | LOCAL_FAKE_PROVIDER_VERIFIED | 5 Playwright tests passed against an isolated DB copy; source DB/uploads before/after summaries matched |
| Real model | NOT VERIFIED | no paid call, account/region/endpoint unknown |
| Real-data migration/recovery | PARTIAL | pre-test 1–15 snapshot copied and upgraded through 018; local E2E incident recovery verified; full two-DB/uploads restore remains unverified |
| Production | NOT VERIFIED | no current release/auth/provider/Schema smoke evidence |

## 2. Cumulative local commands and actual results

### Database feature gate — red evidence

Before implementation, focused tests expected V2 initialization to stop at 10 and V3 readiness to require 12:

```text
python -m pytest tests/test_database.py -q
4 failed, 11 passed
```

Failures showed current code applied 011/012 with V3 disabled and considered V3 ready after removing version 12. A dedicated V3-off API test then failed because V2 course creation queried missing `learning_workspaces`.

An interim full run after gating migrations exposed every affected V2 query rather than being hidden:

```text
50 failed, 167 passed, 5 errors, 3 warnings
```

Root cause: workspace-hiding SQL added to shared course/access/publication paths assumed the V3 table always existed. The implementation was made feature-aware; no tests were removed or skipped.

### Focused regression — green evidence

```text
python -m pytest \
  tests/test_database.py tests/test_learning_workspace.py \
  tests/test_ingestion_api.py tests/test_publication_api.py -q

45 passed, 2 warnings, 18.97s
```

### Full Python regression

```text
python -m pytest -q -o cache_dir=../../work/pytest-cache
241 passed, 1 warning, 51.49s
```

The remaining warning is Starlette’s current `httpx` TestClient deprecation notice. The redirected cache path avoids a local `.pytest_cache` ACL warning; it does not change test selection.

### Static checks

```text
python -m ruff check app tests
All checks passed!

python -m mypy app
Success: no issues found in 52 source files
```

Ruff initially found seven formatting/import findings in the newly added safety test; they were corrected with source edits and Ruff was rerun. No auto-fix changed behavior.

### Web and Task Agent

```text
npm test
Web: 7 files / 30 tests passed
Agent: 9 files / 53 tests passed

npm run typecheck
Web tsc: pass
Agent tsc --noEmit: pass

npm run build
Web Vite: 115 modules, pass
Agent tsc: pass
```

Local Web output at this point was `index-CXB8r7sj.js` 310.12 kB / gzip 90.85 kB and CSS 23.74 kB / gzip 5.28 kB. These numbers are build observations, not performance budgets or deployment proof.

### Browser smoke

```text
npx playwright test --config playwright.v3.config.ts
1 passed, 12.3s (test body 5.2s)
```

The config generated a fresh database under ignored `work/`, explicitly enabled V3, used a test identity and deterministic fake provider, and started localhost ports 18100/15173. It did not open the real `data/rag.sqlite3`.

The flow observed:

1. open CS3481 workspace;
2. upload a private CSV, render its bounded table preview and preserve `=2+2` as inert text;
3. create a private ATOMIC node;
4. submit text problem and receive complete fake solution;
5. click a step knowledge question;
6. receive bridge context in Teaching pane;
7. generate one unit and derive `LEARNED` from REQUIRED coverage;
8. return/focus exact original step;
9. reload and open a new browser context; state remains;
10. use 375×812 viewport without horizontal document overflow.

Desktop and mobile screenshots were visually inspected. They show both panes and `NOT_ASSESSED` separately from `LEARNED`; on mobile panes stack vertically. This is only the current partial UI. The installed DevTools MCP was not available as a callable tool in this session, so browser console/network/accessibility-tree cleanliness is **NOT VERIFIED** beyond Playwright assertions. Process-level `NO_COLOR` warnings came from the test servers, not captured page-console evidence.

## 3. Stage 1 source/provenance evidence

Implemented and exercised locally:

- migration 013 creates immutable `document_versions`, `derived_artifacts` and `chunk_source_versions`, including V2 backfill;
- V3-off initialization still stops at 10 and V2 upload behavior remains unchanged;
- owner workspace uploads create `WORKSPACE_PRIVATE` frozen versions; reviewed owner-course content becomes readable only while the source course is published;
- retrieval authorization is applied in SQL before keyword/vector/structured candidates and checked again before evidence enters a prompt;
- stable version metadata/preview/content endpoints authorize `GET`, `HEAD` and byte `Range` and never expose owner IDs or server paths;
- Markdown/TXT, bounded CSV, static non-executing notebook, PDF and validated raster image capabilities work; Office files use a truthful download-only fallback when no controlled converter exists;
- malformed OOXML, traversal, duplicate normalized members, macros, decompression limits, invalid/truncated images and malformed/deep notebooks are rejected safely;
- source and derived artifact size/hash mismatches fail closed at byte-reading endpoints; a same-size tamper regression proves SHA-256 is checked before metadata preview/content is returned;
- source deletion removes the tested original and derivative on the happy path; crash-safe retry/outbox cleanup is not yet implemented and is not claimed.
- operation idempotency includes path resource IDs, and a model result is rejected if another pane advances the shared workspace revision before finalization.

Focused Stage 1 command after review:

```text
pytest test_document_versions + test_document_previews + test_learning_safety
24 passed, 1 warning, 11.61s
```

Isolated real-data-copy migration evidence through 013:

```text
old_rows_unchanged=true; integrity=ok; foreign_key_violations=0
67 documents -> 67 document_versions
1937 chunks -> 0 unbound chunks
invalid_source_owners=0; v3_invariants_ok=true
```

## 4. Stage 2 Registry, tree and two-axis evidence

The failing-first suite added ten focused checks for migration backfill/repeatability, `ATOMIC`/`COMPOSITE` rules, hierarchy and prerequisite cycles, same-name user isolation, reviewed official visibility, immutable published membership/review metadata, independent state axes, pinned Spec journeys and fail-closed corrupted-tree reads. Before the final hardening changes, five checks failed for the expected missing constraints/read projection; no failing assertion was removed.

Focused and full results on the Stage 2 code state:

```text
pytest learning/workspace/database/document/knowledge focus
49 passed, 1 warning, 16.94s

pytest full Python suite
251 passed, 1 warning, 57.51s

ruff app + affected tests/scripts
All checks passed

mypy app
Success: no issues found in 53 source files

Web Vitest
8 files / 33 tests passed

Web typecheck + production build
PASS; 116 Vite modules

Playwright V3 isolated synthetic flow
1 passed, 18.6s; test body 9.8s
```

Locally verified behavior:

- migration 014 keeps existing node/Spec IDs and adds aliases, lineage, material evidence, normalized immutable Teaching Items, Spec metadata, tree versions, memberships and a separate prerequisite graph;
- personalized tree inserts are workspace/course/owner bound in both service logic and SQLite triggers; private nodes belonging to another user are rejected;
- official DRAFT members remain invisible until node, Spec and tree review state is explicit; published membership and review identity are immutable;
- a deliberately corrupted disposable database fails closed with `TREE_SOURCE_UNAVAILABLE` and returns neither the foreign private node ID nor title;
- `COMPOSITE` owns no Teaching Spec or direct Learning Journey; its Learning Progress is derived from unique ATOMIC descendants;
- a new private Spec version creates a separate pinned Journey, starts at `NOT_STARTED`, and retains the older completed journey as history;
- Learning Progress and Assessment are returned as separate objects; Stage 2 Assessment is explicitly `NOT_ASSESSED`, never numeric zero;
- the Web renders official and personalized views, their review/version status and both axes, and creates an explicit ordered private plan without a publication action;
- changing workspaces hides the old registry synchronously before the next fetch, preventing a prior private node from remaining on screen;
- the browser flow creates a personal tree, teaches one REQUIRED item, returns to the exact Problem step, and restores tree/progress after reload and a new browser context at desktop and 375px widths.

Fresh isolated real-data-copy rehearsal `work/v3-migration-rehearsal-04/`:

```text
source SHA-256 before == after
old_rows_unchanged=true
integrity=ok; foreign_key_violations=0
schema_versions=1..14
documents=67; document_versions=67
chunks=1937; unbound_chunks=0
invalid_source_owners=0; v3_invariants_ok=true
```

The separate `work/v3-cs3481-subset-01/` run used two existing CS3481 document-version/Chunk references without copying their content into evidence output. It created an explicitly unreviewed local fixture with 3 candidate nodes, 2 hierarchy edges, 1 prerequisite edge and 2 material-evidence rows. The tree remained `DRAFT`, reviewer fields remained null, learner output remained `NO_REVIEWED_TREE`, candidate nodes were invisible, model calls were 0, integrity was `ok`, and foreign-key violations were 0. This proves local structure/provenance mechanics only; it is not an official content-quality review.

`SUPPLEMENTAL_ENGINEERING_DECISION`: migration 014 keeps the Registry, normalized current Spec projection and two tree graphs in one additive transaction boundary because none had been applied to the real or production database. The first UI plan editor intentionally creates a flat ordering of explicitly selected ATOMIC nodes; the API/Schema already support hierarchy, while richer drag/reparent editing remains later UI work.

## 5. Stage 3 Teaching plan, delivery and model-run evidence

Stage 3 was driven by failing tests for the missing full-plan cache and safe failed-call evidence. A final browser failure also found that Plan metadata existed only in the immediate POST response; the failing backend regression reproduced its loss after a state reload, and the fix now stores the Plan version/unit/reuse metadata with the teaching unit.

Current full-gate results after that fix:

```text
Python pytest: 264 passed, 2 warnings, 65.30s
Ruff: All checks passed
mypy: Success, 55 source files
Web Vitest: 8 files / 33 tests passed
Task Agent Vitest: 9 files / 53 tests passed
TypeScript typecheck: Web PASS; Agent PASS
Production build: Web 116 modules PASS; Agent tsc PASS
Playwright V3 golden path: 1 passed, 16.6s; test body 8.1s
```

The two pytest warning categories were Starlette's `httpx` TestClient deprecation and inability to write the repository-local `.pytest_cache` on this host; neither changed test selection. Earlier Stage 3 focused runs used an ignored writable cache directory. No tests were skipped.

The hermetic Playwright configuration now explicitly sets both backend `V3_ENABLED=true` and Web `VITE_V3_ENABLED=true`. Before that fix the first run rendered the V3-off 404 page; the next run exposed the missing persisted Plan metadata; only the third run passed. The final flow verifies private upload/preview, personal tree, full solution, Step question, Bridge context, Teaching delivery, `ciallo` display-only check prefix, `LEARNED`, exact return focus, reload/new-context recovery and 375px no-overflow. Desktop and mobile screenshots were visually inspected. Browser request failures and page console errors are asserted empty.

Locally verified Teaching behavior:

- migration 015 adds immutable preference and TeachingPlan versions, normalized Plan units/links, exact delivery evidence and safe model-call evidence;
- v3.2 Planner produces a complete 1–12 unit path; each unit targets 1–3 items and includes 3–5 checks;
- four majors × CASE_A/CASE_B select the intended strategy, while preferences/injected sources cannot remove REQUIRED scope or gain authority;
- normal continuation uses one saved Plan and creates roles `planner, teacher, teacher`; explicit/preference/source/Spec/Bridge/runtime changes record a new version and invalidation reason;
- a failed Executor leaves the valid Planner result available, records safe failure metadata, commits no teaching fact, and resumes without another Planner call;
- incomplete, wrong-item, wrong-Plan-unit and forged delivery evidence is rejected by compiler/service/SQLite boundaries;
- `LEARNED` derives from `VALIDATED` or explicitly migrated `LEGACY_PRESERVED` delivery rows for the pinned Spec, never from check answers or Assessment;
- deterministic provider evidence identifies `FAKE_TEST_ONLY`, not `qwen3.8-max`; the endpoint region is only a configured label, not a verified runtime fact.

Fresh isolated real-data-copy rehearsal `work/v3-migration-rehearsal-05/`:

```text
schema_versions=1..15
old_rows_unchanged=true; integrity=ok; foreign_key_violations=0
courses=5; documents=69; document_versions=69
chunks=1937; unbound_chunks=0; invalid_source_owners=0
CS3481 fixture: DRAFT, learner view NO_REVIEWED_TREE, model_calls=0
```

The Stage 3 note originally described the source as 1–10. The later Stage 4 read-only audit found the actual current source at 1–15 with a last-write time predating the Stage 4 rehearsal; therefore 1–10 is retained only as a superseded historical observation, not current fact. The private evidence directory is ignored and is not a deployment artifact. This is not a full uploads/Task Agent restore drill.

## 6. Stage 4 Problem, multimodal and Bridge evidence

Stage 4 was driven by failing tests for missing Problem revision/index tables, exact knowledge-link identity, private image authorization and restored normalized state. A final UI test was added red-first for the missing post-upload source refresh. The first targeted command used a root-relative test path after npm had already changed into the Web workspace and found no tests; rerunning with `src/...` exercised the intended file. The first Playwright edit also used a RegExp label with `selectOption`, which only accepts a concrete string/value/index; the test was corrected to select the first authorized option. No product assertion was deleted.

Current full-gate results:

```text
Python pytest: 270 passed, 2 warnings, 76.29s
Ruff app/tests and migration script: All checks passed
mypy: Success, 56 source files
Web Vitest: 9 files / 35 tests passed
Task Agent Vitest: 9 files / 53 tests passed
TypeScript typecheck: Web PASS; Agent PASS
Production build: Web 116 modules PASS; Agent tsc PASS
Playwright V3 private-image path: 1 passed, 14.7s; test body 5.8s
```

The warning categories remain Starlette's `httpx` TestClient deprecation and inability to write repository-local `.pytest_cache`; neither changed selection. Browser console errors and failed requests remained empty. Desktop 1280px and mobile 375px screenshots were visually inspected: panes remain side-by-side on desktop and become a non-overflowing single column on mobile.

Locally verified Problem/Bridge behavior:

- migration 016 builds the incremental structured index only from chunks with explicit question metadata and adds immutable ProblemRevision, Attempt, SolutionRevision, StepKnowledgeLink and LearningBridgeContext chains;
- authorized indexed lookup pins exact document version/hash/locator; User B and forged workspace IDs are rejected before retrieval or model context;
- image input accepts an existing authorized PNG/JPEG DocumentVersion, checks scope/path/size/hash, repeats byte hash in the provider value, and sends one private Base64 data URI without a public URL;
- provider/model-run serialization excludes image bytes, data URI, prompt body and private content while retaining content-free version/hash/size metadata;
- strict v3.2 Problem output includes transcription, visual uncertainty, conditions, exam answer, numbered steps, formulae, units, checks, common mistakes, sources and answer verification;
- a VALIDATED knowledge link requires exact node/spec/item and a DB-authorized workspace chain; UNRESOLVED links cannot create a Bridge; legacy links remain visibly `LEGACY_PRESERVED`;
- duplicate semantic Bridge creation is idempotent, forged links fail, and normalized state plus exact return anchor survive refresh/new browser context;
- uploading a private image refreshes the Problem source selector without a page reload.

The Playwright fixture is a synthetic 1×1 PNG plus an explicit transcription hint and a deterministic fake provider. It proves browser upload, ACL, request shape, persistence, uncertainty display and navigation; it explicitly does **not** prove qwen vision accuracy, OCR quality or answer correctness.

Fresh isolated copy rehearsal `work/v3-migration-rehearsal-07/`:

```text
source/current versions=1..15; copied result=1..16
source SHA-256 before == after = BCB04E...AE93ED
old_rows_unchanged=true; integrity=ok; foreign_key_violations=0
documents/document_versions=69/69; unbound_chunks=0
problem_index_entries=0; invalid_problem_index_sources=0
legacy problem/revision=2/2; solution/revision=2/2
steps/normalized links=2/2; bridges/contexts=2/2
all missing-normalization counters=0
```

The zero index is expected and important: legacy chunks contain no structural `question_number`, so the migration does not invent problem identities. The nonzero 2/2 runtime rows prove backfill checks are not vacuous. The source DB was read-only during rehearsal and its SHA remained unchanged. Contrary to the prior Stage 3 note, the current real-local DB was already at 1–15 before this rehearsal; its modification time predates the rehearsal, and the actor/time applying 11–15 is unknown. No migration 016 was applied to it.

Official current Model Studio documentation was checked for the local adapter decision: `qwen3.8-max` is listed for Responses and multimodal image input; Responses image content accepts a complete Base64 data URI. This verifies only the documented contract. The actual account, region, endpoint, model entitlement, response quality, usage and price were not called or verified.

## 7. Stage 5 Assessment, GradePolicy and replan evidence

Focused Assessment contracts:

```text
python -m pytest tests/test_assessment_runtime.py -q
13 passed, 2 warnings

python -m pytest tests/test_assessment_runtime.py tests/test_teaching_plan_runtime.py \
  tests/test_learning_journey.py tests/test_learning_safety.py -q
35 passed
```

The tests verify frozen five-question blueprints with unequal `10/15/20/25/30` marks totaling 100, exact question/rubric/policy versions, official/current-owner pool scope, exclusion of `MODEL_ONLY`, Problem-answer-exposed sibling revisions and Assessment-assisted families, and no answer/rubric fields in the pre-submit projection. A SQLite authorizer additionally proves the in-progress projection succeeds while reads of the server `answer_json` column are denied. Deterministic item marks are recomputed by the backend; open answers use strict `AssessmentGradeProposal`. `NEEDS_REVIEW` remains submitted without a raw score or GradeSnapshot.

Answer reveal or teaching help permanently changes the whole session to `PRACTICE` and every generated PerformanceEvidence row to non-independent. Abandoned/unsubmitted sessions emit neither zero nor F and do not unlock hidden answers. Weak rubric evidence creates a pending trigger without a provider call; a later explicit Teaching action passes only bounded evidence summaries to Planner, persists trigger→Plan→Unit remediation links, and marks the trigger applied only after the planned delivery completes. A low Assessment result never removes `LEARNED`.

GradePolicy tests preserve the supplied A+/A/... values but keep A- numeric value null and raw-score bands empty in `gp_requirements_draft_v1`. Raw score and rubric evidence remain available while letter/numeric mapping says `UNCONFIGURED`; publish rejects incomplete or falsely “CityU official” provenance. A published new policy is immutable and newly frozen blueprints pin it without rewriting older blueprints.

Stage 5 full validation:

```text
Python: 284 passed, 2 warnings
Web: 10 files / 39 tests passed
Task Agent: 9 files / 53 tests passed
Ruff: all checks passed for app, tests and scripts
mypy: 57 source files, no issues
TypeScript: Web and Agent passed
Production build: Web 117 modules; Agent tsc passed
Playwright: 5 passed, 40.3s; final loaded-host rerun 5 passed, 2.6m
```

The two Python warnings are the known Starlette/httpx deprecation and a Windows pytest cache ACL warning. They are not skipped failures. A 5-second Vitest default produced reproducible infrastructure timeouts on five 5.1–5.9-second Windows/JSDOM cold-start tests; an explicit 15-second budget was then committed and all 39 unchanged assertions passed. The final Playwright run covers the existing V2 QA/task/mobile/private-course flows plus V3 private image Problem→Bridge→Teaching→exact return, new browser context, Assessment submit/raw score and reload at 375px. The later 2.6-minute run was on a loaded host; it passed the same five scenarios without relaxing Playwright assertions.

Migration rehearsal `work/v3-migration-rehearsal-08/` used SQLite read-only online backup while the local source was 1–15, initialized the copy twice to 1–18, and reported:

```text
old_rows_unchanged=true; integrity=ok; foreign_key_violations=0
schema_versions=1..18; v3_invariants_ok=true
documents/document_versions=69/69; unbound_chunks=0
legacy problem/revision/solution/bridge context=2/2/2/2
assessment questions/blueprints/sessions/evidence/snapshots=0/0/0/0/0
grade_policy_versions=1; requirements_grade_policy_seed=1
invalid frozen blueprints/policy bindings/independent evidence/snapshots=0/0/0/0
```

Zero Assessment rows are the correct legacy fact; the migration did not invent grades. The one policy is explicitly `DRAFT_UNCONFIGURED` and “not an institutional policy.”

### Default Playwright isolation incident and recovery

The first combined five-test invocation exposed that the legacy default `playwright.config.ts` did not set `RAG_DATABASE_PATH`. It migrated the local real DB from 1–15 to 1–18 and added deterministic test rows/files before the V3 test timed out on its missing seeded Assessment node. This is a failed safety gate, not a PASS, and is retained in the report.

All writers were stopped. Before replacement, the contaminated DB was captured by SQLite online backup. The recovery candidate came from the online snapshot taken immediately before the faulty invocation; migrations 16–18 were retained because applied history must not be rewritten, while every protected V2 row fingerprint and all pre-test V3 table counts were restored. The result passed integrity/FK checks, and exactly two hash-matched synthetic uploads were moved from the active upload root to ignored quarantine rather than deleted. Two contaminated database copies remain under `work/v3-e2e-incident-recovery-20260912/`; that private directory must not be committed or shared.

The permanent fix adds `prepare_full_e2e.py`, points both RAG DB and uploads at a unique `work/e2e-rag-*` target, and has a config regression assertion. The corrected five-test run preserved these before/after values exactly:

```text
database sha256=48852F977EBF37B1A9B77DF1A03E5D3549BEBC71EC77401673BA60F5BD6D906B
database bytes=5,828,608
upload files=70; upload bytes=124,209,888
upload manifest sha256=FB1DBBCEE7E46969C2F361BB8BA09534C13BE8C101AD8694A1A8E35D91E83E03
```

This proves recovery and isolation for the current local run only. It is not production evidence.

## 8. Test data and privacy

- pytest uses `tmp_path` databases/uploads; V3 API fixtures set `v3_enabled=True` explicitly.
- Playwright now uses a read-only online copy under `work/`, a separate upload root and fake content `2 + 3`; screenshots contain only synthetic values.
- The local real RAG database was accidentally initialized once by the disclosed pre-fix default config, then recovered as documented above. The corrected run left DB and upload summaries unchanged.
- No private course body, user identity, key, prompt body or production response is included here.

## 9. Model contract versus model quality

Current deterministic tests can prove:

- strict Pydantic Schema shape and bounded fields;
- invalid node/item/evidence/return IDs are rejected;
- templates are loaded from version-controlled files;
- fake provider path saves/reloads the expected object graph;
- no fallback is needed in deterministic mode.

They cannot prove:

- `qwen3.8-max` account permission or correct regional endpoint;
- Responses versus Chat Completions streaming event compatibility;
- image understanding/OCR correctness;
- Chinese teaching quality for four majors;
- multi-turn tool result handling;
- generated-question solvability or semantic grading fairness;
- production Clerk, Netlify, server/storage or multi-instance behavior;
- actual token cost/latency/rate-limit behavior.

## 10. Required future matrices

| Stage | New evidence required before PASS |
|---|---|
| 1 | implemented preview/provenance slice is locally green; production storage, converter, full citation API and crash-safe deletion cleanup remain later gates |
| 2 | locally verified; official author/review management remains Stage 6 |
| 3 | locally verified; live provider quality/usage/cost remains Stage 7 and production remains Stage 8 |
| 4 | locally verified for text/index/image revisions, solution/step link, private image, Problem→Teaching→return and persistence; reverse Teaching→Problem, two-user/Admin browser and full a11y remain overall gates |
| 5 | locally verified for five unequal/100, answer secrecy, assisted evidence, rubric arithmetic, unconfigured policy and explicit weak-point replan; live grading quality remains Stage 7 |
| 6 | scoped review snapshot, consent/version substitution, withdraw/re-publish and generic Admin denial |
| 7 | smallest approved live canaries with exact model/region/protocol/cost; four-major human rubric |
| 8 | final full regression, final-Schema real-data copy + full restore, preview deploy and production smoke/rollback evidence |

## 11. Open defects and non-PASS items

- Existing `package-lock` audit history reported one high and three moderate advisories; reachability/remediation is not yet resolved and cannot be hidden in launch PASS.
- Current Playwright covers one synthetic owner plus existing V2 flows; two-user/Admin browser paths, Teaching→Problem reverse initiation and accessibility-tree evidence remain missing.
- Model adapter now retains safe metadata on structured-output failure, but actual qwen3.8-max account access, regional endpoint, protocol compatibility, provider usage fidelity and cost remain unverified.
- Official tree author/review APIs are not implemented; Stage 2 publication behavior is exercised only through direct local fixtures and cannot be called production-ready.
- Assessment and GradePolicy are persistent and locally verified; question author/review UI, integrated COMPOSITE exams, human finalization of `NEEDS_REVIEW` and publication snapshots remain unimplemented.

No live or production claim should be inferred from the local green checks.
