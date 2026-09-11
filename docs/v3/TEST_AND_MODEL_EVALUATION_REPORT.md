# CourseMate V3 — Test and Model Evaluation Report

Last updated: 2026-09-12 after Stage 3 implementation and review.

Branch: `feature/coursemate-v3-persistent-learning`

Stage-switch base: `c6158cf34142c311e77a58aa49a3b0b7cbe7fbd8`; Stage 1 commits are `00961ef` through `e9ecd00`; Stage 2 code commits are `6eeff90`, `5a1f9d0`, `0be1a47`, `86032bb` and `5dba760`; Stage 3 code commits are `956d849`, `da1fa2a`, `e5d14d3`, `52514d1` and `2256cf0`.
This report is cumulative and must be updated after every behavior change; old PASS does not cover later code.

## 1. Current evidence summary

| Acceptance layer | Result | Meaning |
|---|---|---|
| Source implementation | PARTIAL | Stages 1–3 source slices exist; Stages 4–8 are not complete |
| Python automated tests | PASS for current Stage 3 code | 264 passed; 1 known dependency deprecation plus local pytest-cache ACL warning |
| Web unit tests | PASS | 8 files / 33 tests passed |
| Task Agent unit tests | PASS | 53 passed; V3 did not take over task tools |
| Python lint/type | PASS | Ruff all checks; mypy strict app 55 files |
| TS typecheck/build | PASS | both workspaces typecheck; production bundles built locally |
| V3 browser flow | LOCAL_FAKE_PROVIDER_VERIFIED | 1 Playwright flow passed with isolated synthetic DB/test identity/deterministic provider |
| Real model | NOT VERIFIED | no paid call, account/region/endpoint unknown |
| Real-data final migration/restore | PARTIAL | 011–015 passed on an isolated read-only-source copy; uploads/full restore/final Schema remain unverified |
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

The source database was opened read-only and stayed at 1–10. The private evidence directory is ignored and is not a deployment artifact. This is not a full uploads/Task Agent restore drill.

## 6. Test data and privacy

- pytest uses `tmp_path` databases/uploads; V3 API fixtures set `v3_enabled=True` explicitly.
- Playwright uses a new path under `work/` and fake content `2 + 3`; screenshots contain only synthetic values.
- The local real RAG database was queried read-only for aggregate baseline facts and never passed to application initialization.
- No private course body, user identity, key, prompt body or production response is included here.

## 7. Model contract versus model quality

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

## 8. Required future matrices

| Stage | New evidence required before PASS |
|---|---|
| 1 | implemented preview/provenance slice is locally green; production storage, converter, full citation API and crash-safe deletion cleanup remain later gates |
| 2 | locally verified; official author/review management remains Stage 6 and Assessment values remain Stage 5 |
| 3 | locally verified; live provider quality/usage/cost remains Stage 7 and production remains Stage 8 |
| 4 | text/image problem revisions, solution/step link, Bridge idempotency/revision/race, both directional pane flows, a11y/console/network |
| 5 | five unequal/100, answer secrecy, assisted evidence, rubric arithmetic, unconfigured policy, weak points/replan triggers |
| 6 | scoped review snapshot, consent/version substitution, withdraw/re-publish and generic Admin denial |
| 7 | smallest approved live canaries with exact model/region/protocol/cost; four-major human rubric |
| 8 | final full regression, final-Schema real-data copy + full restore, preview deploy and production smoke/rollback evidence |

## 9. Open defects and non-PASS items

- Existing `package-lock` audit history reported one high and three moderate advisories; reachability/remediation is not yet resolved and cannot be hidden in launch PASS.
- Current Playwright covers one owner and Problem→Teaching→return; two-user/Admin browser paths, Teaching→Problem reverse initiation and accessibility-tree evidence remain missing.
- Model adapter now retains safe metadata on structured-output failure, but actual qwen3.8-max account access, regional endpoint, protocol compatibility, provider usage fidelity and cost remain unverified.
- Official tree author/review APIs are not implemented; Stage 2 publication behavior is exercised only through direct local fixtures and cannot be called production-ready.
- Assessment, GradePolicy and publication snapshot tests are not yet implemented. The displayed Assessment axis is an explicit `NOT_ASSESSED` placeholder, not persistent Assessment evidence.

No live or production claim should be inferred from the local green checks.
