# Implementation Plan: CourseMate AI

## Overview

The project is delivered as independently verifiable vertical slices. High-risk facts—local document parsing, SQLite FTS5 support, current OpenAI tool calling, and course isolation—are tested before broad UI work.

## Dependency graph

```text
Environment + inventory
        |
Repository contracts + config
        |
        +--> RAG schema -> loaders/chunks -> embeddings/retrieval -> streaming API
        |
        +--> Agent schema -> task repository -> JSON Schema tools -> OpenAI loop
        |
        +--> React shell -> QA UI + Task UI -> QA-to-plan handoff
                                      |
                              corpus import + E2E
                                      |
                             docs -> deploy -> smoke test
```

## Architecture decisions

- Two service-owned SQLite files keep Python and Node migrations independent; `courseId` is the explicit interoperability key.
- SQLite FTS5 implements lexical retrieval, plain stored float arrays implement understandable vector search, and reciprocal-rank fusion avoids incomparable raw BM25/cosine scales.
- Responses API is used directly in both languages; no agent/RAG orchestration framework hides the loops.
- Real OpenAI calls sit behind typed interfaces so unit and E2E tests can be deterministic without fabricating a live verification result.
- POST streaming uses `fetch()` with a readable SSE response because browser `EventSource` cannot POST a JSON question.

## Phase 0: Evidence and foundation

### Task 0.1 — Persist environment and corpus inventory

Acceptance:

- A reproducible read-only inventory script records every source file, extension, size, mapped course, and source path.
- Missing `tut7`/`tut8` are explicit; no source file is changed.

Verification: run the script twice and compare deterministic JSON/CSV counts.

Files: `scripts/inventory.ps1`, `data/inventory/course-files.json`, `docs/COURSE_FILE_INVENTORY.md`.

### Task 0.2 — Scaffold monorepo contracts

Acceptance:

- Root scripts, environment template, directory layout, and service READMEs exist.
- Secrets, dependencies, databases, uploads, and build artifacts are ignored.

Verification: Git status contains only intended source/config; secret scan is empty.

Files: `package.json`, `.env.example`, `.gitignore`, `README.md`, `docs/ARCHITECTURE.md`.

### Checkpoint 0

- Inventory counts reconcile with the source scan.
- Root repository has an atomic foundation commit.

## Phase 1: Minimum RAG vertical slice

### Task 1.1 — RAG configuration and schema

Acceptance:

- Typed settings expose chunk size, overlap, top-k, models, paths, limits, and CORS.
- SQLite tables and FTS5 initialization pass an isolated database test.

Verification: `pytest tests/test_database.py -q` executes non-zero tests.

Files: `app/config.py`, `app/db.py`, `app/models.py`, `tests/test_database.py`.

### Task 1.2 — Paragraph-aware chunker

Acceptance:

- Paragraphs are preserved when possible, oversized paragraphs split safely, overlap is deterministic, and metadata survives.
- Invalid chunk settings fail clearly.

Verification: failing tests first, then `pytest tests/test_chunking.py -q` passes.

Files: `app/rag/chunking.py`, `app/rag/types.py`, `tests/test_chunking.py`.

### Task 1.3 — PDF and Markdown loaders

Acceptance:

- A real local PDF and a Markdown fixture produce page/section metadata.
- Empty, corrupt, and unsupported files return typed errors.

Verification: `pytest tests/test_loaders.py -q` passes with real fixture sampling.

Files: `app/rag/loaders.py`, `app/rag/errors.py`, `tests/test_loaders.py`, `tests/fixtures/sample.md`.

### Task 1.4 — Embeddings and hybrid retrieval

Acceptance:

- OpenAI embedding adapter, deterministic test adapter, cosine scoring, FTS5 keyword scoring, and RRF are separate functions.
- Every query filters by `course_id`; empty results remain empty.

Verification: `pytest tests/test_retrieval.py -q` covers keyword, vector, fusion, isolation, and empty paths.

Files: `app/rag/embeddings.py`, `app/rag/retrieval.py`, `app/repositories/chunks.py`, `tests/test_retrieval.py`.

### Task 1.5 — Ingestion API

Acceptance:

- Course creation and document upload store document/chunk metadata, embeddings, FTS rows, duplicate hashes, and job state.
- PDF/Markdown upload boundaries enforce extension, size, name, and content checks.

Verification: `pytest tests/test_ingestion_api.py -q` passes against temporary SQLite/upload paths.

Files: `app/services/ingestion.py`, `app/api/courses.py`, `app/api/documents.py`, `tests/test_ingestion_api.py`.

