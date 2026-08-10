# Spec: CourseMate AI

Status: approved baseline derived from the user's 2026-08-11 project brief. The brief explicitly authorizes ordinary technical choices without repeated confirmation; material scope changes still require approval.

## Objective

Build a portfolio-quality web application with two connected learning workflows:

1. **Course QA** ingests course documents, performs explainable keyword and vector retrieval scoped by `course_id`, streams a grounded OpenAI answer, and shows traceable citations.
2. **Study Agent** turns natural language into validated task CRUD tool calls, persists tasks, and presents them on a responsive task board.

Primary user: a student revising CS3481 and GE2324 who must also be able to study, reproduce, and explain the implementation in interviews.

## Product contract

### Routes

- `/` — CourseMate AI landing page.
- `/qa` and `/qa/:courseId` — course-scoped RAG chat, documents, upload, and indexing state.
- `/tasks` — natural-language agent and task board.
- `/documents` — cross-course document inventory and upload status.
- `/about` — architecture and portfolio explanation.

### RAG data flow

`source file -> loader -> cleaned page/slide sections -> paragraph-aware chunks -> OpenAI embedding -> SQLite + FTS5 -> keyword retrieval + vector retrieval -> reciprocal-rank fusion -> top-k context -> Responses API stream -> SSE -> React citations`

Required first-class loaders: PDF and Markdown. Required corpus importers when present: TXT, DOCX, PPTX. Legacy PPT is imported only when a safe local converter is available; otherwise it is reported as unsupported instead of silently skipped.

Each citation must include `courseId`, `documentId`, `chunkId`, filename, page/slide/section locator, and the displayed excerpt.

### Study Agent data flow

`React -> Node API -> OpenAI Responses API -> function_call -> JSON parse -> Ajv validation -> allow-listed server executor -> parameterized SQLite CRUD -> function_call_output -> OpenAI final response -> React`

The model never emits executable SQL and never receives database credentials. Tool call arguments and tool results are untrusted data.

Required tools: `createTask`, `searchTask`, `updateTask`, `completeTask`, and `deleteTask`. Destructive deletion through natural-language chat requires an explicit task match; ambiguous matches return a clarification response rather than guessing.

### Cross-module link

Every grounded QA answer exposes **Add to Study Plan**. The frontend sends the selected `courseId`, topic, and citation summary to the Study Agent as a task draft; the Node service remains the only component allowed to create the task.

## Tech stack

- Web: React + TypeScript + Vite; React Router; accessible semantic CSS without a heavyweight component framework.
- RAG service: Python 3.11+; FastAPI; Pydantic; SQLite `sqlite3` + FTS5; official OpenAI Python SDK; PyPDF, python-docx, and python-pptx for supported loaders.
- Agent service: Node.js 22+; TypeScript; Express; official OpenAI JavaScript SDK; Ajv; `better-sqlite3`.
- Tests: pytest, FastAPI TestClient/httpx, Vitest, Supertest, and Playwright.
- Persistence: separate `data/rag.sqlite3` and `data/agent.sqlite3` files locally. Stable `courseId` values form the cross-service contract.
- Deployment: static frontend plus two long-running services with persistent storage. Final provider choice is made from current official deployment documentation after local acceptance passes.

Dependency versions are pinned by generated lockfiles. The available verified runtimes are bundled Node 24.14.0, bundled Python 3.12.13, and local Python 3.11.0. Global `node` is 18.17.1 and is not the target runtime. Docker is currently unavailable.

## API contract

All JSON errors use:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable explanation",
    "details": {}
  }
}
```

Core RAG endpoints:

- `GET /health`
- `GET /api/courses?page=1&pageSize=50`
- `POST /api/courses`
- `GET /api/courses/{courseId}/documents?page=1&pageSize=50`
- `POST /api/courses/{courseId}/documents`
- `GET /api/ingestion-jobs/{jobId}`
- `POST /api/qa/chat` returning `text/event-stream`

Core Agent endpoints:

- `GET /health`
- `GET /api/tasks?page=1&pageSize=50&courseId=&status=`
- `POST /api/tasks`
- `PATCH /api/tasks/{taskId}`
- `DELETE /api/tasks/{taskId}`
- `POST /api/agent/chat`

SSE events are discriminated JSON payloads named `meta`, `delta`, `citation`, `done`, and `error`. No endpoint returns a success-shaped response on failure.

## Commands

Target commands that implementation must make real before completion:

```powershell
# RAG
cd services/rag-api
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# Agent
cd services/agent-api
npm ci
npm run typecheck
npm test
npm run dev

# Web
cd apps/web
npm ci
npm run typecheck
npm test
npm run dev

