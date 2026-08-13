# CourseMate V2 Tutor Pipeline

## Request flow

```text
Authenticated user + selected course
  -> owner-scoped conversation history
  -> language policy
  -> deterministic intent router
  -> bounded follow-up query rewrite
  -> exact locator or hybrid retrieval
  -> context builder
  -> teaching policy
  -> provider stream
  -> citation + assistant metadata persistence
```

The intent router separates grounded course questions, course tutoring, general conversation,
course metadata, and ambiguous requests. General conversation does not call retrieval. Course facts
remain evidence-bound. Tutoring may add clearly labeled general explanation, but citations can only
support retrieved course evidence.

## Teaching policy

The trusted instruction stack declares the following non-overridable order:

1. platform and security rules;
2. tutor core rules and citation truthfulness;
3. course teaching profile (introduced in Stage 7);
4. retrieved course context;
5. conversation context;
6. current user message.

Course documents and history are explicitly marked untrusted. The tutor must not fabricate a
missing premise, calculation, source statement, or citation. It asks a focused question when a
missing premise prevents a correct answer.

Repeated confusion changes the teaching approach from formal explanation to analogy, then a worked
example, then Socratic diagnosis. Referenced examples default to a full teaching sequence and honor
an explicit direct-answer request.

## Context builder

The context builder is course scoped and character-budgeted. It now:

- drops normalized duplicate content before assigning source labels;
- keeps labels contiguous after filtering so `[S1]`, `[S2]` match emitted citations;
- formats filename, page/slide/section, heading path, channels, document ID, and chunk ID;
- compresses a long repeated prefix for same-parent question fragments;
- returns the exact original `SearchHit` objects actually included in the prompt;
- never exceeds `RAG_MAX_CONTEXT_CHARS`.

This preserves the target subpart, necessary question/table context, citation truth, and bounded
prompt size without placing an entire PDF into the model context.

## Retrieval diagnostics

`POST /api/admin/retrieval/diagnostics` accepts the normal `courseId` and `question` fields and is
protected by the server-side administrator dependency. It returns:

- parsed reference;
- selected retrieval strategy;
- structured, keyword, and vector candidates;
- score, channels, filename, locator, structural metadata, and excerpts;
- fused/selected chunks;
- the final bounded context.

Non-admin users receive `403 ADMIN_REQUIRED`. The endpoint is intended for evaluation and incident
diagnosis; it is not called by the normal learner UI.

## Evaluation result

The deterministic hybrid quality gate uses eight labeled cases across CS3481 and GE2324 and checks
course isolation, Recall@3, and mean reciprocal rank. The gate requires Recall@3 >= 0.95 and MRR >=
0.90; it passes. Exact locator golden tests rebuild four real course files into an isolated temporary
database and pass 5/5, including a numeric subpart that continues onto the next PDF page.

The complete RAG suite after Stage 4 passes 112 tests, Ruff, and strict Mypy.

The deterministic embedding used by the small hybrid suite proves ranking mechanics and regression
stability, not production model quality. Provider/model quality is evaluated separately in Stage 5.
Because the current retriever passes this Stage 4 gate, no reranker or multi-query expansion was
added. Either feature now requires a larger before/after benchmark showing measurable benefit.
