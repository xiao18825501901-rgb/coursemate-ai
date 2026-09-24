# JEV_BACKEND_ARCHITECTURE_FINAL

The fixed backend architecture for CourseMate after the owner stopped the Laya direction and restored
TypeSafe Jev. This document is the production source of truth for **who decides what**. Every claim
here is backed by the real code under `services/rag-api/app/` or by a named test; anything not yet
proven is marked `NOT_RUN` or `PARTIAL` rather than asserted.

---

## 1. The three layers

```
CourseMate request
  │
  ├── DeepSeek  (generation only)
  │     text · vision · plan → work · exercise (做一题) · problem solving · explanation (详解)
  │     · assessment reference solution · grading feedback · coverage explanation · Agent generation
  │
  ├── TypeSafe Jev  (fast typed semantic decisions only)
  │     JevGateway → SemanticDecisionService
  │       retrieval · citation · context · intent · pedagogy · coverage · assessment
  │       · template classification · exercise prototype · prerequisite · corpus quality
  │
  └── Deterministic backend  (authority)
        identity & course authorization · file-scope filtering · state machine · idempotency
        · exact locator · mark arithmetic and totals · learning state · accepted coverage evidence
        · transactions · every database write
```

**Jev is not a generator.** It answers Choice / Score / Noul questions over a bounded state and can
only *select among identifiers the server supplied*. There is no free-text channel, so it cannot
author teaching content, a citation, a page number or a document.

**DeepSeek does not replace Jev's judgments.** Generation and judgment are deliberately different
contracts: Jev exists to make cheap, repeatable, calibratable choices; DeepSeek exists to write.

**Qwen is not a production model and not an automatic fallback.** The historical explicit Qwen
configuration remains readable for compatibility, but no new production request is sent to Qwen, and
there is no silent switch to it. Embeddings stay on their own contract (`text-embedding-v4`) and are
not rebuilt because the generation or decision layer changed.

---

## 2. Authority boundaries (enforced in code, not by convention)

| Rule | Where it is enforced |
|---|---|
| Jev never writes grades, LEARNED, permissions, coverage or budgets | `app/jev/**` writes exactly two tables: `jev_decision_receipts` (every decision) and `entity_relations` (**proposals only**, `status='PROPOSED'`, nothing on the retrieval path reads or applies them). Call-site tests assert learning/grade/coverage row counts are unchanged across a full flow |
| Choice may only pick a server-supplied id | `JevGateway._validate` rejects an unknown candidate id with `JEV_INVALID_RESPONSE` |
| Score/Noul are signals, never marks | `probability_is_grade=false`; no call site multiplies a Score into a mark. `Score × 100` is forbidden by design and by test |
| Deterministic code owns arithmetic, state and writes | marks 10/15/20/25/30, totals, grade versions, `grade_snapshots`, learning state transitions |
| Jev failure never breaks the product | typed errors → documented deterministic fallback, one attempt, no retry, labelled as a fallback; a receipt that cannot be written is dropped rather than failing the business operation, and inside assessment grading the receipt is written on the caller's own connection so it commits and rolls back with the grade |
| Jev never sees unauthorized material | identity + course authorization + file-scope filtering run **before** the call; the payload carries only the fragments one decision needs. Module D's evidence resolver repeats that check against the canonical document ACL and answers `unauthorized` instead of leaking |
| The browser never calls TypeSafe | Jev credentials exist only in the backend env; the frontend has no Jev route or key. The one internal route (`POST /api/jev/tool-intent`) is token-gated and answers 503 when unconfigured |

## 3. Modes

`off | shadow | on`, resolved per definition by `JevGateway.mode_for(key)`, default `shadow` — and the
receipt table's CHECK constraint permits exactly those three.

* `off` — nothing is sent; the deterministic path runs.
* `shadow` — the call **is** made and its suggestion is recorded in the receipt ledger (and, at several
  call sites, as a safe annotation such as `jev_citation_support` or `jev_template_id`), but the
  deterministic value is what the product uses. This is the "advisory" state the task describes: the
  suggestion is observable without changing any outcome, which is why no separate `advisory` mode
  exists — inventing one would have to mean either calling the model (shadow already does) or
  surfacing the suggestion to a reviewer (the annotation and the `PENDING_REVIEW` paths already do).
