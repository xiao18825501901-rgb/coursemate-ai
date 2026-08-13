# CourseMate AI V2 Platform Specification

Status: approved for incremental implementation by the V2 master request dated 2026-08-13.

## Objective

Evolve the existing public CourseMate AI application into a Chinese-first, multi-course, personalized AI teaching platform without rewriting or regressing the existing RAG and task Agent systems.

Primary users are authenticated students who need persistent course conversations, grounded and general tutoring, exact assignment-question teaching, private course creation, per-course teaching preferences, and a consent-plus-review publication path.

V2 is complete only when the acceptance criteria in the master request are covered by automated tests, the existing CS3481/GE2324 flows remain green, database migrations are reversible at the release level, and production claims are backed by current runtime evidence.

## Assumptions and Evidence Boundaries

1. The V2 baseline is Git commit `e1ef57a18bb26facf26a3568a7cd5ae1d5ea7ee5` on 2026-08-13.
2. React, FastAPI, Express, Clerk, and service-owned SQLite remain the architecture.
3. Existing official courses stay shared and read-only for ordinary users.
4. New user-created courses are private by default and owned by one verified Clerk subject.
5. Schema changes are additive, idempotent SQLite migrations; no destructive production migration is allowed without a verified backup.
6. The named production deployment report and server access are not present in the current workspace. Git proves Netlify/Render configuration, not live hosting. Public URL probes could not connect from the audit environment and are not treated as downtime evidence.
7. Runtime provider, VM layout, Caddy/systemd/UFW state, backup health, and production database contents remain unknown until redacted runtime evidence is available.

## Technology and Commands

| Concern | Technology / command |
|---|---|
| Web | React 19, TypeScript 5.9, Vite 8, Clerk React |
| RAG/Tutor | Python 3.11+, FastAPI, SQLite/FTS5, OpenAI Python SDK compatible transport |
| Task Agent | Node 24, TypeScript, Express 5, SQLite, OpenAI Responses Function Calling |
| Web/Agent tests | `npm test` |
| Type checks | `npm run typecheck` |
| Web/Agent builds | `npm run build` |
| RAG tests | `services/rag-api/.venv/Scripts/python.exe -m pytest services/rag-api/tests -q` |
| RAG lint | `services/rag-api/.venv/Scripts/python.exe -m ruff check services/rag-api/app services/rag-api/tests scripts/import_corpus.py` |
| RAG types | `services/rag-api/.venv/Scripts/python.exe -m mypy services/rag-api/app scripts/import_corpus.py` |
| Browser regression | `npm run test:e2e` using isolated deterministic test authentication |

## Project Structure

```text
apps/web/                 React product UI and authenticated API clients
services/rag-api/         Tutor, retrieval, ingestion, course and conversation data
services/agent-api/       Task Agent, tool schemas and owner-scoped task data
tests/e2e/                Cross-service browser acceptance flows
docs/specs/               Product/API contracts before implementation
docs/                     Architecture, migration, security, test and handoff material
data/                     Ignored local runtime databases/uploads plus tracked inventories
```

## Architectural Contracts

### Identity and authorization

- The browser supplies a Clerk session token, never an authoritative user ID.
- Both backends verify identity independently.
- Every private course, conversation, document mutation, teaching profile, publication request, and task operation is authorized by verified owner or admin policy at the backend and SQL boundary.
- Foreign private resources return 404 where existence disclosure is unnecessary.

### Course visibility

```text
OFFICIAL                shared read, admin-managed
USER_PRIVATE            owner-only
COMMUNITY_PENDING       owner + admin review only
COMMUNITY_PUBLIC        authenticated shared read, immutable to non-owner
REJECTED / ARCHIVED     owner/admin according to lifecycle policy
```

Actual database values may use lower-case wire values, but API enums are stable and documented.

### Prompt hierarchy

```text
Platform security and privacy rules
  > tutor behavior policy
  > structured course teaching profile
  > current user request
  > retrieved course documents as untrusted evidence
```

Course materials and owner preferences cannot override authentication, authorization, privacy, citation, or tool safety.

### Model providers

- RAG chat, embeddings, and Agent tool calling have separate configuration.
- Existing OpenAI SDK compatible transports remain backward compatible.
- No provider migration is accepted without an eval comparison.
- Fallback, if implemented, is explicit, bounded, observable, and avoids uncontrolled duplicate charging.

### Streaming and persistence

- SSE event names remain additive and backward compatible.
- A chat request may start or continue an owner/course-bound conversation.
- User input is persisted before generation; successful assistant output and citations are persisted at stream completion.
- Interrupted streams preserve the user message and do not fabricate a completed assistant message.

## API Surface (Target)

All endpoints require verified authentication unless explicitly documented otherwise.

