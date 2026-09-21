# Existing → New mapping (structured enhancement round)

One entry per capability. Each entry records the **existing function**, its **real
call point**, **what was missing**, **what this round changes**, the **deterministic
rules**, the **Jev judgment**, **how the result affects business behaviour**, the
**fallback**, and the **tests**. "Reused" means the existing capability/definition is
used as-is (possibly with a richer wrapper); "new" means a new definition id is
proposed.

## Reuse before adding (explicit)

* `retrieval.support.v1` — **reused, unchanged** (module C sits *after* it).
* `source.supports_claim.v1` and `source.select_span.v1` — **reused, unchanged** by
  module D (`ClaimCitationAudit` calls `SemanticDecisionService.supports_claim` /
  `.select_span`, the same two definitions the thin `callsites` wrappers use).
  No second citation service or definition was added.
* `evidence.consistency.v1` — **new** definition id (module C), held as a module
  constant; the gateway path (modes/bounds/receipts/validation) is fully reused.
* `extraction.field_grounded.v1` — **new** definition id owned by module A (another
  workstream); described here for completeness, not owned by this round.
* The gateway, `SemanticDecisionService`, the receipt store, the cache scope and the
  deterministic fusion (`retrieval_orchestrator.py`) are all **reused, not replaced**.

---

## 1. Retrieval rerank — `retrieval.support.v1` (Score 0..4)

* **existing function** — `SemanticDecisionService.rerank_retrieval` / `retrieval_support`, exposed as `callsites.rerank_retrieval`.
* **real call point** — `app/ui_extension/domain.py::_retrieve`, after `fuse_scoped_candidates`, before source budgeting.
* **what was missing** — nothing this round; this is the protected baseline that modules C/D must not regress.
* **what this round changes** — none. Module C is inserted *after* this rerank and only annotates.
* **deterministic rules** — exact file/page/question targets keep their slot (never offered to Jev); official never crowds out private; only non-exact candidates are reordered; no add/drop.
* **Jev judgment** — per-candidate support score, used only when `used_jev` and mode `on`.
* **affects business behaviour** — reorders non-exact candidates only (today `shadow`, so no effect).
* **fallback** — original fused RRF order.
* **tests** — `test_rerank_exact_target_keeps_slot_under_hostile_rerank`, `test_rerank_private_candidate_still_ranked`, `test_retrieval_fusion_unit.py`.

## 2. Citation support (thin layer) — `source.supports_claim.v1` (Noul)

* **existing function** — `SemanticDecisionService.supports_claim`, exposed as `callsites.citation_support`.
* **real call point** — `app/rag/answers.py::evidence_bundle_support`, called from `domain.py::_annotate_evidence`.
* **what was missing** — a deterministic existence/authorization and quote-existence gate before the semantic call (the thin layer judges a span with no quote/authorization check).
* **what this round changes** — module D reuses this definition *inside* its three-layer audit; the thin annotation path is unchanged.
* **deterministic rules** — none at this layer (semantic); layers 1–2 in module D run first.
* **Jev judgment** — "does this supplied span support this exact claim" (Noul probability).
* **affects business behaviour** — annotates `SUPPORTED`/`UNSUPPORTED`/`UNVERIFIED`; never deletes a source (today `shadow`).
* **fallback** — `UNVERIFIED` (keep evidence).
* **tests** — `test_retrieve_wiring_annotates_citation_support`; `test_jev_citation_audit.py` (via module D).

## 3. Citation span selection — `source.select_span.v1` (Choice)

* **existing function** — `SemanticDecisionService.select_span`, exposed as `callsites.select_citation_span`.
* **real call point** — `app/rag/answers.py::evidence_bundle_support`.
* **what was missing** — span ids had to be backend-supplied at the call site; no audit bound them to a located document.
* **what this round changes** — module D reuses `select_span` to pick among backend-supplied spans; the selected id is never invented.
* **deterministic rules** — candidate ids are server-supplied only; the gateway rejects an unknown Choice id.
* **Jev judgment** — "which supplied span best supports the claim" (Choice or `NO_SUPPORT`).
* **affects business behaviour** — selects one supplied span id only (today `shadow`).
* **fallback** — `NO_SUPPORT`, keep evidence.
* **tests** — `test_retrieve_wiring_annotates_citation_support`; `test_span_selection_reuses_backend_supplied_ids`.

## 4. Citation audit (full) — module D, reuses #2 + #3

