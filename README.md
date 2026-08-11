# CourseMate AI

CourseMate AI is a complete learning application with two independent backends: a course-scoped RAG service that answers from uploaded materials with citations, and a Function Calling study agent that persists Todo tasks through five validated tools. The React interface connects both into one evidence-to-action workflow.

## What is ready

- 86 source files inventoried without modifying the originals.
- 66 supported PDF, DOCX, PPTX, Markdown, and text documents imported: 38 for CS3481 and 28 for GE2324.
- 1,936 retrievable chunks, all isolated by course; 20 legacy or data files remain inventory-only.
- Hybrid retrieval with SQLite FTS5, stored embeddings, reciprocal-rank fusion, citations, SSE streaming, and conversation persistence.
- Five strict task tools: create, search, update, complete, and delete.
- Responsive React pages for Home, QA, Study Plan, Documents, and About.
- Deterministic offline providers for repeatable tests and OpenAI Responses/Embeddings providers for production.

## Architecture at a glance

    React / Vite (5173)
      |-- HTTP + SSE --> FastAPI RAG API (8000) --> data/rag.sqlite3
      |                                      \--> OpenAI Responses + Embeddings
      \-- HTTP ------> Express Agent API (8001) -> data/agent.sqlite3
                                             \--> OpenAI Responses tool loop

Each backend owns its database. The browser never receives an OpenAI key and never writes SQLite directly.

## Prerequisites

- Node.js 24.14 or newer; Node 24.14 is the verified runtime and supplies the Agent's built-in SQLite API.
- Python 3.11 or newer; Python 3.12 is the verified runtime.
- Google Chrome for the configured Playwright acceptance suite.
- An OpenAI API key only for live model mode. Offline development and all automated tests use deterministic providers.

## Setup

From the repository root:

    Copy-Item .env.example .env
    python -m venv services/rag-api/.venv
    services/rag-api/.venv/Scripts/python.exe -m pip install -r services/rag-api/requirements-dev.txt
    npm ci

Add OPENAI_API_KEY to .env for live answers and agent chat. Keep RAG_PROVIDER_MODE=openai and AGENT_PROVIDER_MODE=openai in that case. For a credential-free local demo, set both to deterministic.

## Run locally

The helper launches all three processes in separate hidden windows:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_local.ps1

Then open http://localhost:5173. The health endpoints are http://localhost:8000/health and http://localhost:8001/health.

To run services manually:

    cd services/rag-api
    .venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000

    npm run dev:agent
    npm run dev:web

## Import the supplied corpus

The committed database already contains the verified local corpus. To rebuild it from the original, read-only D-drive sources:

    services/rag-api/.venv/Scripts/python.exe scripts/import_corpus.py --reset

The importer reads data/inventory/course-files.json, copies supported files to generated upload names, and writes data/inventory/import-report.json. It never edits or renames a source file. A SHA-256-bound transcription sidecar is used for the scanned assignment_2.pdf.

## Verify

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_inventory.ps1
    services/rag-api/.venv/Scripts/python.exe -m pytest services/rag-api/tests -q
    services/rag-api/.venv/Scripts/python.exe -m ruff check services/rag-api/app services/rag-api/tests scripts/import_corpus.py
    services/rag-api/.venv/Scripts/python.exe -m mypy services/rag-api/app scripts/import_corpus.py
    npm test
    npm run typecheck
    npm run build
    npm run test:e2e

The end-to-end suite uses real Chrome, the full RAG database, deterministic model providers, and a per-run task database. It checks course switching, cited streaming answers, answer-to-plan, tool-driven task creation, editing, completion, and 390 px mobile usability.

## Documentation

- docs/ARCHITECTURE.md — boundaries, runtime topology, trust model, and decisions.
- docs/RAG_PIPELINE.md — ingestion, retrieval, prompt, citations, and acceptance questions.
- docs/AGENT_PIPELINE.md — Responses tool loop and all five tools.
- docs/DATABASE_SCHEMA.md — both SQLite schemas and ownership rules.
- docs/API_REFERENCE.md — HTTP and SSE contracts.
- docs/DEPLOYMENT.md — Netlify + Render instructions and manual gates.
- docs/TECHNICAL_REFERENCES.md — official documentation and research foundations.
- docs/TROUBLESHOOTING.md — reproducible diagnosis paths.
- docs/VERIFICATION_REPORT.md — final corpus, test, security, build, and deployment-gate evidence.
- PROJECT_HANDOFF_FOR_CHATGPT.md — complete teaching and maintenance handoff.

## Privacy and production note

The repository contains local copies of private course materials under data/uploads so the requested local product is immediately usable. Do not publish those files or the populated database to a public repository without permission from the material owners. The provided Render blueprint creates empty persistent disks; production course upload is an explicit, authorized post-deploy step. The APIs are a single-user build without an identity layer, so authentication or platform access control is required before public internet exposure.
