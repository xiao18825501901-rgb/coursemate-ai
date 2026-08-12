# Spec: OpenAI-Compatible Model Endpoints

## Objective

Allow both backend services to use either OpenAI's default API endpoint or an operator-supplied OpenAI-compatible endpoint without changing the RAG, Responses streaming, or Function Calling contracts. The production deployment target is Alibaba Cloud Model Studio in Singapore.

## Tech Stack

- FastAPI/Python with the official `openai` SDK for embeddings and grounded Responses streaming.
- Express/TypeScript with the official `openai` SDK for the Responses Function Calling loop.
- Pydantic Settings and process environment variables for server-only configuration.

## Commands

- RAG tests: `services/rag-api/.venv/Scripts/python.exe -m pytest services/rag-api/tests -q`
- RAG lint: `services/rag-api/.venv/Scripts/python.exe -m ruff check services/rag-api/app services/rag-api/tests scripts/import_corpus.py`
- RAG types: `services/rag-api/.venv/Scripts/python.exe -m mypy services/rag-api/app scripts/import_corpus.py`
- JavaScript tests: `npm test`
- JavaScript types: `npm run typecheck`
- JavaScript builds: `npm run build`

## Project Structure

- `services/rag-api/app` — RAG configuration and OpenAI-compatible adapters.
- `services/rag-api/tests` — provider configuration and ingestion batching tests.
- `services/agent-api/src` — Agent configuration and Responses adapter.
- `services/agent-api/test` — configuration, client injection, and Function Calling regression tests.
- `docs` and root configuration files — operator guidance and Render target values.

## Code Style

Only pass a custom endpoint when it is non-empty, preserving each SDK's default otherwise:

```python
client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
```

## Testing Strategy

- Use fake SDK constructors and injected clients; never make real or paid API calls.
- Prove configured and empty endpoint behavior in both runtimes.
- Ingest more than ten chunks and prove every embedding call has at most ten inputs while the result count remains exact.
- Keep the existing deterministic, auth-isolation, Function Calling, frontend, lint, typecheck, and build suites green.

## Boundaries

- Always: retain `OPENAI_API_KEY`, `OPENAI_CHAT_MODEL`, and `OPENAI_EMBEDDING_MODEL`; keep secrets server-only; preserve client injection.
- Ask first: database changes, authentication changes, dependency changes, or a different production provider.
- Never: read or commit a real provider key, send a real model request, modify `/etc/coursemate/*.env`, remove OpenAI support, or weaken Clerk/user isolation.

## Success Criteria

- `OPENAI_BASE_URL` unset or empty uses the original OpenAI SDK default.
- A non-empty `OPENAI_BASE_URL` reaches RAG embeddings, RAG answers, and Agent Responses clients.
- Embedding ingestion batches are capped at 10 and retain exact ordering/count.
- Responses streaming and the existing Function Calling loop remain unchanged.
- Render targets the supplied Singapore workspace URL, `qwen3.7-plus`, and `text-embedding-v4`; the API key remains an unset secret.
- All required offline verification gates pass with no credential in source, tests, docs, logs, or build output.

## Open Questions

None. The supplied implementation brief defines the endpoint, models, compatibility behavior, and security boundaries.
