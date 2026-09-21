# Jev Call-Site Matrix

Two tables, because the system now has two kinds of definition:

1. **the 12 case definitions** (the original Jev catalog rows) — table 1;
2. **the six structured-enhancement modules** (round-7 P0/P1/P2 work) — table 2,
   each of which either reaches a real business path or is explicitly marked
   `MODULE_ONLY` with the reason.

Every definition in the catalog shares `version = 1.0.0-design` (the catalog
`version`), `default_runtime_mode = shadow`, and a server-derived cache scope.
**All 19 definitions are `shadow` today.** No live Jev call has ever been made:
the offline `FakeTransport` is the only transport that has run, so
`live evidence = NOT_RUN` for every row. A row whose effect column says
`No (shadow)` is one where `used_jev == False`, so the deterministic result is
what the business uses; the parenthetical names the only effect the definition is
allowed to have if it is ever promoted to `on`/`advisory`.

Column key:

* **batch?** — whether one decision covers several questions, i.e. the call is
  batched rather than one call per item;
* **state source** — where the state fields come from (server-derived, never
  client- or model-supplied);
* **affects business result** — what changes in the product today
  (`No (shadow)` = nothing changes yet; the parenthetical is the permitted effect).

## Table 1 — the 12 case definitions

| # | definition id | business entry point | who calls / when | state source | state fields | Jev returns | batch? | behaviour change | fallback | affects business result | cache scope | test | live evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `retrieval.support.v1` | `domain.py::_retrieve` → `callsites.rerank_retrieval` | `V3DomainAdapter`; after global RRF fusion, before source budgeting | authorized fused candidates | `query, exact_target, candidate_id, candidate_text, source_metadata` | Score `0..4` per candidate | No (per candidate) | reorders non-exact candidates only; exact file/page/question targets keep their slot; never add/drop | original fused RRF order | No (shadow) — reorder only | owner + `retrieval` + course/workspace/revision | `test_rerank_exact_target_keeps_slot_under_hostile_rerank`, `test_rerank_private_candidate_still_ranked`, `test_retrieve_wiring_annotates_citation_support` | NOT_RUN |
| 2 | `source.supports_claim.v1` | `domain.py::_annotate_evidence` → `answers.evidence_bundle_support` → `callsites.citation_support` | `V3DomainAdapter`; pre-DeepSeek evidence-bundle check, after rerank | backend-selected span + its source version | `claim, source_span, source_version, task_scope` | Noul `P(supports)` | No | annotates the selected span `SUPPORTED`/`UNSUPPORTED`/`UNVERIFIED`; never deletes a source | keep evidence, `UNVERIFIED` | No (shadow) — annotation only | owner + `citation` + course/workspace | `test_retrieve_wiring_annotates_citation_support` | NOT_RUN |
| 3 | `source.select_span.v1` | `domain.py::_annotate_evidence` → `answers.evidence_bundle_support` → `callsites.select_citation_span` | `V3DomainAdapter`; same evidence-bundle check | backend span ids | `claim, candidate_spans` | Choice among supplied span ids or `NO_SUPPORT` | Yes — all supplied spans in one call | selects one supplied span; never authors a citation | `NO_SUPPORT`, keep evidence | No (shadow) — selection only | owner + `citation` + course/workspace | `test_retrieve_wiring_annotates_citation_support` | NOT_RUN |
| 4 | `context.keep_segment.v1` | `cm_update/app.py::run` → `callsites.keep_history_segment` | `cm_update` run route; filtering the shell history window | the FILTERABLE history window only (never the current turn) | `segment, current_task, fixed_anchor, remaining_scope` | Noul `P(keep)` | No (per segment) | only FILTERABLE history is offered; MUST_KEEP anchors/current question never dropped | keep MUST_KEEP + bounded recent window | No (shadow) — drop of a filterable segment | owner + `intent` + course | `test_context_must_keep_anchor_preserved_when_transport_says_drop`, `test_context_shadow_never_drops_segment` | NOT_RUN |
| 5 | `intent.next_action.v1` | `cm_update/app.py::run` → `callsites.route_next_action` | `cm_update` run route; only after `route_explicit_command` returns `None` | message + mode + assessment state | `message, fixed_anchor, current_mode, active_assessment` | Choice among 8 action ids | No | classifies ambiguous phrasing only; explicit commands cost 0 Jev; never changes Thinking/strength | `OTHER` (DeepSeek, no forced advance) | No (shadow) — routing signal only | owner + `intent` + course | `test_explicit_commands_make_zero_jev_calls` | NOT_RUN |
| 6 | `pedagogy.next_method.v1` | `orchestrator.py::teach` → `callsites.select_pedagogy_method` | `LearningOrchestrator.teach`; written into the plan→work teaching context | node/journey/covered evidence | `learner_request, known_prior_evidence, topic, template_profile, current_step` | Choice among `WORKED_EXAMPLE/TRACE/DEFINITION/COUNTEREXAMPLE/COMPARE/CONTINUE` | No | chosen method written into `context["jev_pedagogy_method"]` the DeepSeek plan→work step consumes; never removes REQUIRED template content | versioned template default (`CONTINUE`) | No (shadow) — presentation hint only | owner + `pedagogy` + workspace/node/spec_version | `test_full_wired_flow_writes_no_learning_grade_or_coverage` | NOT_RUN |
| 7 | `coverage.item_support.v1` | `domain.py::_submit_delivery` → `callsites.coverage_item_support` | `V3DomainAdapter`; delivery submission, recorded in `provenance` only | saved delivery + backend-validated spans | `saved_delivery, required_item, valid_spans, node_spec_version` | Choice `SUPPORTED/PARTIAL/UNSUPPORTED/UNCERTAIN` | No | per-REQUIRED-item signal recorded; reviewer + quote/hash validation still decide coverage; never `UPDATE … LEARNED` | `UNCERTAIN` (coverage stays pending) | No (shadow) — never claims coverage | owner + `coverage` + workspace/node/spec_version | `test_coverage_item_support_uncertain_on_fallback`, `test_coverage_service_none_is_uncertain` | NOT_RUN |
| 8 | `assessment.criterion_review.v1` | `assessments.py::save_submission` → `_apply_jev_criterion_review` → `callsites.review_criterion` | `AssessmentService`; inside the five-question grading loop per frozen criterion | frozen question + rubric + reference solution | `frozen_question, frozen_rubric_criterion, reference_solution, student_answer, deterministic_verification, candidate_answer_spans` | Choice `SATISFIED/PARTIAL/NOT_SATISFIED/NEEDS_REVIEW` | No (per criterion) | flag-only: can set `needs_review`; never changes the mark fraction, never zeroes | existing grader / `NEEDS_REVIEW` | No (shadow) — backend owns mark range, weights, total, grade version | owner + `assessment` + workspace/node | `test_criterion_review_failure_never_flags_review`, `test_review_criterion_fallback_is_not_a_jev_signal` | NOT_RUN |
| 9 | `template.match.v1` | `cm_update/app.py::classify_course_task` → `callsites.match_template` | `cm_update`; after a course upload, layered on the DeepSeek classification | course title + bounded body samples + revision | `course_title, curriculum_samples, materials_revision, known_course_level` | Choice (stage 1 degree → stage 2 template id) | Yes — candidates offered in one call (capped) | hierarchical degree→template signal recorded; DeepSeek classification stays authoritative; never infers learner's degree | `OTHER` | No (shadow) — advisory `jev_template_id` only | course id + `template` | `test_template_match_service_none_returns_other`, `test_template_match_shadow_returns_other`, `test_template_match_on_selects_valid_template` | NOT_RUN |
| 10 | `exercise.prototype.v1` | `cm_update/app.py::generate_exercise_run` → `callsites.select_exercise_prototype` | `cm_update`; exercise generation for the current node | node + server-authorized prototypes | `node, eligible_prototypes, recent_exposures, learning_evidence` | Choice among authorized prototype ids or `NONE` | Yes — eligible prototypes in one call | selects among server-authorized prototypes; never sees hidden answers, never invents a source | `NONE` (existing generation) | No (shadow) — selection only | owner + `exercise` + course | `test_full_wired_flow_writes_no_learning_grade_or_coverage` | NOT_RUN |
| 11 | `graph.prerequisite.v1` | `knowledge.py::select_repair_prerequisite` → `callsites.select_prerequisite` | `KnowledgeService` (from `orchestrator.teach` on remediation); legal neighbours only | published graph neighbourhood | `current_node, error, allowed_predecessor_nodes` | Choice among legal predecessors or `NONE` | Yes — legal predecessors in one call | selects a legal predecessor to review; never creates/publishes a knowledge node | published prerequisite order (first legal predecessor) | No (shadow) — selection only | owner + `prerequisite` + workspace/node | `test_full_wired_flow_writes_no_learning_grade_or_coverage` | NOT_RUN |
| 12 | `corpus.quality.v1` | `cm_update/app.py::upload` → `callsites.assess_corpus_quality` | `cm_update`; document upload parse (also reusable offline) | parse output + parse flags | `document_fragment, source_metadata, parse_flags` | Score `0..3` | No | mark-only parse-quality flag (missing pages/stems/params/weak sourcing/duplicates); never auto-deletes a file | retain original, mark parse limitations (`1`) | No (shadow) — mark only | owner + `corpus_quality` + course | `test_oversized_input_falls_back_without_half_sending` | NOT_RUN |

