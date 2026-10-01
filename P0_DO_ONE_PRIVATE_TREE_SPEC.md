# Spec: P0 Do-One and New Private Course Tree

## Objective

Restore and deploy two independent production journeys without changing the NanoJev or
Visual/ComfyUI worktrees: one Question Engine-backed question for campus and private courses,
and an automatically generated Map50 tree for a newly created owner-private course with READY
source material. Existing Assessment behavior must remain intact and the 13 legacy over-limit
trees must remain paused.

## Assumptions inherited from the approved owner brief

1. `cfc4f3e` is the newest committed safe integration base: it contains `d854b0e` and Visual
   Phase A, but excludes the other task's uncommitted Phase B changes.
2. Existing Question Engine, practice, upload, auto-map, Map50 and activation contracts are the
   authority; this task will repair or extend them rather than create parallel systems.
3. Production inspection is read-only until a release candidate, verified backup and isolated
   migration rehearsal exist.
4. Normal Clerk login is mandatory for authenticated acceptance. MFA or an unavailable real test
   identity is an external gate and will be reported, never bypassed.
5. No schema change will be made unless the current schema cannot express the required durable
   identity or recovery state; any required migration will be additive from the observed maximum.

## Tech stack

- React/Vite browser application with Clerk authentication.
- FastAPI/Pydantic RAG and learning service backed by SQLite.
- Express/TypeScript agent service, unchanged unless regression evidence requires a compatibility fix.
- Existing Question Engine, UI-extension domain adapter and automatic knowledge-map worker.

## Commands

- Backend tests: `services/rag-api/.venv/Scripts/python.exe -m pytest services/rag-api/tests -q`
- Backend lint: `services/rag-api/.venv/Scripts/python.exe -m ruff check services/rag-api/app services/rag-api/tests`
- Backend types: `services/rag-api/.venv/Scripts/python.exe -m mypy services/rag-api/app`
- Web tests: `npm test --workspace @coursemate/web`
- Web types: `npm run typecheck --workspace @coursemate/web`
- Production build: `npm run build`
- Browser acceptance: `npm run test:e2e`

Exact targeted commands and executed counts will be recorded in the final report. Historical test
counts are not accepted as evidence for this branch.

## Project structure

- `services/rag-api/app/cm_update/`: public UI API, runs, Pair/history and durable browser recovery.
- `services/rag-api/app/ui_extension/`: owner-scoped domain adapter into Question Engine and trees.
- `services/rag-api/app/learning/`: Question Engine, practice, Assessment and knowledge contracts.
- `services/rag-api/app/services/auto_knowledge_map.py`: upload-triggered generation, validation and activation.
- `services/rag-api/migrations/`: additive SQLite migrations and invariant triggers.
- `apps/web/src/ui/`: current production learning workspace and API client.
- `services/rag-api/tests/`, `apps/web/src/*.test.*`: targeted and regression tests.

## Code style

Follow the existing typed, fail-closed service pattern:

```python
if existing.status == "UNKNOWN":
    raise ApiError(409, "MODEL_REQUEST_UNCERTAIN", "The existing operation needs reconciliation.")
return existing.public_projection()
```

Use stable public error codes, owner/course-scoped queries, persisted identities, immutable revisions,
and GET-only observers. Do not expose provider exceptions, answers, secrets or absolute paths.

## Testing strategy

- TDD for every behavior change, with a failing targeted test before implementation.
- Backend contract tests for idempotency, revision identity, permissions, recovery and activation.
- Web tests for first-render state, same-run recovery, refresh and user-visible stages.
- Real Chrome for campus/private Do-One and new-private-course tree journeys.
- Read-only production inventory before mutation; isolated database copy for migrations and integrity.
- Full RAG/Web/Agent/Question Engine/tree/auth/Learning Loop regression before release.

## Boundaries

- Always: preserve owner scope; bind answer/solution to one question revision; enforce Map50 before
  activation; retain old active tree on failure; prove backup restore; preserve all other worktrees.
- Ask only when blocked: MFA/verification, unavailable external authorization, irreversible data
  risk, or a semantic merge conflict with another active task.
- Never: fake Clerk identity, reuse private questions or sources across owners, automatically resend
  UNKNOWN operations, restart legacy Map50 backfill, stop GPU owners, modify NanoJev/ComfyUI state,
  force-push, clean/stash/reset another worktree, or restore an old database over new student data.

## Success criteria

All 15 completion conditions in the owner brief must pass on production: campus/private Do-One,
first render, submit/reveal/answer/details/history recovery, private course creation and READY source,
Map50 generation/activation/relogin/authorization isolation, Assessment preservation, parallel work
preservation, deployment and authenticated browser acceptance. Otherwise the final verdict is PARTIAL.

## Open questions to resolve from evidence

- Which exact production release and schema are live now?
- Which current campus and private courses are eligible for safe authenticated acceptance?
- Does an existing persisted identity fully express a durable Do-One session, or is an additive
  session record required?
- Is the new-course failure in source readiness, reconcile/worker configuration, activation, or UI
  projection?

