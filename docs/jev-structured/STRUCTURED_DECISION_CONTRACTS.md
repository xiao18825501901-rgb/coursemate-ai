# Structured decision contracts

Per-definition contract for the semantic-decision layer. Shared facts first, then
one block per definition. The two new ids — `evidence.consistency.v1` (module C)
and `extraction.field_grounded.v1` (module A, another workstream) — are marked
**pending catalog registration** with their exact proposed entry.

## Shared facts (all definitions)

* **catalog version** — `1.0.0-design` (the `decision_catalog.json` `version`).
* **default runtime mode** — `shadow` (a Jev suggestion is recorded, never applied
  unless the definition is individually promoted to `on`).
* **probability_is_grade** — `false`; **thresholds** — `UNSET_UNTIL_CALIBRATED_ON_LABELLED_DATA`.
* **cache scope (8-way)** — `authorization_scope`, `course`, `workspace`,
  `material_revision`, `node_spec_version`, `question_definition_hash`,
  `input_hash`, `provider_model_version`. These map onto the receipt columns
  `owner_scope_hash`, `course_id`, `workspace_id`, `material_revision`,
  `node_id`+`spec_version`, `question_hash`, `input_hash`, `model_version`
  respectively. A cached suggestion is returned only when **every** in-scope
  dimension matches, so an owner-scope or material-revision change is a natural miss.
* **receipt fields** (one row per call, `jev_decision_receipts`) — `id`,
  `definition_key`, `primitive`, `mode`, `caller_role`, `owner_scope_hash`,
  `course_id`, `workspace_id`, `material_revision`, `node_id`, `spec_version`,
  `question_hash`, `input_hash`, `output_json`, `outcome`, `latency_ms`,
  `model_version`, `created_at`. Failed calls are recorded with an `outcome`
  (`off`/`ok`/`cache_hit`/`timeout`/`unavailable`/`invalid_response`/`not_configured`).
* **evaluation label shape** (ablation ground truth) — Choice: `{"choice": "<id>"`
  (or a non-empty string for `dynamic` candidates); Score: `{"score_index": int}`;
  Noul: `{"noul": bool}`.

---

## 1. `intent.next_action.v1` — Choice

* allowed candidates: `CONTINUE`, `ANSWER_AND_RESUME`, `ANSWER_ONLY`, `REPAIR_PREREQUISITE`, `QUIZ_WAIT`, `SUBMIT_ASSESSMENT`, `PAUSE`, `OTHER`.
* required state: `message`, `fixed_anchor`, `current_mode`, `active_assessment`.
* deterministic pre-checks: explicit commands are routed by `route_explicit_command` first (zero Jev); only ambiguous phrasing reaches Jev.
* may change: classify ambiguous follow-up. **may not**: unlock answers, change budgets, change Thinking/strength, or take a privileged action.
* fallback: `OTHER` (DeepSeek answers without forced advancement).
* evaluation label: Choice among the 8 ids.

## 2. `retrieval.support.v1` — Score

* allowed candidates: levels `0`–`4` (Unrelated → Directly supports with exact evidence).
* required state: `query`, `exact_target`, `candidate_id`, `candidate_text`, `source_metadata`.
* deterministic pre-checks: exact-target hits are never offered to Jev; candidates are already-authorized and fused.
* may change: reorder non-exact candidates. **may not**: add/drop, displace an exact target, or let official crowd out private.
* fallback: corrected merged RRF order with exact-target protection.
* evaluation label: `{"score_index": 0..4}`.

## 3. `source.supports_claim.v1` — Noul

* allowed candidates: none (probability in [0,1]).
* required state: `claim`, `source_span`, `source_version`, `task_scope`.
* deterministic pre-checks: the span is backend-supplied; Jev never authors a source.
* may change: annotate support. **may not**: delete a source, invent a citation.
* fallback: `UNVERIFIED` (keep evidence, obtain missing source or defer claim).
* evaluation label: `{"noul": bool}`.

## 4. `source.select_span.v1` — Choice

* allowed candidates: `dynamic` (server-generated span ids) + `NO_SUPPORT`.
* required state: `claim`, `candidate_spans`.
* deterministic pre-checks: candidate ids are server-supplied; the gateway rejects an unknown id.
* may change: select one supplied span id. **may not**: produce text, page numbers or new citations.
* fallback: `NO_SUPPORT` (keep real selected evidence).
* evaluation label: `{"choice": "<span id>"}` or `{"choice": "NO_SUPPORT"}`.

## 5. `context.keep_segment.v1` — Noul

* allowed candidates: none (probability).
* required state: `segment`, `current_task`, `fixed_anchor`, `remaining_scope`.
* deterministic pre-checks: only filterable (optional) history is offered; MUST_KEEP anchors are never dropped.
* may change: drop a filterable segment. **may not**: drop fixed anchors / current question / originals.
* fallback: keep MUST_KEEP + bounded recent history.
* evaluation label: `{"noul": bool}`.

## 6. `pedagogy.next_method.v1` — Choice

