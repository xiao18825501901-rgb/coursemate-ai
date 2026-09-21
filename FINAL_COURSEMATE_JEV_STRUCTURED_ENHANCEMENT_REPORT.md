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
| Regression SHA | `4b968e5` (full backend suite run on this revision) |
| Feature SHAs added after it | `4ec62c8` (evaluation/migration specs), `7842255` (DeepSeek acceptance), `b947455` (P1 modules), `1ff038a` (feedback definitions) |
| Schema | RAG **28** (001–028), UI 13, Agent 1 — no migration added by this round |
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

| Module | Entry point | Deterministic part | Jev part | Writes |
|---|---|---|---|---|
| A `ExtractionVerification` | `extraction.py` | required fields, numeric parse, units, question-number shape, table structure, source id, scope | `extraction.field_grounded.v1` on the residue only | receipts |
| B `CourseEntityResolution` | `entity_resolution.py` | exact id, revision relation, content-hash duplicate, accepted alias; pair canonicalisation and a capped, order-independent score | `entity.relation.v1`, one relation per pair | receipts (relations returned for backend persistence) |
| C `EvidenceConsistency` | `evidence_consistency.py` | version/task difference resolution, pair narrowing, budget accounting | `evidence.consistency.v1` over at most 8 pairs | receipts |
| D `ClaimCitationAudit` | `citation_audit.py` | layer 1 authorization/existence, layer 2 quote existence (whitespace-only normalisation) | `source.supports_claim.v1` + `source.select_span.v1` | receipts |
| E `TeachingCapabilityRouter` | `capability_router.py` | candidate filtering by explicit command, permission, mode, revealed state, assessment, Pair | `teaching.capability.v1` over ≤4 offered candidates, ≤1 disambiguation round | receipts |
| F `ToolIntentCheck` | `tool_intent.py` | schema/permission, and a re-check of permission + object revision immediately before execution | `tool.intent.v1` for side-effecting calls only | receipts |

**Feedback triage** (`feedback.category.v1` Choice + `feedback.severity.v1` Score) is user-initiated
only, stores identifiers by default and a body only with explicit opt-in, and queues the report for a
human; it has no ability to close a ticket, delete feedback, change a mark or sanction a user.

**Catalog:** 19 definitions, every one in `shadow`. Two new ids were registered in this round's P0/P1
work (`extraction.field_grounded.v1`, `evidence.consistency.v1`), three for P1
(`entity.relation.v1`, `teaching.capability.v1`, `tool.intent.v1`) and two for feedback
(`feedback.category.v1`, `feedback.severity.v1`).

## 4. Evidence on the frozen SHA

| Gate | Result |
|---|---|
| Full backend regression on `4b968e5` | **1047 passed, 0 failed**, 1322.16s, exit 0 (`work/current-change/full_run_round9.log`) |
| Module suites (A 16, B 18, C/D 21, E/F 29) | **84 passed** |
| Twelve call-site suite | **16 passed** |
| Measurement layer (dataset build, calibration, A/B/C/D/E harness) | **43 passed**; offline ablation exits 0 with verdict `NOT_INTERPRETABLE` |
| Zero-Laya production guard | **3 passed** (and it caught a real leftover reference, which was fixed) |
| Catalog integrity | green with 19 definitions |
| agent-api | real `tsc --noEmit` **exit 0**, **72 tests passed** |
| Browser journeys (real Chrome, isolated identity) | `coursemate.spec.ts` **4 passed**, `learning.spec.ts` **3 passed**, including multi-student private isolation |
| `ui-refresh.spec.ts` (19 journeys) | **partial**: previously unrunnable; after fixing the static server's missing `/api` proxy and building a dist with the E2E identity it runs — **2 passed**, then the legacy-deep-link journey fails on a missing `h1` and 16 stay unrun. Reported as partial, not as passing |
| Ruff | clean on every file this round touched |
| mypy | no new errors; the only failures are 4 pre-existing ones in `app/jev/gateway.py` |

## 5. Status markers (evidence-based, no marker promoted on plumbing)

| Marker | Status | Basis |
|---|---|---|
| DETERMINISTIC_FIXES | **PASS** | learning-start fact, RRF fusion, raw-score projection, command router — all with regressions |
| DEEPSEEK_TEXT / VISION / AGENT | **LOCAL** | contract + host-spy tests prove the wiring and zero Qwen egress; live calls `NOT_RUN` |
| PROMPT_V2_REGISTRY | **PASS** | 16/16 manifest hashes, V1 retained |
| JEV_GATEWAY | **PASS** (local) | gateway/catalog/receipts/cache/modes tested; live TypeSafe `NOT_RUN` |
| JEV_RETRIEVAL · JEV_CITATION · JEV_CONTEXT · JEV_INTENT · JEV_PEDAGOGY · JEV_COVERAGE · JEV_ASSESSMENT · JEV_CLASSIFICATION · JEV_EXERCISE_SELECTION · JEV_PREREQUISITE · JEV_CORPUS_QUALITY | **SOURCE_IMPLEMENTED + LOCAL_INTEGRATED**, all `shadow` | call-site suite plus the module suites; authority boundaries asserted |
| EXTRACTION_VERIFICATION · ENTITY_RESOLUTION · EVIDENCE_CONSISTENCY · CITATION_AUDIT · CAPABILITY_ROUTER · TOOL_INTENT_CHECK | **SOURCE_IMPLEMENTED + LOCAL_INTEGRATED** | 84 module tests; business wiring for B/E/F described as a one-line insertion, not yet applied |
| USER_FEEDBACK_TRIAGE | **IN_PROGRESS** | definitions registered; module under construction |
| LEARNING_PROGRESS · FIVE_QUESTION_ASSESSMENT | **PASS** (local) | regression suites |
| LOCAL_REGRESSION | **PASS** | 1047 passed / 0 failed on `4b968e5` |
| JEV_LIVE_VALIDATION · DEEPSEEK_LIVE_VALIDATION | **NOT_RUN** | no credential, no budget |
| ABLATION | **NOT_RUN** | harness and 310-sample dataset ready; no labelled live run |
| BROWSER_ACCEPTANCE | **PARTIAL** | 7 journeys green, one suite partially diagnosed and 16 unrun, no production browser acceptance |
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
* No promotion of any definition out of `shadow`; no threshold was invented.
* No production change: no deployment, no migration, no DNS/Netlify/Clerk change; production still
  answers with Qwen and remains on schema 25.
* Business wiring for modules B/E/F is specified at an exact insertion point but not applied, because
  those files belong to other workstreams; it is **not** reported as integrated.
* The UI-refresh suite is not reported as passing.
* Nothing in this round shows that teaching quality, marks or coverage accuracy improved — that requires
  the labelled ablation with a real Jev, which has not run.

## 8. What the next round must do

1. Finish and verify the feedback module, then run the web gate (build, vitest, real `tsc`) on the
   frozen SHA.
2. Apply the three documented business insertions (entity relations, capability routing, tool-intent
   check) and re-run the full regression.
3. Diagnose the legacy-deep-link browser journey and add the module-level browser journeys the task
   lists (extraction, alias retrieval, condition conflict, unsupported citation, capability choice,
   tool misexecution, Jev-down fallback).
4. Whole-app mypy, then freeze one APPLICATION SHA and re-run the complete gate on it.
5. Only then the live gate: TypeSafe credential + bounded budget, DeepSeek key, release window, one
   real login — followed by backup, isolated rehearsal, migration 026–028, immutable release, real
   acceptance and post-release monitoring.
