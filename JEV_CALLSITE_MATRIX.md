# Jev Call-Site Matrix

Three tables, because the system now has three kinds of definition:

1. **the 12 case definitions** (the original Jev catalog rows) — table 1;
2. **the seven structured-enhancement modules** (A-F plus P2 feedback) — table 2,
   each of which either reaches a real business path or is explicitly marked
   `MODULE_ONLY` with the reason;
3. **the two Question Engine validation signals** — table 3. They are separately receipted
   Choice signals and can only keep a candidate under review or allow the deterministic validator
   to proceed; neither returns marks, grades, correctness probability or a combined quality score.

The current catalog contains 21 definitions. **All 21 definitions are `shadow` by default.** The
two Question Engine rows have offline `FakeTransport` contract evidence only; they are not included
in the historical 19-definition live run below and have no live-quality claim.

## Table 3 — Question Engine validation signals (added after the historical live run)

| definition id | business entry point | state fields | Jev returns | permitted effect | fallback | test | live evidence |
|---|---|---|---|---|---|---|---|
| `question.ambiguity.v1` | `question_validator.py::collect_question_semantic_signals` → `callsites.review_question_ambiguity` | public question, type/form, blueprint conditions, objective-scoped evidence rules | Choice `CLEAR/AMBIGUOUS/UNDER_SPECIFIED/CONTRADICTORY/UNCERTAIN` | one ambiguity dimension in `QuestionValidationReport`; only a receipted `CLEAR` can satisfy it | `UNCERTAIN`, candidate stays `NEEDS_REVIEW` | `test_typesafe_jev_signals_are_receipted_separate_and_feed_the_validator`, `test_shadow_or_absent_typesafe_signals_stay_uncertain_and_never_ready` | NOT_RUN |
| `question.answer_agreement.v1` | `question_validator.py::collect_question_semantic_signals` → `callsites.review_question_answer_agreement` | public question, private author candidate, isolated blind solution, blueprint conditions | Choice `AGREE/DISAGREE/AMBIGUOUS/UNCERTAIN` | one consistency dimension; not proof of correctness and never a mark | `UNCERTAIN`, candidate stays `NEEDS_REVIEW` | same two tests | NOT_RUN |

## Live evidence — measured 2026-09-24, and it supersedes the `NOT_RUN` column below

The section after this one was measured at revision `a0e7587` and every `live evidence` cell in
table 1 says `NOT_RUN`, because at that time no live Jev call had ever been made. **That is no
longer true**: `typesafe-sdk==0.7.0` is installed, the key is in the protected store, and the
catalog has now been exercised against the real service, one call per question, through the real
gateway (`SdkTransport`, `default_mode="on"`, caching disabled so a receipt cannot be mistaken for
an answer).

**31 live cases over 19 definitions: 31/31 completed as valid typed answers, 30/31 met the
expectation recorded before the call.** Evidence: `work/current-change/jev-live-cases.json`,
`jev-live-cases.log`, runner `work/current-change/run-live-jev-cases.py`.

| definition | primitive | live cases | expectations met | live answer(s) |
|---|---|---|---|---|
| `intent.next_action.v1` | Choice | 2 | 2/2 | ambiguous-detour = `ANSWER_AND_RESUME`; clear-continue = `CONTINUE` |
| `retrieval.support.v1` | Score | 2 | 2/2 | direct support = **3.99**; unrelated = **0.0** |
| `source.supports_claim.v1` | Noul | 2 | 2/2 | supports = **0.98**; does not address = **0.01** |
| `source.select_span.v1` | Choice | 1 | 1/1 | selects the one supporting span (`s1`) |
| `context.keep_segment.v1` | Noul | 2 | 2/2 | still-relevant constraint = **0.74**; lunch chatter = **0.08** |
| `pedagogy.next_method.v1` | Choice | 1 | 1/1 | `WORKED_EXAMPLE` |
| `coverage.item_support.v1` | Choice | 2 | 2/2 | genuinely taught = `SUPPORTED`; acceptance text only = `UNSUPPORTED` |
| `assessment.criterion_review.v1` | Choice | 2 | 2/2 | alternative correct answer = `SATISFIED`; not addressed = `NOT_SATISFIED` |
| `template.match.v1` | Choice | 1 | 1/1 | `OTHER` for a course whose needs no template matched |
| `exercise.prototype.v1` | Choice | 1 | 1/1 | an authorized main prototype (`p1`) |
| `graph.prerequisite.v1` | Choice | 1 | 1/1 | the current-course node that explains the error (`n1`) |
| `corpus.quality.v1` | Score | 2 | 0/2 | clean notes = **1.77**; garbled scan = **1.05** (see below) |
| `extraction.field_grounded.v1` | Choice | 2 | 2/2 | grounded value = `GROUNDED`; value belonging to another part = `SOURCE_INSUFFICIENT` |
| `evidence.consistency.v1` | Choice | 2 | 2/2 | same-context conflict = `SAME_CONTEXT_CONTRADICTION`; different assumptions = `DIFFERENT_ASSUMPTIONS` |
| `entity.relation.v1` | Choice | 2 | 2/2 | 中英别名 = `ALIAS`; same word, different meaning = `DIFFERENT` |
| `teaching.capability.v1` | Choice | 1 | 1/1 | `direct_qa` for an ambiguous request |
| `tool.intent.v1` | Choice | 2 | 2/2 | destructive intent not stated = `AMBIGUOUS`; explicit authorised read = `CONSISTENT` |
| `feedback.category.v1` | Choice | 2 | 2/2 | wrong coefficient = `ANSWER_WRONG`; page error = `SERVICE_FAULT` |
| `feedback.severity.v1` | Score | 1 | 1/1 | blocking grading dispute = **2.0** (its scale is 0..2) |