# End-to-end from repository root
npm run test:e2e
```

`docker compose up --build` is a documented optional path only after Docker configuration exists and has been validated. Until Docker is installed, native commands are the supported local path.

## Project structure

```text
apps/web/                  React + TypeScript UI
services/rag-api/          FastAPI RAG service
services/agent-api/        Node + TypeScript tool-calling service
data/inventory/            Generated, non-secret corpus inventory
data/                      Local runtime databases (gitignored)
docs/specs/                Product contract
docs/                      Architecture, APIs, pipelines, deployment
scripts/                   Reproducible inventory/import/dev helpers
tests/e2e/                 Cross-service Playwright tests
work/                      Disposable project-local scratch (gitignored)
```

## Code style

Python uses type hints and dependency-injected boundaries:

```python
def fuse_results(
    keyword_hits: list[SearchHit],
    vector_hits: list[SearchHit],
    *,
    top_k: int,
) -> list[SearchHit]:
    """Return course-scoped hits ranked by reciprocal-rank fusion."""
```

TypeScript uses strict types and validated boundaries:

```typescript
export interface ToolResult<T> {
  ok: boolean;
  data: T | null;
  error: { code: string; message: string } | null;
}
```

Conventions: `snake_case` in Python and database columns, `camelCase` in JSON/TypeScript, UTC ISO-8601 timestamps at API boundaries, no broad `any`, and parameterized SQL only.

## Testing strategy

- Unit: loaders, paragraph-aware chunking, cosine similarity, RRF, citations, task repository, every tool, Ajv rejection paths.
- API: health, course/document upload, QA SSE framing, tasks CRUD, agent chat validation, standard error envelope.
- Integration: real SQLite and deterministic fake OpenAI clients; course isolation; ingestion-to-retrieval; function-call-to-task persistence.
- Live integration: opt-in tests against the real OpenAI API when `OPENAI_API_KEY` is present; never run automatically in ordinary unit suites.
- E2E: Playwright covers landing, course switch, streamed answer/citation, task creation/update/completion, and QA-to-plan handoff.
- Security: file extension/MIME/size/name checks, prompt-injection fixture, invalid tool output, secret scan, dependency audit, CORS/header checks.

Tests must report a non-zero test count. Structural checks and semantic retrieval/answer checks are reported separately.

## Security boundaries

Trust boundaries: browser requests, uploaded files, local corpus documents, OpenAI responses/tool arguments, environment variables, and database rows crossing service boundaries.

Controls:

- Upload allowlist, 20 MiB default cap, safe generated storage names, content validation, duplicate SHA-256 detection.
- Per-course retrieval filter in both FTS and vector paths; cross-course hits are a test failure.
- Retrieved document text is delimited as untrusted reference material and never treated as system instructions.
- Strict tool schemas (`additionalProperties: false`) plus Ajv runtime validation and an allow-listed executor.
- Parameterized SQL, bounded model/tool loops, timeouts, output-token limits, restricted CORS, security headers, generic 500 responses, and secrets only from environment variables.

## Boundaries

Always:

- Preserve the six source directories read-only.
- Build vertical slices with tests before expansion.
- Keep SQLite real in local development.
- Keep RAG internals and tool execution visible and explainable.
- Update docs and verification evidence with each completed phase.

Ask first:

- Any paid cloud resource, public deployment that needs billing, or credential/OAuth action.
- Deleting user tasks outside the explicit API/tool request.
- Changing the approved technology stack or importing a third-party repository.

Never:

- Commit or print API keys.
- Modify source course files.
- Let model output execute as SQL, shell, HTML, or file paths.
- Claim real OpenAI or production verification without observed evidence.
- hide the RAG or agent core inside LangChain/LlamaIndex/Agents SDK.

## Success criteria

- CS3481 and GE2324 documents are ingested with course isolation and traceable metadata.
- PDF and Markdown upload work; available DOCX/PPTX course files are imported.
- Keyword, vector, and fused retrieval are independently testable and documented.
- A grounded QA response streams incrementally and renders expandable citations.
- Insufficient evidence produces the approved no-support message rather than invented course content.
- All five required tools use the same JSON Schema for OpenAI definitions and Ajv runtime validation.
- Task CRUD, filters, agent chat, and QA-to-plan handoff persist in SQLite and render in React.
- Unit, API, integration, and browser E2E suites pass with non-zero counts.
- Required documentation and `PROJECT_HANDOFF_FOR_CHATGPT.md` are complete and source-located.
- Local startup is reproducible. Public deployment and production smoke tests are complete, or explicitly marked `MANUAL ACTION REQUIRED` with exact blockers.

## Open questions tracked as risks, not blockers

- `D:\下载\tut7` and `D:\下载\tut8` are absent and no near-name directories were found. Import proceeds with the four present exports and records the gap.
- No Docker executable is installed. Native startup is the first supported path; Docker artifacts can still be built and statically validated.
- A real OpenAI key and cloud-provider login have not yet been established. Local deterministic tests proceed; live acceptance remains gated on credentials.

## Official OpenAI implementation sources

- Responses API recommendation: https://developers.openai.com/api/docs/guides/migrate-to-responses
- Streaming Responses: https://developers.openai.com/api/docs/guides/streaming-responses
- Function calling and strict schemas: https://developers.openai.com/api/docs/guides/function-calling
- Embeddings and cosine similarity: https://developers.openai.com/api/docs/guides/embeddings
