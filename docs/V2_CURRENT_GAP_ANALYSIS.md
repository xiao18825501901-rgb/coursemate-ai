# CourseMate AI V2 Current Gap Analysis

Baseline: `e1ef57a18bb26facf26a3568a7cd5ae1d5ea7ee5`.

## Executive Diagnosis

CourseMate V1 is a complete course-grounded QA and task-planning demo with strong local regression coverage and a real multi-user security boundary. The V2 gap is primarily product orchestration and data modeling: conversations are persisted but cannot be listed, renamed, deleted, restored, or continued; the RAG path treats every input as an independent course-evidence question; course/document ownership is not modeled; chunk metadata is too shallow for exact assignment references; teaching preferences and publication state do not exist.

The correct evolution is additive: retain retrieval, streaming, citations, task tools and Clerk, then add stable resource APIs and an orchestration layer around them.

## Complaint-to-Root-Cause Map

| User complaint | Current code/evidence | Root cause | Planned V2 change | Stage |
|---|---|---|---|---:|
| Chinese teaching is weak | English-only no-support text and course-grounded prompt; no language preference | No language detection/mirroring or course preference | deterministic language policy, preference enum, bilingual terminology prompt and tests | 1 |
| History disappears | DB stores owner/course/messages; only `GET /api/conversations/{id}` exists; React clears state on course change/refresh | Missing list/rename/delete/create contract, no continuation ID, no route/sidebar recovery | full conversation resource API and history sidebar; continue existing conversation | 1 |
| “你好” receives no-evidence refusal | QA always performs hybrid retrieval and returns `NO_SUPPORT_MESSAGE` on zero hits | No intent routing or non-RAG response policy | deterministic intent router with general/grounded/tutoring/meta/ambiguous modes | 2 |
| Follow-ups lose meaning | `QaChatRequest` has no conversation ID; retrieval embeds raw current question only | History not supplied to rewrite/retrieval/prompt | bounded conversation context and standalone query rewrite | 2 |
| Tutor feels like search | prompt is optimized for source-bounded QA; no adaptive explanation strategy | No teaching orchestration/pedagogy policy | tutor response strategy, progressive explanation modes and transparent grounding | 2/4 |
| Assignment Q3(c) cannot be found reliably | chunks have filename only through document join and locator/section; retrieval is lexical/vector | No reference parser, normalized document resolver or question metadata | exact-reference parser, deterministic lookup, structured context and golden tests | 3 |
| Retrieval failures are opaque | no diagnostic endpoint/report per query | Candidate channels/scores/context are not exposed for evaluation | admin/dev retrieval diagnostics with redaction and no ordinary-user access | 4 |
| Model choice is anecdotal | compatible endpoint exists; runtime provider unknown; no eval set | no versioned benchmark data or split model criteria | 50-case eval, official-doc research and tutor/Agent/embedding recommendations | 5 |
| Only fixed official courses | courses have no owner/type/visibility; create/upload are admin-only | shared-corpus schema cannot express private resources | additive course ownership/lifecycle, owner CRUD, quotas and isolated storage | 6 |
| Users cannot specify teaching style | no profile table or prompt layer | no structured preference contract/version | structured teaching profile, version history and safe composition | 7 |
| User uploads could become public implicitly | no publication workflow | no consent, review or immutable public state | explicit request, consent, admin decision and audit trail | 8 |
| Production state is hard to prove | deployment report/server config unavailable; local tests are strong | source/runtime evidence is conflated | backup/restore/monitoring/rollback gates and evidence-based smoke report | 9 |

## Detailed Current-State Findings

### Conversation persistence

Present:

- `conversations.owner_user_id` and `course_id`.
- Persisted user and assistant messages with citation JSON.
- Owner-filtered conversation detail returning 404 for foreign IDs.
- SSE `meta` includes a server-generated conversation ID.

Missing:

- conversation title;
- paginated owner/course list;
- explicit create/new-chat endpoint;
- rename and delete;
- continuation through `conversationId`;
- frontend route/state recovery and sidebar;
- archive policy and optional teaching-profile version.

### Language and tutoring

Present:

- UTF-8 SSE/JSON serialization;
- Unicode FTS tokenizer;
- model transport capable of Chinese text;
- citation metadata independent of answer language.

Missing:

- auto/zh-CN/en/bilingual preference;
- language mirroring instruction;
- general conversation path;
- intent router;
- transparent separation of course evidence and general knowledge;
- progressive teaching state and history-aware follow-up rewrite.

### Retrieval and exact questions

Present:

- course-scoped keyword and vector candidates;
- weighted reciprocal-rank fusion;
- filename, locator type/value and optional section in search hits;
- page/slide information where current loaders provide it.

Missing:

- normalized filename/title resolver;
- question/subpart parser and metadata;
- deterministic question lookup before semantic search;
- parent/child or adjacent context assembly;
- debug/evaluation trace and golden real-corpus exact locator cases.

### Courses and storage

Present:

- course/document/job/chunk tables;
- admin-controlled upload with extension, size and hash handling;
- server-generated storage paths;
- cascade relationships for database records.

Missing:

- course owner/type/visibility/publication/language/update timestamps;
- private-course access policy;
- per-user course/file/byte quotas;
- ownership-aware disk namespace;
- owner document deletion and filesystem cleanup;
- safe course deletion policy across uploads, chunks, FTS and conversations.

### Teaching profile and publication

No dedicated schema, API, versioning, prompt builder, consent record, review queue or community visibility currently exists.

## Risk Register

| Risk | Severity | Mitigation |
|---|---|---|
| Existing database migration damages 1,936 chunks or paths | Critical | additive idempotent migrations; copy/WAL backup; migration-on-copy tests; count/hash checks |
| Private course authorization is missed in one query | Critical | central course access resolver, SQL owner predicates, A/B API matrix |
| Course text becomes prompt injection | High | retrieved text explicitly untrusted; fixed platform hierarchy; injection tests |
| Conversation delete removes evidence unexpectedly | High | owner-only explicit confirmation; define hard-delete/cascade policy; backup before production |
| General chat increases cost without grounding | High | per-user quota remains; intent tests; bounded context; configurable limits |
| Provider benchmark leaks data or spends unexpectedly | High | synthetic/public eval content, explicit model list and budget, no automatic dual calls |
| Frontend history list becomes unbounded | Medium | paginated API and incremental loading |
| Local deterministic tests overstate teaching quality | High | separate contract tests from live benchmark and human rubric |
| Runtime assumptions cause unsafe deploy | Critical | production gate requires current commit/env/service/DB/backup evidence |

## Stage 0 Decision

Proceed with Stage 1 locally on `feature/coursemate-v2-ai-tutor`. Do not deploy or migrate production until Stage 9 gates and current runtime evidence are available.