Notes that matter more than the raw counts:

1. **The negative cases are the ones that prove anything.** Each definition was given a case that
   must *not* get the positive answer, and the live model separated them: 0.98 vs 0.01, 0.74 vs 0.08,
   `SUPPORTED` vs `UNSUPPORTED`, `SATISFIED` vs `NOT_SATISFIED`, `ALIAS` vs `DIFFERENT`,
   `GROUNDED` vs `SOURCE_INSUFFICIENT`. A definition that answered the same thing to both would have
   failed here.
2. **One definition discriminates only weakly on this pair.** `corpus.quality.v1` scored clean notes
   **1.77–1.82** and a deliberately garbled scan **0.95–1.05** across three runs — the right order,
   a narrow band, on a 0–3 scale. The `0/2` above is **not** a model failure: the thresholds
   (`≥2.0`, `≤1.0`) were chosen by the harness author before any calibration, which the catalogue
   itself forbids (`thresholds = UNSET_UNTIL_CALIBRATED_ON_LABELLED_DATA`). It is evidence for the
   calibration work, and it is why this definition stays `shadow`.
3. **The Score primitive needed a code change to be usable at all, and this run found it.** The live
   service answers a Score question with a **decimal on the definition's own scale** (`3.99` on a
   0..4 definition, `2.0` on a 0..2 one, `1.82` on a 0..3 one) rather than with a level key, so the
   typed validator refused every Score answer as `invalid_response` — 5 of the first 26 cases. The
   validator now carries that number as `JevAnswer.score_value` **without inventing a level**
   (`score` stays `None`), the cache and receipt payloads round-trip it, and the service passes it
   through as the provider's own number. The level boundaries remain the calibration decision.
4. **Everything is still `shadow`.** These calls were made with `default_mode="on"` *for the
   measurement*; the catalogue's own default is unchanged and no production path is promoted by this
   run. What changed is that the definitions are now known to answer correctly, which is the
   precondition for the advisory/on decision in §14 of the task.

### Round 90 — the modules' live evidence, from a browser run rather than from a harness

The table above is *definition-level*: it proves each definition answers correctly when asked
directly. It does **not** prove a definition changes what a learner receives. Round 90 adds that
second kind of evidence for four rows of table 2, through the shipped deployment:

| Module | Live / end-to-end evidence | What it establishes |
|---|---|---|
| **B** `entity.relation.v1` | journey "a Chinese question reaches English material through an accepted alias": the question `密度聚类是什么？` returns a citation card for `e2e_density_clustering_en.txt`, a page that never contains the Chinese term; the run's `user_text` is the question verbatim | the deterministic half (accepted-alias expansion, zero Jev) changes what the learner can read, with the original query preserved |
| **B** `entity.relation.v1` | journey "one word in two senses is not merged…": `kernel 是什么意思？` returns **two** cards with different `document_id`, and the knowledge tree's node identity/title/parent/position is identical before and after the run — in the live promoted shape as well as with no credential | the proposal-only boundary holds under a live model: a guess can be recorded, nothing is merged, renamed or reordered |
| **C** `evidence.consistency.v1` | **live, `mode=on`**: the two-sided pair (`5%` and `20%` for the same two-sided test) is surfaced with `jev_conflict_with` on both cards and **both fragments kept** — 18 live decisions in mode `on`; and the deterministic half reports two chunks of one document as `VERSION_OR_TASK_DIFFERENCE` with distinct locators, unchanged by mode | a genuine contradiction reaches the learner as a conflict to be explained, never as a deletion; a difference of task is labelled as one |
| **D** `source.supports_claim.v1` | journey "a figure no cited source states is flagged…": `材料里说默认显著性水平是 42% 吗？` flags **every** card `NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE` at layer `quote` with `['42%']`, decided in code with **zero** model calls, while the control question about `5%` leaves the page that states 5% unflagged; the flagged cards are still delivered and rendered | the audit distinguishes "not supported" from "support", and an unsupported citation is annotated rather than removed |
| **F** `tool.intent.v1` | **live, `mode=on`**: the explicit "add a cs3481 task due 2026-08-20" is executed; with the endpoint unreachable the same write is refused (`fallback:unavailable`, `REQUIRE_CONFIRMATION`, `jevCalls: 0`) and the task board is unchanged | the guard blocks an unverifiable write and does not over-block a verified one |