* `on` — the validated suggestion is used, and only within the authority boundary each call site
  documents.

Promotion is per definition, requires calibration evidence, and is never a global switch or a fixed
`0.8` threshold.

**How a promotion is made, and what that does not mean.** Until round 87 nothing could promote a
definition in a running service: `JevGateway(modes=...)` was constructed by the evaluation harnesses
and by nothing else, so every deployment ran the catalogue default and a promotion could not even be
expressed. `JEV_DEFINITION_MODES` closes that gap — `key=mode` pairs, applied at startup by
`create_app` and validated against the catalogue:

| Setting | Effect |
|---|---|
| unset (default) | empty map: every definition runs the catalogue default (`shadow`), exactly as before |
| `JEV_DEFINITION_MODES="retrieval.support.v1=on"` | that one definition is used; everything else stays in shadow |
| an unknown definition key or mode | **the service refuses to start** |

The refusal is the important row. An unknown key is a typo that leaves the definition in `shadow`,
and an unknown mode is a misspelling of `on`; once the service is running, both are indistinguishable
from "the promotion had no effect" — the hardest kind of mistake to see from the outside, and exactly
the one somebody making a promotion is most likely to make. `MODES` in `gateway.py` is the single
vocabulary that the config validator and `mode_for` both use, so the two cannot drift apart.

What this does **not** mean, said plainly because the setting could be read as permission: the
mechanism existing is not a licence to use it. **Every definition is still `shadow`**, and must stay
so until §14's quality gate has passed for that definition. The live comparison on the calibration
split does not support a promotion today — it improves citation support and worsens
`criterion_error` and `key_fact_retention`, on populations of one to eight samples
(`JEV_CALIBRATION_AND_ABLATION_REPORT.md` §9). The setting also makes the browser acceptance
meaningful: the journey that would notice a live Jev asserts `used_jev === false`, which is false in
shadow whether or not a credential exists, so a test deployment that promotes one definition is what
turns that assertion into evidence.

## 4. The definitions

The catalog (`app/jev/decision_catalog.json`) is the single list; ids and versions are stable. It holds
**19** definitions: the twelve cases below plus the seven introduced by the structured-enhancement
round (`extraction.field_grounded.v1`, `evidence.consistency.v1`, `entity.relation.v1`,
`teaching.capability.v1`, `tool.intent.v1`, `feedback.category.v1`, `feedback.severity.v1`). All 19 are
in `shadow`.

| # | Definition | Primitive | Business intent |
|---|---|---|---|
| 1 | `intent.next_action.v1` | Choice | route an *ambiguous* follow-up; explicit commands never reach Jev |
| 2 | `retrieval.support.v1` | Score | re-rank already-authorized fused candidates (reorder only) |
| 3 | `source.supports_claim.v1` | Noul | does a supplied span really support the claim |
| 4 | `source.select_span.v1` | Choice | pick among server-supplied span ids |
| 5 | `context.keep_segment.v1` | Noul | keep/drop **filterable** context segments only |
| 6 | `pedagogy.next_method.v1` | Choice | choose the presentation method for the next teaching step |
| 7 | `coverage.item_support.v1` | Choice | support signal for one REQUIRED item (advisory) |
| 8 | `assessment.criterion_review.v1` | Choice | per-criterion semantic review inside grading |
| 9 | `template.match.v1` | Choice | classify a newly uploaded course into one of 14 templates or OTHER |
| 10 | `exercise.prototype.v1` | Choice | pick an exercise prototype among authorized candidates |
| 11 | `graph.prerequisite.v1` | Choice | pick a prerequisite among legal graph neighbours |
| 12 | `corpus.quality.v1` | Score | flag material/parse quality problems for review |

`JEV_CALLSITE_MATRIX.md` records, per definition, the business entry point, the state, who calls it,
when, what the answer changes, the fallback, the tests and the live-evidence status.

## 5. Retrieval chain (unchanged and protected)

```
authorized scopes → exact locator → official / private / workspace recall
  → merge → dedupe → global RRF → Jev rerank → entity relations (proposals only)
  → evidence consistency (conflict note) → evidence bundle → DeepSeek
  → citation audit bound to the message revision → citation cards
```

* Jev may only **reorder** what the fusion already authorized; it can neither add nor delete a source.
* An explicit filename / page / question-number request is resolved by the deterministic exact
  locator and its slot is protected — a semantic score may not replace the user's specified question.
