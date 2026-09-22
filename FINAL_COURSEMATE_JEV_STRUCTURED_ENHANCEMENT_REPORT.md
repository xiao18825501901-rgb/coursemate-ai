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
| Backend regression SHA | `169bd57` (full backend suite run on this revision; previously `6e65396`) |
| Current HEAD | `169bd57` — the backend gate was re-run on this revision and `git diff 169bd57 -- services/rag-api benchmarks` is empty; the browser suites were re-run on `6ba70b0`, and `apps/` + `tests/e2e/` are unchanged since (`git diff 6ba70b0 -- apps tests/e2e` empty) |
| Schema | RAG **30** (001–030; 029 is the proposal-only `entity_relations` store, 030 the durable feedback queue), UI 13, Agent 1 |
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
| A `ExtractionVerification` | `extraction.py` + `reference_verification.py` | required fields, numeric parse, units, question-number shape, table structure, source id, scope; on this surface: the label's shape and the locator span | `extraction.field_grounded.v1` on the residue only | receipts | **WIRED (round 30)** — the surface is the query-side exact-locator label (`parse_query_reference`), whose value becomes a hard `chunks.metadata_json` filter in both the official and the private scope. An affirmative defect (or a deterministic failure) drops that label and retrieval falls back to hybrid search; `UNCERTAIN`/off/shadow/no-service keep the deterministic reference unchanged. Fixing the parser that fed it also removed an invented-sub-part filter that had been suppressing legitimate exact recall. Reasoning, reproduced defect and disposal rule: `SOURCE_EXTRACTION_AND_ENTITY_RELATIONS.md` §9.4 |
| B `CourseEntityResolution` | `entity_resolution.py` | exact id, revision relation, content-hash duplicate, accepted alias; pair canonicalisation and a capped, order-independent score; **per-concept** name groups for expansion | `entity.relation.v1`, one relation per pair | receipts + `entity_relations` proposals | **WIRED**: `_retrieve` expands the query only for a concept the query itself names (both directions), so an unrelated question is never widened by the course's other aliases, and records resolved relations as `PROPOSED` rows. Proven on the real GE2324 corpus |
| C `EvidenceConsistency` | `evidence_consistency.py` | version/task difference resolution, pair narrowing, budget accounting | `evidence.consistency.v1` over at most 8 pairs | receipts | **WIRED and consumed**: a deterministic per-source `jev_consistency` signal plus a genuine-contradiction channel that reaches the teaching prompt as a bounded note, so both sides are explained and no source is dropped; version/assumption differences are never called conflicts |
| D `ClaimCitationAudit` | `citation_audit.py` + `citation_evidence.py` | layer 1 authorization/existence through the canonical ACL (read-only, version- and locator-aware, bounded text), layer 2 quote existence **and** a unit-aware number check (`missing_claim_numbers`) | `source.supports_claim.v1` + `source.select_span.v1` | receipts | **WIRED and consumed**: the pre-generation evidence bundle is annotated as before, and after generation `audit_answer_citations` binds each cited span to the sentence that cites it, records the verdict/layer/claim on the citation card, and the shipped shell marks only a *real* negative verdict (≤6 cards per answer) |
| E `TeachingCapabilityRouter` | `capability_router.py` | candidate filtering by explicit command, permission, mode, revealed state, assessment, Pair; only the capabilities this endpoint serves are offered | `teaching.capability.v1` over ≤4 offered candidates, ≤1 disambiguation round | receipts | **WIRED and consumed**: the resolved `skill_id` decides `teaching_flow` (journey binding vs answer-only) in `cm_update.run_capability`, and is reported on the create-run response |
| F `ToolIntentCheck` | `tool_intent.py` | schema/permission, and a re-check of permission + object revision immediately before execution | `tool.intent.v1` for side-effecting calls only | receipts | **WIRED, opt-in**: `services/agent-api` `ToolExecutor` gates the four write tools over the token-authenticated `POST /api/jev/tool-intent`; default mode `off` makes no call and leaves the path byte-identical |

