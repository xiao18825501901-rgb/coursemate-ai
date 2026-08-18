# CourseMate AI V2 Implementation Plan

## Release-candidate status (2026-08-13)

Stages 0-8 and Stage 9 source hardening, review, migration rehearsal, backup/restore package, full
regression and handoff are complete on `feature/coursemate-v2-ai-tutor`. The billable Stage 5 live
model comparison and Stage 9 production deployment/smoke are intentionally not complete because the
request forbids unapproved paid calls and no reachable production/control-plane access was present.
See `V2_TEST_REPORT.md` for the acceptance matrix; criteria G and N remain not passed.

This plan implements `docs/specs/V2_PLATFORM_SPEC.md` through small vertical slices. Every task has an acceptance gate and touches no more than five primary files unless explicitly split.

## Stage 0 — Baseline and Contracts

- [x] Capture Git/schema/API/provider/runtime baseline.
- [x] Map user complaints to current source and root causes.
- [x] Define V2 platform/API/security/test contracts.
- [x] Create isolated branch `feature/coursemate-v2-ai-tutor`.

Checkpoint: documentation diff passes whitespace checks; baseline commit remains unchanged; no production write occurred.

## Stage 1 — Chinese and Conversation History

### Task 1.1 — Conversation schema migration

- Add `title`, `preferred_language`, and profile-version-ready metadata additively.
- Auto-title deterministically from the first meaningful user message.
- Verify clean DB, V1 migration, idempotence, legacy owner quarantine and existing row preservation.
- Files: RAG DB, models and DB tests.

### Task 1.2 — Conversation resource API

- Add owner/course-paginated list, explicit create, rename and delete.
- Continue QA with optional `conversationId`, rejecting cross-owner and cross-course use as not found.
- Verify 401, A/B 404, pagination/order, CRUD, continuation and cascade.
- Files: QA models, service, routes and QA tests.

### Task 1.3 — Language policy

- Add deterministic language detection and auto/zh-CN/en/bilingual prompt policy.
- Preserve English technical terminology in Chinese mode and leave citations/SSE unchanged.
- Verify the three required Chinese cases plus English and mixed terms.
- Files: language module/tests, prompt and QA service integration.

### Task 1.4 — React history contract

- Add typed conversation client methods and consume SSE conversation metadata.
- Verify contract parsing and authenticated requests.
- Files: web API types/client/tests.

### Task 1.5 — Conversation sidebar and recovery

- Add New Chat, paginated history, open, continue, rename and confirmed delete.
- Put conversation ID in the route and restore messages on mount/refresh.
- Verify loading/empty/error/streaming states, keyboard labels, mobile layout and owner-safe API behavior.
- Files: QA page/component/styles/tests/App routes.

Checkpoint: RAG + web suites, type/lint/build, isolated browser refresh flow, original grounded QA regression.

## Stage 2 — Tutor Router and Multi-turn Orchestration

### Task 2.1 — Intent contract and deterministic router

- Implement `COURSE_GROUNDED`, `COURSE_TUTORING`, `GENERAL_CONVERSATION`, `COURSE_META`, `AMBIGUOUS`.
- Validate representative Chinese/English cases without paid calls.

### Task 2.2 — History-aware query rewrite

- Build bounded standalone retrieval queries for short follow-ups.
- Keep stored original message distinct from retrieval query.

### Task 2.3 — Strategy-specific context and prompts

- General conversation bypasses forced RAG.
- Grounded answers cite only retrieved evidence.
- Tutoring combines labeled course evidence with transparent supplementary explanation.

### Task 2.4 — Progressive teaching

- Track explanation attempts from recent messages and change strategy instead of repeating.
- Test formal → analogy → numerical → Socratic progression deterministically.

Checkpoint: “你好” never emits the no-support refusal; grounded citations and SSE remain green.

## Stage 3 — Exact Question and Example Teaching

### Task 3.1 — Reference parser

- Parse normalized filename/title, assignment/tutorial/slide/page, question and subpart in Chinese/English.

### Task 3.2 — Additive chunk metadata migration

- Add structured metadata JSON/source locator/parent fields without rewriting existing embeddings.
- Preserve old chunks with inferred baseline metadata.

### Task 3.3 — Structure-aware ingestion

- Detect headings/question/subparts supported by actual loaders and retain parent relations.
- Re-index only fixtures/copies until production migration is approved.

### Task 3.4 — Deterministic locator retrieval

- Resolve document and question before hybrid fallback; assemble bounded stem/adjacent context.

### Task 3.5 — Example tutor policy and golden tests

- Add real CS3481/GE2324 filename/question/subpart cases with correct citations and course isolation.

Checkpoint: exact-locator eval gate and all original retrieval tests pass.

## Stage 4 — Teaching Quality and Evaluation

### Task 4.1 — Context builder

- Deduplicate, merge necessary adjacent blocks, enforce source diversity/course filter/token budget.

