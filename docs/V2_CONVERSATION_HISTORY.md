# CourseMate AI V2 Conversation History

Status: implemented and locally verified on branch `feature/coursemate-v2-ai-tutor`.

## User behavior

The Course QA workspace now supports:

- creating a new course-bound conversation;
- listing the authenticated user's conversations for the selected course;
- opening and continuing an old conversation through `/qa/{courseId}/{conversationId}`;
- deterministic first-question titles, plus owner rename;
- confirmed owner deletion with message cascade;
- restoring messages and citations after route reload or a later sign-in;
- `auto`, `zh-CN`, `en`, and `bilingual` response preferences stored per conversation.

The responsive layout is three columns on wide screens and a stacked, single-column workspace at 1024 px and below. History actions have explicit accessible names; loading and empty states remain visible without relying on color.

## API contract

All operations require a verified bearer session. The server derives `owner_user_id` from the authenticated identity and never accepts it in request JSON.

```text
GET    /api/conversations?courseId={courseId}&page=1&pageSize=100
POST   /api/conversations
GET    /api/conversations/{conversationId}
PATCH  /api/conversations/{conversationId}
DELETE /api/conversations/{conversationId}
POST   /api/qa/chat  # accepts optional conversationId and streams SSE
```

Foreign-owner and wrong-course conversation references return `404 CONVERSATION_NOT_FOUND`. A delete removes the conversation and its messages through the existing SQLite foreign-key cascade. Lists are newest-updated first and paginated.

## Persistence lifecycle

1. A user starts a chat explicitly or the first QA request creates a conversation.
2. The user message is committed before retrieval/model generation.
3. The SSE `meta` event identifies the durable conversation.
4. A successful assistant answer and its citations are committed before `done`.
5. An interrupted/model-error stream leaves the user message but does not fabricate an assistant completion.
6. Reloading the route fetches the durable messages and citations.

The web client suppresses history re-fetch while an SSE stream is active. This prevents a route change to a newly assigned conversation ID from replacing the optimistic assistant message with a partial database snapshot. It fetches the final durable conversation after streaming finishes.

## Migration

RAG database migration version 2 additively introduces:

```text
conversations.title
conversations.preferred_language
```

Legacy conversations receive a deterministic title derived from their first user message only when migration 2 is first applied. The migration is idempotent and retains existing IDs, ownership, course bindings, messages, citations, and timestamps.

Production migration remains gated on a verified consistent backup of the SQLite database plus WAL/SHM files and uploads. Local tests use isolated temporary databases and do not mutate the ignored project corpus database.

## Verification evidence

Verified on 2026-08-13:

```text
RAG API: 67 pytest tests passed
RAG lint: ruff passed
RAG types: mypy passed for 27 source files
Web: 16 Vitest tests passed
Agent API: 47 Vitest tests passed
Web + Agent type checks passed
Web production build passed
```

Coverage includes clean/V1/idempotent migration, CRUD, continuation, course and owner isolation, delete authorization, blank-title validation, language preference override, API client payloads, route recovery, sidebar actions, course switching, and the SSE route/history race.

The five browser-level persistence scenarios from the master request still require the Stage 9 isolated browser/production evidence gate. Backend owner isolation and component-level reload behavior are already deterministic and covered; this document does not claim a production browser result.

## Rollback

Application rollback is to the prior release commit. Database columns are intentionally retained because SQLite column removal would be destructive and older application code ignores them. If a production restore is required, restore the verified database/WAL/SHM/upload consistency unit according to the Stage 9 runbook; do not edit the live database in place.