### Task 1.6 — Grounded streaming QA

Acceptance:

- Context construction delimits untrusted documents, enforces size limits, and includes stable source labels.
- `/api/qa/chat` emits valid `meta/delta/citation/done` SSE; no-support and OpenAI failure paths are observable.

Verification: `pytest tests/test_qa_api.py -q` passes with a deterministic streamed model.

Files: `app/rag/prompt.py`, `app/services/qa.py`, `app/api/qa.py`, `tests/test_qa_api.py`.

### Checkpoint 1

- One real PDF completes `parse -> chunk -> index -> retrieve -> answer -> citation` locally.
- Full RAG suite, lint, and type checks pass.

## Phase 2: Minimum Function Calling vertical slice

### Task 2.1 — Agent configuration and task schema

Acceptance:

- Task schema covers all required fields and constraints.
- Repository supports create/list/get/update/complete/delete with parameterized queries.

Verification: `npm test -- task-repository` passes with isolated SQLite.

Files: `src/config.ts`, `src/db.ts`, `src/types.ts`, `test/task-repository.test.ts`.

### Task 2.2 — Strict tool schemas and Ajv validation

Acceptance:

- One schema source defines all five OpenAI tools and runtime validators.
- `additionalProperties` and malformed dates/IDs are rejected.

Verification: `npm test -- tool-schemas` executes valid and invalid cases.

Files: `src/tools/schemas.ts`, `src/tools/validator.ts`, `test/tool-schemas.test.ts`.

### Task 2.3 — Server tool executor

Acceptance:

- Allow-listed dispatch executes all CRUD tools and returns typed `ToolResult` values.
- Unknown tools, missing tasks, and ambiguous searches never mutate data.

Verification: `npm test -- tool-executor` passes for every required tool.

Files: `src/tools/executor.ts`, `src/repositories/tasks.ts`, `src/errors.ts`, `test/tool-executor.test.ts`.

### Task 2.4 — Responses API tool loop

Acceptance:

- The service sends strict tools, validates returned arguments, executes server code, sends `function_call_output`, and bounds iterations.
- A deterministic fake proves `createTask -> SQLite -> final response` without bypassing the loop.

Verification: `npm test -- agent-service` passes.

Files: `src/openai/client.ts`, `src/services/agent.ts`, `src/openai/types.ts`, `test/agent-service.test.ts`.

### Task 2.5 — Agent and task REST API

Acceptance:

- REST CRUD, filters/pagination, and `/api/agent/chat` expose consistent typed errors.
- Security headers, limits, and explicit CORS are enabled.

Verification: `npm test -- api` and `npm run typecheck` pass.

Files: `src/app.ts`, `src/routes/tasks.ts`, `src/routes/agent.ts`, `test/api.test.ts`.

### Checkpoint 2

- Natural language produces a validated `createTask` and persisted board row through the actual orchestration code.
- Agent unit/API suites and dependency audit pass.

## Phase 3: Unified React experience

### Task 3.1 — Web foundation and design system

Acceptance:

- Vite/React routes, API configuration, responsive shell, typography, color tokens, focus states, and error boundary work.

Verification: unit smoke test, typecheck, and production build pass.

Files: `src/main.tsx`, `src/App.tsx`, `src/styles.css`, `src/types/api.ts`, `vite.config.ts`.

### Task 3.2 — Landing and navigation

Acceptance:

- Home exposes Course QA and Study Agent cards; navigation works on desktop and mobile.
- About explains the two real backend flows.

Verification: component tests and keyboard navigation check pass.

Files: `src/pages/HomePage.tsx`, `src/pages/AboutPage.tsx`, `src/components/Layout.tsx`, `src/App.test.tsx`.

### Task 3.3 — Course QA interface

Acceptance:

- Course selector, chat history, POST SSE streaming, expandable citations, document list/upload, and indexing status work.
- Loading, no-support, disconnected, and validation errors are readable.

Verification: mocked component/integration tests plus browser stream inspection pass.

Files: `src/pages/QaPage.tsx`, `src/services/ragApi.ts`, `src/hooks/useQaStream.ts`, `src/components/CitationList.tsx`, `src/pages/QaPage.test.tsx`.

### Task 3.4 — Study Agent and task board

Acceptance:

- Chat and CRUD board share fresh state; course/status filters and due-date editing work responsively.

Verification: component/API integration tests cover create, update, complete, delete, and filters.

