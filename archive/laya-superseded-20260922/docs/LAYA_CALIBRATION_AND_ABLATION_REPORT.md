# SUPERSEDED_BY_JEV_DECISION

This document belongs to the abandoned Laya direction (2026-09-22). The owner stopped Laya
and restored the TypeSafe Jev backend semantic layer. Nothing here is a production source of
truth; it is retained only as history and for the reusable ideas listed in
DSH_JEV_DEEPSEEK_EXECUTION_STATE.md.

---

# Laya Calibration & Ablation 鈥?Measurement Layer Report

Workstream: the auditable Laya judgment dataset, probability calibration, and the
A/B/C/D/E ablation for replacing the TypeSafe Jev semantic layer with the self-hosted
`convaiinnovations/laya` (subfolder `multilingual`, revision
`1c5edc17a7acd8701df6fc341c0d179f1c62c982`, Apache-2.0).

**Headline: the ablation result is `NOT_RUN`. No quality claim is made, and no sentence
in this document (or anywhere in the code) says "Laya improved X%".** The reason is
mechanical: no Laya service and no DeepSeek key exist in this environment, so no real
labelled data was ever executed. Everything below is the measurement layer 鈥?dataset,
calibration maths, harness 鈥?plus an offline plumbing run whose only honest output is
`NOT_INTERPRETABLE`.

---

## 1. Files delivered

| File | Purpose |
|---|---|
| `benchmarks/laya-judgments.dataset.json` | The real, self-describing labelled dataset (310 samples). |
| `benchmarks/laya-calibration.split.json` | The frozen split manifest (grouping keys, per-split counts, content hash). |
| `services/rag-api/app/evaluation/laya_calibration.py` | Pure calibration maths (no I/O): ECE, temperature fitting, buckets, application rules. |
| `services/rag-api/app/evaluation/laya_ablation.py` | The A/B/C/D/E harness: arms, metrics, dataset/split validation, runner, comparison. |
| `scripts/build_laya_dataset.py` | Deterministic builder/validator (`--build`, `--validate`, `--stats`; no network). |
| `scripts/calibrate_laya.py` | Fits + writes a temperature artifact from a predictions file; refuses without a held-out calibration split. |
| `scripts/run_laya_ablation.py` | CLI; offline by default; `--transport fake|live`; `--allow-billable` for anything billable. |
| `services/rag-api/tests/test_laya_calibration.py` | Hand-computed ECE/temperature, refusal paths, precision caveats. |
| `services/rag-api/tests/test_laya_ablation.py` | Arm nesting, metric hand-checks, split-leakage, refusal paths, label-tier invariants. |
| `LAYA_CALIBRATION_AND_ABLATION_REPORT.md` | This report. |

The existing JeV files (`app/evaluation/jev_ablation.py`, `scripts/run_jev_ablation.py`,
`benchmarks/jev-ablation-cases.example.json`, `tests/test_jev_ablation*.py`) were read
and **not modified**. The Laya harness reuses their metric semantics by importing
(`recall_at_k`, `mrr`, `locator_accuracy`, `citation_support_accuracy`,
`unsupported_claim_rate`, `coverage_confusion`, `criterion_error`,
`image_answer_accuracy`, `latency_summary`, `cost_split`, `failure_rate`, the result
dataclasses, and `compare_arms` for the refusal semantics).

## 2. Dataset composition (real numbers, from `--stats`)

```
total samples: 310
```

Per definition (12 catalogue definitions + the image-transcription family, which is
DeepSeek vision, not a Laya/Jev decision):

```
retrieval.support.v1            58   (50 ranking + 8 exact-locator)
source.supports_claim.v1        42
intent.next_action.v1           37   (25 single-turn + 12 multi-turn trajectories)
pedagogy.next_method.v1         24
assessment.criterion_review.v1  24
corpus.quality.v1               24
context.keep_segment.v1         19
coverage.item_support.v1        18
source.select_span.v1           16
template.match.v1               16
exercise.prototype.v1           12
graph.prerequisite.v1           12
image_transcription.v1           8
```

Per label tier:

```
OBJECTIVE_VERIFIED   235   (generated and checked by code: rules, ids, negation flips, arithmetic)
SOURCE_REVIEWED       38   (cite the in-repo course inventory/transcription with a locator + review reason)
SILVER_DEEPSEEK       34   (marked "unreviewed", NOT human gold)
DISPUTED               3   (both readings recorded; excluded from single-label metrics)
```

Per language:

```
en  165
zh  145     (CourseMate's primary language is well represented)
```

Option-count distribution (genuinely different shapes, 2/4/6 plus score widths and
dynamic-cardinality choices):

```
2 options   74    (noul + span-negatives)
3 options   20    (dynamic choice with NONE/NO_SUPPORT, small candidate sets)
4 options   81    (coverage/criterion/corpus-quality + span selection)
5 options   58    (retrieval score levels 0鈥?)
6 options   24    (pedagogy)
8 options   37    (intent)
15 options  16    (template.match: T01鈥揟14 + OTHER)
```