## Table 2 — the six structured modules

| module | definition(s) | business entry point | when it runs | state source | batch? | Jev returns | how it really affects business | authority boundary | fallback | cache scope | tests | live evidence | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **A** ExtractionVerification | `extraction.field_grounded.v1` | *(none yet)* | — | — | — | — | **`MODULE_ONLY`**: the pipeline (`app/jev/extraction.py`) is complete and tested, but no ingestion/parse call site invokes it yet. It is not claimed as wired. | never rewrites a field silently; only flags `NEEDS_REVIEW` | deterministic format checks + `REVIEW` | owner `extraction-pipeline` + `extraction` | `test_jev_extraction.py` (16) | NOT_RUN | MODULE_ONLY |
| **B** CourseEntityResolution | `entity.relation.v1` | `domain.py::_retrieve` (expansion + `CourseEntityResolver.resolve`) | every authorized retrieval with ≥2 fused candidates; expansion before the first recall | already-authorized fused candidates + accepted knowledge-node aliases | Yes — candidate pairs offered in one call, capped, deterministic order | Choice `SAME_CONCEPT/ALIAS/QUESTION_VARIANT/DOCUMENT_VERSION_RELATION/RELATED_NOT_SAME/DIFFERENT/UNCERTAIN` | **Wired, proposal-only**: relations are written to `entity_relations` as `status=PROPOSED` (idempotent, `used_jev`/`receipt_id` recorded) and accepted aliases expand the *query* (recall only). Nothing is merged, renamed, reordered or deleted; the original query stays the prefix and an explicit file/page/question target skips expansion. | Jev may add a proposal, never accept/reject it and never alter the tree, ids, files or the fused order | `()` aliases (query unchanged), no relation written | owner + `entity_resolution` + course/workspace/revision | `test_jev_entity_resolution.py` (18), `test_jev_shadow_invariance.py` (6, incl. `test_duplicate_evidence_is_recorded_as_a_proposed_relation`) | NOT_RUN | WIRED (shadow) |
| **C** EvidenceConsistency | `evidence.consistency.v1` | *(none yet)* | — | — | — | — | **`MODULE_ONLY`**: `app/jev/evidence_consistency.py` classifies `SAME_CONTEXT_CONTRADICTION / DIFFERENT_ASSUMPTIONS / VERSION_OR_TASK_DIFFERENCE / COMPATIBLE / INSUFFICIENT_EVIDENCE` and is tested; no retrieval/evidence-pack call site invokes it yet. | never deletes one of two conflicting sources | `INSUFFICIENT_EVIDENCE` | owner + `evidence_consistency` + course/workspace | `test_jev_evidence_consistency.py` + `test_jev_citation_audit.py` (21) | NOT_RUN | MODULE_ONLY |
| **D** ClaimCitationAudit | `source.supports_claim.v1` + `source.select_span.v1` (three-layer audit) | *(call sites 2/3 exist; the audit module is not yet its caller)* | — | — | — | `SUPPORTED/PARTIALLY_SUPPORTED/CONTRADICTED/NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE/INSUFFICIENT_CONTEXT` | **`MODULE_ONLY`** as the three-layer audit: the two definitions reach the evidence-bundle annotation path (table 1, #2/#3), but post-generation claim→citation auditing is not yet bound to the message revision. | never invents a page/quote/URL; "not mentioned in this span" is never reported as "the document proves it wrong" | `UNVERIFIED` / keep evidence | owner + `citation` + course/workspace | `test_jev_citation_audit.py` + `test_jev_evidence_consistency.py` (21), `test_retrieve_wiring_annotates_citation_support` | NOT_RUN | PARTIAL (call sites wired, audit module MODULE_ONLY) |
| **E** TeachingCapabilityRouter | `teaching.capability.v1` | `cm_update/app.py::run` → `run_capability` | every teaching run, after `route_explicit_command`; explicit commands cost 0 Jev | endpoint-verified preconditions, lane, node/Pair binding, teaching mode, explicit command | Yes — the offered candidate set (capped at 4) goes in one call, plus at most one disambiguation round | Choice among the **offered** capabilities or `NO_SKILL` | **Wired and consumed**: only the capabilities this endpoint actually serves are offered; the code-owned baseline equals the flow the shell already took; the resolved `skill_id` decides `teaching_flow`, i.e. whether the run binds the V3 journey through the orchestrator (`knowledge.begin_learning`) or answers without advancing the lesson. An explicit "answer only" is now really honoured (0 Jev, no journey, no learning-ledger write) instead of being discarded. The decision is reported on the create-run response. | never Normal→Thinking, never reveals a hidden answer, never re-enables an entry point, never changes the Pair/node binding, never dispatches a capability the endpoint lacks | code-owned baseline (`node_lesson` for a node-bound run, `direct_qa` otherwise), `used_jev=False` under shadow/off | owner + `capability` + course | `test_jev_capability_router.py` (17), `test_jev_capability_business_dispatch.py` (10, incl. an end-to-end run), `test_jev_shadow_invariance.py` | NOT_RUN | WIRED (shadow) |
| **F** ToolIntentCheck | `tool.intent.v1` | `services/agent-api` `ToolExecutor.execute` → `JevToolIntentGate` → `POST /api/jev/tool-intent` → `ToolIntentCheck.authorize` | only model-proposed **write** tool calls (`createTask/updateTask/completeTask/deleteTask`); `searchTask` is read-only and never gated; explicit/read-only actions cost 0 Jev | the user's own turn message + the proposed tool + code-computed permissions + object revision | No (per proposed call) | Choice `CONSISTENT / INCONSISTENT_WITH_INTENT / AMBIGUOUS` | **Wired, opt-in**: `JEV_TOOL_INTENT_MODE=off` (default) makes no HTTP call and keeps the existing synchronous path byte-identical; `advisory` records the verdict on the tool result and still executes; `enforce` blocks a non-`ALLOW` write with `CONFIRMATION_REQUIRED`/`INTENT_REFUSED`. The token-authenticated internal endpoint fails closed (503 without a configured token). | a `CONSISTENT` verdict can never grant a permission the actor lacked; document content is never treated as user authorization; Jev never executes the tool | `REQUIRE_CONFIRMATION` (`intent:unavailable`) — never fail-open | owner + `tasks` (owner-scoped) | `test_jev_tool_intent.py` (12), `test_api_tool_intent.py` (8), agent-api `intent-gate.test.ts` (8) + `executor-intent-gate.test.ts` (6) | NOT_RUN | WIRED (opt-in, default off) |
| **P2** UserFeedbackTriage | `feedback.category.v1`, `feedback.severity.v1` | `POST /api/feedback` → `FeedbackTriage.submit` | only when a user actively submits a report | the report the user chose to send (body only when `attach_body=true`) | Yes — category + severity decided in one call | Choice category / Score severity | **Wired**: the report is classified and queued for human review; the deterministic backend owns persistence and the queue. | never scans private messages, never profiles a user, never changes a grade, never suspends or deletes | `OTHER` + middle severity (still queued) | owner + `feedback` + course | `test_jev_feedback_triage.py` (17), `test_qa_api.py` | NOT_RUN | WIRED (shadow; in-memory queue + receipt ledger) |

## Host wiring (done in this round)

One shared semantic-decision layer is now assembled at application startup and
threaded through the whole app, instead of each caller building its own gateway:

`app/main.py::create_app` → `application.state.jev_service` →
`app/ui_extension/mount.py` → `app/cm_update/integration.py` →
`app/cm_update/app.py::create_app(jev=…)` → `V3DomainAdapter(jev=…)`, and reused by
`app/api/feedback.py` and `app/api/tool_intent.py`. With no TypeSafe credential the
`SdkTransport` fails typed (`JevNotConfiguredError`), every definition stays in
`shadow`, and the deterministic result remains the user-visible one.

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
case call sites with a successful `FakeTransport` in `on` mode and asserts
learning/grade/coverage row counts are unchanged while the only writes are the Jev
receipts (plus, for entity resolution, the proposal-only `entity_relations` store).

## Still open (not claimed as done)

1. **Modules A, C and the three-layer audit of D are `MODULE_ONLY`.** They are
   implemented and tested but not yet invoked from ingestion/parse, the evidence-pack
   step, or post-generation citation binding. No business effect is claimed for them.
   **A browser journey cannot exist for them yet**, and none was written: a journey
   that asserts behaviour no call site produces would be fiction.
2. **`retrieval.support.v1` is one call per candidate.** The SDK
   `system_one(state, questions)` supports several questions per call; a multi-question
   `evaluate` on `JevGateway` would batch it (the transport contract was not touched).
3. **`answers.evidence_bundle_support` is the shared citation check** (invoked from
   `domain._retrieve`); `app/services/qa.py::QaService.stream` is its intended second
   caller and is outside the listed edit scope.
4. **Live Jev validation, calibration and the A/B/C/D/E ablation have not run** for any
   row: no TypeSafe credential exists in this environment. Every `live evidence` cell
   above is `NOT_RUN`, and no quality claim is made anywhere for a definition that has
   only produced shadow receipts.

## Browser evidence per wired module

| Module | Journey | Assertion |
|---|---|---|
| E CapabilityRouter | `tests/e2e/jev-structured.spec.ts` → "the shipped shell reports the capability it dispatched" | the shipped shell's own create-run response reports `direct_qa` / `teaching_flow=false` / `used_jev=false` for "只回答" and `node_lesson` / `teaching_flow=true` for a normal teaching message, and both runs reach `completed` |
| E + all definitions (Jev unavailable) | `tests/e2e/jev-structured.spec.ts` → "with no TypeSafe credential every decision degrades and teaching still works" | with **no** TypeSafe credential configured, every decision reports `used_jev=false`, and the teaching run still completes with citations and no error |
| B EntityResolution (query expansion half) | `services/rag-api/tests/test_jev_shadow_invariance.py` | the original query stays the prefix, accepted aliases only add recall, an explicit file/page/question target skips expansion, and the fused order is byte-identical under shadow / unavailable / `jev=None` |
| F ToolIntentCheck | agent-api `test/executor-intent-gate.test.ts` (+ the endpoint tests) | write tools gated, `searchTask` never gated, `off` byte-identical, `advisory` records, `enforce` blocks |
| Shell entry for the feedback module | `tests/e2e/ui-refresh.spec.ts` | the "报告问题" entry is reachable in the shipped shell |