Files: `src/pages/TasksPage.tsx`, `src/services/agentApi.ts`, `src/components/TaskBoard.tsx`, `src/components/AgentChat.tsx`, `src/pages/TasksPage.test.tsx`.

### Task 3.5 — QA-to-plan handoff

Acceptance:

- A citation-backed topic can be sent as a task draft and appears on the board after confirmed server creation.

Verification: React integration test and Playwright happy path pass.

Files: `src/components/AddToPlan.tsx`, `src/pages/QaPage.tsx`, `src/pages/TasksPage.tsx`, `tests/e2e/handoff.spec.ts`.

### Checkpoint 3

- Responsive browser walkthrough completes both product flows.
- Accessibility, console, and network checks show no blocking issue.

## Phase 4: Corpus, full verification, and documentation

### Task 4.1 — DOCX/PPTX/TXT import and full corpus ingestion

Acceptance:

- Present supported files import with page/slide/section metadata and per-file outcomes.
- CS3481 and GE2324 counts and failures are summarized; course isolation tests use real imported samples.

Verification: importer tests plus inventory-to-ingestion reconciliation pass.

Files: `app/rag/loaders.py`, `scripts/import_courses.py`, `data/inventory/import-report.json`, `tests/test_corpus_import.py`.

### Task 4.2 — Cross-service integration and E2E suite

Acceptance:

- Health, QA/citations/course switch, agent create/update/complete, and handoff pass through running services.
- Test questions verify expected course sources and reject cross-course citations.

Verification: full pytest, Node, web, and Playwright commands report non-zero passing counts.

Files: `tests/e2e/qa.spec.ts`, `tests/e2e/tasks.spec.ts`, `playwright.config.ts`, `scripts/dev.ps1`.

### Task 4.3 — Required engineering documentation

Acceptance:

- Every required document exists, matches actual commands/files, and links decisions to implementation.
- Handoff includes architecture, complete tree, both data flows, schema/API, 50 terms, lessons, exercises, bugs, interview questions, decisions, and zero-to-rebuild instructions.

Verification: documented commands are executed; links and file references are sampled against the repository.

Files: the required files under `docs/`, `README.md`, and `PROJECT_HANDOFF_FOR_CHATGPT.md` in focused documentation commits.

### Task 4.4 — Security and quality review

Acceptance:

- Secret scan, dependency audit, upload/tool abuse tests, CORS/header checks, lint/typecheck/build, and self-review pass.
- Known limitations are documented rather than hidden.

Verification: quality gate report records exact commands, counts, and outcomes.

Files: `docs/SECURITY.md`, `docs/VERIFICATION.md`, focused tests/fixes only.

### Checkpoint 4 — STEP 1 complete

- All local acceptance criteria pass with evidence.
- Real OpenAI tests pass if a key is available; otherwise the credential gate is explicit and STEP 2 does not pretend success.

## Phase 5: Deploy and verify

### Task 5.1 — Select and prepare production topology

Acceptance:

- Current official provider docs support the chosen runtime, persistent storage, secrets, CORS, and health checks.
- Deployment docs include storage, migrations, rollback, and cost/login prerequisites.

Verification: production builds and configuration validation pass locally.

### Task 5.2 — Deploy services and frontend

Acceptance:

- Public URLs are produced only from authenticated provider actions.
- Secrets are stored in provider secret managers, never source files.

Verification: provider status and all `/health` URLs are observed.

### Task 5.3 — Production smoke and browser verification

Acceptance:

- Real QA streaming/citations and Agent create/update flows pass on production.
- Failures produce `MANUAL ACTION REQUIRED` with exact steps and no fabricated checkmarks.

Verification: timestamped smoke evidence and browser observations are recorded in `docs/VERIFICATION.md`.
## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Global Node 18 is old | Build failure | Use bundled Node 24.14.0; declare engines and document PATH command. |
| Python launcher is misconfigured | Startup confusion | Use explicit Python 3.11 or bundled 3.12 path to create the project venv. |
| Docker absent | No compose runtime validation | Make native startup first-class; validate Compose statically and report runtime gap. |
| PPT legacy parsing | Some corpus files skipped | Detect LibreOffice; convert copies only if available; record per-file outcomes. |
| OpenAI key absent | No live semantic acceptance | Deterministic adapters prove orchestration; live gate remains incomplete until key exists. |
| SQLite production persistence | Data loss on ephemeral hosts | Require a persistent volume or documented production adapter; keep local SQLite. |
| Prompt/tool injection | Unsafe mutation or false answers | Delimit corpus text, validate model output, allow-list tools, parameterize SQL, bound loops. |
