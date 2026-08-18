# CourseMate AI V2 Architecture

## Delivered platform

CourseMate V2 evolves the original two-course RAG demo additively. The React/Vite application still
uses Clerk and the independent FastAPI RAG and Express Agent services. V2 adds a teaching
orchestrator, durable course-bound conversations, private user courses, versioned teaching profiles,
and moderated community publication without moving task data into the RAG database.

```text
React / Vite / Clerk
  |-- Course Center, History, Tutor, Settings, Publication Review
  |       -> FastAPI RAG API
  |            -> access policy -> SQLite RAG data + server-owned uploads
  |            -> router -> rewrite -> exact/hybrid retrieval -> tutor prompt
  |            -> OpenAI-compatible chat and embedding boundaries
  |
  `-- Study Plan -> Express Agent API -> strict tool dispatcher -> Agent SQLite
                                      -> OpenAI Responses-compatible tool model
```

## Trust boundaries

- The browser sends a Clerk bearer token; both APIs verify identity independently.
- Owner and administrator IDs are derived server-side and are never trusted from request bodies.
- `require_course_access` is the canonical course policy: public reads, owner reads/writes,
  administrator reads/writes, and existence-hiding 404s for foreign private resources.
- Published community courses are read-only to their owner until an administrator unpublishes them.
  This prevents reviewed content from being silently replaced after approval.
- Uploaded filenames are metadata only. The server generates stored paths and enforces extension,
  size, ownership and safe-deletion boundaries.
- Retrieved documents, history, custom teaching requirements and provider responses are untrusted.
  Platform/security and citation rules stay above all of them in the prompt hierarchy.
- Secrets remain backend-only. Responses exclude owner/reviewer IDs and never include stored paths.

## Tutor data flow

```text
question + course + optional conversation
  -> authenticated course/conversation authorization
  -> language preference and deterministic intent
  -> bounded history-aware standalone query
  -> exact structured locator, otherwise course-scoped hybrid retrieval
  -> bounded/deduplicated context
  -> pinned teaching-profile version + fixed tutor policy
  -> provider stream
  -> SSE metadata/deltas/citations/done + durable assistant message
```

General conversation deliberately bypasses retrieval. Course-fact answers remain citation-bound;
tutoring may add transparent general explanation but may not cite it as course evidence.

## Data ownership

The RAG database owns courses, documents, ingestion jobs, chunks/FTS, conversations/messages,
teaching-profile versions, publication audit records and RAG rate windows. The Agent database keeps
owner-scoped tasks and its own rate windows. Foreign keys and cascades are enabled on every RAG
connection. SQLite WAL remains the local/production persistence model.

## Compatibility decisions

- Existing CS3481 and GE2324 rows migrate to official, public, published courses.
- Existing conversations/messages, citations, document IDs, chunks and embeddings remain in place.
- Exact-question metadata is additive; legacy chunks continue through hybrid retrieval.
- Model roles have independent environment variables with legacy OpenAI-variable fallback.
- No provider was switched on benchmark claims: the live paid benchmark remains unrun.

## Runtime evidence boundary

The tracked Netlify and Render files are source configuration, not proof of the live topology. The
requested production topology is Netlify plus Alibaba Cloud Hong Kong/Caddy/systemd, but this
workspace had no SSH, platform connector, redacted runtime export or reachable health endpoint.
Accordingly, source readiness and local verification are complete; production deployment is an
explicit release gate documented in `V2_PRODUCTION_DEPLOYMENT.md`.
