# Architecture

## System context

    Student browser
      |
      +-- /qa and /documents -- HTTP + SSE --> FastAPI RAG service
      |                                          |-- loaders and chunker
      |                                          |-- FTS5 + embedding retrieval
      |                                          |-- grounded answer stream
      |                                          \-- RAG-owned SQLite
      |
      \-- /tasks ---------------- HTTP --------> Express Agent service
                                                 |-- Responses reasoning loop
                                                 |-- strict tool validator/executor
                                                 \-- Agent-owned SQLite

The frontend coordinates one cross-service action: an answered question and its first citation are converted to a task request sent to the Agent API. There is no browser-side database and no browser-side OpenAI secret.

## Responsibilities

### React web

Owns routing, presentation, form state, accessible feedback, SSE parsing, and client-side orchestration. The main integration points are apps/web/src/services/ragApi.ts and apps/web/src/services/agentApi.ts.

### FastAPI RAG service

Owns course and document records, upload validation, extraction, chunking, embeddings, FTS synchronization, hybrid retrieval, context construction, answers, citations, and conversation/message persistence. Every retrieval operation requires a course_id and filters both keyword and vector candidates before fusion.

### Express Agent service

Owns tasks and the natural-language tool loop. Model output is never executed directly: services/agent-api/src/tools/validator.ts checks the exact strict schema and services/agent-api/src/tools/executor.ts dispatches only allow-listed functions to a parameterized repository.

## Runtime data flow

    original files (read only)
        -> inventory JSON
        -> import/upload validation
        -> safe generated copies
        -> extracted located blocks
        -> paragraph-aware chunks
        -> embedding JSON + FTS5 rows

    courseId + question
        -> FTS5 keyword candidates
        -> cosine vector candidates
        -> reciprocal-rank fusion
        -> bounded, labelled context
        -> Responses stream
        -> text deltas + citations + done event
        -> conversations/messages

    natural-language study request
        -> Responses function_call
        -> Ajv strict validation
        -> allow-listed executor
        -> SQLite transaction
        -> function_call_output
        -> final model response

## Service-owned SQLite

data/rag.sqlite3 and data/agent.sqlite3 deliberately have different owners. This prevents cross-runtime migrations and lock ownership. A stable lowercase course_id is duplicated across services, while answer-to-plan uses an HTTP call rather than a cross-database write. See docs/decisions/ADR-001-service-owned-sqlite.md.

## Retrieval strategy

SQLite FTS5/BM25 supplies exact-term recall; stored embeddings and cosine similarity supply semantic recall. Reciprocal-rank fusion combines positions instead of attempting to normalize unrelated score scales. JSON vectors and an application scan are intentionally transparent at this corpus size. A vector index becomes justified only after measured latency or corpus growth crosses an agreed threshold.

## Provider modes

- openai: official Python/JavaScript OpenAI SDKs, Responses API, configurable chat/embedding models, and an optional trusted `OPENAI_BASE_URL` for OpenAI-compatible providers.
- deterministic: stable local embeddings, extractive answers, and a constrained task-intent parser. This is a test/demo provider, not a hidden mock database.

Provider selection is environment configuration. When `OPENAI_BASE_URL` is unset or empty, both SDKs use their original OpenAI endpoint; otherwise both backends use the configured compatible endpoint. Business logic, Responses streaming, Function Calling, authentication, and API contracts remain the same.

## Trust boundaries

| Boundary | Primary risk | Control |
|---|---|---|
| Upload | oversized, disguised, corrupt, duplicate, path traversal | byte limit, extension/signature checks, loader errors, SHA-256 uniqueness, generated storage names |
| Course text | prompt injection in untrusted material | delimited source context, instruction hierarchy, explicit evidence-only prompt, citations |
| Retrieval | cross-course leakage | mandatory course_id in both candidate paths plus repository filters |
| Model tools | arbitrary function or malformed arguments | five strict schemas, Ajv, no dynamic evaluation, bounded rounds |
| SQL | injection or corrupted state | parameterized statements, CHECK constraints, transactions, foreign keys |
| Browser/API | malformed input, XSS, secret exposure | Pydantic/Ajv validation, React escaping, CORS allow-list, security headers, server-only key |
| Deployment | ephemeral SQLite data | paid persistent disks mounted at /var/data; single instance per disk |

## Failure behavior

- No relevant context: the RAG service returns an evidence-insufficient answer and no invented citation.
- Loader/embedding failure: the job and document become failed with a user-readable message; existing data remains intact.
- Invalid tool call: the model receives a structured error; no repository mutation occurs.
- Tool-round limit: the Agent terminates with an explicit error instead of looping indefinitely.
- Missing OpenAI key: regular CRUD and deterministic mode continue; live model operations return a controlled configuration error.

## Deployment topology

Netlify hosts the static Vite site. Render hosts two long-lived services, each on a paid Starter instance with its own persistent disk. Netlify receives only public API base URLs. Render receives the model-provider key under `OPENAI_API_KEY`, optional compatible endpoint configuration, and the exact Netlify origin. Private source documents are uploaded only after authorization.