* **existing function** — none; **new service** `app/jev/citation_audit.py::audit_citation` / `ClaimCitationAudit`.
* **real call point** — intended for the grounded-QA stream and any DeepSeek-proposed claim/quote (not wired into `qa.py` this round; `domain._retrieve` keeps the thin annotation).
* **what was missing** — case 4 + case 10 had no single three-layer check (existence/authorization → quote existence → support).
* **what this round changes** — one service with layers 1–2 deterministic and layer 3 semantic, five evidence labels + `REJECTED`.
* **deterministic rules** — layer 1 (document/version/location exists + caller authorized) via `EvidenceResolver`; layer 2 (`quote_exists`) via whitespace-only normalization that never erases a sign/inequality/number/unit; direct numeric conflict is a unit-aware deterministic check.
* **Jev judgment** — layer 3 only: `source.supports_claim.v1` (+ `source.select_span.v1`), mapped to `SUPPORTED`/`PARTIALLY_SUPPORTED`/`CONTRADICTED`/`NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE`.
* **affects business behaviour** — gates "verified" display (`is_verified`), holds high-impact material open until `is_definitive`, rejects unauthorized/missing citations with zero Jev.
* **fallback** — `INSUFFICIENT_CONTEXT` (never "verified").
* **tests** — `test_jev_citation_audit.py` (13 tests).

## 5. Evidence consistency — module C, `evidence.consistency.v1` (Choice, **new**)

* **existing function** — none; **new service** `app/jev/evidence_consistency.py::check_evidence_consistency` / `EvidenceConsistency`.
* **real call point** — intended to sit in `domain._retrieve` between the rerank and the evidence pack (not wired; documented for the other workstream editing `domain.py`).
* **what was missing** — no condition/conflict check between candidate fusion and the evidence pack; a silent contradiction could reach DeepSeek.
* **what this round changes** — a bounded (≤ 8 pair) comparison over deterministically-narrowed pairs, with explicit unchecked-pair accounting.
* **deterministic rules** — pair narrowing by version/task/variable/concept; version/task differences are resolved with zero Jev; nothing is reordered or dropped; prompt-injection is a marker only.
* **Jev judgment** — classify each narrowed semantic pair as `SAME_CONTEXT_CONTRADICTION` / `DIFFERENT_ASSUMPTIONS` / `COMPATIBLE` / `INSUFFICIENT_EVIDENCE`.
* **affects business behaviour** — a real contradiction keeps both sources and requests a DeepSeek explanation; different assumptions are explained as scopes; missing evidence triggers a bounded extra read.
* **fallback** — `COMPATIBLE` (no conflict determined) with `used_jev=False`.
* **tests** — `test_jev_evidence_consistency.py` (8 tests).

## 6. Extraction verification — module A (owned by another workstream), `extraction.field_grounded.v1`