### Task 4.2 — Tutor system prompt

- Encode language, grounding, pedagogy, citations, examples, uncertainty and prompt hierarchy.

### Task 4.3 — Admin/dev retrieval diagnostics

- Return query strategy/candidates/scores/selected context only to admin or test mode; redact content where appropriate.

### Task 4.4 — Versioned 50-case eval suite

- Cover language, grounding, locator, examples, multi-turn, general chat, isolation, private courses, security and profiles.

### Task 4.5 — Regression/quality runner

- Produce deterministic retrieval/contract metrics and a human/model rubric template without claiming subjective scores automatically.

Checkpoint: existing CS3481/GE2324 and task Agent gates stay green; eval artifact is reproducible.

## Stage 5 — 2026 Model Benchmark and Provider Boundaries

### Task 5.1 — Official-source research

- Record current official API/model/region/stream/tool/embedding facts for eligible providers with citations and dates.

### Task 5.2 — Provider interfaces

- Make tutor stream, embedding, and Agent tool-call boundaries explicit without forcing one provider.

### Task 5.3 — Controlled benchmark harness

- Run only configured models with explicit budget/timeouts; validate external responses as untrusted.

### Task 5.4 — Recommendation report

- Recommend tutor, Agent, embedding and fallback separately with evidence, cost and limitations.

Checkpoint: no live provider switch before benchmark evidence and production approval gate.

## Stage 6 — User-created Private Courses

### Task 6.1 — Course lifecycle migration/access resolver

- Add owner/type/visibility/status/language/timestamps; mark existing courses official.

### Task 6.2 — Private course create/list/update

- Add owner-safe APIs and split Official/My/Community views.

### Task 6.3 — Secure owner upload and quotas

- Validate extension/MIME/size/name/ownership and configurable course/file/byte quotas.

### Task 6.4 — Isolated storage and ingestion

- Server generates user/course/document namespace; client never supplies a path.

### Task 6.5 — Document/course deletion

- Owner confirmation and transactional DB cascade plus controlled filesystem cleanup; define conversation policy.

### Task 6.6 — Course UI

- Create wizard, files/index state, settings and private QA; responsive/accessibility tests.

Checkpoint: user B cannot see/query/mutate user A private course across every endpoint.

## Stage 7 — Teaching Profile and Prompt Builder

### Task 7.1 — Versioned structured profile schema/API

- Add level, goal, language, style, answer policy, detail, examples, terminology and custom notes.

### Task 7.2 — Safe prompt compiler

- Compile fixed platform policy + tutor policy + validated profile; never execute arbitrary system override.

### Task 7.3 — Prompt builder

- Convert simple owner preferences into validated structured output; keep explicit preview and save.

### Task 7.4 — Settings UI/version rollback

- Manual and AI builder modes with version history.

Checkpoint: prompt injection and cross-owner profile tests pass.

## Stage 8 — Publication Workflow

### Task 8.1 — Request/audit schema

- Add consent, status, submit/reviewer/note timestamps and immutable audit fields.

### Task 8.2 — Owner submission and withdrawal

- Private remains private until explicit consent and pending request.

### Task 8.3 — Admin review

- Approve/reject with notes; only approved courses become community-readable.

### Task 8.4 — Community read/clone

- Non-owner public access is read-only; clone creates a separate private owned course.

Checkpoint: state-matrix and A/B permission tests prove no accidental publication.

## Stage 9 — Production Hardening and Ship

### Task 9.1 — Full review and security/performance audit

- Resolve critical/required findings; audit pagination/indexes/uploads/prompts/secrets/dependencies.

### Task 9.2 — Migration rehearsal and backup/restore

- Snapshot DB + WAL/SHM + uploads, migrate a copy, verify counts/foreign keys/FTS/files, restore into isolation.

### Task 9.3 — Deployment and rollback package

- Document current runtime, environment-name diff, system service commands/config and exact rollback commit/data procedure.

### Task 9.4 — Staged production deployment

- Requires verified access, current backup and runtime evidence. Deploy with flags off, health check, enable staged capabilities.

### Task 9.5 — Production smoke and handoff

- Execute existing/new flows, monitor errors/latency, produce required V2 docs and file request packs.

Checkpoint: production is not labeled complete until current live evidence covers health, identity, isolation, data counts, backup/restore readiness and rollback.

## Cross-cutting Risks

| Risk | Mitigation |
|---|---|
| Large branch becomes unreviewable | one behavior per atomic commit; full gate at each stage |
| SQLite lock/contention | short transactions, WAL, pagination, no model call inside transaction |
| AI behavior flakes tests | deterministic provider for contracts; live benchmark reported separately |
| Incomplete features leak publicly | safe-default feature flags and backend authorization |
| Prompt content overrides platform rules | fixed compiler hierarchy and injection tests |
| Runtime facts remain unavailable | continue local work; block only Stage 9 production mutation and label evidence honestly |
