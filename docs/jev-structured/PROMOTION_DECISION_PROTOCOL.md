# Jev promotion decision protocol — **pre-registered**

**Registered 2026-09-24 (round 96), before the live component ablation and before any
calibration fit on the current 58-sample calibration split. Nothing is promoted today: all 19
definitions are `shadow` in the committed configuration.**

Why this document exists, in one sentence: §14's instruction is "promote `retrieval.support.v1`
plus at least one of context/intent/pedagogy once the calibration gate passes", and a gate that is
described after its numbers are known is not a gate. Everything a promotion decision may look at,
in what order, with what arithmetic, is fixed here **now**, so that when the budget arrives the
decision is executed rather than negotiated.

---

## 1. What is being decided, and by what mechanism

| Item | Value |
|---|---|
| Decision | for each definition, whether its runtime mode leaves `shadow` for `on` |
| Mechanism | `JEV_DEFINITION_MODES`, a comma-separated list of `key=mode` pairs |
| Allowed modes | `off`, `shadow`, `on` — `app/jev/gateway.py:69` (`MODES`) |
| Refusals | an unknown definition key, an unknown mode, or a malformed entry raises at **boot**, not at first use: `app/config.py::jev_definition_mode_map` (`JEV_DEFINITION_MODES entries must be key=mode`, `names an unknown definition`, `mode ... is not one of`). The reason is recorded in that property's docstring: an unknown key is a typo that silently leaves a definition in `shadow`, and a misspelled mode looks exactly like "the promotion had no effect" once the deployment is running |
| Default | `shadow` — the gateway falls back to the catalogue's `default_runtime_mode` (`app/jev/gateway.py:344`, `app/jev/catalog.py:119`) unless `modes` is passed; the service passes `resolved_settings.jev_definition_mode_map` (`app/main.py:140-145`), which is empty when the variable is unset |
| What `on` changes | the callsite consumes the decision instead of recording it; the deterministic half (permissions, locators, state machines, transactions, scores, coverage, `LEARNED`, database writes) never depends on Jev and is asserted unchanged by the shadow-invariance tests |

## 2. The evidence a decision may use, and the order it may be read in

| Step | What | Tool | What it must record |
|---|---|---|---|
| 1 | Population arithmetic — "can this definition be fitted and evaluated at all?" | `split_coverage`, `unfittable_definitions`, `unevaluated_definitions` (`app/evaluation/jev_semantic_ablation.py`) | per-definition train/calibration/test counts, zeros included |
| 2 | Arm measurement on the **calibration split**, live transport, real baseline | `scripts/run_jev_semantic_ablation.py --arm all --transport live --allow-billable --deepseek-baseline --out <fresh path>` (A–E) and the same with `--arm all-components` | `transport_used`, per-arm `metric_denominators`, per-case rows, `deepseek_call_delta_from_A` |
| 3 | Threshold fit on the calibration split only | `scripts/calibrate_jev.py --predictions <file> --split <manifest> --predictions-provenance <statement>` | `fitted_on_split: "calibration"` (hardcoded), `predictions_sha256`, `predictions_provenance`, `dataset_content_hash` |
| 4 | **One** look at the test split, with thresholds frozen | the same arm command against the test split | the artifact hash of the frozen thresholds it was run with |
| 5 | Promotion, if earned | `JEV_DEFINITION_MODES=<key>=on` | the receipt rows the promoted definition now writes (`mode=on`) |

Rules that come with the order:

* **The ablation's own preflight demands more than the run spends.** `_live_preflight` refuses a live
  run without `--allow-billable` **and** refuses when either `TYPESAFE_API_KEY` **or**
  `DEEPSEEK_API_KEY` is absent from the environment (`scripts/run_jev_semantic_ablation.py:213-223`),
  so the 93-decision component ablation — which makes **zero** DeepSeek calls — still cannot start
  unless the DeepSeek key is present. Both variables are also required for the A–E arms with
  `--deepseek-baseline`, where the DeepSeek calls are real.
* **The test split is read once.** If the rule below is not satisfied, the answer is `HOLD`, and the
  next look at test happens only after a *new* calibration decision — never by re-reading test.
* **The baseline is the shipped deterministic path with live DeepSeek**, never an abstaining stub.
  `compare_jev_arms` refuses a quality verdict from a fake transport, an unlabelled dataset, or a
  placeholder baseline; `run_jev_semantic_ablation.py` refuses to write when a component arm measures
  nothing (**exit 4**) and when the measured transport disagrees with the one the artifact would
  claim. A fake-transport run is `NON_INTERPRETABLE_PLUMBING_ONLY` and can never feed this decision.
