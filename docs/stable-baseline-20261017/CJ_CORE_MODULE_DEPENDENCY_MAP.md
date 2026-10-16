# Core module dependency map

## Runtime topology

```text
Netlify UI
  -> Clerk bearer token
  -> rag.47-237-179-69.sslip.io (Singapore TLS/tunnel)
  -> Hangzhou FastAPI RAG/UI-extension service
       -> authoritative RAG SQLite (schema migration 81)
       -> UI-extension SQLite (schema version 16)
       -> retrieval, learning, question, assessment and OpenJEV modules
  -> Agent API when the legacy task/chat surface uses it
       -> authoritative Agent SQLite (schema migration 3)
```

## Seven student paths

| Capability | Browser entry | Public API | Trusted runtime | Durable authority | External/model boundary |
|---|---|---|---|---|---|
| Knowledge learning | `apps/web/src/ui/pages.jsx`, pair-bound teaching pane | `POST /conversations/{id}/runs`; `GET /runs/{id}/events` | `app/cm_update/app.py`, `public_events.py`, provider adapters | UI runs/messages/events plus RAG citations | current UI provider; safe public-event allowlist required |
| Knowledge tree | course knowledge view/build status | `GET /courses/{id}/knowledge`; build status; learning workspace knowledge APIs | `app/ui_extension/domain.py`, learning orchestrator/map pipeline | RAG workspace/spec/map tables and UI course bindings | private-course tree exception remains DeepSeek; display capped at 50 nodes |
| Do One | learning toolbar/command and exercise card | create/get exercise, hint, attempt, reveal, explanation | `app/cm_update/app.py`, `learning/question_runtime.py`, `learning_loop.py`, `question_author.py` | question revisions, practice operations/submissions/evaluations, Pair binding | READY reuse is zero-call; cold author currently hard-blocks non-DeepSeek receipts |
| Problem response | right-side problem pane | pair run/event path and learning solution route | UI runner plus `LearningOrchestrator.solve` | conversation/run/message history and cited evidence | general LLM role; public output must exclude planning/reasoning |
| Start assessment | assessment setup/workspace | setup, preparation, session, draft, submit, explain, history | `app/cm_update/app.py`, `learning/assessments.py`, `question_runtime.py` | point catalog/spec, question revisions, blueprints, sessions, submissions, grades | source-backed K and qualified questions; UNKNOWN never replayed |
| RAG | documents/course sources and citations | upload/preview plus QA/learning retrieval APIs | ingestion, retriever, citation resolver, storage resolver | RAG SQLite plus stored objects, owner/course ACL | embeddings remain their own non-generative role |
| OpenJEV | no independent student platform | internal semantic-decision calls | `app/jev/*`, `learning/openjev_observer.py` | decision receipts/cache scoped by input and model version | advisory only unless an existing hard rule explicitly requires a valid verdict |

## Important shared boundaries

- `apps/web/src/ui/api.js` is the authenticated browser boundary. It generates request IDs, parses
  incremental SSE, deduplicates event IDs, and exposes distinct Do One and Assessment clients.
- `services/rag-api/app/cm_update/app.py` is a large shared hotspot. Changes here must be narrow and
  staged because teaching, practice, assessment, Pair, history, classification, and explanations all
  meet in this module.
- `services/rag-api/app/learning/question_runtime.py` is the existing Question Engine coordinator.
  New work must extend it rather than create a parallel generator or qualification service.
- `services/rag-api/app/learning/assessments.py` is the AssessmentService authority for freezing,
  submission, grading, drafts, explanations, and history.
- Clerk ownership checks, course/source authorization, evidence hashes, answers, and rubric fields are
  server-owned. Model output is untrusted content and cannot assert those identities.

## S0 decisions

1. Keep the current split frontend and backend deployment topology for R1–R3; changing domains is not
   required to restore the seven functions.
2. Instrument the existing run/event path for TTFRT rather than adding another streaming service.
3. Repair provider-role identity in the existing author/reviewer contracts; do not relax question
   content validation and do not add another Question Engine.
4. Exercise and assessment remain separate student workflows even though they share question assets.
5. Treat the RAG/Agent effective-environment mismatch as a call-site audit input, not as permission to
   bulk-change environment files.