**Feedback triage** (`feedback.category.v1` Choice + `feedback.severity.v1` Score) is user-initiated
only, stores identifiers by default and a body only with explicit opt-in, sends **one** batched call,
and queues the report for a human; it has no ability to close a ticket, delete feedback, change a mark
or sanction a user. The queue is **durable** since round 29 (migration 030, `feedback_reports`:
idempotent by report key, `status` starting `OPEN`, read by an admin-only queue endpoint and by the
submitter's own list), and the privacy rule is a schema CHECK rather than a convention, so no future
code path can store a question/answer body without consent.

**Catalog:** 19 definitions, every one in `shadow`. Two new ids were registered in this round's P0/P1
work (`extraction.field_grounded.v1`, `evidence.consistency.v1`), three for P1
(`entity.relation.v1`, `teaching.capability.v1`, `tool.intent.v1`) and two for feedback
(`feedback.category.v1`, `feedback.severity.v1`).

## 4. Evidence on the frozen SHA

**Re-verified 2026-09-22 (rounds 31–35).** This table's rows were originally measured on `6e65396`.
Every row that could have moved has been re-measured since, and the rows below name the revision they
were measured on; where a row still stands from the earlier revision, it says so. Two rows were
**wrong** when first written and are corrected here rather than quietly overwritten: the mypy row said
the whole-app count was "unchanged" (it was not — see its cell) and the false-claim history for that
number is in `docs/recovery/CURRENT_BLOCKER_LEDGER.md` B-10.

| Gate | Result |
|---|---|
| Full backend regression on the frozen revision `169bd57` | **1293 passed, 0 failed**, 1577.08s (0:26:17), exit 0 (`work/current-change/full_run_round35.log`). The delta from 1235 is accounted for: +17 (4 QA + 13 module-metric tests), +8 (split/calibration tests), +33 (the DeepSeek switch-window config guards) = 1293. The row's earlier measurement stands as history: **1235 passed, 0 failed**, 1467.07s, exit 0 on `6e65396` (`work/current-change/full_run_round30_final2.log`) |
| Sub-suites re-measured on the frozen revision (round 35) | **Jev + DeepSeek set (23 files): 343 passed / 0 failed** — gateway, absent-ledger, orchestrator wiring, the twelve call sites, capability router + dispatch, extraction, entity resolution, evidence consistency + wiring, citation audit + binding, feedback triage, tool-intent endpoint, calibration, A/B/C/D/E + semantic ablation, module metrics, and the DeepSeek canary/contract/provider-role/config-guard suites. **Measurement + module-metric set (8 files): 121 passed / 0 failed.** **Zero-Laya production guard: 3 passed** |
| Jev module + call-site suites (A extraction, reference verification, business path, absent ledger, B entity resolution, C evidence consistency + wiring, D citation audit/evidence/binding, high-impact gate, E capability router + dispatch, F tool intent + endpoint, P2 feedback triage, the call sites themselves) | **208 passed** (measured on `6e65396`; the same files are inside the 343-test re-measurement above) |
| Host-wiring suite (orchestrator receives the shared service; receipts never stall a business call) | **4 passed** |
| Twelve call-site suite | **16 passed** |
| Structured-insertion suites (shadow invariance 6, capability dispatch 10, tool-intent endpoint 8) | **24 passed** |
| Real-corpus golden suite (incl. the Chinese-alias → English-material case) | **6 passed** |
| Measurement layer (dataset build, calibration, A/B/C/D/E + the six component arms) | **97 passed**; offline runs exit 0, arms tagged `NON_INTERPRETABLE_PLUMBING_ONLY` |
| Zero-Laya production guard | **3 passed** |
| Catalog integrity | green with 19 definitions |
| Migrations on an isolated database (measured on `6e65396`; no schema change since — `LATEST_V3_SCHEMA_VERSION` is still `30` in `app/db.py`, with 026–030 the newest files) | `expected_schema=30`, idempotent replay, `integrity=ok`, `fk_violations=0`, `max_migration=30`, no `*_old`/`*_new` leftovers |
| agent-api | real `tsc --noEmit` **exit 0**, **92 tests passed** (12 files), build **exit 0** |
| Web app | real `tsc --noEmit` **exit 0**, **73 tests passed** (19 files), build **exit 0** (68/18 before the reference-gate note added its 5 tests) |
| Browser journeys (real Chrome, isolated identity, real three-service shape) | `ui-refresh.spec.ts` **19/19**, `jev-structured.spec.ts` **6/6** (three new module-A journeys), `coursemate.spec.ts` **4**, `learning.spec.ts` **3** — **32 journeys, 0 failed** |
| Ruff | **1815 errors before and 1815 after** this round's three-file change, measured on `app` + `tests` with `services/rag-api` as the working directory (the cwd changes ruff's verdict — recorded in `CHATGPT_REVIEW_CURRENT_STATUS_AND_BLOCKERS.md` §6). Mid-round the count did rise to **1821** when the ablation-harness rename pushed six lines past 100 columns; those were rewrapped in their own commit, so the total is back to 1815 rather than claimed unchanged without measuring |
| mypy | whole-app: **1004 errors in 32 files** (from 1074/39 when this report was first written, and 1077/38 when it was actually re-measured on `cfd0ef1`). **`app/jev/` and `app/evaluation/` now report zero errors**: six of this round's errors were fixed as real type defects in the Jev layer rather than deferred, and `app/jev/citation_evidence.py`, `app/evaluation/jev_semantic_ablation.py`, `app/evaluation/jev_ablation.py`, `app/evaluation/jev_calibration.py`, `app/evaluation/deepseek_canary.py`, `app/jev/receipt_store.py` and `app/jev/gateway.py` are each clean. What remains is legacy `cm_update`/`ui_extension` debt (728 of the 1004 in `app/cm_update/app.py`) and is reported by rule, not hidden. The earlier claim in this table that the count was "unchanged" was wrong and is corrected here |

