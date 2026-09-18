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
| `tests/ui_extension/test_provider.py` (rewritten to new contract) | pending final run | two-call thinking contract, single-call normal contract, problem-lane Word prompt, billing gate, error handling, responses protocol |
| Full rag-api regression | pending final run (last: 13 failing legacy-contract tests being updated) | stage7 env leak fixed via `.env` hold-rename; schema-6 compat test updated |
| `tests/test_ui_extension_schema_compat.py` | updated for schema 6 | older-release refusal semantics preserved |

## Frontend (apps/web)

| Item | Result |
|---|---|
| `tsc -b && vite build` | pending (frontend agent fixing JSX balance, pages.jsx:672) |
| vitest unit tests | pending |

## Agent (services/agent-api)

| Item | Result |
|---|---|
| `tsc` build | **exit 0** |
| vitest | **10 files, 66 tests passed** |

## Local runtime smoke (browser-level)

NOT_RUN this round: the deterministic browser acceptance harness used by earlier
rounds requires a dedicated offline server build; contract tests cover the same
state machine server-side. Listed honestly as a follow-up in the deployment round.

## Verification boundary

- Everything above proves contracts and deterministic state transitions.
- Real qwen3.8-max quality (classification, teaching, exercises, explanations),
  native reasoning parameters, and production migration rehearsal: NOT_RUN —
  require explicit paid/deployment approval.
