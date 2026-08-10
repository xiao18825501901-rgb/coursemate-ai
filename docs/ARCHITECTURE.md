# Architecture

## System context

```text
Browser / React
├── Course QA ──HTTP + SSE──> FastAPI RAG service
│                              ├── document loaders
│                              ├── paragraph-aware chunker
│                              ├── SQLite FTS5 + stored embeddings
│                              ├── explicit hybrid ranker
│                              └── OpenAI Responses + Embeddings APIs
│
└── Study Agent ──HTTP──────> Node/TypeScript Agent service
                               ├── strict JSON Schema tools
                               ├── Ajv validator + allow-listed executor
                               ├── SQLite task repository
                               └── OpenAI Responses tool loop
```

The browser coordinates the lightweight cross-module link: a grounded QA citation becomes a task draft sent to the Agent service. The frontend never writes either database directly.

## Service boundaries

### Web

Owns presentation, browser routing, local interaction state, SSE parsing, accessibility, and user-readable errors. It does not contain retrieval, task mutation, secret, or OpenAI logic.

### RAG API

Owns courses, documents, ingestion, chunks, embeddings, keyword/vector retrieval, context construction, conversations, citations, and streamed grounded answers. Every retrieval query requires `course_id`.

### Agent API

Owns task persistence and the tool-calling loop. OpenAI can propose one of five allow-listed actions; only validated server functions can execute CRUD.

## Data ownership

- `data/rag.sqlite3`: `courses`, `documents`, `chunks`, `chunks_fts`, `ingestion_jobs`, `conversations`, and `messages`.
- `data/agent.sqlite3`: `tasks` and agent conversation/audit records.
- Shared value: normalized lowercase `course_id` such as `cs3481` or `ge2324`.

Separate databases keep migrations and transactions service-owned. The trade-off is deliberate duplication of stable course identifiers; no distributed transaction is required because QA-to-plan is an ordinary Agent API call.

## Retrieval decision

SQLite FTS5 provides explainable lexical search. Embeddings are stored as JSON float arrays for the portfolio-scale corpus and scored in application code with cosine similarity. Reciprocal-rank fusion combines the result ranks, avoiding misleading normalization between BM25 and cosine score ranges.

This first version favors inspectability over a specialized vector database. A future vector adapter can replace the scan behind the same typed interface if measured corpus size or latency requires it.

## OpenAI decision

Both services use the official SDK and Responses API. RAG uses `responses.create(..., stream=True)` after locally constructing context; the Agent consumes `function_call` items, validates arguments with the exact schemas supplied to OpenAI, executes server code, and returns `function_call_output` items for the final natural-language response.

Default models are configuration, not hard-coded behavior: `gpt-5.6-luna` for cost-sensitive text/tool work and `text-embedding-3-small` for embeddings. Live model availability is verified only when credentials are present.

## Trust boundaries and controls

| Boundary | Risk | Control |
|---|---|---|
| File upload | oversized, corrupt, disguised, duplicate file | size/type/content checks, safe generated name, SHA-256, isolated upload directory |
| Course corpus | prompt injection or poisoned text | delimiter and explicit untrusted-data instruction; citations; course partition |
| OpenAI output | invalid arguments or unsafe action | strict JSON Schema, Ajv, allow-listed tools, bounded rounds, parameterized SQL |
| Browser input | malformed requests or XSS | server validation, React escaping, structured errors, limits |
| Environment | leaked API key | `.env` only, ignore rules, secret scan, no logging |

## Deployment constraints

The local contract uses real SQLite. Production must run the Python and Node services as long-lived processes with persistent volumes or use an explicitly documented storage adapter. The static React site may deploy independently. No production topology is accepted until current provider documentation and real health/browser checks confirm persistence and connectivity.

## Decisions

- `docs/decisions/ADR-001-service-owned-sqlite.md` — service-owned SQLite databases.
- Additional ADRs are added when retrieval fusion, API transport, or production storage decisions become expensive to reverse.
