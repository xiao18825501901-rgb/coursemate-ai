# FINAL_COURSEMATE_JEV_STRUCTURED_ENHANCEMENT_REPORT

Outcome of the "structured incremental enhancement built on the twelve Jev cases" round: what was
adopted, merged, kept as development-only or deliberately not adopted; what actually changed in the
code and where it is called from; which definitions exist and in what mode; the test evidence **for
one frozen SHA**; and every item that is not verified. No live model call was made in this round, so
nothing here claims a quality improvement.

---

## 1. Identities

| Item | Value |
|---|---|
| Work tree | `D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY` |
| Branch | `fix/codex-dsh-audit-20260919` |
| Backend regression SHA | `35ef493` (full backend suite run on this revision) |
| Current HEAD | `35ef493` — backend, shell and browser suites all re-run on this same revision |
| Schema | RAG **29** (001–029; 029 is the proposal-only `entity_relations` store), UI 13, Agent 1 |
| Live TypeSafe model/calibration version | **none configured** — live Jev is `NOT_RUN` |

## 2. Case dispositions (summary of `docs/jev-structured/CASE_ADOPTION_MATRIX.md`)

| Case | Disposition |
|---|---|
| 11 Extraction cascade | **Adopted, highest priority** (P0 module A) |
| 3 RAG passage classification / conflict | **Adopted** (P0 module C) |
| 4 Citation checking | **Adopted** (P0 module D) |
| 10 Paper Trellis | **Merged into case 4** — no second citation service |
| 2 Entity alignment | **Adopted** (P1 module B) |
| 6 Skill suggestion | **Adopted** (P1 module E, restricted to CourseMate's own capabilities) |
| 7 Tool risk middleware | **Adopted** (P1 module F, side-effecting calls only) |
| 8 Ticket triage | **Adopted last** (P2 lightweight, user-initiated only) |
| 1 Notra / brand mentions, 9 website expression scoring | **Not adopted** — marketing scoring must not judge teaching |
| 12 CatBoost student prediction | **Not adopted** — no ability/churn prediction this round |
| 5 Browser Use | **Development probe only** — never in the student request path |

The Word source referenced by the task (`85462d42…m(3).doc`) is **not present** in this workspace or
any readable download folder, and the 60-case collection it cites was never provided. The dispositions
above therefore follow the task specification's own case list; nothing is claimed about unread
material, and no quoted URL was treated as an API path.

## 3. What exists now, and where it is called from

**The twelve core call sites** (`app/jev/callsites.py`, detailed in `JEV_CALLSITE_MATRIX.md`):
retrieval rerank after the global RRF fusion (reorder-only, exact target protected), citation support
and span selection in the evidence path, context keep/drop over the filterable class only, intent for
ambiguous follow-ups (explicit commands cost zero Jev calls), pedagogy into the plan→work context,
coverage item support, assessment criterion review inside the grading loop, hierarchical template
match, exercise prototype, prerequisite among legal graph neighbours, and corpus quality in upload /
pool preparation. All twelve are `shadow`.

**The six structured modules** (all new files under `services/rag-api/app/jev/`):

| Module | Entry point | Deterministic part | Jev part | Writes | Business wiring |
|---|---|---|---|---|---|
| A `ExtractionVerification` | `extraction.py` | required fields, numeric parse, units, question-number shape, table structure, source id, scope | `extraction.field_grounded.v1` on the residue only | receipts | **`MODULE_ONLY`, investigated** — no production surface produces an `ExtractionRecord`-shaped record; every candidate was inspected and ruled out with a reason (`SOURCE_EXTRACTION_AND_ENTITY_RELATIONS.md` §9.4). No effect claimed |
| B `CourseEntityResolution` | `entity_resolution.py` | exact id, revision relation, content-hash duplicate, accepted alias; pair canonicalisation and a capped, order-independent score; **per-concept** name groups for expansion | `entity.relation.v1`, one relation per pair | receipts + `entity_relations` proposals | **WIRED**: `_retrieve` expands the query only for a concept the query itself names (both directions), so an unrelated question is never widened by the course's other aliases, and records resolved relations as `PROPOSED` rows. Proven on the real GE2324 corpus |
| C `EvidenceConsistency` | `evidence_consistency.py` | version/task difference resolution, pair narrowing, budget accounting | `evidence.consistency.v1` over at most 8 pairs | receipts | **WIRED and consumed**: a deterministic per-source `jev_consistency` signal plus a genuine-contradiction channel that reaches the teaching prompt as a bounded note, so both sides are explained and no source is dropped; version/assumption differences are never called conflicts |
| D `ClaimCitationAudit` | `citation_audit.py` + `citation_evidence.py` | layer 1 authorization/existence through the canonical ACL (read-only, version- and locator-aware, bounded text), layer 2 quote existence **and** a unit-aware number check (`missing_claim_numbers`) | `source.supports_claim.v1` + `source.select_span.v1` | receipts | **WIRED and consumed**: the pre-generation evidence bundle is annotated as before, and after generation `audit_answer_citations` binds each cited span to the sentence that cites it, records the verdict/layer/claim on the citation card, and the shipped shell marks only a *real* negative verdict (≤6 cards per answer) |
| E `TeachingCapabilityRouter` | `capability_router.py` | candidate filtering by explicit command, permission, mode, revealed state, assessment, Pair; only the capabilities this endpoint serves are offered | `teaching.capability.v1` over ≤4 offered candidates, ≤1 disambiguation round | receipts | **WIRED and consumed**: the resolved `skill_id` decides `teaching_flow` (journey binding vs answer-only) in `cm_update.run_capability`, and is reported on the create-run response |
| F `ToolIntentCheck` | `tool_intent.py` | schema/permission, and a re-check of permission + object revision immediately before execution | `tool.intent.v1` for side-effecting calls only | receipts | **WIRED, opt-in**: `services/agent-api` `ToolExecutor` gates the four write tools over the token-authenticated `POST /api/jev/tool-intent`; default mode `off` makes no call and leaves the path byte-identical |

**Feedback triage** (`feedback.category.v1` Choice + `feedback.severity.v1` Score) is user-initiated
only, stores identifiers by default and a body only with explicit opt-in, sends **one** batched call,
and queues the report for a human; it has no ability to close a ticket, delete feedback, change a mark
or sanction a user. Two disclosed limitations belong with that claim: the review queue is **in-memory**
plus the existing receipt ledger (no migration was allowed in this round, so the queue is not durable
across a restart — a persistent queue is a follow-up for the migration workstream), and the shell
helper posts to the RAG host path `/api/feedback`, whose exact proxying under a `/ui-extension` mount
must be confirmed by the workstream that owns that mount before release.

**Catalog:** 19 definitions, every one in `shadow`. Two new ids were registered in this round's P0/P1
work (`extraction.field_grounded.v1`, `evidence.consistency.v1`), three for P1
(`entity.relation.v1`, `teaching.capability.v1`, `tool.intent.v1`) and two for feedback
(`feedback.category.v1`, `feedback.severity.v1`).

## 4. Evidence on the frozen SHA

| Gate | Result |
|---|---|
| Full backend regression on `35ef493` | **1163 passed, 0 failed**, 1404.46s, exit 0 (`work/current-change/full_run_round25.log`) |
| Module suites (A 16, B 20, C 9+wiring 4, D 14+12+7, E/F 29, P2 17) | **128 passed** |
| Twelve call-site suite | **16 passed** |
| Structured-insertion suites (shadow invariance 6, capability dispatch 10, tool-intent endpoint 8) | **24 passed** |
| Real-corpus golden suite (incl. the Chinese-alias → English-material case) | **6 passed** |
| Measurement layer (dataset build, calibration, A/B/C/D/E harness) | **43 passed**; offline ablation exits 0 with verdict `NOT_INTERPRETABLE` |
| Zero-Laya production guard | **3 passed** |
| Catalog integrity | green with 19 definitions |
| Migration 029 on an isolated database | `integrity=ok`, `fk_violations=0`, `max_migration=29`, no `*_old`/`*_new` leftovers |
| agent-api | real `tsc --noEmit` **exit 0**, **92 tests passed** (12 files), build **exit 0** |
| Web app | real `tsc --noEmit` **exit 0**, **68 tests passed** (18 files), build **exit 0** |
| Browser journeys (real Chrome, isolated identity, real three-service shape) | `ui-refresh.spec.ts` **19/19**, `jev-structured.spec.ts` **2/2**, `coursemate.spec.ts` **4**, `learning.spec.ts` **3** — **28 journeys, 0 failed** |
| Ruff | clean on every file this round touched (pre-existing debt elsewhere unchanged) |
| mypy | whole-app runs and reports **1068 pre-existing errors in 38 files** (legacy `ui_extension`/`cm_update`); the whole Jev layer has **6**, all pre-existing in `gateway.py` (5) and `receipt_store.py` (1) |

The browser gate found one real product bug, which is fixed rather than papered over: a `GET /layout`
still in flight when the learner moved a reasoning-strength slider overwrote the new value on arrival,
and the next save wrote the stale value back, so the control visibly snapped back
(`apps/web/src/ui/pages.jsx`, `setStrength`/`load`). Three stale test expectations written against
earlier UI drafts and one weak assertion (which matched a textarea's own value instead of the persisted
comment) were corrected without weakening any product assertion.

## 5. Status markers (evidence-based, no marker promoted on plumbing)

| Marker | Status | Basis |
|---|---|---|
| DETERMINISTIC_FIXES | **PASS** | learning-start fact, RRF fusion, raw-score projection, command router, and the reasoning-strength save race — all with regressions |
| DEEPSEEK_TEXT / VISION / AGENT | **LOCAL** | contract + host-spy tests prove the wiring and zero Qwen egress; live calls `NOT_RUN` |
| PROMPT_V2_REGISTRY | **PASS** | 16/16 manifest hashes, V1 retained |
| JEV_GATEWAY | **PASS** (local) | gateway/catalog/receipts/cache/modes tested; one shared service app-wide; live TypeSafe `NOT_RUN` |
| JEV_RETRIEVAL · JEV_CITATION · JEV_CONTEXT · JEV_INTENT · JEV_PEDAGOGY · JEV_COVERAGE · JEV_ASSESSMENT · JEV_CLASSIFICATION · JEV_EXERCISE_SELECTION · JEV_PREREQUISITE · JEV_CORPUS_QUALITY | **SOURCE_IMPLEMENTED + LOCAL_INTEGRATED**, all `shadow` | call-site suite plus the module suites; authority boundaries asserted |
| ENTITY_RESOLUTION | **PASS (local, shadow)** | wired into the authorized retrieval path, proposal-only store with an idempotency and degradation proof, per-concept expansion proven to preserve the original query, leave unrelated queries untouched, and reach the English material for a Chinese question on the real GE2324 corpus |
| EVIDENCE_CONSISTENCY | **PASS (local, shadow)** | wired into the evidence-pack step; byte-identical sources under off/shadow/unavailable/no-Jev, a real contradiction kept and explained through the teaching prompt, and version/assumption differences never presented as conflicts |
| CAPABILITY_ROUTER | **PASS (local, shadow)** | the decision is consumed (flow dispatch + reported on the response), zero-Jev explicit commands proven by receipt count, hardened against a hostile transport, and exercised end to end in real Chrome |
| TOOL_INTENT_CHECK | **PASS (local, default-off)** | real gate at the model-proposed write boundary on both sides, 14 Node tests + 8 endpoint tests + 12 guard tests; `off` proven to make no call |
| EXTRACTION_VERIFICATION | **SOURCE_IMPLEMENTED, `MODULE_ONLY` (investigated)** | module tested (16) but **no production surface produces the record shape it verifies**; the candidate surfaces and the reason each is ruled out are recorded, and no effect is claimed |
| CITATION_AUDIT | **PASS (local, shadow)** | all three layers bound to the teaching path: a deterministic layer-2 verdict that costs zero model calls, a layer-1 re-check through the canonical ACL on a real migrated database (incl. cross-user and cross-course `unauthorized`), the verdict recorded on the card the client receives and marked in the shipped shell, an enforced per-answer budget, and byte-identical cards when no semantic layer is configured. A unit-regex defect that could fabricate a CONTRADICTION was found and fixed |
| USER_FEEDBACK_TRIAGE | **SOURCE_IMPLEMENTED + LOCAL_INTEGRATED** | module, backend route, shell entry, 17 tests; human review queue only (in-memory — see the disclosed limitation) |
| LEARNING_PROGRESS · FIVE_QUESTION_ASSESSMENT | **PASS** (local) | regression suites plus the browser assessment journey (start → 5 questions → submit → graded) |
| LOCAL_REGRESSION | **PASS** | 1163 passed / 0 failed on `35ef493`; backend, shell and all four browser suites re-run on that same revision |
| JEV_LIVE_VALIDATION · DEEPSEEK_LIVE_VALIDATION | **NOT_RUN** | no credential, no budget |
| ABLATION | **NOT_RUN** | harness and 310-sample dataset ready; no labelled live run |
| BROWSER_ACCEPTANCE | **PASS (local)** | 28 journeys across four suites in real Chrome against the real services, including the Jev-unavailable deployment; production browser acceptance still `NOT_RUN` |
| PRODUCTION_DEPLOYMENT · PRODUCTION_ACCEPTANCE | **BLOCKED** | requires the release window and the credentials in `MINIMAL_OWNER_ACTION_CARD.md` |

## 6. Cost, latency and quality

No live Jev or DeepSeek call was made, so there is **no cost, latency or quality measurement** to
report. The offline ablation numbers exist only to prove the arms are wired and differentiated and are
tagged `NON_INTERPRETABLE_PLUMBING_ONLY`. The measurements that must be produced before any definition
leaves `shadow` — Recall@K, MRR, NDCG, exact-locator accuracy, citation support, field
false-acceptance/rejection, entity false-merge, condition distinction, anchor retention, intent
accuracy, capability misroute, tool false-allow/block, coverage FP/FN, criterion error, end-to-end
success, p50/p95 latency, per-provider cost and failure rate — are specified in
`docs/jev-structured/EVALUATION_AND_CALIBRATION.md` and remain `NOT_RUN`.

## 7. Explicitly not done, not claimed

* No live TypeSafe Jev call, no live DeepSeek call, no calibration, no ablation result.
* No promotion of any definition out of `shadow`; no threshold was invented. A wired call site is
  still not evidence of quality, and nothing here claims teaching quality improved.
* No production change: no deployment, no migration, no DNS/Netlify/Clerk change; production still
  answers with Qwen and remains on schema 25.
* Module **A (extraction)** is `MODULE_ONLY` after a full investigation: no production surface
  produces the record shape it verifies, and the candidate surfaces are listed with the reason each is
  ruled out. Every other structured module (B, C, D, E, F, feedback) is wired to a real business path
  with a consumer; none of them is promoted out of `shadow`.
* Module D's high-impact gate (`is_definitive`, "audit the reference solution **before** presenting it")
  is implemented in the module but not yet bound to the assessment reference-solution path: that path
  is the next binding, and no claim is made that reference solutions are gated today.
* The evidence-consistency conflict note and every D verdict other than the deterministic layer-2 one
  can only appear in mode `on`; with no TypeSafe credential they have never been produced by a live
  decision. What is proven today is that they are *absent* (and the prompt/cards byte-unchanged) in
  every mode the deployment can currently reach.
* The tool-intent gate ships **default-off**; with `off` (the current production setting) it makes no
  call and changes nothing, so its enforcement path has never run against a live model in production.
* The user-feedback review queue is in-memory plus the receipt ledger; it is not durable across a
  restart until the migration workstream owns a table for it.
* Whole-app mypy is now honest rather than green: 1068 pre-existing errors in 38 files. That debt is
  inherited legacy code and is **not** cleaned up in this round.
* Production browser acceptance, production deployment and production acceptance have not run.

## 8. What the next round must do

1. Bind `is_definitive` to the high-impact path: the assessment reference solution and grading
   rationale must be audited **before** they are presented, using the layer-1/2/3 machinery that now
   exists, and a non-definitive verdict must hold the material rather than publish it.
2. Decide module **A** explicitly: either wire the `extract_structured_blocks` question-number/part
   labels *with a real consumer* (structured retrieval distrusting a misassigned 题号, marked only on a
   real signal, which needs a migration) or leave it `MODULE_ONLY` in the final report. Inventing a
   field decomposition is not an option.
3. Add the browser journeys that can exist for the wired modules and record the rest as `NOT_RUN` with
   the reason (a conflict/citation journey needs a live Jev signal; extraction has no call site).
4. Re-run the whole gate on one frozen APPLICATION SHA.
5. Only then the live gate: TypeSafe credential + bounded budget, DeepSeek key, release window, one
   real login — followed by backup, isolated rehearsal, migration 026–029, immutable release, real
   acceptance and post-release monitoring.
