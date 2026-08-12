# CourseMate AI

CourseMate AI is a multi-user learning application with Clerk authentication, a shared read-only course corpus, private cited conversations, and owner-isolated Todo tasks. Two independently verified backends connect the React interface into one evidence-to-action workflow.

## What is ready

- 86 source files inventoried without modifying the originals.
- 66 supported PDF, DOCX, PPTX, Markdown, and text documents imported: 38 for CS3481 and 28 for GE2324.
- 1,936 retrievable chunks, all isolated by course; 20 legacy or data files remain inventory-only.
- Hybrid retrieval with SQLite FTS5, stored embeddings, reciprocal-rank fusion, citations, SSE streaming, and conversation persistence.
- Five strict task tools: create, search, update, complete, and delete.
- Responsive React pages for Home, QA, Study Plan, Documents, and About.
- Deterministic offline providers for repeatable tests and OpenAI Responses/Embeddings providers for production.
- Clerk verification in both backends, owner-scoped tasks/conversations, admin-only corpus mutation, and per-user AI limits.

## Architecture at a glance

    React / Vite + Clerk (5173)
      |-- Bearer + SSE -> FastAPI RAG API (8000) --> data/rag.sqlite3
      |                                      \--> OpenAI Responses + Embeddings
      \-- Bearer -----> Express Agent API (8001) -> data/agent.sqlite3
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

Create a Clerk application, then set `VITE_CLERK_PUBLISHABLE_KEY`, `CLERK_PUBLISHABLE_KEY`, and `CLERK_SECRET_KEY`. Add `OPENAI_API_KEY` for live answers and agent chat. `ADMIN_USER_IDS` is a comma-separated allowlist of Clerk user IDs that may mutate the corpus. Automated browser tests use a fixed adapter accepted only in test + deterministic mode.

## Run locally

The helper launches all three processes in separate hidden windows:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_local.ps1

Then open http://localhost:5173. The health endpoints are http://localhost:8000/health and http://localhost:8001/health.

To run services manually:

    cd services/rag-api
    .venv/Scripts/python.exe -m uvicorn app.main:create_app --factory --reload --port 8000

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

## Security and production note

The repository contains local copies of private course materials under data/uploads. Do not publish them or the populated database without permission. The Render blueprint creates empty persistent disks; an allowlisted administrator must perform production ingestion. Clerk and OpenAI secrets belong only in backend secret stores; the browser receives only the Clerk publishable key. Deployment still requires the owner to create accounts, approve paid storage, set secrets, seed authorized data, and run production smoke tests.