Two defects had to be fixed before *any* of this could be observed, and both are recorded in
`DSH_JEV_DEEPSEEK_EXECUTION_STATE.md` (round 90): until `d824a5b`, module D's layer 1 was built over
the UI extension's own database (`no such table: document_versions` on every card, swallowed by the
"never lose an answer" handler, so no verdict ever reached a reader), and the local `test` provider
emitted no citation markers, so `citations` was empty in every browser run and the whole citation
path was unreachable in acceptance. Neither was a missing helper: both were wired, and inert.

Cost of the live structured run, from its own receipt store rather than an estimate: **169 decisions,
all `outcome=ok`, all carrying a `model_version`** — see the round-90 block of the execution state for
the per-definition breakdown and the observed 0.68–1.35 s latency.

### Round 92 — the exact locator under a *live* rerank

`retrieval.support.v1` is the promotion §14 lists first, and the property that promotion most risks is
the one §16 names: an exact question number must not be replaced by a semantic ranking. Offline that
was already asserted against a hostile rerank
(`test_rerank_exact_target_keeps_slot_under_hostile_rerank`); the end-to-end half did not exist,
because the fixture corpus had no chunk carrying question metadata at all (a probe over the local
corpus found **0** such chunks), so a journey could only have asserted the parser's output.

| | |
|---|---|
| Fixture added | `e2e_locator_questions.txt` — explicit `Question 3` / `(b)` structure, ingested through the product's own pipeline so the structured parser really produces `question_number=3`, `question_part=b` |
| Journey (credential-free) | "a named question number is used as a hard filter and is not replaced by ranking": the named document occupies the **first** citation slot, and the card carries `jev_reference` with `questioned: true`, `question_number: 3`, `question_part: b`, `dropped: []` |
| Journey (live) | "a promoted ranking decision still cannot displace an exact question number": the same two assertions with `retrieval.support.v1=on` and a live credential — **passed**, so a model that is really reordering the candidates kept the exact target in slot 0 |
| Cost | **47 decisions** for the narrow run (9 `retrieval.support.v1` in mode `on`, 38 shadow decisions the same two teach runs make) |
| Artefacts | `work/current-change/browser_jev_locator_promoted_round92.log`, `count_jev_receipts.py` over that run's database |

This is what moves §16's third verification from PARTIAL to PASS, and it is also the first live
evidence for the *first* promotion candidate rather than for one of the advisory-only definitions.



## Verified against the tree (revision `a0e7587`, measured)

The code, tests and catalog are byte-identical to `a0e7587`; this document is the only tracked file
changed after that measurement, so the checks below describe the code that ran the gate. A matrix is a
claim document, so its claims are checked mechanically rather than trusted:

| Check | Result |
|---|---|
| Definition ids: every id named here exists in `app/jev/decision_catalog.json`, and every catalog row appears here | 19 named, 19 in the catalog, **0 either way** |
| Default runtime mode: nothing is promoted out of `shadow` | every catalog row inherits `default_runtime_mode = "shadow"` |
| Catalog status and thresholds, quoted honestly | `status = IMPLEMENTATION_SPEC_NOT_LIVE_VALIDATED`, `thresholds = UNSET_UNTIL_CALIBRATED_ON_LABELLED_DATA` |
| The task's 12 case definitions: each has a row **and** is registered | 12 of 12 |
| File references (36 `*.py` / `*.ts` / `*.spec.ts` paths) | all exist |
| Test **function** names (17) | all defined in the suite they are attributed to |
| Quoted **test counts** (16 Python files, 2 TypeScript files) | all match `--collect-only`; two were corrected in round 79 — `test_jev_evidence_consistency.py` 9 → **10**, `test_jev_citation_audit.py` 12 → **14** (row C had drifted from row D) |

Rerun both checks with `work/current-change/verify-callsite-matrix.py` and
`work/current-change/verify-callsite-test-counts.py`; the first prints the revision it checked, the
second prints every matrix-versus-collected pair.

**What this still does not prove:** that a call site *behaves* as described. These are static checks —
ids, paths, names and counts. Behaviour is the business of the suites named in the `test` column, all of
which ran in the full gate on this same revision (**1570 passed / 3 skipped / 0 failed**,
`work/current-change/full_run_round78.log`). Every `live evidence` cell stays `NOT_RUN`: no TypeSafe
credential exists here, so no row has produced anything but a shadow receipt.

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

