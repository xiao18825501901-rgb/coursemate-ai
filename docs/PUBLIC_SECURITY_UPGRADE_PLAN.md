# Implementation Plan: Public Production Security Upgrade

## Architecture decisions

- Clerk session JWTs are the sole browser identity proof; both APIs verify independently.
- `ADMIN_USER_IDS` is the smallest auditable admin policy for a personal portfolio deployment.
- Ownership is enforced in repository SQL, not post-filtered.
- Idempotent in-place SQLite migrations quarantine old private rows as `legacy_orphaned`.
- Per-user model-call limits use each service's existing single-instance SQLite database.

## Phase 1: Authentication foundations

- [ ] Add pinned Clerk dependencies and validated environment configuration.
  - Acceptance: production configuration fails closed when Clerk verification values are missing; deterministic tests can inject a verifier.
  - Verify: config unit tests and dependency lock checks.
- [ ] Add RAG and Agent authentication primitives.
  - Acceptance: no/invalid token is 401; valid token exposes only verified user ID; exact authorized party is configured.
  - Verify: focused backend authentication tests.

## Phase 2: Tenant-safe persistence

- [ ] Migrate Agent tasks and scope repository/tool operations by owner.
  - Acceptance: A/B create/list/update/delete isolation holds at SQL and HTTP/tool layers; legacy rows remain orphaned.
  - Verify: fresh/legacy migration and repository/API tests.
- [ ] Migrate RAG conversations and scope persisted history by owner.
  - Acceptance: conversation creation records verified owner and cross-owner conversation lookup is denied/not found.
  - Verify: database/service/API isolation tests.

## Checkpoint: backend isolation

- [ ] Both backend suites pass with authentication enforced.
- [ ] Existing RAG streaming/citation and Agent tool loops remain green.

## Phase 3: Authorization and abuse controls

- [ ] Protect shared corpus routes and admin-only mutations.
  - Acceptance: authenticated reads/QA work; normal upload/create gets 403; admin succeeds.
  - Verify: RAG route tests.
- [ ] Add persistent per-user model-backed rate limits.
  - Acceptance: limits are keyed by verified owner; calls beyond configured windows return 429 before providers execute.
  - Verify: RAG and Agent counter tests.

## Phase 4: Frontend Clerk UX

- [ ] Add Clerk provider, auth-aware navigation, and protected route shell.
  - Acceptance: signed-out Home/About work; protected pages require login; signed-in user/profile/sign-out appear.
  - Verify: React component tests and accessibility assertions.
- [ ] Add token-aware API clients and remove normal-user corpus mutation UI.
  - Acceptance: all protected calls include a fresh bearer token; signed-out paths make no API request.
  - Verify: API client tests plus real-browser deterministic auth flow.

## Checkpoint: integrated product

- [ ] Web, Agent, and RAG tests pass.
- [ ] Cross-course cited QA and private task flow pass in Chrome.

## Phase 5: Production configuration and ship gate

- [ ] Update `.env.example`, Render, Netlify, CORS docs, security ADR, and deployment instructions.
- [ ] Run full lint/type/build/test/audit/secret/migration/port checks.
- [ ] Produce `SECURITY_UPGRADE_HANDOFF_FOR_CHATGPT.md` with all 25 required sections and exact commit hash.
- [ ] Commit atomically without logging in or deploying.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Clerk SDK API drift | High | Follow current official docs and pin versions |
| Existing SQLite rows lack owners | High | Quarantine as `legacy_orphaned`; never auto-claim |
| IDOR through task/conversation IDs | Critical | Owner predicate in every repository query |
| Registered-user OpenAI abuse | High | Per-user SQLite counters before model invocation |
| Test-only auth leaks into production | High | Explicit dependency injection/test provider; production config fails closed |
| Cross-origin bearer header blocked | Medium | Exact origin and explicit `Authorization` allow-header tests |