* **existing function** — `app/jev/extraction.py` (module A); `field_grounded_definition()` builds the pending `extraction.field_grounded.v1` definition locally.
* **real call point** — between the vision/parser pass and anything that teaches/grades (module A's wiring).
* **what was missing** — silently-wrong extraction (wrong field, dropped negation/constraint, unreadable region) could poison teaching/grading.
* **what this round changes** — **not owned by this round**; described as such. Deterministic checks first (required fields, numeric/unit, question-number shape, source exists + authorized), then Jev judges only the residue, then at most one bounded repair.
* **deterministic rules** — REJECTED/FLAGGED with zero Jev; a `GROUNDED` verdict never overrides an unreadable region; student answers repaired for legibility only.
* **Jev judgment** — `GROUNDED / WRONG_FIELD / NEGATION_LOST / CONSTRAINT_LOST / SOURCE_INSUFFICIENT / UNCERTAIN`.
* **affects business behaviour** — ACCEPTED / REJECTED / FLAGGED / NEEDS_REVIEW disposition for extraction records.
* **fallback** — deterministic result + `NEEDS_REVIEW` (typed `FallbackReason`).
* **tests** — `test_jev_extraction.py` (module A's; not owned here).

## 7. Coverage — `coverage.item_support.v1` (Choice)

* **existing function** — `SemanticDecisionService.item_support`, exposed as `callsites.coverage_item_support`.
* **real call point** — `domain.py::_submit_delivery` (recorded in provenance).
* **what was missing / changes** — unchanged this round.
* **deterministic rules** — the reviewer + quote/hash validation still decide coverage; Jev never claims coverage.
* **Jev judgment** — `SUPPORTED/PARTIAL/UNSUPPORTED/UNCERTAIN` per REQUIRED item.
* **affects business behaviour** — per-item signal only; never `UPDATE … LEARNED`.
* **fallback** — `UNCERTAIN` (coverage stays pending).
* **tests** — `test_coverage_item_support_uncertain_on_fallback`, `test_coverage_service_none_is_uncertain`.

## 8. Assessment criterion review — `assessment.criterion_review.v1` (Choice)

* **existing function** — `SemanticDecisionService.criterion_review`, exposed as `callsites.review_criterion`.
* **real call point** — `assessments.py::save_submission` → `_apply_jev_criterion_review`.
* **what was missing / changes** — unchanged this round.
* **deterministic rules** — backend owns mark range, weights, totals, grade version; Jev only sets `needs_review`.
* **Jev judgment** — `SATISFIED/PARTIAL/NOT_SATISFIED/NEEDS_REVIEW`.
* **affects business behaviour** — flag-only; never changes the mark fraction, never zeroes.
* **fallback** — existing grader / `NEEDS_REVIEW`.
* **tests** — `test_criterion_review_failure_never_flags_review`, `test_review_criterion_fallback_is_not_a_jev_signal`.

## 9. Intent routing — `intent.next_action.v1` (Choice)

* **existing function** — `SemanticDecisionService.next_action`, exposed as `callsites.route_next_action`.
* **real call point** — `cm_update/app.py::run`, only after `route_explicit_command` returns `None`.
* **what was missing / changes** — unchanged this round.
* **deterministic rules** — explicit commands (`继续/暂停/只回答/…`) are answered with zero Jev; Thinking/strength never changed.
* **Jev judgment** — classify ambiguous phrasing among 8 action ids.
* **affects business behaviour** — routing signal only.
* **fallback** — `OTHER` (DeepSeek, no forced advance).
* **tests** — `test_explicit_commands_make_zero_jev_calls`.

## 10. Pedagogy — `pedagogy.next_method.v1` (Choice)

* **existing function** — `SemanticDecisionService.next_method`, exposed as `callsites.select_pedagogy_method`.
* **real call point** — `orchestrator.py::teach`, written into the plan→work context.
* **what was missing / changes** — unchanged this round.
* **deterministic rules** — never removes REQUIRED template content; never a grade/model/budget choice.
* **Jev judgment** — `WORKED_EXAMPLE/TRACE/DEFINITION/COUNTEREXAMPLE/COMPARE/CONTINUE`.
* **affects business behaviour** — presentation hint only.
* **fallback** — versioned template default (`CONTINUE`).
* **tests** — `test_full_wired_flow_writes_no_learning_grade_or_coverage`.

## 11. Classification — `template.match.v1` (Choice)

* **existing function** — `SemanticDecisionService.match_template`, exposed as `callsites.match_template`.
* **real call point** — `cm_update/app.py::classify_course_task` (after upload).
* **what was missing / changes** — unchanged this round.
* **deterministic rules** — DeepSeek classification stays authoritative; never infers the learner's degree.
* **Jev judgment** — stage 1 degree → stage 2 template id (hierarchical).
* **affects business behaviour** — advisory `jev_template_id` only.
* **fallback** — `OTHER`.
* **tests** — `test_template_match_service_none_returns_other`, `test_template_match_shadow_returns_other`, `test_template_match_on_selects_valid_template`.

## 12. Exercise prototype — `exercise.prototype.v1` (Choice)

* **existing function** — `SemanticDecisionService.exercise_prototype`, exposed as `callsites.select_exercise_prototype`.
* **real call point** — `cm_update/app.py::generate_exercise_run`.
* **what was missing / changes** — unchanged this round.
* **deterministic rules** — only server-authorized prototype ids; never the answer, never an invented source.
* **Jev judgment** — select among authorized prototype ids or `NONE`.
* **affects business behaviour** — selection only.
* **fallback** — `NONE` (existing generation).
* **tests** — `test_full_wired_flow_writes_no_learning_grade_or_coverage`.

## 13. Prerequisite — `graph.prerequisite.v1` (Choice)

* **existing function** — `SemanticDecisionService.prerequisite`, exposed as `callsites.select_prerequisite`.
* **real call point** — `knowledge.py::select_repair_prerequisite` (remediation).
* **what was missing / changes** — unchanged this round.
* **deterministic rules** — legal graph neighbours only; never creates/publishes a node.
* **Jev judgment** — select among legal predecessors or `NONE`.
* **affects business behaviour** — selection only.
* **fallback** — published prerequisite order (first legal predecessor).
* **tests** — `test_full_wired_flow_writes_no_learning_grade_or_coverage`.

## 14. Corpus quality — `corpus.quality.v1` (Score 0..3)

* **existing function** — `SemanticDecisionService.corpus_quality`, exposed as `callsites.assess_corpus_quality`.
* **real call point** — `cm_update/app.py::upload` (parse review; reusable for pool prep).
* **what was missing / changes** — unchanged this round.
* **deterministic rules** — never auto-deletes originals; never auto-publishes official material.
* **Jev judgment** — offline evidence suitability score.
* **affects business behaviour** — mark-only parse-quality flag.
* **fallback** — retain original, mark limitations (`1`).
* **tests** — `test_oversized_input_falls_back_without_half_sending`.