## Table 2 — the seven structured modules

| module | definition(s) | business entry point | when it runs | state source | batch? | Jev returns | how it really affects business | authority boundary | fallback | cache scope | tests | live evidence | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **A** ExtractionVerification | `extraction.field_grounded.v1` | `tutor/references.py::parse_query_reference` → `app/jev/reference_verification.py::verify_query_reference` → `callsites.verify_extraction_field` | every retrieval that carries a question label: `domain.py::_retrieve` (per request, before the structured exact search) and `QaService.stream` (before `retrieve_structured` / `is_referenced_example`). A message that names no question label costs **0 Jev calls** | the label the deterministic parser just read, its character span in the learner's own normalised message, and the message itself as the supplied text | No — one bounded call per labelled field (at most 2) | Choice `GROUNDED / WRONG_FIELD / NEGATION_LOST / CONSTRAINT_LOST / SOURCE_INSUFFICIENT / UNCERTAIN` | **Wired and consumed**: the report is attached to every returned source as `jev_reference` and to the QA `meta` event as `referenceVerification`. A deterministic failure or an affirmative defect (`WRONG_FIELD`/`NEGATION_LOST`/`CONSTRAINT_LOST`/`SOURCE_INSUFFICIENT`) **drops that label**, so the exact-locator SQL filter is not applied and retrieval falls back to hybrid search; `UNCERTAIN`, `off`, `shadow`, no-service and timeout keep the deterministic reference **exactly as it was** and only report `NEEDS_REVIEW`. The parser fix that made this possible also restored legitimate exact recall: a word following the number used to donate its first letter as a phantom sub-part filter (`question 5 have …` → `question_part='h'`), which suppressed the exact hits for question 5. | dropping a label can only ever **remove** a filter, so this module can never widen what a learner may read, add a source, or reach an unauthorized chunk; a sub-part whose parent question is untrusted is dropped with it; the model never rewrites a field, and a Jev agreement is never treated as vision verification | deterministic reference unchanged + `NEEDS_REVIEW` per field (0 behaviour change under off/shadow/unavailable) | owner + `official`/`mine` authorization scope + course (required arguments; the scope is derived from the caller, never from the transport) | `test_jev_reference_verification.py` (29, including the prose regression cases for the parser defect and the owner-scoped cache), `test_jev_reference_business_path.py` (4, real chunker + real `context.retrieve`), `test_jev_absent_ledger.py` (6), journey 4-6 of `tests/e2e/jev-structured.spec.ts` | NOT_RUN (no live Jev call has been made; the report is `fallback:jev_shadow` with `used_jev=false` everywhere) | WIRED (shadow) |
| **B** CourseEntityResolution | `entity.relation.v1` | `domain.py::_retrieve` (expansion + `CourseEntityResolver.resolve`) | every authorized retrieval with ≥2 fused candidates; expansion before the first recall | already-authorized fused candidates + the accepted name groups of the course's knowledge registry (canonical title + accepted aliases, subject-scoped) | Yes — candidate pairs offered in one call, capped, deterministic order | Choice `SAME_CONCEPT/ALIAS/QUESTION_VARIANT/DOCUMENT_VERSION_RELATION/RELATED_NOT_SAME/DIFFERENT/UNCERTAIN` | **Wired, proposal-only**: relations are written to `entity_relations` as `status=PROPOSED` (idempotent, `used_jev`/`receipt_id` recorded) and accepted names expand the *query* (recall only) — a concept the query already names contributes its other accepted names, in both directions (Chinese term → English alias and back), while a query that names no registered concept is **not** expanded at all, so a course-wide alias list is never injected into every question. Nothing is merged, renamed, reordered or deleted; the original query stays the prefix and an explicit file/page/question target skips expansion. | Jev may add a proposal, never accept/reject it and never alter the tree, ids, files or the fused order | `()` name groups (query unchanged), no relation written | owner + `entity_resolution` + course/workspace/revision | `test_jev_entity_resolution.py` (20, incl. bidirectional expansion and the unrelated-query precision rule), `test_jev_shadow_invariance.py` (6, incl. `test_duplicate_evidence_is_recorded_as_a_proposed_relation`) | NOT_RUN | WIRED (shadow) |
| **C** EvidenceConsistency | `evidence.consistency.v1` | `domain.py::_retrieve` → `check_evidence_consistency` | every authorized retrieval with ≥2 fused candidates, after the rerank and the citation annotation, before the `sources` list is built | the already-authorized fused candidates (bounded pair enumeration inside the module) | Yes — at most 8 pairs in one call, with the pair budget and unchecked residue recorded | Choice `SAME_CONTEXT_CONTRADICTION / DIFFERENT_ASSUMPTIONS / VERSION_OR_TASK_DIFFERENCE / COMPATIBLE / INSUFFICIENT_EVIDENCE` | **Wired and consumed**: every source carries a deterministic `jev_consistency` signal derived from the version/task narrowing (identical under off/shadow/unavailable and with no Jev at all), and a genuine `SAME_CONTEXT_CONTRADICTION` additionally attaches `jev_conflict_with`, which `provider.conflict_note` turns into a bounded instruction in the three teaching prompt builders — so DeepSeek explains **both** sides with every source kept. `DIFFERENT_ASSUMPTIONS` / `VERSION_OR_TASK_DIFFERENCE` are never described as a conflict. | never drops, reorders, merges, rewrites or truncates a source; a conflict is surfaced to the model, not resolved by deletion; the note can only come from a real signal | `COMPATIBLE` + no conflict key + `conflict_note` returns `None` (prompt byte-unchanged) | owner + `evidence_consistency` + course/workspace/revision | `test_jev_evidence_consistency_wiring.py` (4, incl. byte-identity across off/shadow/unavailable/no-Jev), `test_jev_evidence_consistency.py` (10), `test_jev_citation_audit.py` (14) | NOT_RUN | WIRED (shadow) |
| **D** ClaimCitationAudit | `source.supports_claim.v1` + `source.select_span.v1` (three-layer audit) | `cm_update/app.py::audit_answer_citations` (post-generation, on the fixed message revision) + `domain.py::_annotate_evidence` (pre-generation evidence bundle) | after the answer is generated and its `[Sn]` markers are known; at most 6 citation cards per answer | the sentence(s) that actually cite each source, the source text the learner was shown, and the backend-resolved document/version/locator | Yes — the cards of one answer are audited in one pass, and identical claim+source states are de-duplicated by the gateway | `SUPPORTED / PARTIALLY_SUPPORTED / CONTRADICTED / NOT_ADDRESSED_IN_AVAILABLE_EVIDENCE / INSUFFICIENT_CONTEXT` (+ `REJECTED` for a layer-1 failure) | **Wired and consumed**: layer 2 runs first and deterministically (a figure the claim asserts that the source never states is `NOT_ADDRESSED…` at **zero** model cost); layer 1 re-checks existence + authorization at the message revision through `DocumentEvidenceResolver` (canonical ACL, read-only, bounded text, never another course's/user's text); layer 3 is the Jev support decision. The verdict, the producing layer and the audited claim are recorded on the citation card the client already receives, and the shipped shell marks only a *real* negative verdict. | never invents a page, quote or URL; never drops, reorders or rewrites a citation; a layer-1 failure is a verdict, not an exception; no verdict is produced without a real signal | `INSUFFICIENT_CONTEXT` (unannotated-looking chip), cards returned **byte-identical** when no semantic layer is configured, audit failure recorded on the cards | owner + `citation` + course (per answer, ≤6 cards) | `test_jev_citation_evidence.py` (12, real migrated DB), `test_citation_audit_binding.py` (7), `test_jev_citation_audit.py` (14), `citationSupport.test.ts` (4) | NOT_RUN | WIRED (shadow) |
| **E** TeachingCapabilityRouter | `teaching.capability.v1` | `cm_update/app.py::run` → `run_capability` | every teaching run, after `route_explicit_command`; explicit commands cost 0 Jev | endpoint-verified preconditions, lane, node/Pair binding, teaching mode, explicit command | Yes — the offered candidate set (capped at 4) goes in one call, plus at most one disambiguation round | Choice among the **offered** capabilities or `NO_SKILL` | **Wired and consumed**: only the capabilities this endpoint actually serves are offered; the code-owned baseline equals the flow the shell already took; the resolved `skill_id` decides `teaching_flow`, i.e. whether the run binds the V3 journey through the orchestrator (`knowledge.begin_learning`) or answers without advancing the lesson. An explicit "answer only" is now really honoured (0 Jev, no journey, no learning-ledger write) instead of being discarded. The decision is reported on the create-run response. | never Normal→Thinking, never reveals a hidden answer, never re-enables an entry point, never changes the Pair/node binding, never dispatches a capability the endpoint lacks | code-owned baseline (`node_lesson` for a node-bound run, `direct_qa` otherwise), `used_jev=False` under shadow/off | owner + `capability` + course | `test_jev_capability_router.py` (17), `test_jev_capability_business_dispatch.py` (10, incl. an end-to-end run), `test_jev_shadow_invariance.py` | NOT_RUN | WIRED (shadow) |
| **F** ToolIntentCheck | `tool.intent.v1` | `services/agent-api` `ToolExecutor.execute` → `JevToolIntentGate` → `POST /api/jev/tool-intent` → `ToolIntentCheck.authorize` | only model-proposed **write** tool calls (`createTask/updateTask/completeTask/deleteTask`); `searchTask` is read-only and never gated; explicit/read-only actions cost 0 Jev | the user's own turn message + the proposed tool + code-computed permissions + object revision | No (per proposed call) | Choice `CONSISTENT / INCONSISTENT_WITH_INTENT / AMBIGUOUS` | **Wired, opt-in**: `JEV_TOOL_INTENT_MODE=off` (default) makes no HTTP call and keeps the existing synchronous path byte-identical; `advisory` records the verdict on the tool result and still executes; `enforce` blocks a non-`ALLOW` write with `CONFIRMATION_REQUIRED`/`INTENT_REFUSED`. The token-authenticated internal endpoint fails closed (503 without a configured token). | a `CONSISTENT` verdict can never grant a permission the actor lacked; document content is never treated as user authorization; Jev never executes the tool | `REQUIRE_CONFIRMATION` (`intent:unavailable`) — never fail-open | owner + `tasks` (owner-scoped) | `test_jev_tool_intent.py` (12), `test_api_tool_intent.py` (8), agent-api `intent-gate.test.ts` (8) + `executor-intent-gate.test.ts` (6) | NOT_RUN | WIRED (opt-in, default off) |
| **P2** UserFeedbackTriage | `feedback.category.v1`, `feedback.severity.v1` | `POST /api/feedback` → `FeedbackTriage.submit` → `FeedbackStore.record` | only when a user actively submits a report | the report the user chose to send (body only when `attach_body=true`) | Yes — category + severity decided in one call | Choice category / Score severity | **Wired and durable**: the report is classified, written to `feedback_reports` (migration 030, idempotent by report key) and queued for human review; the deterministic backend owns persistence and the queue. A database CHECK constraint refuses any body text without the submitter's opt-in, so the privacy rule is structural. The queue has exactly one reader — `GET /api/feedback/queue` (admin, most severe first) — plus `GET /api/feedback/mine` for the caller's own reports. | never scans private messages, never profiles a user, never changes a grade, never suspends or deletes; the store exposes read/append only, and status starts `OPEN` | `OTHER` + middle severity (still queued) | owner + `feedback` + course | `test_jev_feedback_triage.py` (17), `test_feedback_queue.py` (6), `tests/e2e/jev-structured.spec.ts` journey 2 | NOT_RUN | WIRED (shadow; durable queue) |

