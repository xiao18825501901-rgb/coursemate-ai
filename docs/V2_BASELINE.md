# CourseMate AI V2 Baseline

Captured: 2026-08-13, Asia/Shanghai.

## Git Baseline

| Field | Value |
|---|---|
| `V2_BASELINE_COMMIT` | `e1ef57a18bb26facf26a3568a7cd5ae1d5ea7ee5` |
| Commit message | `feat: support OpenAI-compatible model endpoints` |
| Source branch at capture | `main` |
| V2 development branch | `feature/coursemate-v2-ai-tutor` |
| Remote observation | `origin/main` pointed to the baseline commit |
| Preserved unrelated worktree items | untracked `ACTUAL_IMPLEMENTED_CHANGES_AUDIT.md` and `curl`; neither is part of this baseline |

## Source Architecture

```text
React/Vite/Clerk frontend
  -> FastAPI RAG API -> RAG SQLite + uploads -> OpenAI SDK compatible chat/embedding
  -> Express Agent API -> Agent SQLite -> OpenAI Responses Function Calling
```

The services independently verify Clerk sessions. Conversations and tasks have owner IDs. Shared course reads require authentication; shared corpus mutation requires an administrator. RAG and Agent model calls have separate per-user SQLite minute windows.

## V2 Baseline Database Schema

### RAG source schema

| Table | Important baseline fields |
|---|---|
| `courses` | `id`, `name`, `description`, `created_at` |
| `documents` | course, server path, MIME/extension/hash, status, chunk count, timestamps |
| `ingestion_jobs` | document, status, processed count, error, timestamps |
| `chunks` | document/course, ordinal, content, locator type/value, section, embedding |
| `chunks_fts` | content, chunk ID, course ID |
| `conversations` | `id`, `owner_user_id`, `course_id`, timestamps |
| `messages` | conversation, role, content, citation JSON, timestamp |
| `rate_limit_windows` | verified owner, action, minute window, count |
| `schema_migrations` | version, name, applied timestamp |

RAG migration version 1 is `conversation ownership and per-user limits`.

### Agent source schema

| Table | Important baseline fields |
|---|---|
| `tasks` | `owner_user_id`, title/notes/course/status/priority/due date/citation/timestamps |
| `rate_limit_windows` | verified owner, action, minute window, count |
| `schema_migrations` | version, name, applied timestamp |

Agent migration version 1 is `task ownership and per-user limits`.

### Inspected local ignored RAG data

| Measure | Value |
|---|---:|
| Database size | 4,448,256 bytes |
| Courses | 2 |
| Documents | 66 |
| Chunks | 1,936 |
| Conversations | 8 |
| Messages | 16 |
| Rate-limit windows | 1 |
| Migration rows | 1 |

This is local runtime data, not a production snapshot. The local Agent database was not present at baseline capture.

## Current API Baseline

### RAG

```text
GET  /health
POST /api/courses                         admin
GET  /api/courses                         signed-in
GET  /api/courses/{courseId}/documents    signed-in
POST /api/courses/{courseId}/documents    admin
GET  /api/ingestion-jobs/{jobId}          admin
GET  /api/conversations/{conversationId}  owner
POST /api/qa/chat                         signed-in, SSE
```

The QA request contains `courseId` and `question` only. Every call starts a new conversation. The SSE `meta` event exposes the new conversation ID, but the React page does not retain it for continuation.

### Agent

The Agent provides authenticated owner-scoped task CRUD and a bounded strict Function Calling chat endpoint. Its baseline behavior and JSON Schemas are protected as V2 regressions.

## Provider and Model Baseline

Source defaults:

```text
RAG/Agent provider mode: openai
OpenAI-compatible base URL: optional
Chat model default: gpt-5.6-luna
Embedding model default: text-embedding-3-small
```

Tracked `render.yaml` selects an Alibaba Model Studio Singapore compatible endpoint, `qwen3.7-plus`, and `text-embedding-v4`. This is configuration evidence, not proof of current production runtime.

## Environment Variable Names

No values are recorded.

```text
OPENAI_API_KEY
OPENAI_BASE_URL
OPENAI_CHAT_MODEL
OPENAI_EMBEDDING_MODEL
RAG_PROVIDER_MODE
AGENT_PROVIDER_MODE
WEB_ORIGIN
VITE_RAG_API_URL
VITE_AGENT_API_URL
VITE_CLERK_PUBLISHABLE_KEY
CLERK_PUBLISHABLE_KEY
CLERK_SECRET_KEY
CLERK_JWT_KEY
ADMIN_USER_IDS
RAG_DATABASE_PATH
RAG_UPLOAD_DIR
CHUNK_SIZE
CHUNK_OVERLAP
TOP_K
MAX_UPLOAD_BYTES
MAX_CONTEXT_CHARS
RAG_QA_REQUESTS_PER_MINUTE
AGENT_DATABASE_PATH
AGENT_PORT
AGENT_MAX_TOOL_ROUNDS
AGENT_CHAT_REQUESTS_PER_MINUTE
APP_ENV
```

## Existing Features to Preserve

- CS3481 and GE2324 course selection and indexed source display.
- Markdown/text/PDF/PPTX/DOCX loading supported by the current loaders.
- Keyword + vector hybrid retrieval, course filtering, context budget, SSE and citations.
- Clerk browser session and independent Bearer verification in both APIs.
- Owner-isolated conversations and tasks.
- Admin-only shared corpus mutation.
- Strict five-tool task Agent with JSON Schema validation and persistent CRUD.
- Per-user model-call rate limits and exact-origin CORS.

## V2 Baseline Production Status

| Claim | Status at capture |
|---|---|
| `https://qqttai.com` and API health | UNKNOWN — connection could not be established from this execution environment |
| Netlify/Render files in Git | VERIFIED as tracked configuration |
| Alibaba Cloud HK/Caddy/systemd/UFW runtime | UNKNOWN — no report/server evidence available |
| Clerk Production runtime | UNKNOWN from runtime; source implementation verified |
| Live provider/models | UNKNOWN |
| Live database/upload counts | UNKNOWN |
| Current backup/restore/monitoring/rollback | UNKNOWN |

Production deployment is gated on redacted runtime inspection and a restorable backup. Local implementation may proceed independently.