The browser gate found one real product bug, which is fixed rather than papered over: a `GET /layout`
still in flight when the learner moved a reasoning-strength slider overwrote the new value on arrival,
and the next save wrote the stale value back, so the control visibly snapped back
(`apps/web/src/ui/pages.jsx`, `setStrength`/`load`). Three stale test expectations written against
earlier UI drafts and one weak assertion (which matched a textarea's own value instead of the persisted
comment) were corrected without weakening any product assertion.

## 5. Status markers (evidence-based, no marker promoted on plumbing)

**Re-checked 2026-09-22 (round 35).** No marker was promoted: every definition is still in `shadow`,
and the two live markers are still `NOT_RUN`. What changed is the *evidence* behind the local markers —
`JEV_GATEWAY` is now type-clean, the backend and browser gate numbers are current, and the agent
service has its own row. The rule this table follows is unchanged: a wired call site, a shadow receipt,
a fake transport or an HTTP 200 is never a PASS.

| Marker | Status | Basis |
|---|---|---|
| DETERMINISTIC_FIXES | **PASS** | learning-start fact, RRF fusion, raw-score projection, command router, and the reasoning-strength save race — all with regressions |
| DEEPSEEK_TEXT / VISION / AGENT | **LOCAL** | contract + host-spy tests prove the wiring and zero Qwen egress; live calls `NOT_RUN`. The switch-window configuration is now guarded as well: 33 tests pin the refusals (host allowlist, `/v1` path, scheme, embedded credentials, the `deepseek-flash` model pin, the missing credential, production pricing) and two ordering facts — validation runs before the database is opened, so a bad environment fails at boot without half-initialised state |
| PROMPT_V2_REGISTRY | **PASS** | 16/16 manifest hashes, V1 retained |
| JEV_GATEWAY | **PASS** (local) | gateway/catalog/receipts/cache/modes tested; one shared service app-wide; live TypeSafe `NOT_RUN`. **Type-clean since round 35**: the whole `app/jev/` layer reports zero mypy errors, and the two errors this file carried were fixed as narrowing rather than suppression |
| JEV_RETRIEVAL · JEV_CITATION · JEV_CONTEXT · JEV_INTENT · JEV_PEDAGOGY · JEV_COVERAGE · JEV_ASSESSMENT · JEV_CLASSIFICATION · JEV_EXERCISE_SELECTION · JEV_PREREQUISITE · JEV_CORPUS_QUALITY | **SOURCE_IMPLEMENTED + LOCAL_INTEGRATED**, all `shadow` | call-site suite plus the module suites; authority boundaries asserted |
| ENTITY_RESOLUTION | **PASS (local, shadow)** | wired into the authorized retrieval path, proposal-only store with an idempotency and degradation proof, per-concept expansion proven to preserve the original query, leave unrelated queries untouched, and reach the English material for a Chinese question on the real GE2324 corpus |
| EVIDENCE_CONSISTENCY | **PASS (local, shadow)** | wired into the evidence-pack step; byte-identical sources under off/shadow/unavailable/no-Jev, a real contradiction kept and explained through the teaching prompt, and version/assumption differences never presented as conflicts |
| CAPABILITY_ROUTER | **PASS (local, shadow)** | the decision is consumed (flow dispatch + reported on the response), zero-Jev explicit commands proven by receipt count, hardened against a hostile transport, and exercised end to end in real Chrome |
| TOOL_INTENT_CHECK | **PASS (local, default-off)** | real gate at the model-proposed write boundary on both sides, 14 Node tests + 8 endpoint tests + 12 guard tests; `off` proven to make no call |
| EXTRACTION_VERIFICATION | **PASS (local, shadow)** | wired in round 30 to the query-side exact-locator surface and consumed there: `reference_records`/`verify_query_reference` (29 tests incl. the negation residue and the owner-scoped cache), 4 tests driving the real `context.retrieve` adapter over a document labelled by the real chunker, the parser defect fixed with its prose cases pinned, and a real-browser journey reading the report out of the shipped QA page's own `POST /api/qa/chat` stream. An affirmative defect needs the live credential, so that half stays `NOT_RUN` |
| CITATION_AUDIT | **PASS (local, shadow)** | all three layers bound to the teaching path: a deterministic layer-2 verdict that costs zero model calls, a layer-1 re-check through the canonical ACL on a real migrated database (incl. cross-user and cross-course `unauthorized`), the verdict recorded on the card the client receives and marked in the shipped shell, an enforced per-answer budget, and byte-identical cards when no semantic layer is configured. A unit-regex defect that could fabricate a CONTRADICTION was found and fixed |
| USER_FEEDBACK_TRIAGE | **SOURCE_IMPLEMENTED + LOCAL_INTEGRATED + DURABLE** | module, backend route, durable queue (migration 030), admin reader and the caller's own list, shell entry; 17 triage tests + 6 queue tests + a real-browser journey through the dialog. The privacy rule is a schema CHECK, not a convention |
| LEARNING_PROGRESS · FIVE_QUESTION_ASSESSMENT | **PASS** (local) | regression suites plus the browser assessment journey (start → 5 questions → submit → graded) |
| LOCAL_REGRESSION | **PASS** | **1293 passed / 0 failed** on the frozen revision `169bd57` (1577.08s, exit 0, `work/current-change/full_run_round35.log`); `git diff 169bd57 -- services/rag-api benchmarks` is empty, so the run describes the committed tree. History kept rather than overwritten: the first measurement was **1235 passed / 0 failed** on `6e65396`, and before that the round's first run was 1226/2 with both failures a real defect in the Jev layer (an absent receipt ledger raising out of a learner request), fixed there rather than in the test. No test was renamed, skipped or weakened to reach 1293, and two tests drafted and then found to assert a false contract were **deleted** (B-10) |
| JEV_LIVE_VALIDATION · DEEPSEEK_LIVE_VALIDATION | **NOT_RUN** | no credential, no budget |
| ABLATION | **NOT_RUN** | harness and 310-sample dataset ready; no labelled live run |
| BROWSER_ACCEPTANCE | **PASS (local)** | **32 journeys / 0 failed** across four suites in real Chrome against the real services (`ui-refresh` 19, `jev-structured` 6 with three new module-A journeys, `coursemate` 4, `learning` 3), including the Jev-unavailable deployment; re-run on `6ba70b0` with `apps/` + `tests/e2e/` unchanged since. The seven further journeys the task lists are classified per item in `JEV_CALLSITE_MATRIX.md` (Skill selection and Jev-unavailable exist as browser journeys; alias retrieval, tool misexecution, extraction verification and unsupported citation are verified at their real boundaries with the reasons stated; a condition-conflict journey cannot exist until a live credential produces `SAME_CONTEXT_CONTRADICTION`). Production browser acceptance remains `NOT_RUN` |
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
* Module **A (extraction)** is wired (round 30) to the query-side exact-locator label — the surface the
  earlier investigation had missed — and its disposal rule can only ever *remove* an exact-locator
  filter, so it cannot widen what a learner may read. The document-side parser labels stay unwired with
  their original reasons recorded. Every structured module (A, B, C, D, E, F, feedback) is wired to a
  real business path with a consumer; none of them is promoted out of `shadow`.