## Host wiring

One shared semantic-decision layer is assembled at application startup and threaded
through the whole app, instead of each caller building its own gateway:

`app/main.py::create_app` → `application.state.jev_service` →
**`LearningOrchestrator(…, jev=…)`** (which hands it to `AssessmentService` and
`KnowledgeService`) → `app/ui_extension/mount.py` → `app/cm_update/integration.py` →
`app/cm_update/app.py::create_app(jev=…)` → `V3DomainAdapter(jev=…)`, and reused by
`app/api/feedback.py` and `app/api/tool_intent.py`. With no TypeSafe credential the
`SdkTransport` fails typed (`JevNotConfiguredError`), every definition stays in
`shadow`, and the deterministic result remains the user-visible one.

The orchestrator was **missing** from that chain until round 26, which made call sites
6 (pedagogy), 8 (assessment criterion review) and 11 (prerequisite) unreachable in a
real deployment even though their tests passed with an injected service.
`tests/test_jev_orchestrator_wiring.py` now pins the whole chain: the orchestrator, its
`assessments` and its `knowledge` all hold the *same* service object.

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

## Browser journeys: what exists, what cannot exist yet, and why

**Measured on revision `e4656aa`** (the suites start the real three-service shape — RAG API with the
UI extension mounted, the Node task agent, and the production web build behind the Netlify-shaped
static server — and drive real Chrome):

