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
| Jev never writes grades, LEARNED, permissions, coverage or budgets | `app/jev/**` writes only the receipt table; call-site tests assert learning/grade/coverage row counts are unchanged across a full flow |
| Choice may only pick a server-supplied id | `JevGateway._validate` rejects an unknown candidate id with `JEV_INVALID_RESPONSE` |
| Score/Noul are signals, never marks | `probability_is_grade=false`; no call site multiplies a Score into a mark. `Score × 100` is forbidden by design and by test |
| Deterministic code owns arithmetic, state and writes | marks 10/15/20/25/30, totals, grade versions, `grade_snapshots`, learning state transitions |
| Jev failure never breaks the product | typed errors → documented deterministic fallback, one attempt, no retry, labelled as a fallback |
| Jev never sees unauthorized material | identity + course authorization + file-scope filtering run **before** the call; the payload carries only the fragments one decision needs |
| The browser never calls TypeSafe | Jev credentials exist only in the backend env; the frontend has no Jev route or key |

## 3. Modes

`off | shadow | on | advisory`, resolved per definition by `JevGateway.mode_for(key)`, default
`shadow`. In `shadow` the deterministic result is what the user sees and the Jev suggestion is
recorded in a receipt; `on` uses the Jev value only when it validates; `advisory` surfaces the
suggestion to a review path without changing the outcome. Promotion is per definition and requires
calibration evidence — never a global switch, and never a fixed `0.8` threshold.

## 4. The twelve definitions

The catalog (`app/jev/decision_catalog.json`) is the single list; ids and versions are stable.

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
  → merge → dedupe → global RRF → Jev rerank → evidence bundle → DeepSeek
```

* Jev may only **reorder** what the fusion already authorized; it can neither add nor delete a source.
* An explicit filename / page / question-number request is resolved by the deterministic exact
  locator and its slot is protected — a semantic score may not replace the user's specified question.
* Private candidates must be able to outrank official ones; the fusion applies a per-scope recall cap
  before the single global ranking, which is what prevents "official fills top_k first".
* If Jev times out or is unavailable, the original RRF order stands and the answer still ships.

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
| The 12 call sites | `JEV_CALLSITE_MATRIX.md`; the real business wiring is the round's active workstream |
| Calibration / A-B-C-D-E ablation | harness + dataset ready; **result `NOT_RUN`** (no live Jev, no labelled run) |
| Production deployment / acceptance | `NOT_RUN` — requires the credential and release window in `MINIMAL_OWNER_ACTION_CARD.md` |

No element of this architecture is claimed to improve teaching quality: that requires the ablation to
run on labelled data with a real Jev, which has not happened.
