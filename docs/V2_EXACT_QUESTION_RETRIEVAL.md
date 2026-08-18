# V2 Exact Question Retrieval

## Outcome

CourseMate V2 resolves explicit course references before semantic retrieval. A request such as
`assignment_2.pdf Question 1(b)` now selects the named document and structural locator inside the
selected course, expands only bounded same-question context, and exposes the strategy through SSE
metadata. When no structural row matches, the existing keyword/vector hybrid path remains the
fallback.

## Pipeline

```text
User message
  -> deterministic reference parser
  -> exact document resolver (case-insensitive filename, course scoped)
  -> question/page/slide locator
  -> target fragment first
  -> bounded same-parent context
  -> context builder and Example Tutor

No exact match
  -> keyword + vector retrieval
  -> reciprocal-rank fusion
```

The `meta` SSE event and persisted assistant metadata include `retrievalStrategy` with
`structured_locator`, `hybrid`, `course_metadata`, or `not_applicable`. Citations retain the
existing response shape; exact rows use the `locator` channel and added sibling context uses
`parent_context`.

## Structured ingestion

Schema migration 4 adds `chunks.metadata_json` and `chunks.parent_key`. Ingestion recognizes
Assignment, Tutorial/Tut, Practice, explicit `Question`/`Q`, numbered tutorial questions, and
subparts written as `(a)`, `a)`, `b.`, or `(1)`. Stored metadata includes document kind/number,
question number/part, heading path, source locator, and fragment role.

Long stems and tables are preserved as parent fragments. The subpart-bearing fragment is marked as
the target and ordered first, so the primary citation is readable while the prompt can still include
the necessary table, stem, or sibling work. Structure state carries across pages, which is required
for Tutorial 1 Question 2: its definition begins on page 1 and its calculation request continues on
page 2.

## Example Tutor

When a request names a question, the default policy teaches in this order:

1. what the question is asking;
2. required concepts;
3. step-by-step solution;
4. final answer;
5. why the method works;
6. common mistakes.

An explicit request such as `直接给答案` or `just give me the answer` selects the concise direct
mode. The chosen `exampleMode` is included in SSE and saved with the assistant message.

## Real corpus evidence

`tests/test_real_course_golden.py` reads the existing corpus database in SQLite read-only mode,
copies only four source files into a temporary evaluation database, rebuilds them through the V2
ingestion path, and verifies:

- `CS_3481_Assignment_2.pdf Question 2` resolves the correct CS3481 document;
- `assignment_2.pdf Question 1(b)` resolves the exact GE2324 subpart and parent context;
- `Tutorial 1 Question 2` includes both page 1 and page 2;
- `GE2324_Tut07.docx Q1` resolves inside GE2324;
- the GE2324 filename cannot be retrieved through the CS3481 course filter.

The isolated golden run passed 4/4. The complete RAG suite passed 104 tests, Ruff, and strict Mypy.
The source `data/rag.sqlite3` was not migrated or reindexed during development.

## Migration and rollout

The schema migration is additive and repeatable. Existing chunks receive `{}` metadata and no
parent key, so they continue to work through hybrid retrieval. Exact locator improvements require a
controlled corpus reindex in the target environment:

1. back up the database and upload directory;
2. run the application migration on a copy and verify schema version 4;
3. reindex documents using the same embedding mode as production;
4. run the real locator smoke cases and course-isolation checks;
5. switch traffic only after counts and citations pass;
6. roll back to the backup if migration, counts, or smoke tests fail.

Production reindexing is intentionally deferred until the real server, provider configuration, and
verified backup path are available.