| suite | journeys | result |
|---|---|---|
| `tests/e2e/jev-structured.spec.ts` | **6** | 6 passed in 2.2 m (`work/current-change/browser_jev_round79.log`) |
| `tests/e2e/ui-refresh.spec.ts` | **21** | 21 passed in 4.3 m (`work/current-change/browser_ui_round79.log`) |

The six `jev-structured` journeys, by name: *the shipped shell reports the capability it dispatched*,
*the shipped shell can file a problem report without leaving the lesson*, *with no TypeSafe credential
every decision degrades and teaching still works*, *the shipped page verifies a named question
reference before filtering on it*, *prose that merely follows the number is not a sub-part*, and *a
question that names no question spends nothing*.

The task lists seven journeys to add. Six of them exist or are covered at a lower
layer with a real assertion; one cannot be written truthfully today because the
behaviour it would assert does not happen in any reachable runtime mode. Every row
says which, so a missing journey is never mistaken for a passing one.

| Task item | Status | Where it is actually verified |
|---|---|---|
| Skill selection (capability choice) | **EXISTS** | `tests/e2e/jev-structured.spec.ts` — the shipped shell's own create-run response reports `direct_qa`/`teaching_flow=false` for "只回答" and `node_lesson`/`teaching_flow=true` for a normal teaching message, and both runs reach `completed` |
| Jev unavailable / safe degradation | **EXISTS** | same file: the suite runs with **no** TypeSafe credential on purpose; every decision reports `used_jev=false` and the teaching run still completes with citations and no error. Also the whole 19-journey `ui-refresh.spec.ts`, which runs against the same shadow deployment |
| Alias retrieval (Chinese alias → English material) | **EXISTS at the retrieval boundary, deliberately not as a browser journey** | `tests/test_real_course_golden.py` on the **real GE2324 corpus**: the Chinese question has no lexical hit, and with the registry's accepted alias it reaches `assignment_2.pdf`. A browser journey cannot show this in the E2E environment because the deterministic stub embeddings answer any query with *some* similarity, so the citation list is not a discriminator; asserting it there would be a weaker claim dressed as a stronger one |
| Tool misexecution (a wrong side-effecting tool call) | **EXISTS at the real execution boundary** | agent-api `test/executor-intent-gate.test.ts` + `test/intent-gate.test.ts` (14 tests): write tools gated, `searchTask` never gated, `enforce` blocks with `CONFIRMATION_REQUIRED`, `off` byte-identical. A browser journey is impossible today because the E2E agent runs the **deterministic** model client, which never proposes a tool call — there would be nothing to block |
| Extraction verification | **EXISTS** | `tests/e2e/jev-structured.spec.ts` → "the shipped page verifies a question reference before filtering on it": the shipped QA page composes and sends its own `POST /api/qa/chat`, and the `meta` event it receives reports `questioned=true` with both labels, `dropped=[]`, and `used_jev=false` on every field; a prose message reports only `question_number` (no phantom part); a message naming no question reports `questioned=false` and `jev_calls=0`. A real *defect* verdict (`WRONG_FIELD` etc.) needs the live credential and stays `NOT_RUN` |
| Condition conflict | **CANNOT EXIST YET** | the conflict note requires a real `SAME_CONTEXT_CONTRADICTION`, which only a live TypeSafe decision can produce (mode `on`). What is provable today is the *absence*: `test_jev_evidence_consistency_wiring.py` proves the prompt is byte-unchanged under off/shadow/unavailable/no-Jev. The journey becomes possible the moment a real credential exists |
| Unsupported citation | **PARTIALLY EXISTS** | the deterministic half is proven without any credential (`test_citation_audit_binding.py`: a figure the claim asserts but the source never states is flagged with **zero** model calls; an unauthorized citation is `REJECTED`), and the shell's marker is unit-tested (`citationSupport.test.ts`). The semantic half (`NOT_ADDRESSED`/`CONTRADICTED` from a real decision) needs the live credential, so the end-to-end journey is `NOT_RUN` |

