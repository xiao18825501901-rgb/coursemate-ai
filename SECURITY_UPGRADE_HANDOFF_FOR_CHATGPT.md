# CourseMate AI — Public Production Security Upgrade Handoff

Audit date: 2026-08-12  
Implementation branch: `feature/public-security-upgrade`  
Audited implementation commit: `149814d67f7e5cc34a0da9fab492d3130e5d8625`  
Deployment status: **not deployed**; no Git remote is configured.

## 1. Security architecture

The browser uses Clerk for identity and sends a Clerk session token as `Authorization: Bearer <token>` to both APIs. FastAPI and Express independently verify the token and derive the stable user ID from verified claims. The RAG corpus is shared read-only among authenticated users; conversations and tasks are private. Corpus mutation is enforced server-side through an administrator allowlist. Model-backed calls use SQLite-backed per-user minute limits. Both services remain single-instance because they own separate SQLite databases and Render disks.

## 2. Clerk integration architecture

- Frontend dependency: `@clerk/react@6.14.1`.
- Express dependency: `@clerk/express@2.1.55`.
- FastAPI dependency: `clerk-backend-api==6.0.1`.
- React is wrapped in `ClerkProvider`; `useAuth().getToken()` supplies the session token.
- Express uses `clerkMiddleware()` and `getAuth()`, with `authorizedParties=[WEB_ORIGIN]` and session tokens only.
- FastAPI uses `authenticate_request()` with `AuthenticateRequestOptions`, the exact `WEB_ORIGIN`, and session tokens only.
- `CLERK_JWT_KEY` is optional on each backend. When supplied, the official SDK verifies networklessly; otherwise the SDK can retrieve Clerk JWKS using the backend secret.
- Production services fail closed if required Clerk verification configuration is absent.
- A fixed test adapter exists only for automated browser tests. It is rejected unless the service is simultaneously in `test` environment and deterministic provider mode.

## 3. Exact files changed

Relative to the previous deployment-handoff commit `8da4dcc`, the upgrade changed:

```text
.env.example
README.md
apps/web/package.json
apps/web/src/App.test.tsx
apps/web/src/App.tsx
apps/web/src/auth/AuthProvider.tsx
apps/web/src/components/Layout.tsx
apps/web/src/components/ProtectedRoute.tsx
apps/web/src/main.tsx
apps/web/src/pages/DocumentsPage.tsx
apps/web/src/pages/QaPage.test.tsx
apps/web/src/pages/QaPage.tsx
apps/web/src/pages/TasksPage.test.tsx
apps/web/src/pages/TasksPage.tsx
apps/web/src/services/agentApi.ts
apps/web/src/services/http.test.ts
apps/web/src/services/http.ts
apps/web/src/services/ragApi.ts
apps/web/src/styles.css
docs/DEPLOYMENT.md
docs/PUBLIC_SECURITY_UPGRADE_PLAN.md
docs/specs/PUBLIC_SECURITY_UPGRADE_SPEC.md
netlify.toml
package-lock.json
playwright.config.ts
render.yaml
scripts/start_local.ps1
services/agent-api/package.json
services/agent-api/src/app.ts
services/agent-api/src/auth.ts
services/agent-api/src/config.ts
services/agent-api/src/db.ts
services/agent-api/src/rate-limit.ts
services/agent-api/src/repositories/tasks.ts
services/agent-api/src/server.ts
services/agent-api/src/services/agent.ts
services/agent-api/src/tools/executor.ts
services/agent-api/test/agent-service.test.ts
services/agent-api/test/api.test.ts
services/agent-api/test/config.test.ts
services/agent-api/test/task-repository.test.ts
services/agent-api/test/tool-executor.test.ts
services/rag-api/app/api/ingestion.py
services/rag-api/app/api/qa.py
services/rag-api/app/auth.py
services/rag-api/app/config.py
services/rag-api/app/db.py
services/rag-api/app/main.py
services/rag-api/app/models.py
services/rag-api/app/services/qa.py
services/rag-api/requirements.txt
services/rag-api/tests/test_database.py
services/rag-api/tests/test_ingestion_api.py
services/rag-api/tests/test_qa_api.py
```

This handoff file is added in the following documentation commit and is therefore not part of the implementation hash above.

## 4. Exact frontend auth behavior

Signed out users can view Home, About, and the not-found page. Private navigation is hidden. Direct access to `/qa`, `/qa/:courseId`, `/tasks`, or `/documents` renders a sign-in gate. Clerk modal buttons provide sign-up and sign-in. Signed-in users see QA, Study Plan, Documents, the current account label, Clerk profile control, and sign-out through `UserButton`.

All RAG/Agent clients call one `authenticatedFetch()` helper. It asks Clerk for the current session token, refuses the request locally if no token exists, preserves existing headers, and adds the Bearer header. JSON, SSE, DELETE, and upload clients share the rule. The ordinary-user UI has no upload controls; the Documents page is read-only.

