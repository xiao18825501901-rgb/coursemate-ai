# Visual Learning Engine Phase A — Source Mapping

Baseline captured: 2026-10-01

## Repository baseline

- Repository: `D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY\work\auto-knowledge-map-20260927\candidate`
- Branch: `feature/learning-loop-20260928`
- HEAD: `d854b0ed8a159ff2580622497dc28ec3ec8926f7`
- Working tree: tracked files clean; pre-existing untracked P0 reports, screenshots, downloads and artifact folders preserved.
- RAG schema: migration 066 is the latest applied source migration before Phase A.
- Baseline verification:
  - focused RAG database/storage/UI integration: 58 passed;
  - refreshed Learn UI: 15 passed;
  - Web TypeScript check: passed.
- Phase-A application commit: `d2dcd745d3d5f238e70bd8b5d288b5855ffabf65`.

## Real source mapping

| Disposition | Current source | Phase A use |
|---|---|---|
| KEEP | `services/rag-api/app/auth.py`, `course_access.py` | Existing identity and hidden-not-found course policy remain authoritative. |
| KEEP | `services/rag-api/app/storage/backends.py`, `storage/factory.py` | Immutable visual assets use the existing local/OSS `StorageBackend`; Phase A uses local storage. |
| KEEP | `services/rag-api/app/cm_update/db.py` | Pair and message ownership remains in the refreshed UI database. |
| KEEP | `services/rag-api/app/ui_extension/domain.py` | Existing RAG course/source access remains authoritative. |
| MODIFY | `services/rag-api/app/config.py` | Add disabled-by-default visual provider, worker, output and quota settings. |
| MODIFY | `services/rag-api/app/db.py` | Register additive migration 067 for visual jobs, assets, cache and events. |
| MODIFY | `services/rag-api/app/main.py` | Construct the visual service and start its worker only when enabled. |
| MODIFY | `services/rag-api/app/ui_extension/mount.py` | Install visual routes before the UI static catch-all and bind both databases. |
| MODIFY | `apps/web/src/ui/api.js` | Add create/status/list/cancel/retry/content calls under the existing API base. |
| MODIFY | `apps/web/src/ui/pages.jsx` | Attach message-level visual actions and durable polling to current `Learn`. |
| MODIFY | `apps/web/src/ui/styles*.css` | Add responsive, theme-compatible visual card styles. |
| ADD | `services/rag-api/app/visual/*` | Strict VisualSpec, planner, compiler, router, provider, state store, worker, validators and API. |
| ADD | `services/rag-api/migrations/067_visual_learning_engine.sql` | Service-owned durable visual state. Pair/message IDs are verified against the UI database before insertion and retained as immutable external bindings. |
| ADD | `apps/web/src/ui/VisualAssetCard.jsx`, `VisualJobStatus.jsx` | Small accessible components for terminal and active job states. |
| DO NOT TOUCH | Question Engine, OpenJEV, Map50, grades, learning-loop state, Clerk policy, Agent API | Phase A has no authority to change these systems. |

## Trust boundaries

The browser may submit only course/message/pair/node IDs, an action and a request ID. The mounted UI API verifies the caller, Pair, assistant message and course access. Workflow, renderer, model, provider, storage key, source snapshot and visual content are selected or derived server-side. Model/planner output is untrusted until strict schema and semantic validation succeeds.

## Increment plan

1. Strict VisualSpec, versioned prompts, rule evaluation, compiler and MockComfy contract.
2. Migration 067, durable state machine, cache, quotas, immutable storage and recovery.
3. Authenticated mounted API and no-GPU end-to-end tests.
4. Current Learn UI cards, polling, cancellation/retry and accessibility tests.
5. Regression, build, security scan, documentation and acceptance report.