## Still open (not claimed as done)

1. **Modules A, B, C, D, E, F and the P2 feedback module are all wired with a consumer**, and none of
   them is promoted out of `shadow`. Module A's earlier `MODULE_ONLY` decision was reversed in round 30
   once the *query-side* exact-locator surface was found (the round-26 investigation had only looked at
   document-side field records); the full reasoning, the reproduced parser defect and the disposal rule
   are in `docs/jev-structured/SOURCE_EXTRACTION_AND_ENTITY_RELATIONS.md` §9.4.
2. **`retrieval.support.v1` costs one call per non-exact candidate, bounded at 16.** The bound is
   `DEFAULT_MAX_EVAL_CANDIDATES = 16`, so a retrieval page costs at most 16 rerank calls — *not* one per
   candidate in an unbounded page. **Corrected in round 31:** an earlier version of this line said a
   multi-question `evaluate` "would batch it". Checking the transport contract shows that is not
   available for this shape: `JevCall` is "one shared state, one or more questions" with the definition
   key as the question key, so several questions per call is only possible *over one shared state* —
   and per-candidate scoring has a different state per candidate. `evaluate_batch` loops `evaluate`, so
   it would not reduce transport calls either. The bound is the real cost control; if
   `DEFAULT_MAX_EVAL_CANDIDATES` is ever raised, this line and the cost estimate must move with it.
3. **Live Jev validation, calibration and the A/B/C/D/E ablation have not run** for any
   row: no TypeSafe credential exists in this environment. Every `live evidence` cell
   above is `NOT_RUN`, and no quality claim is made anywhere for a definition that has
   only produced shadow receipts.

### Closed in round 31

