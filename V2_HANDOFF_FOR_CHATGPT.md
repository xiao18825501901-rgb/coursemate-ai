# CourseMate AI V2 Handoff for ChatGPT

This is the teaching and maintenance map for the V2 release candidate. Read the matching V2 document
and file-request pack before changing a subsystem. Do not claim model or production acceptance from
local tests.

## 1. Chinese teaching

**Old behavior:** one English-first grounded prompt and an English no-support message.
**Problem:** Chinese questions were transport-compatible but not taught naturally.
**New architecture:** deterministic language detection plus course default and conversation
preference (`auto`, `zh-CN`, `en`, `bilingual`) feed a language policy below security/grounding rules.
**New code:** `app/tutor/language.py`, conversation models/migration, QA prompt composition and UI
preference.
**Why:** language is stable, testable session state; citations remain language-neutral.

## 2. Conversation history

**Old behavior:** messages were stored but the UI could not list, restore or continue them.
**Problem:** refresh/course switching felt like data loss and each question started a new chat.
**New architecture:** owner-scoped paginated conversation resources, explicit create/rename/delete,
route IDs and optional continuation in SSE chat.
**New code:** `app/api/qa.py`, `app/services/qa.py`, `ConversationSidebar.tsx`, `QaPage.tsx`.
**Why:** the database becomes the durable source of truth; foreign IDs remain existence-hiding 404s.

## 3. Query router and general conversation

**Old behavior:** every message ran retrieval and no evidence meant the course refusal.
**Problem:** “你好” was treated as a failed course search.
**New architecture:** deterministic intents distinguish grounded QA, tutoring, general conversation,
course metadata and ambiguous prompts. General conversation bypasses RAG.
**New code:** `app/tutor/routing.py`, `app/tutor/strategy.py`, QA orchestration/tests.
**Why:** routing is cheap, auditable and prevents forced citations for non-course chat.

## 4. Query rewrite

**Old behavior:** retrieval embedded only the current short message.
**Problem:** “那第二步呢？” lost its referent.
**New architecture:** bounded recent history creates a standalone retrieval query while the original
message remains stored and shown.
**New code:** `app/tutor/rewrite.py` and `test_query_rewrite.py`.
**Why:** retrieval gains context without rewriting user history or creating unbounded prompts.

## 5. Exact question locator and example teaching

**Old behavior:** assignment filenames/question parts relied on fuzzy hybrid ranking.
**Problem:** a requested subpart could retrieve the wrong page or omit its stem/table.
**New architecture:** parse filename/document kind/question/subpart/page/slide, resolve within the
selected course, rank the target first and add bounded parent/adjacent context before hybrid fallback.
Referenced examples use concepts -> steps -> answer -> why -> mistakes unless a direct answer is
requested.
**New code:** `app/tutor/references.py`, `app/rag/structure.py`, structured retriever and real-corpus
golden tests.
**Why:** explicit references are identifiers, not semantic guesses.

## 6. Tutor prompt and retrieval improvements

**Old behavior:** a source-bounded answer prompt mostly summarized retrieved chunks.
**Problem:** correct retrieval did not guarantee good teaching or adaptation after confusion.
**New architecture:** fixed hierarchy (platform/security -> tutor/citation -> profile -> course
evidence -> history -> user), deduplicated budgeted context, progressive formal/analogy/worked/
Socratic strategies and admin-only diagnostics.
**New code:** `app/rag/prompt.py`, `app/services/qa.py`, `app/tutor/strategy.py`, diagnostics route and
retrieval eval suite.
**Why:** pedagogy is explicit while course facts and citations remain evidence-bound.

## 7. Model benchmark and provider abstraction