* Private candidates must be able to outrank official ones; the fusion applies a per-scope recall cap
  before the single global ranking, which is what prevents "official fills top_k first".
* If Jev times out or is unavailable, the original RRF order stands and the answer still ships.
* **Entity relations** are written as proposals (migration 029) and never applied: the fused order and
  the source ids are byte-identical under `off`/`shadow`/unavailable/no-Jev. Query expansion adds the
  other accepted names of a concept *only when the query itself names that concept*, so an unrelated
  question is never widened by a course-wide alias list.
* **Evidence consistency** annotates each source deterministically and surfaces a genuine
  `SAME_CONTEXT_CONTRADICTION` to the teaching prompt as a bounded note, so DeepSeek explains both
  sides with every source kept; version and assumption differences are never called conflicts. The
  prompt is byte-unchanged whenever the decision is not a real signal.
* **The citation audit** runs after generation: layer 2 is deterministic (a figure the claim asserts
  that the source never states is `NOT_ADDRESSED…` at zero model cost), layer 1 re-checks existence and
  authorization at the message revision through the canonical document ACL, and layer 3 is the semantic
  support decision. Cards are annotated, never dropped or reordered; with no semantic layer configured
  they are byte-identical to before the audit existed. At most 6 cards per answer bound the cost.
* **The assessment reference solution** is verified before it is used as grading evidence: a stale,
  unauthorized or contradicted reference flags that question `needs_review` with a reason, and no mark,
  weight, total, grade or coverage value is touched.

## 6. Failure and degradation policy

| Failure | Behaviour |
|---|---|
| Jev timeout / unavailable / queue full | deterministic path; receipt records the fallback reason |
| Jev returns an invalid or unknown id | rejected, fallback, no user-visible effect |
| Input does not fit the decision's budget | fall back deterministically rather than send half a question |
| Coverage uncertain or Jev down | `PENDING_REVIEW` — never "student has not learned" |
| Assessment criterion uncertain | the existing review path; a Jev failure never scores zero |
| Retrieval rerank unavailable | original RRF order |

Detailed credential handling, data-scope rules and the failure matrix live in
`JEV_SECURITY_AND_FAILURE_MODES.md`.

## 7. Evidence status of this document

| Element | Status |
|---|---|
| DeepSeek-only generation with zero Qwen egress | `DEEPSEEK_TEXT/VISION/AGENT` wiring proven by contract + host-spy tests; live calls `NOT_RUN` |
| Jev gateway, catalog, receipts, cache, modes | implemented and tested; live TypeSafe calls `NOT_RUN` (no credential) |
| The 12 case call sites | wired and reachable in the production wiring: the single shared service is threaded into `LearningOrchestrator` (pedagogy 6, criterion review 8, prerequisite 11), the UI extension (retrieval, citation, coverage, entity resolution, evidence consistency), the run endpoint (intent, context, template, exercise, capability routing, citation audit) and the two internal APIs; `tests/test_jev_orchestrator_wiring.py` pins the chain. Per-definition entry points, state, fallbacks and tests: `JEV_CALLSITE_MATRIX.md` |
| The six structured modules | B, C, D, E, F, A and the P2 feedback module are all wired with a consumer. **A (ExtractionVerification) was `MODULE_ONLY` until round 30**, when the *query-side* exact-locator surface was found (`parse_query_reference` → a hard chunk-metadata filter); the reversal, the reproduced parser defect it fixed and the disposal rule are recorded in `docs/jev-structured/SOURCE_EXTRACTION_AND_ENTITY_RELATIONS.md` §9.4 |
| Calibration / A-B-C-D-E ablation | harness, dataset and split manifest ready, the six component arms added; **result `NOT_RUN`** (no live Jev, no labelled run). Five of the six component arms report `INSUFFICIENT_SAMPLES` because the frozen dataset has no samples for their definitions, and the harness refuses to invent a number |
| Production deployment / acceptance | `NOT_RUN` — requires the credential and release window in `MINIMAL_OWNER_ACTION_CARD.md`; the release-candidate state is in `FINAL_COURSEMATE_JEV_DEEPSEEK_PRODUCTION_REPORT.md` |

No element of this architecture is claimed to improve teaching quality: that requires the ablation to
run on labelled data with a real Jev, which has not happened.