## 5. Exact RAG authentication mechanism

`services/rag-api/app/auth.py` adapts FastAPI `Request` directly to Clerk's `Requestish` protocol. `authenticate_request()` verifies the token using the configured secret/JWT public key and exact authorized party. Only `signed-in` state with a non-empty string `sub` claim becomes `AuthenticatedUser.user_id`; client-submitted user IDs are ignored. `require_user` returns 401 for missing/invalid credentials. `create_app()` fails at startup when neither a real Clerk verifier nor the tightly gated test verifier is configured.

## 6. Exact Agent authentication mechanism

`services/agent-api/src/auth.ts` installs official `clerkMiddleware()` with Clerk publishable/secret keys, optional JWT public key, the exact frontend origin in `authorizedParties`, and `acceptsToken: "session_token"`. Routes call `getAuth(request).userId` through `AuthStrategy`. A null result returns the standard 401 envelope. The browser cannot provide or override the owner ID. Startup requires Clerk keys except in explicitly gated test deterministic mode.

## 7. Exact authorization rules

| Resource/action | Signed out | Authenticated user | Allowlisted admin |
|---|---:|---:|---:|
| Health endpoints | Allow | Allow | Allow |
| List shared courses/documents | 401 | Allow | Allow |
| QA/retrieval/citations | 401 | Allow, private conversation | Allow |
| Read conversation by ID | 401 | Own only; foreign ID is 404 | Own only |
| Task create/list/search/update/complete/reopen/delete | 401 | Own rows only | Own rows only |
| Create course | 401 | 403 | Allow |
| Upload document | 401 | 403 | Allow |
| Inspect ingestion job | 401 | 403 | Allow |

No authorization decision trusts request bodies, query parameters, frontend state, or an admin flag supplied by the client.

## 8. Task ownership implementation

`tasks.owner_user_id TEXT NOT NULL` stores the verified Clerk user ID. Repository methods require `ownerUserId` as their first argument. Every read, count, search, update, completion/reopen, and delete SQL statement includes `owner_user_id = ?`. Tool execution and AgentService thread the authenticated owner from HTTP to repository. Cross-owner object access returns not found and never reveals whether the target exists.

## 9. Conversation ownership implementation

`conversations.owner_user_id TEXT NOT NULL` stores the verified Clerk user ID when QA begins. Messages inherit authorization through the owned conversation foreign key. `GET /api/conversations/{conversation_id}` first selects the conversation by both ID and owner, then returns its messages; another user with the exact ID receives 404. Shared chunks/documents do not carry per-user ownership because the approved corpus is intentionally common read-only material.

## 10. Admin/corpus mutation rules

The selected design is a backend environment allowlist: `ADMIN_USER_IDS` is parsed as comma-separated Clerk user IDs by the RAG service. `require_admin` compares only the verified token subject. Course creation, document upload, and ingestion-job inspection require that allowlist and return 403 to ordinary authenticated users. Course/document listing remains authenticated shared read access. The public frontend exposes no mutation entry point. Corpus deletion endpoints do not currently exist; any future mutation must use the same dependency.

## 11. Rate limiting / abuse protection

- RAG QA: default 10 requests per authenticated user per minute.
- Agent chat: default 10 requests per authenticated user per minute.
- SQLite tables use `(owner_user_id, action, window_start)` as the primary key and atomic upsert increments.
- Old windows are opportunistically removed.
- Limits apply before model calls, so a rejected request does not consume OpenAI usage.
- Existing Express general IP limit remains 120 requests/minute.
- Express JSON bodies remain limited to 64 KiB; QA question length remains 2,000 characters; RAG uploads retain the configured byte limit and type/path checks.
- No Redis or new paid database was introduced. This design assumes the existing single instance per SQLite-backed Render service.

## 12. Database schema changes

Both databases gained `schema_migrations` and `rate_limit_windows`. Agent `tasks` gained `owner_user_id` plus owner/status/due and owner/course/status indexes. RAG `conversations` gained `owner_user_id` plus owner/update and owner/course/update indexes. Fresh schemas require owner values without a public default.

## 13. Migration behavior

Initialization is idempotent and safe to repeat. For a legacy Agent database, `ALTER TABLE tasks ADD COLUMN owner_user_id TEXT NOT NULL DEFAULT 'legacy_orphaned'` preserves data without assigning it to a real user. RAG applies the same quarantine strategy to old conversations. Application queries only real verified Clerk IDs, so quarantined rows are inaccessible. Migration version 1 is inserted with `INSERT OR IGNORE`; running initialization twice leaves one record. No database is deleted or reset.

## 14. New environment variables

