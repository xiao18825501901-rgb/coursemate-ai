# Jev Decision Catalog and Calibration

Source of truth: `services/rag-api/app/jev/decision_catalog.json` (in-repo copy of
the pack's `JEV_DECISION_CATALOG.json`, version `1.0.0-design`,
status `IMPLEMENTATION_SPEC_NOT_LIVE_VALIDATED`). It is an **application-owned
business spec, not a TypeSafe POST payload** — the only code that touches the
SDK is `app/jev/gateway.py::SdkTransport`, and it uses only the verified
signature (see `JEV_SKILL_DECISIONS.md`).

## Centralized, uncalibrated thresholds

| Setting | Value | Meaning |
|---|---|---|
| `probability_is_grade` | `false` | A Noul yes-probability or Score level is **never** a mark, mastery level or GPA. |
| `default_runtime_mode` | `shadow` | Every definition runs in shadow until calibrated. |
| `thresholds` | `UNSET_UNTIL_CALIBRATED_ON_LABELLED_DATA` | No magic `0.8` anywhere; no threshold is applied to any decision. |

Runtime mode is resolved per definition key by `JevGateway.mode_for(key)`
(`off | shadow | on`, default `shadow`). **No definition is `on` today.**

## The 12 definitions

Every definition has the same `cache_scope`:
`authorization_scope, course, workspace, material_revision, node_spec_version,
question_definition_hash, input_hash, provider_model_version` — a cached
suggestion is only reused when all of those match, and is invalidated on a
material-revision or authorization change (`SqlReceiptStore.lookup` +
`invalidate`).

| key | primitive | authorized inputs (`required_state`) | fallback | wired |
|---|---|---|---|---|
| `intent.next_action.v1` | Choice | message, fixed_anchor, current_mode, active_assessment | **in-repo deterministic router first** (`app/learning/intent_commands.py::route_explicit_command`: 继续 / 暂停 / 只回答 / 给答案然后继续 / 做一题 / 回到主线 / 交卷 and English equivalents are answered without a Jev call), otherwise DeepSeek answers without forcing advancement | service helper (`SemanticDecisionService.next_action`) |
| `retrieval.support.v1` | Score (0–4) | query, exact_target, candidate_id, candidate_text, source_metadata | corrected merged RRF with exact-target protection | **yes** — `domain.py::_retrieve` re-rank |
| `source.supports_claim.v1` | Noul | claim, source_span, source_version, task_scope | mark unverified, obtain source or defer claim | service helper |
| `source.select_span.v1` | Choice | claim, candidate_spans | keep real selected evidence or return no support | service helper |
| `context.keep_segment.v1` | Noul | segment, current_task, fixed_anchor, remaining_scope | keep fixed anchors + bounded recent originals | service helper (`keep_segment`) |
| `pedagogy.next_method.v1` | Choice | learner_request, known_prior_evidence, topic, template_profile, current_step | versioned template default | service helper |
| `coverage.item_support.v1` | Choice (SUPPORTED/PARTIAL/UNSUPPORTED/UNCERTAIN) | saved_delivery, required_item, valid_spans, node_spec_version | coverage remains pending; LEARNING unchanged | **yes** — signal recorded in `_submit_delivery` provenance only |
| `assessment.criterion_review.v1` | Choice (SATISFIED/PARTIAL/NOT_SATISFIED/NEEDS_REVIEW) | frozen_question, frozen_rubric_criterion, reference_solution, student_answer, deterministic_verification, candidate_answer_spans | existing grader / NEEDS_REVIEW; never zero because Jev is unavailable | service helper (`criterion_review`) |
| `template.match.v1` | Choice | course_title, curriculum_samples, materials_revision, known_course_level | DeepSeek evidence-based classification or OTHER | service helper |
| `exercise.prototype.v1` | Choice | node, eligible_prototypes, recent_exposures, learning_evidence | deterministic nearest qualified prototype or theory-derived diagnostic | service helper |
| `graph.prerequisite.v1` | Choice | current_node, error, allowed_predecessor_nodes | published prerequisite order without semantic expansion | service helper |
| `corpus.quality.v1` | Score (0–3) | document_fragment, source_metadata, parse_flags | retain original; mark parse limitations for ingestion review | service helper |

Primitive split: **Choice** × 8 (`intent.next_action`, `source.select_span`,
`pedagogy.next_method`, `coverage.item_support`, `assessment.criterion_review`,
`template.match`, `exercise.prototype`, `graph.prerequisite`), **Noul** × 2
(`source.supports_claim`, `context.keep_segment`), **Score** × 2
(`retrieval.support`, `corpus.quality`).

## Hard rules enforced by code (not by the catalog prose)

* **Choice selects, never creates**: `JevGateway._validate` rejects any choice id
  that is not in the server-supplied `criteria` dict (`JEV_INVALID_RESPONSE`).
  The model can never mint a candidate id that reaches the user.
* **Score/Noul are signals, never grades**: a Score is an ordered level key and a
  Noul is a probability in `[0, 1]`; neither is multiplied into a mark.
* **off / shadow / failed → deterministic**: `SemanticDecisionService._decide`
  returns the deterministic fallback unless `mode == "on"` *and* the suggestion
  validated. `shadow` still records the suggestion in the receipt only.
* **Jev never writes state**: the only table the layer writes is
  `jev_decision_receipts` (migration `028`). No learning state, grade, LEARNED or
  budget write exists anywhere in `app/jev/` or the two wired call sites.
* **No paid auto-retry**: the gateway calls the transport exactly once per
  decision; `retry policy = none`.

## Wire sites

1. **Retrieval re-rank** (`app/ui_extension/domain.py::_retrieve`) — after global
   RRF fusion, `SemanticDecisionService.rerank_retrieval` may REORDER the
   already-authorized candidates only. Exact file/page/question targets keep
   their slot; nothing is added or dropped.
2. **Coverage item support** (`app/ui_extension/domain.py::_submit_delivery`) — a
   per-REQUIRED-item signal is recorded in the delivery `provenance`; the
   reviewer + server quote/hash validation still decide coverage.
3. **Intent routing / context selection / assessment criterion review** — ready
   helpers (`next_action`, `keep_segment`, `criterion_review`) in
   `SemanticDecisionService`; their production call sites live outside this repo
   (Node teaching-run / shell history) or in the grading loop, so they are
   delivered as shadow-mode service methods, not live `on` integrations.

## Calibration gate (not done)

All 12 remain `shadow`. Promotion to `on` requires labelled data (the pack plans
200 semantic judgments, 40 multi-turn trajectories, 30 image cases) and a frozen
threshold per definition — retrieval re-rank and context/intent first, then
coverage/assessment (higher risk). Thresholds stay centralized in `Catalog`
(`UNSET`), never scattered as magic numbers.