Split sizes (group-level, never row-level):

```
train          196
calibration     47
test            67
content_hash   bf299f5a1240a61b4797150c9351d8ec93b923d57b23628dca746e960a699a57
```

Coverage of the required shapes: option counts 2/4/6, Chinese and English states,
short and long evidence, negation and numeric cases, multi-turn continue/pause
trajectories, image-transcription-linked items (the real `GE2324 Assignment 2` K-means
color-clustering transcription), and cross-permission negatives (a candidate/segment/
prototype/predecessor from another course or workspace that must be rejected or scored
`0`/`UNSUPPORTED`/`NONE`).

No `state` contains a hidden plan or a private answer; states are small, bounded, and
match each definition's `required_state` (validated by `validate_laya_dataset`).

## 3. Split-leakage proof

Splits are assigned **by `(document_id, node_id, question_family)` group, never by row**.
`assign_split` is a pure, deterministic function of the group key (a 3:1:1
train/calibration/test repeating pattern over the per-group ordinal, so every
definition contributes to every split). `validate_split_leakage` enforces, in code:

1. every sample is assigned to exactly one of train/calibration/test;
2. no `sample_id` appears in more than one split;
3. samples sharing a `(document_id, node_id, question_family)` group are in the same
   split 鈥?this is the "same underlying question with different numbers must not appear
   in two splits" protection, because numeric/negation variants of one question share
   one group key.

This is asserted in `scripts/build_laya_dataset.py` (`validate()`) and in two tests
(`test_split_leakage_validation_passes_on_frozen_manifest`,
`test_split_leakage_rejects_a_group_split_across_splits`,
`test_same_group_gets_the_same_split_and_manifest_matches`). The manifest also carries a
`content_hash` over the labelled samples, so a temperature fitted against one dataset
cannot silently be applied to a different one.

## 4. Calibration maths and its precision caveat

`app/evaluation/laya_calibration.py` is pure (no I/O, no model, no network). It provides:

* `expected_calibration_error(conf, correct, bins=15)` 鈥?equal-width, bin-mass-weighted
  ECE, matching the official `rl_common.ece_score` semantics the README numbers come
  from.
* `temperature_bucket(primitive, language, option_count)` 鈥?the bucket key
  `"{primitive}:{language}:{size}"` with cardinality bands `2 / 3-5 / 6-10 / 11+`
  (per-primitive / per-language / per-option-count, exactly as required).
* `fit_temperature` / `fit_temperatures_by_bucket` 鈥?one temperature per bucket,
  minimising mean NLL over a deterministic log-spaced grid (`0.5 .. 2.0`), fitted only
  on the held-out **calibration** split (refuses `fitted_on_split != "calibration"`).
* `apply_recorded_temperature` 鈥?a fitted temperature is only applied when it is
  **recorded** (raises `TemperatureNotRecorded` otherwise), and a second temperature is
  refused on an already-scaled value (raises `DoubleTemperatureApplication`).
* `normalized_entropy_confidence` 鈥?documented **only** as distribution concentration
  (`1 鈭?normalized entropy`); it is never mapped to `p_correct`, never treated as
  accuracy, and never becomes a grade anywhere.

**Precision caveat (recorded in code and in every artifact):** the official Laya service
rounds every reported probability to **4 decimal places**
(`rl_agent_api.py` -> `round(float(v), 4)`). Calibration therefore runs on the
highest-precision values the service can give, and any 4-decimal value carries the
stated limitation (`PRECISION_DECIMALS = 4`, `PRECISION_LIMITATION_NOTE`). Probability
鈫?logit inversion (`probs_to_logits`) is a lossy projection when the probabilities were
already rounded. No fitted temperature artifact is committed here because **no real
predictions exist** 鈥?only the maths and the writer script are delivered. (A smoke test
with synthetic uniform-ish logits ran `calibrate_laya.py` end-to-end: 47 calibration
rows -> 12 buckets -> ECE 0.3994 -> 0.1466; those numbers are plumbing, not results.)

## 5. Ablation arms (as implemented)

`ARM_NAMES = ("A", "B", "C", "D", "E")`; nesting is validated strictly
(`A 鈯?B 鈯?C 鈯?D 鈯?E`). The on-keys reference the unchanged catalogue ids via
`load_catalog()`:

| Arm | Laya turns "on" | Stays on DeepSeek/deterministic |
|---|---|---|
| **A** | *(none)* | everything |
| **B** | `retrieval.support.v1` | everything else |
| **C** | B + `context.keep_segment.v1`, `intent.next_action.v1`, `pedagogy.next_method.v1` | template/exercise/prerequisite/corpus/coverage/assessment/citation |
| **D** | C + `coverage.item_support.v1`, `assessment.criterion_review.v1` | template/exercise/prerequisite/corpus/citation |
| **E** | D + `source.supports_claim.v1`, `source.select_span.v1` | template/exercise/prerequisite/corpus |