* allowed candidates: `WORKED_EXAMPLE`, `TRACE`, `DEFINITION`, `COUNTEREXAMPLE`, `COMPARE`, `CONTINUE`.
* required state: `learner_request`, `known_prior_evidence`, `topic`, `template_profile`, `current_step`.
* deterministic pre-checks: none beyond scope/authorization.
* may change: presentation method. **may not**: model, budget, mastery, grade, scope.
* fallback: versioned template default (`CONTINUE`).
* evaluation label: Choice among the 6 ids.

## 7. `coverage.item_support.v1` — Choice

* allowed candidates: `SUPPORTED`, `PARTIAL`, `UNSUPPORTED`, `UNCERTAIN`.
* required state: `saved_delivery`, `required_item`, `valid_spans`, `node_spec_version`.
* deterministic pre-checks: reviewer + quote/hash validation still own coverage; Jev is a signal only.
* may change: per-REQUIRED-item signal. **may not**: claim coverage or write `LEARNED`.
* fallback: `UNCERTAIN` (coverage stays pending).
* evaluation label: Choice among the 4 ids.

## 8. `assessment.criterion_review.v1` — Choice

* allowed candidates: `SATISFIED`, `PARTIAL`, `NOT_SATISFIED`, `NEEDS_REVIEW`.
* required state: `frozen_question`, `frozen_rubric_criterion`, `reference_solution`, `student_answer`, `deterministic_verification`, `candidate_answer_spans`.
* deterministic pre-checks: backend owns mark range/weights/totals/grade version.
* may change: set `needs_review`. **may not**: change the mark fraction or zero a score.
* fallback: existing grader / `NEEDS_REVIEW`.
* evaluation label: Choice among the 4 ids.

## 9. `template.match.v1` — Choice

* allowed candidates: `dynamic` (14 professional template ids) + `OTHER`.
* required state: `course_title`, `curriculum_samples`, `materials_revision`, `known_course_level`.
* deterministic pre-checks: two-stage degree→template; DeepSeek classification stays authoritative.
* may change: advisory template id. **may not**: infer learner degree/identity, overwrite newer revision.
* fallback: `OTHER`.
* evaluation label: `{"choice": "<template id>"}` or `{"choice": "OTHER"}`.

## 10. `exercise.prototype.v1` — Choice

* allowed candidates: `dynamic` (authorized prototype ids) + `NONE`.
* required state: `node`, `eligible_prototypes`, `recent_exposures`, `learning_evidence`.
* deterministic pre-checks: prototypes are server-filtered/authorized.
* may change: select an authorized prototype. **may not**: see hidden answers or invent a source.
* fallback: `NONE` (existing generation).
* evaluation label: `{"choice": "<prototype id>"}` or `{"choice": "NONE"}`.

## 11. `graph.prerequisite.v1` — Choice

* allowed candidates: `dynamic` (legal predecessor ids) + `NONE`.
* required state: `current_node`, `error`, `allowed_predecessor_nodes`.
* deterministic pre-checks: legal graph neighbours only.
* may change: select a legal predecessor. **may not**: create/publish a node.
* fallback: published prerequisite order (first legal predecessor).
* evaluation label: `{"choice": "<node id>"}` or `{"choice": "NONE"}`.

## 12. `corpus.quality.v1` — Score

* allowed candidates: levels `0`–`3`.
* required state: `document_fragment`, `source_metadata`, `parse_flags`.
* deterministic pre-checks: none beyond scope/authorization.
* may change: mark parse-quality limitations. **may not**: auto-delete originals or auto-publish.
* fallback: retain original, mark limitations (`1`).
* evaluation label: `{"score_index": 0..3}`.

---

## 13. `evidence.consistency.v1` — Choice — **pending catalog registration** (module C)

Owned by this round. Held as `EVIDENCE_CONSISTENCY_KEY` + a module-level
`DecisionDefinition` in `app/jev/evidence_consistency.py`; **not** in
`decision_catalog.json` yet. The module builds a `DecisionRequest` with this
definition so the gateway runs it today (modes/bounds/receipts/validation apply).

* allowed candidates: `SAME_CONTEXT_CONTRADICTION`, `DIFFERENT_ASSUMPTIONS`, `VERSION_OR_TASK_DIFFERENCE`, `COMPATIBLE`, `INSUFFICIENT_EVIDENCE`.
* required state: `left`, `right` (the two bounded candidate fragments).
* deterministic pre-checks: pair narrowing (version/task/variable/concept); version/task pairs are resolved deterministically with zero Jev; at most 8 semantic pairs per request; nothing is reordered or dropped; a prompt-injection marker is annotation-only.
* may change: annotate a pair's relation (and request a DeepSeek conflict explanation). **may not**: drop/reorder a source, override an older document, or decide any permission.
* fallback: `COMPATIBLE` with `used_jev=False` ("no conflict determined", not a Jev confirmation).
* cache scope: the shared 8-way.
* evaluation label: Choice among the 5 ids.

### Exact proposed entry

