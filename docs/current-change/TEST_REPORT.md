# TEST_REPORT

All tests run against the D: workspace (`01_SOURCE_REPOSITORY`), zero billable model
calls (deterministic/test providers only). Env used for backend suites:
`CMUI_PROVIDER_MODE=test`, `CMUI_AUTO_VERIFY_NEW_USERS=true`
(new contract suite pins the auto-verify flag to false to keep the campus-gate
assertions meaningful).

## Backend (rag-api)

| Suite | Result | Notes |
|---|---|---|
| `tests/test_current_change_features.py` (new, 11 tests) | **11 passed** | templates, pairs+binding, normal/thinking modes, plan privacy, exercises/reveals, explanations, verification+campus gate, grandfather boundary, shares+join, classification |
| `tests/ui_extension/test_provider.py` (rewritten to new contract) | **passed** | two-call thinking contract, single-call normal contract, problem-lane Word prompt, billing gate, error handling, responses protocol |
| Legacy contract suites updated | **passed** | conftest provider `**kwargs`, generated_prompt whitelist assertion, disabled-provider pinning, two-phase test → teaching_mode='thinking' |
| **Full rag-api regression** | **542 passed, 0 failed** | env: CMUI_PROVIDER_MODE=test, CMUI_AUTO_VERIFY_NEW_USERS=true (new contract suite pins the flag false internally); `.env` redaction artifact moved out of the settings path |
| Real backend bug found & fixed during regression | ✅ | run-endpoint node claim crashed on unique-index violation when the node was bound to another pair; fixed with conflict pre-check + IntegrityError guard (coverage suite now green) |

## Frontend (apps/web)

| Item | Result |
|---|---|
| `tsc -b && vite build` | **exit 0** (dist produced: index.html + ui.html + bundles) |
| vitest unit tests | **13 files, 55 tests passed** |

## Agent (services/agent-api)

| Item | Result |
|---|---|
| `tsc` build | **exit 0** |
| vitest | **10 files, 66 tests passed** |

## Local runtime smoke (standalone cm_update app, uvicorn 127.0.0.1:8765, TestProvider)

Live HTTP checks performed (all green): dev login; course create with name `x`
(displayed exactly `x`, display_type=private); pair create; normal-mode teach run
completed; `GET /runs/{id}` contains no `generated_prompt` field; exercise run
completed with question-only message; reveal before = 0 steps, after = 3 steps with
stable step ids; explanation completed with cached text; verification status read.
Smoke server stopped afterwards; scratch data under `work/current-change/smoke-data/`.

## Verification boundary

- Everything above proves contracts and deterministic state transitions.
- Real qwen3.8-max quality (classification, teaching, exercises, explanations),
  native reasoning parameters, and production migration rehearsal: NOT_RUN —
  require explicit paid/deployment approval.