```text
GET    /api/conversations?courseId=&page=&pageSize=
POST   /api/conversations
GET    /api/conversations/{id}
PATCH  /api/conversations/{id}
DELETE /api/conversations/{id}
POST   /api/qa/chat                 # optional conversationId, SSE response

GET    /api/courses
POST   /api/courses
GET    /api/courses/{id}
PATCH  /api/courses/{id}
DELETE /api/courses/{id}
GET    /api/courses/{id}/documents
POST   /api/courses/{id}/documents
DELETE /api/courses/{id}/documents/{documentId}

GET    /api/courses/{id}/teaching-profile
PUT    /api/courses/{id}/teaching-profile
POST   /api/courses/{id}/teaching-profile:build

POST   /api/courses/{id}/publication-requests
GET    /api/admin/publication-requests
POST   /api/admin/publication-requests/{id}/approve
POST   /api/admin/publication-requests/{id}/reject
```

List responses are paginated. Errors use the existing `{ error: { code, message, details } }` envelope. Input names are camelCase on the wire and additive relative to V1.

## Code Style

Keep orchestration explicit and typed. Boundary models validate input once; services work with trusted values; SQL receives parameters.

```python
def rename_conversation(
    self, *, owner_user_id: str, conversation_id: str, title: str
) -> dict[str, object]:
    normalized = title.strip()
    with self.database.connect() as connection:
        row = connection.execute(
            "UPDATE conversations SET title = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND owner_user_id = ? RETURNING *",
            (normalized, conversation_id, owner_user_id),
        ).fetchone()
    if row is None:
        raise ApiError(404, "CONVERSATION_NOT_FOUND", "The conversation was not found.")
    return dict(row)
```

## Testing Strategy

- Pure language, routing, reference parsing, prompt assembly, quotas, and visibility rules: small unit tests.
- Schema migration, owner isolation, CRUD, ingestion, SSE persistence and retrieval: SQLite-backed API/service integration tests.
- React history, course creation/settings, responsive layout and accessibility states: component tests.
- Login-equivalent deterministic auth, refresh/reopen persistence, cross-course QA, task Agent, private course and publication flows: limited browser E2E tests.
- AI behavior: deterministic provider contract tests plus a versioned 50-case eval dataset; live model benchmark results must state model/date/region/cost and cannot be fabricated.

## Boundaries

### Always

- Back up SQLite database, WAL/SHM state, and RAG uploads as one consistency unit before production migration.
- Add migration tests for clean and existing V1 databases.
- Enforce ownership in backend services and SQL, not only React.
- Preserve citations as references only to retrieved course evidence.
- Test both enabled and disabled states of incomplete feature flags.
- Keep secrets out of source, logs, fixtures, screenshots, and reports.

### Requires a verified production gate

- Applying migrations to live databases.
- Enabling V2 flags for public users.
- Changing provider/model values in live environments.
- Replacing Caddy/systemd/firewall/DNS configuration.
- Executing a production rollback or restore.

### Never

- Delete or overwrite production data without a restorable backup and explicit target verification.
- Trust client-supplied owner IDs, course visibility, filesystem paths, or admin flags.
- Allow arbitrary course text to become a higher-priority system prompt.
- Automatically publish user files without owner consent and admin approval.
- Claim production verification from local tests or deployment configuration alone.

## Stage Success Criteria

1. Stage 0: baseline, gap analysis, target contracts and implementation plan committed.
2. Stage 1: natural Chinese mirroring; complete owner-scoped conversation create/list/get/continue/rename/delete; refresh/login recovery UI.
3. Stage 2: deterministic intent router with general conversation, grounded/tutoring modes, and history-aware query rewrite.
4. Stage 3: filename/question/subpart resolver and structure-aware context with golden CS3481/GE2324 tests.
5. Stage 4: tutor policy, admin-only retrieval diagnostics, 50-case eval dataset and regression gate.
6. Stage 5: official-source 2026 provider research and reproducible model benchmark; recommendations separated for tutor/Agent/embedding.
7. Stage 6: private course CRUD, secure upload/ingestion, configurable quotas, isolated storage and safe deletion.
8. Stage 7: structured, versioned teaching profile and bounded AI profile builder.
9. Stage 8: private-to-pending-to-approved/rejected publication workflow with consent and admin audit trail.
10. Stage 9: all automated gates green, migration/backup/restore/rollback documentation complete, and production smoke evidence captured only after access and backup gates pass.

## Open Runtime Questions

- What commit and environment variables are actually running at `qqttai.com` and its APIs?
- Are the live APIs on Alibaba Cloud HK, Render, or another target?
- Which provider/models are active for RAG chat, embeddings, and Agent calls?
- What are the live database row counts, upload manifest, backup schedule, monitoring path, and rollback mechanism?

These questions do not block local V2 implementation. They block production migration and the final production-verified label.
