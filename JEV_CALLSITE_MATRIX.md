# Jev Call-Site Matrix

One row per decision definition. Every definition shares `version = 1.0.0-design`
(the catalog `version`), `default_runtime_mode = shadow`, and the same 8-way cache
scope. All 12 remain **`shadow`** today — nothing is `on`/`advisory`. There is no
live Jev call anywhere: the offline `FakeTransport` is the only transport that has
run, so `live evidence = NOT_RUN` for every row.

Column key:

* **affects final state** — `No (shadow)` means `used_jev == False` today, so the
  deterministic fallback is what the business uses. The parenthetical notes the
  *only* effect the definition is allowed to have if it is ever promoted to `on`.

| # | definition id | business entry point | who calls / when | input state | Jev returns | behaviour change | fallback | affects final state | test |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `retrieval.support.v1` | `domain.py::_retrieve` → `callsites.rerank_retrieval` | `V3DomainAdapter`; after global RRF fusion, before source budgeting | `query, exact_target, candidate_id, candidate_text, source_metadata` | Score `0..4` per authorized candidate | reorders non-exact candidates only; exact file/page/question targets keep their slot; never add/drop | original fused RRF order | No (shadow) — reorder only | `test_rerank_exact_target_keeps_slot_under_hostile_rerank`, `test_rerank_private_candidate_still_ranked`, `test_retrieve_wiring_annotates_citation_support` |
| 2 | `source.supports_claim.v1` | `domain.py::_annotate_evidence` → `answers.evidence_bundle_support` → `callsites.citation_support` | `V3DomainAdapter`; pre-DeepSeek evidence-bundle check, after rerank | `claim, source_span, source_version, task_scope` | Noul `P(supports)` | annotates the selected span `SUPPORTED`/`UNSUPPORTED`/`UNVERIFIED`; never deletes a source | keep evidence, `UNVERIFIED` | No (shadow) — annotation only | `test_retrieve_wiring_annotates_citation_support` |
| 3 | `source.select_span.v1` | `domain.py::_annotate_evidence` → `answers.evidence_bundle_support` → `callsites.select_citation_span` | `V3DomainAdapter`; same evidence-bundle check | `claim, candidate_spans` | Choice among supplied span ids or `NO_SUPPORT` | selects one supplied span; never authors a citation | `NO_SUPPORT`, keep evidence | No (shadow) — selection only | `test_retrieve_wiring_annotates_citation_support` |
| 4 | `context.keep_segment.v1` | `cm_update/app.py::run` → `callsites.keep_history_segment` | `cm_update` run route; filtering the shell history window | `segment, current_task, fixed_anchor, remaining_scope` | Noul `P(keep)` | only FILTERABLE history is offered; MUST_KEEP anchors/current question never dropped | keep MUST_KEEP + bounded recent window | No (shadow) — drop of a filterable segment | `test_context_must_keep_anchor_preserved_when_transport_says_drop`, `test_context_shadow_never_drops_segment` |
| 5 | `intent.next_action.v1` | `cm_update/app.py::run` → `callsites.route_next_action` | `cm_update` run route; only after `route_explicit_command` returns `None` | `message, fixed_anchor, current_mode, active_assessment` | Choice among 8 action ids | classifies ambiguous phrasing only; explicit commands cost 0 Jev; never changes Thinking/strength | `OTHER` (DeepSeek, no forced advance) | No (shadow) — routing signal only | `test_explicit_commands_make_zero_jev_calls` |
| 6 | `pedagogy.next_method.v1` | `orchestrator.py::teach` → `callsites.select_pedagogy_method` | `LearningOrchestrator.teach`; written into the plan→work teaching context | `learner_request, known_prior_evidence, topic, template_profile, current_step` | Choice among `WORKED_EXAMPLE/TRACE/DEFINITION/COUNTEREXAMPLE/COMPARE/CONTINUE` | chosen method written into `context` the DeepSeek plan→work step consumes; never removes REQUIRED template content | versioned template default (`CONTINUE`) | No (shadow) — presentation hint only | `test_full_wired_flow_writes_no_learning_grade_or_coverage` |
| 7 | `coverage.item_support.v1` | `domain.py::_submit_delivery` → `callsites.coverage_item_support` | `V3DomainAdapter`; delivery submission, recorded in `provenance` only | `saved_delivery, required_item, valid_spans, node_spec_version` | Choice `SUPPORTED/PARTIAL/UNSUPPORTED/UNCERTAIN` | per-REQUIRED-item signal recorded; reviewer + quote/hash validation still decide coverage; never `UPDATE … LEARNED` | `UNCERTAIN` (coverage stays pending) | No (shadow) — never claims coverage | `test_coverage_item_support_uncertain_on_fallback`, `test_coverage_service_none_is_uncertain` |
| 8 | `assessment.criterion_review.v1` | `assessments.py::save_submission` → `_apply_jev_criterion_review` → `callsites.review_criterion` | `AssessmentService`; inside the five-question grading loop per frozen criterion | `frozen_question, frozen_rubric_criterion, reference_solution, student_answer, deterministic_verification, candidate_answer_spans` | Choice `SATISFIED/PARTIAL/NOT_SATISFIED/NEEDS_REVIEW` | flag-only: can set `needs_review` (uncertainty/contradiction); never changes the mark fraction, never zeroes | existing grader / `NEEDS_REVIEW` | No (shadow) — backend owns mark range, weights, total, grade version | `test_criterion_review_failure_never_flags_review`, `test_review_criterion_fallback_is_not_a_jev_signal` |
| 9 | `template.match.v1` | `cm_update/app.py::classify_course_task` → `callsites.match_template` | `cm_update`; after a course upload, layered on the DeepSeek classification | `course_title, curriculum_samples, materials_revision, known_course_level` | Choice (stage 1 degree → stage 2 template id) | hierarchical degree→template signal recorded; DeepSeek classification stays authoritative; never infers learner's degree | `OTHER` | No (shadow) — advisory `jev_template_id` only | `test_template_match_service_none_returns_other`, `test_template_match_shadow_returns_other`, `test_template_match_on_selects_valid_template` |
| 10 | `exercise.prototype.v1` | `cm_update/app.py::generate_exercise_run` → `callsites.select_exercise_prototype` | `cm_update`; exercise generation for the current node | `node, eligible_prototypes, recent_exposures, learning_evidence` | Choice among authorized prototype ids or `NONE` | selects among server-authorized prototypes; never sees hidden answers, never invents a source | `NONE` (existing generation) | No (shadow) — selection only | `test_full_wired_flow_writes_no_learning_grade_or_coverage` |
| 11 | `graph.prerequisite.v1` | `knowledge.py::select_repair_prerequisite` → `callsites.select_prerequisite` | `KnowledgeService` (from `orchestrator.teach` on remediation); legal neighbours only | `current_node, error, allowed_predecessor_nodes` | Choice among legal predecessors or `NONE` | selects a legal predecessor to review; never creates/publishes a knowledge node | published prerequisite order (first legal predecessor) | No (shadow) — selection only | `test_full_wired_flow_writes_no_learning_grade_or_coverage` |
| 12 | `corpus.quality.v1` | `cm_update/app.py::upload` → `callsites.assess_corpus_quality` | `cm_update`; document upload parse (also reusable for pool prep / offline review) | `document_fragment, source_metadata, parse_flags` | Score `0..3` | mark-only parse-quality flag (missing pages/stems/params/weak sourcing/duplicates); never auto-deletes a file | retain original, mark parse limitations (`1`) | No (shadow) — mark only | `test_oversized_input_falls_back_without_half_sending` |

