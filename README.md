# CourseMate AI

CourseMate AI combines a transparent course-document RAG pipeline with a natural-language study task agent in one React application.

## Current status

The repository contract and read-only course inventory are complete. RAG, Agent, and web vertical slices are implemented incrementally according to `docs/IMPLEMENTATION_PLAN.md`; this README is updated only with commands that exist and have been exercised.

## Repository map

```text
apps/web/              React + TypeScript frontend
services/rag-api/      Python + FastAPI RAG service
services/agent-api/    Node.js + TypeScript tool-calling service
data/inventory/        Reproducible source-file inventory
docs/                  Specifications, ADRs, and implementation guides
scripts/               Inventory, import, and local-development helpers
tests/e2e/             Browser-level acceptance tests
```

## Verified local toolchain

| Tool | Verified version | Note |
|---|---:|---|
| Bundled Node.js | 24.14.0 | Target runtime; satisfies current Vite requirements. |
| Global Node.js | 18.17.1 | Too old for the selected Vite release; do not use. |
| Bundled Python | 3.12.13 | Preferred for the project virtual environment. |
| Local Python | 3.11.0 | Available by explicit `C:\Python311\python.exe`. |
| Git | 2.54.0.windows.1 | Repository initialized on `main`. |
| Docker | unavailable | Native startup is the first supported path. |

## Inventory

The source scan is read-only. Regenerate and verify it with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\inventory.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_inventory.ps1
```

Observed baseline: 86 files, with 50 mapped to CS3481 and 36 mapped to GE2324. See `docs/COURSE_FILE_INVENTORY.md`.

## Configuration

Copy `.env.example` to `.env`, then set `OPENAI_API_KEY` for live OpenAI integration. Deterministic unit and integration tests do not require a key. The real key is never stored in source or printed by project commands.

## Source-backed decisions

- OpenAI Responses is the API used for new text and tool-calling flows: https://developers.openai.com/api/docs/guides/migrate-to-responses
- OpenAI streaming uses Responses SSE events: https://developers.openai.com/api/docs/guides/streaming-responses
- Vite setup and Node runtime requirements: https://vite.dev/guide/
- FastAPI tests use `TestClient`/HTTPX: https://fastapi.tiangolo.com/tutorial/testing/
- Express routing follows the Express 5 router contract: https://expressjs.com/en/5x/starter/basic-routing/

## Project contract

Read `docs/specs/PROJECT_SPEC.md` for acceptance criteria and `docs/IMPLEMENTATION_PLAN.md` for the ordered Build → Run → Test → Fix → Commit workflow.
