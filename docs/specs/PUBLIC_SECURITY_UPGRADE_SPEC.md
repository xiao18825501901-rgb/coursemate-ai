# Spec: Public Production Security Upgrade

Status: approved implementation baseline derived from the owner's 2026-08-12 security brief.

## Objective

Upgrade CourseMate AI from controlled staging to a public-registration product using Clerk Authentication. Any signed-in user may query the shared read-only CS3481/GE2324 corpus and use a private Study Agent/task board. User-owned tasks, conversations, and messages must be isolated in backend database queries. Corpus mutations must be admin-only.

## Threat model

Trust boundaries are browser to Clerk, browser to each Render API, each API to Clerk JWT verification, untrusted uploads to ingestion, retrieved course text to the model, model tool output to the executor, and each service to its own SQLite database.

Protected assets are Clerk identities/session tokens, OpenAI spend, private tasks, private conversation history, the shared course corpus, uploaded storage, and admin capabilities. Primary abuse cases are forged/expired tokens, cross-user IDOR, client-supplied owner IDs, normal-user corpus mutation, prompt-driven cross-user task operations, oversized requests/uploads, and repeated model-backed calls.

## Authentication contract

- Frontend uses the current `@clerk/react` SDK, wraps the application in `ClerkProvider`, obtains a current session token with `useAuth().getToken()`, and sends `Authorization: Bearer <token>` to both APIs.
- Each backend verifies the Clerk session JWT independently, including signature, expiry/not-before, session-token type, and authorized party. The stable owner ID is the verified `sub`/Clerk user ID only.
- Missing, invalid, or expired credentials return the existing structured error shape with HTTP 401.
- Health remains public. Landing and About remain viewable signed out. Course, document-read, QA, task, and Agent endpoints require authentication.
- Tests inject an explicit verifier seam; production never accepts a header or body as an identity substitute.

## Authorization and ownership

- `ADMIN_USER_IDS` is a comma-separated backend-only allowlist of exact Clerk user IDs. Both APIs enforce it independently where applicable.
- Shared corpus reads and QA are available to authenticated users.
- Course creation, document upload, ingestion-job inspection, and future corpus mutations are admin-only. Non-admin authenticated requests return 403.
- Every task has non-null `owner_user_id`; all create/list/update/delete/tool queries include that owner.
- Every conversation has non-null `owner_user_id`; messages inherit access through their conversation. Any conversation lookup must include the authenticated owner.
- Existing ownerless task/conversation rows are migrated to the reserved, non-Clerk owner `legacy_orphaned`. They are never assigned to a real user and remain inaccessible through public APIs.

## Abuse protection

- Keep global IP-oriented API limiting as a coarse layer.
- Add authenticated per-user limits for model-backed calls using the existing single-instance SQLite databases: QA and Agent chat consume bounded per-minute counters atomically.
- Keep JSON at 64 KiB, QA question/model loop bounds, upload byte cap, pagination caps, and strict tool schemas.
- Rate-limit failures return structured HTTP 429 without calling the model.

## Database migrations

- Migrations are idempotent and tracked in `schema_migrations`.
- New databases are created with ownership/rate-limit schema already present.
- Existing tables are upgraded without deleting databases. Owner columns are added with the reserved legacy value, indexes are added, and subsequent application writes always use verified Clerk IDs.

## Frontend behavior

- Signed out: Home/About visible; navigation offers Sign in and Sign up; protected routes show a login-required screen and do not call protected APIs.
- Signed in: Course QA, Study plan, and Documents reads are available; the current user and sign-out affordance are visible.
- Corpus upload controls are hidden unless the verified backend-facing admin configuration is represented locally. Because frontend admin display is not a security boundary, the backend always enforces 403. For the minimal public build, upload management is not shown to normal users.

## CORS

Both APIs allow only exact `WEB_ORIGIN`, allow the `Authorization` and `Content-Type` headers, and never combine credential-bearing requests with wildcard origins. Bearer tokens are used rather than cross-origin cookies.

## Tech stack additions

- Web: `@clerk/react` 6.12.8.
- Agent: `@clerk/express` current pinned package.
- RAG: `clerk-backend-api` 6.0.1.

## Commands

    services/rag-api/.venv/Scripts/python.exe -m pytest services/rag-api/tests -q
    services/rag-api/.venv/Scripts/python.exe -m ruff check services/rag-api/app services/rag-api/tests scripts/import_corpus.py
    services/rag-api/.venv/Scripts/python.exe -m mypy services/rag-api/app scripts/import_corpus.py
    npm test
    npm run typecheck
    npm run build
    npm run test:e2e
    npm audit --audit-level=high

## Testing strategy

Backend integration tests prove real middleware/dependency enforcement with deterministic injected token verifiers. Repository tests prove SQL-level tenant isolation and legacy migration. Frontend tests prove protected routes do not call APIs signed out and authenticated requests include the token. Existing RAG SSE/citation and Agent function-calling tests remain green. Real-browser acceptance uses an explicit test auth adapter only in Playwright's deterministic local environment; production builds use Clerk.

## Boundaries

- Always: derive owners from verified claims, parameterize SQL, use exact-origin CORS, reject by default, preserve structured errors, and test 401/403/429/IDOR paths.
- Ask first: add paid infrastructure, deploy, change Clerk tenant settings, or choose real admin IDs.
- Never: place Clerk/OpenAI secrets in Vite variables, logs, tests, snapshots, Git, or request bodies; assign legacy rows to a real user; trust frontend authorization.

## Success criteria

All twelve required security/compatibility test categories in the owner brief pass; fresh and legacy databases start safely; tracked files/history/frontend build contain no real secrets; configs/docs list exact variables; the 25-section handoff contains the final commit hash; repository is committed but not deployed.
