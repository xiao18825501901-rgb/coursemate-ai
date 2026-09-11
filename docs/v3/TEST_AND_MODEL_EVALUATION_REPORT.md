# CourseMate V3 — Test and Model Evaluation Report

Last updated: 2026-09-12 after Stage 1 implementation and review.

Branch: `feature/coursemate-v3-persistent-learning`

Stage-switch base: `c6158cf34142c311e77a58aa49a3b0b7cbe7fbd8`; current verified code commits: `00961ef`, `fb38efd`, `e9ecd00` plus this evidence update.
This report is cumulative and must be updated after every behavior change; old PASS does not cover later code.

## 1. Current evidence summary

| Acceptance layer | Result | Meaning |
|---|---|---|
| Source implementation | PARTIAL | Stage 1 file/provenance/private-overlay slice and minimal learning loop exist; full Master spec does not |
| Python automated tests | PASS for current Stage 1 code | 241 passed, 1 known dependency deprecation warning |
| Web unit tests | PASS | 30 passed |
| Task Agent unit tests | PASS | 53 passed; V3 did not take over task tools |
| Python lint/type | PASS | Ruff all checks; mypy strict app 52 files |
| TS typecheck/build | PASS | both workspaces typecheck; production bundles built locally |
| V3 browser flow | LOCAL_FAKE_PROVIDER_VERIFIED | 1 Playwright flow passed with isolated synthetic DB/test identity/deterministic provider |
| Real model | NOT VERIFIED | no paid call, account/region/endpoint unknown |
| Real-data final migration/restore | PARTIAL | 011–013 passed on an isolated read-only-source copy; uploads/full restore/final Schema remain unverified |
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

## 4. Test data and privacy

- pytest uses `tmp_path` databases/uploads; V3 API fixtures set `v3_enabled=True` explicitly.
- Playwright uses a new path under `work/` and fake content `2 + 3`; screenshots contain only synthetic values.
- The local real RAG database was queried read-only for aggregate baseline facts and never passed to application initialization.
- No private course body, user identity, key, prompt body or production response is included here.

## 5. Model contract versus model quality

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

## 6. Required future matrices

| Stage | New evidence required before PASS |
|---|---|
| 1 | implemented preview/provenance slice is locally green; production storage, converter, full citation API and crash-safe deletion cleanup remain later gates |
| 2 | registry/homonym/de-dup, hierarchy vs prerequisite DAG, tree publish versions, double-axis projections |
| 3 | four majors × CASE_A/B, plan cache/invalidation, REQUIRED preservation, injection/invalid output, complete coverage evidence |
| 4 | text/image problem revisions, solution/step link, Bridge idempotency/revision/race, both directional pane flows, a11y/console/network |
| 5 | five unequal/100, answer secrecy, assisted evidence, rubric arithmetic, unconfigured policy, weak points/replan triggers |
| 6 | scoped review snapshot, consent/version substitution, withdraw/re-publish and generic Admin denial |
| 7 | smallest approved live canaries with exact model/region/protocol/cost; four-major human rubric |
| 8 | final full regression, final-Schema real-data copy + full restore, preview deploy and production smoke/rollback evidence |

## 7. Open defects and non-PASS items

- Existing `package-lock` audit history reported one high and three moderate advisories; reachability/remediation is not yet resolved and cannot be hidden in launch PASS.
- Current Playwright covers one owner and Problem→Teaching→return; two-user/Admin browser paths, Teaching→Problem reverse initiation and accessibility-tree evidence remain missing.
- Existing model adapter has incomplete regional/protocol capability validation and may lose usage metadata when structured output is invalid.
- Bridge path ID is not yet proven part of canonical idempotency hash; stale model-finalization compare-and-set needs a focused race test.
- Tree, Assessment, GradePolicy and publication snapshot tests are not yet implemented. DocumentVersion/DerivedArtifact tests exist only at local-contract level.

No live or production claim should be inferred from the local green checks.