* Module D's high-impact gate now runs: the reference solution is verified **before** it is used as
  grading evidence (deterministic layer 1 over its `source_ref` chunks plus the semantic support
  decision), a negative verdict marks that question `needs_review` with a reason, and no mark, weight,
  total, grade or coverage value is touched. The semantic half of the gate is recorded as `shadow` until
  a credential exists, like every other definition.
* **A production wiring defect was found and fixed this round**: the shared service was never handed to
  `LearningOrchestrator`, so call site 6 (pedagogy), 8 (criterion review) and 11 (prerequisite) were
  unreachable in a real deployment even though their tests passed with an injected service. Wiring them
  also exposed a latent hazard — grading calls the criterion review from inside its own write
  transaction — which is now solved properly: the receipt store can be handed the caller's open
  connection (`receipt_connection(...)`), so the receipt is written in that same transaction and commits
  or rolls back with the grade. Outside such a transaction the write stays best-effort and a lock
  conflict drops the receipt rather than stalling or failing the operation.
* The evidence-consistency conflict note and every D verdict other than the deterministic layer-2 one
  can only appear in mode `on`; with no TypeSafe credential they have never been produced by a live
  decision. What is proven today is that they are *absent* (and the prompt/cards byte-unchanged) in
  every mode the deployment can currently reach.
