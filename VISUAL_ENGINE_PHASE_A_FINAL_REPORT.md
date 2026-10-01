# CourseJesus Visual Learning Engine — Phase A Final Report

Date: 2026-10-01

```text
START_HEAD=d854b0ed8a159ff2580622497dc28ec3ec8926f7
APPLICATION_RELEASE_SHA=d2dcd745d3d5f238e70bd8b5d288b5855ffabf65
BRANCH=feature/learning-loop-20260928
MIGRATION=067_visual_learning_engine.sql
PROVIDER=MockComfyProvider
GPU_USED=false
CLOUD_PROVISIONED=false
REAL_COMFY_CALLED=false
PRODUCTION_DEPLOYED=false
READY_FOR_GPU=true
NEXT=WAITING_FOR_CODEX_PHASE_A_RESULT_REVIEW
```

`READY_FOR_GPU=true` means only that the local Phase-A engineering gates A–O have evidence and the result can enter independent review. It is not authorization to buy/provision a GPU, not a real-provider qualification and not production acceptance.

## Delivered implementation

- Strict VisualSpec 1.0 models, semantic/source/reference validation and bounded fields.
- Versioned runtime planner/compiler/validator prompts with stored prompt hash.
- Deterministic router/compiler plus the full 40-case routing fixture.
- Additive migration 067 for durable jobs, immutable assets, cache and append-only events.
- Idempotent create, legal transitions, leases, restart recovery, cancellation, bounded retry and deterministic fallback lineage.
- Existing Local/OSS `StorageBackend` reuse with server-generated keys and SHA-256 publication.
- Server-owned workflow registry and deterministic `MockComfyProvider` modes.
- Fail-closed Alibaba EAS seam with no network transport.
- Server-side concurrency/daily/output/duration/retry controls.
- Authenticated mounted `/api/ui/v1` routes that derive answer/evidence from owned messages.
- Current Learn-page diagram/visual/animation actions, status/cancel/retry/fallback, protected preview/download, dark/mobile/reduced-motion styling and refresh restoration.
- Isolated production-build Playwright harness using test identity only; no production auth bypass.

Question Engine, OpenJev, Map50, grades, learning history, Clerk policy, Agent API and existing document storage semantics were not replaced.

## Acceptance matrix

| Gate | State | Evidence |
|---|---|---|
| A Source audit | PASS | current branch/HEAD/status captured in `VISUAL_PHASE_A_SOURCE_MAPPING.md` |
| B Strict schema | PASS | schema/semantic negative tests |
| C Runtime prompt | PASS | file load/version/hash assertion |
| D Routing | PASS | 40/40; zero forbidden exact-to-generative; zero unnecessary video |
| E Durable job | PASS | migration, idempotency, transition, stale lease and restart tests |
| F Async isolation | PASS | answer exists before visual action; separate worker/API lifecycle |
| G Cache | PASS | one provider submit for identical authorized input; scope/version isolation |
| H Failure handling | PASS | fail/unknown/invalid/cancel/late-result/retry/fallback tests |
| I Storage | PASS | existing StorageBackend, hash and authenticated content tests |
| J Security | PASS | strict request, workflow injection rejection, cross-user denial, SVG allowlist, bundle/secret scans |
| K Quota | PASS | atomic active quota and pre-submit daily quota tests |
| L Current UI | PASS | 156 Web tests including all states/cache/actions/accessibility; mock browser flow |
| M Mock E2E | PASS | question/answer to job/provider/asset/UI and refresh restoration |
| N Regression | PASS | final 98 relevant backend + Web 156 + Agent 100 + typecheck/build |
| O No GPU/cloud | PASS | settings allow only mock; disabled adapter performs no network call |
| P Ready for GPU review | PASS | A–O passed; independent review still required |

## Verification summary

- Final relevant Python regression: 98 passed.
- Phase-A visual tests: 40 passed.
- Web: 156 passed; Agent: 100 passed.
- TypeScript typecheck and production builds: passed.
- Visual Ruff and isolated mypy: passed.
- Built frontend credential-flow scanner and Phase-A credential-shaped literal scan: passed.
- Broad backend context: 2278 passed, 4 skipped, 2 failed; one obsolete in-flight visual snapshot and one reproducible untouched provider-parser failure. See the detailed test report; neither is hidden.

## Security and data handling

The browser provides only server-owned identifiers, an action and a request ID. The server rechecks identity, course access, Pair/message ownership and assistant role. Frozen private answer/evidence text, planner/spec internals, provider IDs, workflows and storage keys are not projected. Asset reads are owner/course checked and returned `private, no-store` with `nosniff`.

No production database, real user data, private course source, cloud credential or paid endpoint was used. Pre-existing untracked P0 reports, bridge downloads, model/map artifacts and screenshots were preserved and excluded from the Phase-A application commit.

## Rollback

Set `VISUAL_ENGINE_ENABLED=false` and restart the RAG service. No worker or visual routes are then activated, while existing text teaching remains available. Reverting the application/frontend is safe; migration 067 and historical visual rows/assets should remain in place. Do not restore an old database over newer chats, files, grades or assessments.

## Stop state

Phase A is complete and stopped at:

`WAITING_FOR_CODEX_PHASE_A_RESULT_REVIEW`

No GPU purchase, Alibaba provisioning, real Comfy integration or production deployment was performed.