| Variable | Service | Secret | Required/meaning |
|---|---|---:|---|
| `VITE_CLERK_PUBLISHABLE_KEY` | Web | No | Required production Clerk publishable key |
| `CLERK_PUBLISHABLE_KEY` | Agent | No | Required by Clerk Express middleware |
| `CLERK_SECRET_KEY` | RAG + Agent | Yes | Backend Clerk verification credential |
| `CLERK_JWT_KEY` | RAG + Agent | Sensitive config | Optional Clerk public PEM for networkless verification |
| `ADMIN_USER_IDS` | RAG | No, but restrict visibility | Comma-separated admin Clerk user IDs |
| `RAG_QA_REQUESTS_PER_MINUTE` | RAG | No | Default `10` |
| `AGENT_CHAT_REQUESTS_PER_MINUTE` | Agent | No | Default `10` |
| `APP_ENV` | RAG | No | `production`, `development`, or `test` |
| `AUTH_TEST_USER_ID` | Test only | No | Rejected outside test + deterministic mode; never set in production |
| `VITE_AUTH_TEST_TOKEN` | Playwright dev server only | No | Fixed local E2E token; never set in Netlify |

## 15. Updated Render variables

RAG now expects `CLERK_SECRET_KEY`, optional `CLERK_JWT_KEY`, `ADMIN_USER_IDS`, `RAG_QA_REQUESTS_PER_MINUTE`, and `APP_ENV=production`, in addition to its existing OpenAI/storage/origin variables. Agent now expects `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, optional `CLERK_JWT_KEY`, and `AGENT_CHAT_REQUESTS_PER_MINUTE`. Render's `PORT` is now honored when `AGENT_PORT` is absent. The RAG start command is the fail-closed factory form: `uvicorn app.main:create_app --factory ...`.

## 16. Updated Netlify variables

Set exactly these public build variables:

```text
VITE_RAG_API_URL=https://<rag-render-origin>
VITE_AGENT_API_URL=https://<agent-render-origin>
VITE_CLERK_PUBLISHABLE_KEY=<Clerk publishable key>
```

Never set `OPENAI_API_KEY`, `CLERK_SECRET_KEY`, `CLERK_JWT_KEY`, `ADMIN_USER_IDS`, passwords, or session tokens in Netlify/Vite variables.

## 17. CORS changes

Both APIs allow only the exact `WEB_ORIGIN`, with no wildcard and no credentials/cookies. Allowed methods remain explicit. `Authorization` was added to allowed request headers alongside `Content-Type`. Preflight tests verify the header. Clerk `authorizedParties` independently checks the same frontend origin during token verification.

## 18. Tests added

Coverage now proves: missing token 401; invalid token 401; authenticated QA; authenticated Agent chat; A/B task create/read/mutation isolation; A/B conversation ID isolation; ordinary-user corpus write 403; admin course/upload allowed; frontend Bearer injection and no-token short circuit; CORS Authorization preflight; legacy task/conversation quarantine; repeatable migrations; per-user RAG/Agent rate limits; production fail-closed config; test-adapter gating; Render `PORT` fallback; existing RAG streaming/citations; existing Agent function calls and task tools.

## 19. Full verification results

Run on 2026-08-12 from the repository root using Node 24.14 and the existing Python virtual environment:

| Check | Result |
|---|---|
| Web Vitest | 11 passed, 0 failed |
| Agent Vitest | 41 passed, 0 failed |
| RAG pytest | 50 passed, 0 failed |
| Total automated unit/integration tests | 102 passed, 0 failed |
| TypeScript typecheck (both workspaces) | Passed |
| Web + Agent production builds | Passed |
| Ruff | Passed |
| mypy | Passed |
| `git diff --check` | Passed before implementation commit |
| Chrome Playwright scenarios | 3/3 assertions passed twice |

Playwright limitation: on this Windows runner, all three tests complete successfully in about five seconds, but the Playwright process does not exit after its managed WebServer teardown and the outer command times out (tested at 120 and 180 seconds). This is recorded as a runner teardown issue, not reported as a green command. Test stdout confirms each case `ok`; no scenario assertion failed. Python also reports a third-party TestClient deprecation warning and a sandbox-denied pytest-cache warning; neither changes test results.

Secret audit: tracked files and built assets were searched for real-looking Clerk/OpenAI keys, private-key headers, long Bearer values, and secret-bearing `VITE_*` names; no real secret was found. `.env.example` contains empty placeholders only. The entire reachable Git history still requires the operator's final platform/repository scanning before publication because this local audit cannot attest to external secret scanners.

## 20. Remaining security limitations

- Clerk configuration and real-token verification have not been exercised against a live Clerk tenant.
- SQLite rate limits are single-instance and reset only through window progression; they are not distributed and do not prevent mass account creation.
- There is no CAPTCHA, email-domain restriction, Clerk signup policy, global spend cap, or automated abuse alerting in this repository.
- `ADMIN_USER_IDS` is operational configuration; a mistaken allowlist can grant corpus mutation.
- Ingestion uses an in-process FastAPI background task, so process restarts can interrupt work.
- There is no user self-service deletion/export workflow for tasks or conversation history.
- Legacy quarantined data needs an explicit audited reassignment/export procedure if it must be recovered.
- SQLite backups, disk encryption/retention, OpenAI data handling, Clerk session policy, CSP tuning, and production observability remain operator responsibilities.
- Playwright WebServer teardown hangs on the current Windows test host despite 3/3 passing cases.

## 21. Remaining deployment blockers

No Git remote exists and nothing has been pushed. No Clerk application, Render service, Netlify site, DNS/domain, production secret, administrator user ID, or paid disk has been configured by this work. The authorized production corpus has not been seeded. Real Clerk signup/sign-in, cross-origin JWT verification, live OpenAI calls, backups, production logs, and two-account smoke tests remain unverified. Therefore production is not deployed and not fully verified.

## 22. Any paid-service implications

The code adds no Redis or paid database. Existing Render persistent SQLite storage still requires two paid disk-backed services under the planned topology. Clerk and Netlify may be usable within their current plans, but the owner must review current quotas/terms. OpenAI calls incur usage charges. Public signup can increase those charges even with per-user minute limits, so configure Clerk signup controls, OpenAI budget alerts/limits, monitoring, and an incident shutoff before launch. Do not create or approve any paid resource without the owner's explicit action.

## 23. Exact Git commit hash

The fully tested security implementation baseline is:

```text
149814d67f7e5cc34a0da9fab492d3130e5d8625
```

Upgrade commits in order:

```text
cae6907181712797baa0ea4d51c77df94e52ca8c  docs: define public security upgrade
7ab0efea248ef63adbbf4c91c53d3d8c67345898  feat: secure backend APIs by authenticated owner
88524c03848aa79d2122b41ac6351e322491d88b  feat: add Clerk-protected web experience
bb7a7506018a8a5dc5f0e7b03e0e0e3dcc509d44  chore: harden production security configuration
149814d67f7e5cc34a0da9fab492d3130e5d8625  fix: validate agent chat before charging quota
```

The final repository HEAD will be one documentation commit later because it contains this handoff. The deployment tutor must deploy the final audited branch HEAD, not stop at the implementation baseline.

## 24. Updated public-production deployment order

1. Review this handoff, the security spec, deployment guide, data rights, pricing, and limitations.
2. Create a private GitHub repository, run a repository/secret scan, push the final audited branch, and protect the production branch.
3. Create/configure the Clerk application: production domain, allowed origins, session policy, signup controls, and the owner's user account. Record keys only in platform secret UIs.
4. Create both Render services from `render.yaml`, explicitly approve the two paid persistent disks, keep one instance each, and set all backend Clerk/OpenAI/admin/origin variables.
5. Start the empty backends and verify public `/health`; verify protected routes return 401 without a token.
6. Create the Netlify site with the three public `VITE_*` variables and deploy a draft.
7. Replace both `WEB_ORIGIN` values with the exact final Netlify production origin; configure the same origin in Clerk; redeploy backends and frontend.
8. Sign up/sign in with two ordinary accounts and the allowlisted administrator. Verify private navigation, profile, sign-out, 401/403 behavior, A/B isolation, and per-user 429 behavior.
9. After confirming document rights, use only the administrator session to create courses and ingest authorized files. Verify all jobs, citations, and course isolation.
10. Exercise live OpenAI QA and Agent flows with budget/usage dashboards open. Inspect sanitized logs and browser network/console.
11. Configure SQLite/upload backups, restore rehearsal, monitoring, alerts, Clerk/OpenAI spending controls, and rollback records.
12. Only after every production smoke/security/data-rights/billing check passes, mark production deployed and verified.

## 25. Minimal next actions for ChatGPT deployment tutor

The next ChatGPT should proceed one operator-confirmed gate at a time:

1. Ask the owner to confirm data rights and that they accept the two Render disk/service costs; do not buy anything.
2. Guide creation of a private GitHub remote and push of the final HEAD; ask only for the non-secret repository URL.
3. Guide Clerk application creation and exact environment-variable placement; never ask the owner to paste secret values into chat.
4. Guide Render Blueprint creation, one service at a time, and require `/health` plus 401 evidence before continuing.
5. Guide Netlify configuration with only the three public Vite variables, then close the exact-origin CORS/authorized-party loop.
6. Guide two-user + admin smoke tests, production corpus ingestion, live OpenAI budget checks, backups, and rollback verification.
7. Report deployment complete only after external URLs, authentication, isolation, admin 403/allow, persistence, and monitoring are all directly evidenced.

Current handoff verdict: **security upgrade implementation complete; public production deployment not started.**
