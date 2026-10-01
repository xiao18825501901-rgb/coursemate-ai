# Visual Learning Engine Phase A Test Report

Date: 2026-10-01

Branch: `feature/learning-loop-20260928`

Baseline: `d854b0ed8a159ff2580622497dc28ec3ec8926f7`

Application commit: `d2dcd745d3d5f238e70bd8b5d288b5855ffabf65`

## Result

The repository implementation is locally verified with deterministic renderers and `MockComfyProvider`. No GPU, Alibaba EAS endpoint, real ComfyUI workflow, paid visual model or production deployment was used.

| Verification | Result |
|---|---|
| Phase-A Python visual + database/storage/UI regression | 98 passed, 1 deprecation warning |
| Phase-A Python visual-only suite | 40 passed, 1 deprecation warning |
| 40-case renderer routing fixture | 40/40 matched; forbidden exact-to-generative routes 0; unnecessary video routes 0 |
| Visual package Ruff | passed; 21 files formatted |
| Visual package mypy (`--follow-imports=skip`) | passed; 14 source files |
| Web Vitest | 33 files, 156 tests passed |
| Agent Vitest | 13 files, 100 tests passed |
| Workspace TypeScript typecheck | passed |
| Production Web + Agent build | passed; 141 Web modules transformed |
| Built-bundle PAT/credential-flow scan | passed; 7 files, no persistence/URL/logging leak |
| Credential-shaped literal scan over Phase-A files | no findings |
| Playwright current Learn mock flow | 1 passed in 1.5 min; test body 18.7 s |

The final Playwright flow covered teaching question, assistant answer, visual creation, MockComfy rendering, authenticated asset display and refresh restoration. An earlier concurrent rerun is retained as failed evidence: the host was saturated by a 48-minute Python suite and other independent jobs, and its trace shows the browser `fill` action itself taking about 87 seconds before the send click. That attempt never reached the visual create API. After isolating the run, the final application/config completed the test successfully.

## Commands and evidence

```text
.\.venv\Scripts\python.exe -m pytest -q services/rag-api/tests/test_visual_spec_router.py services/rag-api/tests/test_visual_store_provider.py services/rag-api/tests/test_visual_service.py services/rag-api/tests/test_visual_api_integration.py services/rag-api/tests/test_database.py services/rag-api/tests/test_storage_backend.py services/rag-api/tests/test_ui_extension_integration.py services/rag-api/tests/test_ui_extension_tree_and_dual_mode.py services/rag-api/tests/test_ui_extension_legacy_history.py
Result: 98 passed, 1 warning in 152.55 s

.\.venv\Scripts\python.exe -m pytest -q services/rag-api/tests/test_visual_spec_router.py services/rag-api/tests/test_visual_store_provider.py services/rag-api/tests/test_visual_service.py services/rag-api/tests/test_visual_api_integration.py
Result: 40 passed, 1 warning in 113.85 s

npm --workspace @coursemate/web test -- --run
Result: 33 files, 156 tests passed

npm --workspace @coursemate/agent-api test -- --run
Result: 13 files, 100 tests passed

npm run typecheck
Result: passed

npm run build
Result: passed; Web bundle PAT scan passed

npx playwright test --config playwright.visual.config.ts
Result: 1 passed in 1.5 min; test body 18.7 s
```

## Full-backend context

A broad `services/rag-api/tests` run began before the last Phase-A patches were applied and completed with `2278 passed, 4 skipped, 2 failed` in 2917.24 seconds. The visual failure used the earlier in-memory class that did not yet contain deterministic fallback; the same test passed on the final code. The remaining failure, `test_a_json_object_wrapped_in_prose_is_extracted`, was reproduced alone and is in untouched pre-existing provider parsing code. It is not relabelled as green and is outside the Visual Engine change.

## Contract proofs

- Strict VisualSpec rejects extra fields, over-limit fragments, invalid renderer/type combinations, dangling graph references and unauthorized source/reference IDs.
- The real planner loads a versioned prompt file and persists its SHA-256.
- Deterministic SVG preserves validated nodes, edges, edge labels and exact labels.
- Cache reuse leaves `MockComfyProvider.submit_count == 1`; private owner scopes and version changes miss safely.
- Quota rejection occurs before provider submission. Concurrent active-job checks share one `BEGIN IMMEDIATE` transaction.
- A stale rendering lease reuses the persisted provider job ID; restart after asset linking reuses the immutable asset ID.
- Provider fail, unknown, invalid bytes, invalid receipt, cancellation and late success do not publish an invalid/late asset or alter the text answer.
- API bodies cannot choose provider, workflow, checkpoint, model, storage key or answer/source authority.
- Cross-user job and asset reads return hidden-not-found behavior.
- SVG validation rejects active elements, event handlers and external references.
- Alibaba EAS selection is rejected by Phase-A settings and its adapter contains no transport.

## Known limits

- Generated pixels are mock fixture data; they are not evidence of real visual quality.
- `semantic_validation=LIMITED` remains required for generated pixels.
- The future real-provider seam still needs measured polling/backoff, lease renewal under long GPU jobs, pinned workflow/model hashes, qualification, cost approval and canary evidence.
- Repository-wide mypy is not clean because of existing unrelated typing debt; the isolated visual package is clean under the recorded command.
- The retained Playwright contention trace is environmental evidence, not a production incident; the final isolated mock run passed.