`template.match.v1`, `exercise.prototype.v1`, `graph.prerequisite.v1` and
`corpus.quality.v1` are never replaced by Laya in this workstream and are measured as
**separate families** (classification, exercise, prerequisite, corpus quality).

Metrics computed (same semantics as the JeV harness, labels-only): Recall@K, MRR,
NDCG@K, exact-target protection (`locator_accuracy`), citation support accuracy +
unsupported-claim rate, span-selection accuracy, context key-fact retention +
compaction, intent accuracy, pedagogy accuracy, coverage false-confirm/false-miss
(`coverage_confusion`), criterion error, classification/exercise/prerequisite accuracy,
corpus-quality MAE, mainline recovery rate, image answer accuracy, end-to-end latency
(`latency_summary`), local resource use (Laya call count), DeepSeek call delta (vs arm
A), and total cost. Metrics read labels only 鈥?a Laya/DeepSeek probability or
`confidence` is never a label, grade, or accuracy reference (the result dataclasses do
not even carry one).

Honesty guards (enforced in code): a fake transport run is tagged
`NON_INTERPRETABLE_PLUMBING_ONLY`; `compare_laya_arms` returns `NOT_INTERPRETABLE` for
fake transports, unlabelled data, **and** any family whose non-Laya baseline is a
placeholder (abstention or a default constant) rather than the shipped deterministic
path 鈥?and it **raises** on a requested quality claim in those cases.

## 6. Verification run (real output)

**Tests** 鈥?`pytest tests/test_laya_calibration.py tests/test_laya_ablation.py -q`:

```
43 passed in 0.52s
```

Covering: hand-computed ECE (`0.25/3 + 0.175路2/3 = 0.2`), hand-computed temperature fit
(NLL grid `0.5/1.0/2.0` -> argmin `0.5`), `temperature_scale_probs([0.9,0.1], 2.0) ->
[0.75,0.25]`, the recorded-only/double-application refusals, the `confidence`-is-
concentration semantics, the bucket-key scheme, the 4-decimal precision constant, arm
nesting, `ndcg`/`choice_accuracy`/`score_level_mae`/`key_fact_retention` hand-checks,
the dataset's composition and label-tier invariants, the split-leakage proof, and the
fake-run refusal paths.

**Dataset** 鈥?`python scripts/build_laya_dataset.py --validate --stats`:

```
validation ok: schema, label-tier invariants, split-leakage, content hash
total samples: 310
... (full composition in 搂2)
```

**Ablation** 鈥?`python scripts/run_laya_ablation.py --arm all --transport fake --out <fresh path>`:

```
comparison verdict=NOT_INTERPRETABLE
exit_code=0
```

Every arm is tagged `NON_INTERPRETABLE_PLUMBING_ONLY`; the verdict line is
`NOT_INTERPRETABLE`. (The per-arm plumbing numbers 鈥?e.g. `recall@k=1.000` in arm A 鈥?are artifacts of the deliberately non-informative fake responder's tie-break and carry
**no meaning**; they are not results.)

**Lint** 鈥?`ruff check` on all seven new Python files: `All checks passed!`.

## 7. What could NOT be done (and is therefore NOT_RUN)

1. **No live ablation.** No Laya service and no DeepSeek key exist here, and no network
   calls were made. `run_laya_ablation.py --transport live` refuses unless
   `--allow-billable` **and** both `LAYA_SERVICE_URL` and `DEEPSEEK_API_KEY` are
   configured. The report therefore states the ablation as **NOT_RUN**.
2. **No fitted temperature artifact.** Fitting requires real model predictions for the
   47-sample calibration split; none exist, so no `temperature_by_options` artifact is
   committed (only the writer + maths). The default `ml_rl_agent_config.json` values
   (`temperature [1.0,1.0,1.0]`, `temperature_by_options {}`) remain unmodified 鈥?if a
   temperature is later fitted, it must be recorded (and never double-applied), which
   the code refuses to do silently.
3. **No `SILVER_DEEPSEEK` / `DISPUTED` promotion.** Those tiers are explicitly not
   human gold (silver) or have no single gold answer (disputed) and are excluded from
   any single-label quality claim; they exist for provenance, not accuracy.
4. **No quality claim of any kind.** This is enforced, not just asserted: a quality
   claim from fake/unlabelled/placeholder data raises `ValueError`.

## 8. Honesty rules, satisfied

1. Fake transports are `NON_INTERPRETABLE_PLUMBING_ONLY`; `compare_laya_arms` returns
   `NOT_INTERPRETABLE` and raises on a requested quality claim. 鉁?2. No "Laya improved X%" sentence appears; the ablation is `NOT_RUN`. 鉁?3. `confidence` is documented and handled as distribution concentration only. 鉁?4. A fitted temperature is recorded with its bucket and a second application is refused
   in code. 鉁?5. Metrics read labels only 鈥?never a model's own confidence/probability. 鉁?