```json
{
  "key": "evidence.consistency.v1",
  "primitive": "Choice",
  "required_state": ["left", "right"],
  "criteria": {
    "SAME_CONTEXT_CONTRADICTION": "A genuine conflict between the two fragments under identical assumptions",
    "DIFFERENT_ASSUMPTIONS": "Each fragment is valid under its own stated conditions or scope",
    "VERSION_OR_TASK_DIFFERENCE": "The fragments concern different versions or different tasks",
    "COMPATIBLE": "The fragments agree or complement each other",
    "INSUFFICIENT_EVIDENCE": "The fragments are too thin to judge the relation"
  },
  "instructions": "Classify the relation between two already-authorized evidence candidates about the same concept/value in the same context. SAME_CONTEXT_CONTRADICTION only for a genuine conflict under identical assumptions; DIFFERENT_ASSUMPTIONS when each is valid under different stated conditions; VERSION_OR_TASK_DIFFERENCE when they concern different versions or tasks; COMPATIBLE when both agree or complement; INSUFFICIENT_EVIDENCE when the fragments are too thin to judge. Never infer a document should be dropped or a permission changed.",
  "failure_policy": "COMPATIBLE (keep both, no conflict escalation).",
  "cache_scope": [
    "authorization_scope", "course", "workspace", "material_revision",
    "node_spec_version", "question_definition_hash", "input_hash", "provider_model_version"
  ]
}
```

(Note: the module's `_EVIDENCE_CONSISTENCY_DEFINITION` holds the same id/primitive/
required_state/failure_policy/cache_scope; its `criteria` uses label-as-description,
which is functionally equivalent for Choice validation — only the keys are checked.)

---

## 14. `extraction.field_grounded.v1` — Choice — **pending catalog registration** (module A)

Owned by module A (another workstream), held in `app/jev/extraction.py` via
`field_grounded_definition()`; **not** in `decision_catalog.json` yet. Documented
here for the shared contracts index, not owned by this round.

* allowed candidates: `GROUNDED`, `WRONG_FIELD`, `NEGATION_LOST`, `CONSTRAINT_LOST`, `SOURCE_INSUFFICIENT`, `UNCERTAIN`.
* required state: `question_id`, `part_id`, `field_name`, `candidate_value`, `unit`, `supplied_text`, `source_region`.
* deterministic pre-checks: required fields, numeric parse, unit consistency, question-number shape, table structure, source exists and is inside the authorized scope; a failing record is rejected/flagged with zero Jev.
* may change: judge the semantic residue of one field. **may not**: read pixels (a `GROUNDED` verdict only confirms the already-read text), confirm an unreadable region, or help a student cheat.
* fallback: deterministic result + `NEEDS_REVIEW` (typed `FallbackReason`).
* cache scope: the shared 8-way.
* evaluation label: Choice among the 6 ids.

### Exact proposed entry

```json
{
  "key": "extraction.field_grounded.v1",
  "primitive": "Choice",
  "required_state": [
    "question_id", "part_id", "field_name", "candidate_value", "unit",
    "supplied_text", "source_region"
  ],
  "criteria": {
    "GROUNDED": "The candidate value actually belongs to this question/condition and is fully supported by the supplied source text",
    "WRONG_FIELD": "The value was copied from an adjacent example or a different field, not this question/condition",
    "NEGATION_LOST": "A negation (not/no/except/unless) was dropped, inverting the value",
    "CONSTRAINT_LOST": "A constraint or condition (range, unit, scope, if/when) was dropped from the value",
    "SOURCE_INSUFFICIENT": "The supplied source text is not enough to confirm the value belongs here",
    "UNCERTAIN": "Cannot resolve reliably from the supplied text"
  },
  "instructions": "Judge ONLY the supplied source text: does the candidate value actually belong to this question/condition, or was it copied from an adjacent example, or a negation/constraint dropped? Use no outside knowledge; never confirm a value the supplied text does not show; when the text is insufficient say SOURCE_INSUFFICIENT.",
  "failure_policy": "NEEDS_REVIEW; never a confident acceptance",
  "cache_scope": [
    "authorization_scope", "course", "workspace", "material_revision",
    "node_spec_version", "question_definition_hash", "input_hash", "provider_model_version"
  ]
}
```

---

## Registration — **done**

Both pending entries above are **in `app/jev/decision_catalog.json`** (19 definitions
total), so the catalog is the owner of their vocabulary, criteria text, instructions
and cache scope.

What changed when that landed, and what was left:

* `extraction.field_grounded.v1` — the module-local shim was **removed**;
  `app/jev/extraction.py::field_grounded_definition()` projects the catalog entry and
  asserts its own candidate/required-state/cache-scope constants against it.
* `evidence.consistency.v1` — the shim survived longer than it should have and is now
  **also removed** (`app/jev/evidence_consistency.py::evidence_consistency_definition()`).
  This one mattered more than a tidy-up: the module had been sending
  `{relation: relation}` as the criteria labels, so what the model was shown was **not**
  the registered criteria, and a calibration run would have measured the duplicate
  rather than the catalog entry. The request now carries the registered id→description
  map and the registered instructions, pinned by
  `test_the_registered_definition_is_the_one_the_model_is_shown`.

Neither definition is promoted out of `shadow`; promotion still requires
labelled-calibration evidence, never a global switch.