* The tool-intent gate ships **default-off**; with `off` (the current production setting) it makes no
  call and changes nothing, so its enforcement path has never run against a live model in production.
* The user-feedback review queue is now **durable** (migration 030, `feedback_reports`),
  written idempotently by report key with a schema-level CHECK that refuses any body text
  without the submitter's opt-in, and read by an admin-only queue endpoint.
* The exact-locator parser carried a real defect until round 30: a word following the number donated its
  first letter as a phantom sub-part (`question 5 have …` → `question_part='h'`, `q mean` →
  `question_number='M'`), and that phantom label became a hard chunk-metadata filter. It suppressed
  legitimate exact recall and could pin retrieval onto a wrong sub-question. Fixed at the parser, with
  the prose cases pinned as regression tests; the module-A wiring above is what made the defect visible.
* Whole-app mypy is honest rather than green: **1004 errors in 32 files** as of round 35 (it read
  **1074 in 39 files** when this section was written, and the claim made here and in the evidence table
  that the count was "unchanged" was **wrong** — re-measuring showed 1077/38, because rounds 25–31 had
  in fact moved it). What the later rounds cleaned up is the whole Jev layer, not the legacy debt:
  `app/jev/` and `app/evaluation/` now report **zero** errors, while the inherited `cm_update` /
  `ui_extension` debt (728 of the 1004 in `app/cm_update/app.py`) is still **not** cleaned up and is
  reported by rule rather than hidden. The full accounting, including the six in-scope defects fixed in
  round 35 and the one strict-mypy trade-off, is in `docs/recovery/CURRENT_BLOCKER_LEDGER.md` B-10.
* Production browser acceptance, production deployment and production acceptance have not run.

## 8. What the next round must do

1. Move the semantic calls that run inside a business write transaction out of it (or write their
   receipts on the caller's connection), so the assessment grading path never drops a receipt — the
   only known place where the ledger and a business transaction contend.
2. Extend the labelled dataset with samples for the five module definitions that currently report
   `INSUFFICIENT_SAMPLES` (`extraction.field_grounded.v1`, `entity.relation.v1`,
   `evidence.consistency.v1`, `teaching.capability.v1`, `tool.intent.v1`) — a sampling task that needs
   the live model and the owner's budget.
3. Add the browser journeys that can exist once a credential does (condition conflict, unsupported
   citation end to end, and an extraction verdict that actually *drops* a label); the tool-misexecution
   journey is impossible while the E2E agent uses the deterministic model client.
4. Re-run the whole gate on one frozen APPLICATION SHA.
5. Only then the live gate: TypeSafe credential + bounded budget, DeepSeek key, release window, one
   real login — followed by backup, isolated rehearsal, migration 026–029, immutable release, real
   acceptance and post-release monitoring.
