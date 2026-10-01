# Implementation Plan: P0 Do-One and New Private Course Tree

## Architecture decisions

- Reuse the production Question Engine and automatic map worker; no second generation path.
- Deliver vertical slices and keep each code task within roughly five files.
- Establish production facts and reproduce failures before selecting any schema or code change.
- Reconcile with the latest integration candidate only after this branch is independently green.

## Phase 1: isolation and evidence

### Task 1: Freeze the independent baseline

**Acceptance:** dedicated branch/worktree exists at committed `cfc4f3e`; NanoJev and Visual worktrees,
processes, ports and GPU owners are identified and untouched.

**Verification:** `git worktree list`, branch/status/log snapshots and process/port/GPU inventory.

**Dependencies:** none. **Files:** isolation report only. **Scope:** S.

### Task 2: Map both existing feature paths

**Acceptance:** entrypoints, endpoints, workers, tables, state machines, tests, observed unknowns and
planned files are recorded for both features.

**Verification:** paths and symbols resolve on this branch; source-map review against current code.

**Dependencies:** Task 1. **Files:** source-map/spec/plan documents. **Scope:** S.

### Task 3: Inventory current production without writes

**Acceptance:** current release/schema/configurations/questions/qualification/trees/flags and legacy
over-limit status are queried from live read-only sources with IDs, counts, states and safe errors only.

**Verification:** database opened read-only; before/after live fingerprint unchanged.

**Dependencies:** Task 2. **Files:** current-status JSON and evidence logs. **Scope:** M.

## Phase 2: Do-One vertical slice

### Task 4: Reproduce campus and private failures

**Acceptance:** one campus and one private flow produce a stage-specific ledger with request/run,
HTTP, Question Engine, revision and DOM evidence; no code is changed before reproduction.

**Verification:** deterministic replay or authenticated live reproduction tied to exact IDs.

**Dependencies:** Task 3. **Files:** failure ledger and browser artifacts. **Scope:** M.

### Task 5: Repair durable request and recovery behavior

**Acceptance:** READY reuse performs zero new model calls; empty pool uses the existing engine;
double click/refresh/SSE loss recover the same operation; UNKNOWN and cancelled late results do not resend/revive.

**Verification:** new failing tests first, then targeted backend and web suites.

**Dependencies:** Task 4. **Files:** one domain/API slice plus focused tests, max five per increment. **Scope:** M per increment.

### Task 6: Prove reveal, revision and history consistency

**Acceptance:** attempt, reveal, correct answer, worked solution, independent detail and Pair/history
all bind to one question revision and survive refresh/re-entry with owner isolation.

**Verification:** backend contract, web component and real Chrome tests.

**Dependencies:** Task 5. **Files:** practice projection/UI/tests, max five per increment. **Scope:** M.

## Phase 3: new private tree vertical slice

### Task 7: Reproduce the new-course source-to-tree path

**Acceptance:** new private course and permitted source show the exact processing/reconcile/generation
or activation failure; existing 13 legacy targets remain unclaimed.

**Verification:** persisted source/job/target/receipt evidence and browser state.

**Dependencies:** Task 3. **Files:** failure ledger and artifacts. **Scope:** M.

### Task 8: Enforce new-source readiness and idempotent generation

**Acceptance:** only READY indexed frozen sources generate; repeated course/snapshot/generator/policy
requests reuse one job; worker restart and UNKNOWN reconcile without a blind resend.

**Verification:** 1-PDF, multi-PDF, processing/parser/index failure, duplicate click and restart tests.

**Dependencies:** Task 7. **Files:** auto-map service/API/tests, max five per increment. **Scope:** M.

### Task 9: Enforce Map50 validation and atomic activation

**Acceptance:** generated tree is complete and <=50; cycles/dangling/foreign sources/duplicate titles
are rejected; old active revision survives failure; source version change creates a new revision.

**Verification:** targeted service/migration tests plus database integrity/FK checks.

**Dependencies:** Task 8. **Files:** validator/activation/tests, max five per increment. **Scope:** M.

### Task 10: Prove UI first render and owner isolation

**Acceptance:** browser shows upload -> processing -> READY -> tree preparing -> READY without F5;
refresh/relogin persists; three units and source links work; second user receives no access.

**Verification:** unit tests and authenticated real Chrome acceptance.

**Dependencies:** Task 9. **Files:** UI/API client/tests, max five per increment. **Scope:** M.

## Phase 4: regression, integration and release

### Task 11: Full regression and adversarial review

**Acceptance:** current-HEAD RAG/Web/Agent/Question Engine/tree/auth/Learning Loop suites, lint,
typecheck and production build pass with non-zero counts; security and code review have no open P0/P1.

**Dependencies:** Tasks 6 and 10. **Files:** reports only unless a proven regression is fixed. **Scope:** M.

### Task 12: Reconcile parallel branches

**Acceptance:** current production/integration, Visual and NanoJev diffs are compared; conflicts are
merged by intent or documented precisely without changing the other worktrees.

**Dependencies:** Task 11. **Files:** isolation/conflict report. **Scope:** M.

### Task 13: Backup, deploy and production acceptance

**Acceptance:** verified off-host backup and restore rehearsal, compatible backend-first then web
deployment, exact markers/health/schema/workers, authenticated production matrix and rollback flags.

**Dependencies:** Task 12. **Files:** release, live acceptance and final usability reports. **Scope:** M.

## Checkpoints

- After Tasks 1-3: isolation and current facts reviewed; no production writes.
- After Tasks 4-6: Do-One targeted suites and authenticated journey green before tree code changes.
- After Tasks 7-10: new-tree targeted suites and authenticated journey green; legacy 13 still paused.
- After Tasks 11-13: exact release evidence, rollback and final COMPLETE/PARTIAL verdict.

## Principal risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Another task advances production | High | Re-read heads immediately before integration/deploy; never reset shared branches. |
| Random browser request IDs defeat recovery | High | Persist or deterministically recover one owner/course/target operation identity. |
| Legacy backfill is accidentally resumed | High | Explicitly verify/lock `AUTO_KNOWLEDGE_MAP_LEGACY_BACKFILL_ENABLED=false`. |
| Provider outcome is UNKNOWN | High | Receipt/artifact reconciliation only; no automatic resend. |
| Disk pressure during backup | High | Use current verified off-host/memory-backed backup procedure and validate free space. |
| Clerk/MFA unavailable | Medium | Complete all non-auth work; report exact live blocker without bypass. |