* **`QaService.stream` now runs the same module-D evidence bundle as the UI path.** A new private
  `QaService._evidence_bundle` builds `S1..Sn` spans from the hits the learner will see, calls
  `answers.evidence_bundle_support`, and annotates the citation cards — at most two calls (select one
  span, judge that span) whatever the page size. `answers.evidence_bundle_support` therefore has
  **two** production callers. With the layer genuinely absent (`jev=None`) the cards are byte-identical
  to before; with a configured-but-uncredentialed layer they carry `jev_citation_support: UNVERIFIED`
  and `jev_selected_span: false` — the same honest shape the UI path has produced since round 25.
  Pinned by four tests in `tests/test_qa_api.py`.
* **`is_definitive` has a caller.** The assessment high-impact gate reports `definitive` (a real
  `SUPPORTED`/`CONTRADICTED` verdict) separately from `verified` (layer 1 found nothing wrong), using
  `citation_audit.is_definitive` as the single source of that rule. See
  `docs/jev-structured/EVIDENCE_AND_CITATION_AUDIT.md` §"Wiring status" item 4.
* **Module D's resolver is mypy-clean.** `app/jev/citation_evidence.py` had four real type errors
  (`RetrievalAccess` receiving `str` where `Literal["official","mine"]` is required, and three
  `no-any-return`); it now reports no issues. The remaining whole-app mypy debt is untouched legacy code.

## Browser evidence per wired module

| Module | Journey | Assertion |
|---|---|---|
| A ExtractionVerification | `tests/e2e/jev-structured.spec.ts` → "the shipped page verifies a question reference before filtering on it" | the shipped QA page sends its own `POST /api/qa/chat`; its `meta` event reports `questioned=true` + `question_number`/`question_part` + `dropped=[]` + `used_jev=false` per field for a named reference, only `question_number` for prose that merely follows the number with a word, and `questioned=false` + `jev_calls=0` for a message that names no question. Plus the answer and citation list still render |
| E CapabilityRouter | `tests/e2e/jev-structured.spec.ts` → "the shipped shell reports the capability it dispatched" | the shipped shell's own create-run response reports `direct_qa` / `teaching_flow=false` / `used_jev=false` for "只回答" and `node_lesson` / `teaching_flow=true` for a normal teaching message, and both runs reach `completed` |
| E + all definitions (Jev unavailable) | `tests/e2e/jev-structured.spec.ts` → "with no TypeSafe credential every decision degrades and teaching still works" | with **no** TypeSafe credential configured, every decision reports `used_jev=false`, and the teaching run still completes with citations and no error |
| B EntityResolution (query expansion half) | `services/rag-api/tests/test_jev_shadow_invariance.py` + `tests/test_real_course_golden.py` | the original query stays the prefix, an unrelated query is not expanded, an explicit file/page/question target skips expansion, and the fused order is byte-identical under shadow / unavailable / `jev=None`. On the **real GE2324 corpus** with the real registry lookup, the real expansion and the real lexical search: a purely Chinese question ("聚类分析是什么意思") has **no** lexical hit, and with the registry's accepted alias "clustering" it reaches `assignment_2.pdf` — the "Chinese alias finds the English material" requirement, measured on real course files |
| F ToolIntentCheck | agent-api `test/executor-intent-gate.test.ts` (+ the endpoint tests) | write tools gated, `searchTask` never gated, `off` byte-identical, `advisory` records, `enforce` blocks |
| C EvidenceConsistency | `services/rag-api/tests/test_jev_evidence_consistency_wiring.py` | `sources` are byte-identical across off/shadow/unavailable/no-Jev; a real contradiction keeps both sources with unchanged ids/order, attaches `jev_conflict_with`, and appends exactly one bounded note to the teaching prompt; version/assumption differences never produce a conflict note |
| D ClaimCitationAudit | `services/rag-api/tests/test_citation_audit_binding.py` + `test_jev_citation_evidence.py` + `apps/web/src/ui/citationSupport.test.ts` | a figure the claim asserts but the source never states is flagged in code with **zero** Jev calls; a shadow decision annotates the cards without altering or dropping any; an unauthorized citation is `REJECTED` with its reason; a real signal records `SUPPORTED`; an audit failure never loses the answer; the per-answer budget (6 cards) is enforced; the resolver proves cross-user/cross-course material is `unauthorized` on a real migrated DB; the shell marks only a real negative verdict |
| Shell entry for the feedback module | **CORRECTED (round 79) — it is a real submission, and it is in the other suite** | `tests/e2e/jev-structured.spec.ts` → "the shipped shell can file a problem report without leaving the lesson": the shipped shell opens the 报告问题 dialog, sends its own `POST /api/feedback`, and the response carries a `feedback_…` report id. An earlier version of this row said `ui-refresh.spec.ts`; that suite only proves the entry is reachable through the help surface, which is a weaker claim than the one the module needs |