* **A component arm reads both labelled datasets** (primary + companion), because no single file
  labels all six modules; `--no-module-dataset` is available but a metric left without samples is
  reported as `INSUFFICIENT_SAMPLES`, never as a zero.
* **Every rate is read with its denominator.** The arm summaries publish `metric_denominators` for
  exactly this reason: on the live calibration run, `key_fact_retention` moving 1.000 → 0.000 is
  **one** case out of two.

## 3. The decisive metric per candidate, declared now

The contrasts are the design's own nesting: **B vs A** adds retrieval reranking, **C vs B** adds
context/intent/pedagogy, **D vs C** adds coverage/assessment criterion support, **E vs D** adds
citation support and span selection. The module metrics are the ones `component_arm_metrics(arm)`
returns:

| Candidate definition(s) | Contrast | Decisive (primary) metrics | Safety metrics — zero tolerance |
|---|---|---|---|
| `retrieval.support.v1` | B vs A | `locator_accuracy`; `recall_at_k` / `mrr` / `ndcg_at_k` **when the dataset grades relevance** (today it does not: the live denominator was 0, so they are not measurable and cannot be used) | — |
| `context.keep_segment.v1` | C vs B | `key_fact_retention`, `context_compaction` | — |
| `intent.next_action.v1` | C vs B | `intent_accuracy` | — |
| `pedagogy.next_method.v1` | C vs B | `pedagogy_accuracy`, `mainline_recovery_rate` | — |
| `coverage.item_support.v1` | D vs C | `coverage_confusion` (precision and recall reported separately) | — |
| `assessment.criterion_review.v1` | D vs C | `criterion_error` | — |
| `source.supports_claim.v1` | E vs D | `citation_support_accuracy` | `unsupported_claim_rate` |
| `source.select_span.v1` | E vs D | `span_selection_accuracy` | — |
| `extraction.field_grounded.v1` | M-EXTRACT | — | `extraction_false_acceptance`, `extraction_false_rejection` |
| `entity.relation.v1` | M-ENTITY | — | `entity_false_merge`, `entity_conflict_false_positive` |
| `evidence.consistency.v1` | M-CONSISTENCY | `condition_distinction` | — |
| `teaching.capability.v1` | M-CAPABILITY | — | `capability_misroute` |
| `tool.intent.v1` | M-TOOL | — | `tool_false_allow` (the safety-critical one), `tool_false_block` |

All other metrics are **reported but never decisive**. That is the whole point of naming the primary
one in advance: with ~30 metrics per arm, "some metric improved" is not a finding.

## 4. The decision rule, in arithmetic

For a candidate definition, let `D` be its decisive metric and `S` its safety metrics:

1. **Decisiveness.** The published denominator of `D` must be **≥ 20** on the calibration split and
   **≥ 20** on the test split. If not → `INSUFFICIENT_EVIDENCE`. *This floor is a policy choice, made
   now so it cannot be made after seeing the number.* Its rationale is measured, not stylistic: at
   today's denominators a single case moves a rate by 17–50 points, and the live A–E result is
   exactly that (one case each way on `criterion_error` and `key_fact_retention`).
2. **No harm.** No safety metric may move in the harmful direction at all (margin **0**), and `D`
   may not fall by more than the granularity of its own denominator.
3. **Benefit.** `D` must improve in the intended direction.
4. **Consistency.** The sign of the change in `D` must agree between the calibration split and the
   test split.
5. **Same run shape.** Both contrasts must come from runs whose `transport_used` is `live`, whose
   baseline is the shipped deterministic path, and whose datasets are the frozen ones (content hashes
   recorded in the artifacts).

| Outcome | Condition | What is recorded |
|---|---|---|
| `PROMOTE` | 1–5 all satisfied | `JEV_DEFINITION_MODES=<key>=on`, the two artifacts, the frozen thresholds, and the receipts the definition writes afterwards |
| `HOLD` | decisive but 2/3/4 fail | the numbers, and the explicit statement that the definition stays in `shadow` |
| `INSUFFICIENT_EVIDENCE` | rule 1 fails | the denominators, so the shortfall is visible as a number |
| `REJECT` | a safety metric moves harmfully | the metric, the case ids, and a note that the defect is in the module, not in the data |

## 5. Where that stands today — the honest version

**Executing this protocol on the current data returns `INSUFFICIENT_EVIDENCE` for every
definition, including the task's first candidate.** This is not a prediction; it is the two
populations the tools actually report:

* Dataset-level calibration samples (primary dataset, 345 samples, 13 definitions — from
  `split_coverage`): `retrieval.support.v1` **10**, `corpus.quality.v1` 8, `source.supports_claim.v1`
  7, `intent.next_action.v1` 6, `coverage.item_support.v1` 5, `pedagogy.next_method.v1` 5,
  `source.select_span.v1` 4, `exercise.prototype.v1` 4, `assessment.criterion_review.v1` 3,
  `template.match.v1` 3, `context.keep_segment.v1` 2, `graph.prerequisite.v1` 1,
  `image_transcription.v1` **0**. Companion dataset (54 samples): `extraction.field_grounded.v1` 4,
  `teaching.capability.v1` 3, `entity.relation.v1` 2, and 1 each for `evidence.consistency.v1`,
  `feedback.category.v1`, `feedback.severity.v1`, `tool.intent.v1`. **No definition reaches 20.**
* Measured arm denominators from the live A–E calibration run
  (`work/current-change/jev-ablation-live-baseline3.json`, which ran on the **47**-sample
  calibration view of the time — `work/current-change/jev-calibration-split.dataset.json`; the split
  is 58 samples since round 95, so these denominators are the smallest the decision will ever see, not
  a current maximum): `citation_support_accuracy` **6**,
  `unsupported_claim_rate` 6, `span_selection_accuracy` 4, `intent_accuracy` 3,
  `criterion_error` 3, `key_fact_retention` **2**, and `locator_accuracy` **0**. That file contains no
  `retrieval.support.v1` sample at all (that was the round-95 gap) and its sample schema carries no
  graded-relevance or exact-locator field, so the retrieval family's decisive metric had nothing to
  measure — which is why `recall_at_k` / `mrr` / `ndcg_at_k` are `null` rather than `0.0` in every arm.

Two consequences, both stated rather than buried:

1. **A favourable live ablation alone cannot promote anything**, and the existing live A–E result is
   *unfavourable* on two metrics anyway (`criterion_error` 0.000 → 0.333,
   `key_fact_retention` 1.000 → 0.000).
2. **The cheapest honest path to a real promotion decision is more labels, not more model calls.**
   Reaching the floor for the first candidate needs ~10 more rule-derived calibration samples for
   `retrieval.support.v1` (and its decisive metric needs exact-locator expectations to exist at all);
   `source.supports_claim.v1` would need ~13. Round 95 did exactly this kind of extension for four
   definitions at zero model cost, and it is additive: appended samples keep the earlier ids stable,
   while the dataset content hash necessarily moves — and every live measurement taken before the
   extension refers to the old hash, which the artifacts record.

**If the owner prefers a lower floor than 20, that is their policy decision and it must be recorded
here, with its date, before the live run** — not inferred afterwards from a favourable number.

## 6. What this protocol forbids

* Fitting a threshold on `train` or `test` (the calibrator cannot do it: `fitted_on_split` is
  hardcoded to `calibration`, and it refuses an empty calibration split or an unpredicted row).
* Reading the test split more than once per calibration decision.
* Promoting on a fake transport, an unlabelled dataset, a placeholder baseline, a shadow receipt, a
  `health=200`, or a Jev `confidence` value (a confidence is never a label — `jev_calibration`'s own
  rule).
* Promoting a definition whose decision no callsite consumes, or one whose module is safety-critical
  (`tool.intent.v1`, `coverage.item_support.v1`, `assessment.criterion_review.v1`) beyond advisory use.
* Changing a decisive metric, a contrast, or the floor after seeing an outcome number.
* Treating "no harm observed on 2–6 cases" as a promotion licence.

## 7. Rollback

Every promotion is a single environment value, so the rollback is the same value: remove the
`key=on` pair (or set `key=shadow`), restart the service, and the definition returns to recording
receipts instead of steering behaviour. No data migration, no schema change and no code change is
involved, which is why the mechanism was built as configuration rather than as a code path.

## 8. Cross-references

* `docs/jev-structured/EVALUATION_AND_CALIBRATION.md` — the acceptance/calibration evidence behind §2.
* `JEV_CALIBRATION_AND_ABLATION_REPORT.md` §9 — the live A–E result and the component-arm tables.
* `docs/recovery/CURRENT_BLOCKER_LEDGER.md` **B-07** — the promotion blocker this protocol serves.
* `MINIMAL_OWNER_ACTION_CARD.md` §1b — the budget decision that unlocks the live runs, and the
  owner's call on which definitions may leave `shadow`.