## Rule-12 input budget + provenance

`SemanticDecisionService.bound_state` caps the state payload per definition, keeps the
decisive fields (current question, key conditions, negations, numbers, units) verbatim,
and drops only non-decisive fields that do not fit; an oversized decisive field raises
`InputBudgetExceeded` and falls back (`fallback:input_too_long`) instead of half-sending.
Per call it records: definition key + version, state char budget, candidate count, input
token estimate, trimmed flag, latency, outcome — exposed via `service.summary()`.
Covered by `test_oversized_input_falls_back_without_half_sending` and
`test_input_budget_provenance_recorded`.

## No-state-write invariant

`test_full_wired_flow_writes_no_learning_grade_or_coverage` drives every one of the 12
call sites with a successful `FakeTransport` in `on` mode and asserts learning/grade/
coverage row counts are unchanged while the only write is to `jev_decision_receipts`.

## Requests to other workstreams

1. **Host wiring (default-off today).** `cm_update.create_app(jev=…)` and
   `LearningOrchestrator(…, jev=…)` now accept a `SemanticDecisionService`, but no
   production caller passes one yet. Wire `JevGateway` + `SqlReceiptStore(database)` in
   `app/main.py` / `app/cm_update/integration.py` / `app/ui_extension/mount.py` once a
   TypeSafe credential exists (still `shadow`).
2. **Single-call per-candidate batching.** `retrieval.support.v1` still makes one gateway
   call per candidate; the SDK `system_one(state, questions)` supports multiple questions
   in one call, which would need a multi-question `evaluate` on `JevGateway` (transport
   contract was not touched).
3. **Grounded-QA citation support.** `answers.evidence_bundle_support` is the shared
   citation check (invoked from `domain._retrieve`); `app/services/qa.py::QaService.stream`
   is its intended second caller and is outside the listed edit scope.