**Old behavior:** OpenAI SDK construction and model variables were shared, with configuration intent
treated informally as a model decision.
**Problem:** chat, embedding and Agent roles have different contracts; “compatible” does not always
mean Responses-compatible.
**New architecture:** independent RAG chat/embedding and Agent model keys/base URLs/names, legacy
fallback and a 50-case opt-in benchmark runner.
**New code:** settings/provider constructors, `benchmarks/`, `run_model_benchmark.py`,
`MODEL_BENCHMARK_2026.md`.
**Why:** models can be evaluated and migrated per role. No live paid benchmark ran, so criterion G
remains not passed and no winner/provider switch is claimed.

## 8. User-created courses, ownership and ingestion

**Old behavior:** only administrator-created shared courses existed.
**Problem:** no private workspace or ownership model.
**New architecture:** official/user type, private/public visibility, canonical access resolver,
owner CRUD, opaque owner-isolated server paths, atomic course/file/byte quotas, isolated ingestion
and cascade deletion.
**New code:** schema V5, `course_access.py`, ingestion service/routes, Course Center/Settings UI.
**Why:** private-by-default is enforced at every API boundary, not merely hidden in the UI.

## 9. Teaching profile and prompt builder

**Old behavior:** all courses shared one teaching style.
**Problem:** learner level, goals and pedagogy could not be durable or course-specific.
**New architecture:** typed immutable profile versions; deterministic natural-language preview;
historical restore creates a new version; conversations pin the current version on first use.
**New code:** schema V6, `services/teaching_profiles.py`, profile API and Course Settings builder.
**Why:** structured fields are reviewable and safe; arbitrary text remains a low-trust preference,
not a system instruction.

## 10. Publication moderation

**Old behavior:** no user-course publication state or consent record.
**Problem:** adding community visibility could accidentally expose private/copyrighted material.
**New architecture:** dual owner consent -> pending -> owner withdrawal or administrator
approve/reject -> public read-only. Published owners are mutation-locked until administrator
unpublish. Cross-owner file cloning is deferred pending a license/attribution policy.
**New code:** schema V7, publication service/API, admin review page and permission matrix tests.
**Why:** public visibility is an audited server transition; reviewed content cannot be swapped later.

## 11. Database migration

**Old behavior:** schema versions 1-4 represented security/history/routing/structured retrieval.
**Problem:** production data must survive course/profile/publication additions.
**New architecture:** additive idempotent introspection-based migration; operations SQL record;
online backup plus isolated restore rehearsal.
**New code:** `app/db.py`, migrations 005-010, `ops/*.sh`.
**Why:** SQLite cannot safely apply unconditional `ADD COLUMN`; executable migration checks actual
schema and repairs historical null timestamps. A local copied DB passed two runs/integrity/counts.

## 12. Security

The canonical rules are: verified identity only; derive ownership server-side; private existence is
hidden; use parameterized SQL; generate stored paths; keep secrets backend-only; treat documents,
profiles and provider output as untrusted; bound requests/model/tool loops; never mutate reviewed
public content without unpublish/re-review. Rotate the previously at-risk provider credential before
any live work. See `docs/V2_SECURITY.md`.

## 13. Production deployment

Local source/test/build/migration-copy gates pass. Production was unreachable and no server/control-
plane access was present, so it was not changed. The real provider, commit, data counts, services,
backup and monitoring remain unknown. Follow `docs/V2_PRODUCTION_DEPLOYMENT.md`, require a restorable
backup, deploy incrementally and append only verified facts to
`PRODUCTION_DEPLOYMENT_CHANGELOG_AND_FINAL_STATE.md`. Criterion N remains not passed.

## 14. Verification and next safe work

The final local evidence is 144 RAG tests, 29 Web tests, 48 Agent tests, Ruff, strict Mypy 39 files,
both TypeScript checks/builds and Chrome 4/4. Review `docs/V2_TEST_REPORT.md`. The next authorized
release work is production evidence collection and credential rotation; the next quality work that
requires new authorization is the billable 50-case model benchmark. Immutable external publication
audit retention and license-aware community-course cloning are known follow-ups.
