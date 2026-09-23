# JEV_CALIBRATION_AND_ABLATION_REPORT

How the Jev decision layer is measured: the judgment dataset, the calibration procedure, the
A/B/C/D/E arms and the honesty rules that stop a plumbing run from being read as a quality result.

**Ablation result: live A–E run done on the calibration split; the *comparison* is
`NOT_INTERPRETABLE` and that is the harness's own verdict.** The Jev half of the ablation now runs
against the real service (`typesafe-sdk==0.7.0`, live transport, 53 calls over the 47-sample
calibration split), and each arm's absolute metrics against the labels are real numbers (§8). What
is still missing is a **production/DeepSeek baseline predictor**, so arm A abstains on every sample
and the harness refuses to read the difference as a quality claim
(`reason: "placeholder baseline (no production predictor injected)"`). Nothing in this report is a
claim that Jev beats DeepSeek; the per-arm numbers in §8 are what the live model actually scored,
and the calibration thresholds remain untuned (`thresholds = UNSET_UNTIL_CALIBRATED_ON_LABELLED_DATA`).

The DeepSeek side of the earlier statement still holds for the *comparison*: no live DeepSeek
baseline has been run in this harness. (The separate DeepSeek canary did run live — 10/10 roles —
and that is reported in `docs/coursejesus/MODEL_SECRET_IMPORT_AND_LIVE_RESULTS.md`, not here.)

---

## 1. What is real today

| Asset | Path | State |
|---|---|---|
| Judgment dataset (310 samples) | `benchmarks/jev-judgments.dataset.json` | real, self-describing, validated by the builder — **measured at round 82: 310 samples covering 13 definitions, splits 196/47/67** (the split manifest's own `count` fields) |
| Frozen split manifest | `benchmarks/jev-calibration.split.json` | real; group-level splits + content hash |
| Companion module dataset (49 samples) | `benchmarks/jev-module-judgments.dataset.json` | real — 7 samples each for the seven definitions the frozen set does not cover, which is what the six module arms are measured on |
| Calibration maths | `services/rag-api/app/evaluation/jev_calibration.py` | real; covered by `test_jev_calibration.py` (**19 tests, collected at round 82** — an earlier version of this row said 43, which no suite in the tree collects) |
| A/B/C/D/E ablation harness | `services/rag-api/app/evaluation/jev_semantic_ablation.py` | real, arms run offline; the measurement suite as a whole is **122 tests across eight files** (`test_jev_calibration`, `test_jev_ablation`, `test_jev_ablation_baselines`, `test_jev_module_metrics`, `test_jev_module_split_calibration`, `test_jev_semantic_ablation`, `test_jev_semantic_component_ablation`, `test_jev_semantic_ablation_cli`) |
| Builders / CLIs | `scripts/build_jev_dataset.py`, `scripts/calibrate_jev.py`, `scripts/run_jev_semantic_ablation.py` | real, offline-safe |
| Older A–D plumbing harness | `app/evaluation/jev_ablation.py`, `scripts/run_jev_ablation.py` | kept, untouched; superseded for reporting by the semantic harness |

`python scripts/build_jev_dataset.py --validate --stats` output (real):

```
310 samples
per definition family: retrieval 50 · citation 42 · intent 25 · pedagogy 24 · corpus_quality 24
                       criterion 24 · context 19 · coverage 18 · classification 16 · span_selection 16
                       exercise 12 · prerequisite 12 · trajectory 12 · image 8 · locator 8
label tiers: OBJECTIVE_VERIFIED · SOURCE_REVIEWED · SILVER_DEEPSEEK · DISPUTED
split sizes: train 196 · calibration 47 · test 67
content_hash: 2af0f40d1d1e89c6f7a8092cb846258f2b36b208c58f0211932344a32d33c10d
```

Option counts span 2/3/4/5/6/8/15 so the evaluation exercises small and large candidate sets rather
than one shape repeated. The dataset is deliberately **not** 300 variants of one question.

## 2. Labels and leakage control

* Tiers: `OBJECTIVE_VERIFIED` (a rule, an id or arithmetic decides it), `SOURCE_REVIEWED` (a course
  source and a review reason are recorded), `SILVER_DEEPSEEK` (a model suggestion, explicitly **not**
  human gold) and `DISPUTED` (both readings written down).
* Splits are assigned by `(document_id, node_id, question_family)` — never by row — so the same
  underlying question with different numbers cannot appear in two splits. The builder's `--validate`
  and the tests both assert complete assignment, unique ids and group atomicity.
* Thresholds may only be fitted on the calibration split. The test split is for the final evaluation
  and must not be used to tune a threshold until the numbers look good.

## 3. Calibration

`jev_calibration.py` implements expected calibration error, a deterministic-grid temperature fit,
per-`(primitive, language, option-count)` bucket keys, and enforcement that a fitted temperature is
recorded with its bucket. Applying a second temperature to an already temperature-scaled probability
raises rather than silently stacking.

Precision caveat, recorded in code and in the artifact: the SDK returns probabilities already rounded
to four decimals. Calibration therefore uses the highest precision the SDK exposes and never pretends
to reconstruct logits; a fitted temperature is reported as an approximation at that precision.

`confidence` is `1 − normalized entropy` of the answer distribution — **distribution concentration**.
It is never mapped to `p_correct`, never used as an accuracy reference, and never becomes a grade.

**Where the artefact's numbers come from (added in round 41).** `scripts/calibrate_jev.py` already pinned
its dataset by content hash and its split by name, and recorded the input paths. It now also records
`predictions_sha256` — the digest of the predictions file, which is the only model evidence it consumes —
and `predictions_provenance`, an explicit statement supplied with the new optional
`--predictions-provenance` flag. When that flag is omitted the artefact records **`UNSTATED`** and the CLI
prints a note saying the numbers are only as real as the predictions file. That matters here more than
elsewhere: this is the artefact a promotion out of `shadow` would lean on, and before this change a
synthetic predictions file produced a file that read exactly like a fitted result. Run it as:

```
python scripts/calibrate_jev.py --predictions <file> \
  --predictions-provenance "jev shadow run <revision> (<date>)" \
  --dataset benchmarks/jev-judgments.dataset.json \
  --split benchmarks/jev-calibration.split.json --out <artifact>
```

## 4. Arms (versioned; historical definitions unchanged)

| Arm | Definition |
|---|---|
| A | DeepSeek + deterministic fixes, **no Jev** |
| B | A + `retrieval.support.v1` rerank |
| C | B + `context.keep_segment.v1` + `intent.next_action.v1` + `pedagogy.next_method.v1` |
| D | C + `coverage.item_support.v1` + `assessment.criterion_review.v1` |
| E | D + `source.supports_claim.v1` + `source.select_span.v1` |

Classification, exercise prototype, prerequisite and corpus quality have their own families and are
measured separately. The nesting A⊂B⊂C⊂D⊂E is asserted, so a later edit cannot silently break it.

Metrics: Recall@K, MRR, NDCG, exact-locator accuracy, citation-support accuracy and unsupported-claim
rate, context anchor retention, intent accuracy, pedagogy case success, coverage FP/FN, assessment
criterion error, score error, latency (p50/p95), Jev cost, DeepSeek cost and failure rate.

## 5. Honesty guardrails (all enforced in code and tested)

1. Every metric reads **labels only**; a model's own probability or confidence is never ground truth.
2. A `fake` transport run is tagged `NON_INTERPRETABLE_PLUMBING_ONLY` and `compare_jev_arms` returns
   `NOT_INTERPRETABLE`; asking for a quality claim raises `ValueError`.
3. A live run is interpretable only with a `LABELLED_DATASET`, never the example file.
4. A family whose non-Jev baseline is a placeholder (abstention, or a service default) is named in
   `placeholder_baselines` and makes the comparison `NOT_INTERPRETABLE` until the real baseline is
   injected — so arm A is the pipeline the product actually ships.
5. Fixed anchors and exact locators are never offered to Jev for dropping; the harness asserts this.

Offline run just executed (`--arm all --transport fake`, exit 0):

```
arm=A..E  interpretation=NON_INTERPRETABLE_PLUMBING_ONLY
arm=E     recall@k=1.000 mrr=0.857 ndcg=0.895 citation_acc=0.300 ...
comparison verdict=NOT_INTERPRETABLE
```

Those numbers exist only to prove the arms are wired and differentiated. **They are not results.**

## 6. Component arms for the six structured modules (implemented, and honest about labels)

Alongside A–E (whose definitions are untouched), the harness now exposes one component arm
per structured-enhancement module. `--arm all` still means A–E; `--arm all-components` runs the
six below.

| Arm | Module | Definition turned on | Metric | Status on the frozen dataset |
|---|---|---|---|---|
| `M-EXTRACT` | ExtractionVerification | `extraction.field_grounded.v1` | extraction false acceptance / false rejection | `INSUFFICIENT_SAMPLES` (see §6.1 — this dataset has none) |
| `M-ENTITY` | EntityResolution | `entity.relation.v1` | entity false merge / missed alias / conflict false positive | `INSUFFICIENT_SAMPLES` (see §6.1) |
| `M-CONSISTENCY` | EvidenceConsistency | `evidence.consistency.v1` | condition distinction | `INSUFFICIENT_SAMPLES` (see §6.1) |
| `M-CITATION` | ClaimCitationAudit | `source.supports_claim.v1` + `source.select_span.v1` | citation-support accuracy, unsupported-claim rate (citation, n=42), span-selection accuracy (span_selection, n=16) | **MEASURED** |
| `M-CAPABILITY` | CapabilityRouter | `teaching.capability.v1` | capability misroute | `INSUFFICIENT_SAMPLES` (see §6.1) |
| `M-TOOL` | ToolIntentCheck | `tool.intent.v1` | tool false allow / false block | `INSUFFICIENT_SAMPLES` (see §6.1) |

Five of the six report `INSUFFICIENT_SAMPLES` for **every** module metric and emit **no number**: the
frozen 310-sample dataset contains zero samples for `extraction.field_grounded.v1`,
`entity.relation.v1`, `evidence.consistency.v1`, `teaching.capability.v1` and `tool.intent.v1`. The
intent family labels `intent.next_action.v1` actions (CONTINUE/PAUSE/…), not capability ids, and the
citation family labels claim-support, not condition distinction — so deriving those labels would mean
inventing a measurement, which the harness refuses to do. `compare_jev_arms` also refuses a quality
verdict whenever any contributing arm has an unmeasured metric.

To make those five measurable, the dataset must be extended with labelled samples for their
definitions (a sampling task that needs the live model and the owner's budget). Until then their
component arms are plumbing: differentiated, offline, and explicitly unmeasured.

### 6.1 Round 31: the companion dataset, and the reason it was not enough on its own

Five of those arms were refusing for **two** reasons, and only one of them was data:

* **the runner had no result collection for those families at all** — `extraction_false_acceptance`,
  `entity_false_merge`, `condition_distinction`, `capability_misroute`, `tool_false_allow/block`
  could not be computed for *any* dataset. All ten module metrics (plus two for P2 feedback) are now
  implemented, each with its population stated in the docstring and its denominator published in
  `metric_denominators`, so a `0.0` over an empty population cannot be read as a clean result;
* **the frozen dataset had no labels for them**, and it is immutable (its `content_hash` and split
  are pinned by test). A **companion** dataset was therefore added rather than an edit:
  `benchmarks/jev-module-judgments.dataset.json` — 49 samples, 7 per definition, for exactly the
  seven definitions that had none; tiers 6 `OBJECTIVE_VERIFIED` (each naming a deterministic rule
  checked in the code), 41 `SOURCE_REVIEWED`, 2 `DISPUTED` (both readings recorded) and **zero
  `SILVER_DEEPSEEK`**, because no model was called.

With both fixed, the arms report `MEASURED` over the companion dataset:

| Arm | Metric | Status (companion dataset) |
|---|---|---|
| `M-EXTRACT` | extraction false acceptance / false rejection | **MEASURED** (n=7 each) |
| `M-ENTITY` | entity false merge / missed alias / conflict false positive | **MEASURED** (n=7 each) |
| `M-CONSISTENCY` | condition distinction | **MEASURED** (n=7) |
| `M-CAPABILITY` | capability misroute | **MEASURED** (n=7) |
| `M-TOOL` | tool false allow / false block | **MEASURED** (n=7 each) |
| (none) | feedback category accuracy / severity MAE | **MEASURED** (n=7 each; P2 has no component arm) |

**Computable is not the same as interpretable.** Every one of those numbers comes from the
deterministic fake transport, so the run stays `NON_INTERPRETABLE_PLUMBING_ONLY` and
`compare_jev_arms` still refuses a quality verdict. The values prove the metric discriminates; they
say nothing about a model.

### 6.2 The companion split manifest, and two limitations it makes visible in code

The companion dataset initially had no split manifest, which made it unreachable for the calibrator
(whose contract is "fit only on the held-out calibration split, refuse when there is none").
`scripts/build_jev_module_split.py` now builds `benchmarks/jev-module-judgments.split.json` from the
same code as the frozen manifest (`build_split_manifest`) and is idempotent — it verifies instead of
rewriting, and a difference is a hard error rather than a silent change to a pinned split.

The manifest records `train 28 / calibration 10 / test 11`, and `split_coverage()` prints both
limitations explicitly rather than letting a reader assume full coverage:

* **`entity.relation.v1` has no calibration-split sample** → its temperature cannot be fitted until
  it has more groups. This also corrects a false claim in the code: `assign_split`'s docstring used
  to promise that "every definition contributes to every split", which a hash-based assignment
  cannot guarantee. The docstring now says what the function does.
* **`extraction.field_grounded.v1` has no test-split sample** → nothing is held out to evaluate it
  on yet.

Two provenance defects were fixed at the same time, both exposed by making the dataset
configurable: the artifact used to record the *frozen* manifest name and dataset path even when
fitting a companion set (`split_ref` / `dataset_path` now name the files actually used), which would
have pinned an artifact to a split it never saw.

Finally, the calibration path is proven to run over the companion dataset end to end:
`calibrate_jev.py --dataset … --split …` produced an artifact with `n_calibration = 10`, 5 buckets
and the companion `content_hash`. **The predictions in that run were synthetic** (a flat
distribution written by the test), which is why ECE is unchanged before and after — that run
demonstrates the plumbing, and is not a calibration result.

### 6.3 Round 39: which dataset each arm must run against, and the offline numbers

The table above reports "status on the frozen dataset", which is now only half the story, because the
labels are split across two files on purpose. **No single dataset covers all six arms:**

| Dataset | Samples | Definitions it labels |
|---|---|---|
| `benchmarks/jev-judgments.dataset.json` (frozen) | 310 | 13 — including `source.supports_claim.v1` (42) and `source.select_span.v1` (16), which is why the citation arm needs this file |
| `benchmarks/jev-module-judgments.dataset.json` (companion) | 49 | 7 — the definitions that had none, which is why the other five arms need this file |

Together they cover every catalog definition exactly once (13 + 7 = 20 ids = **19 catalog definitions**
plus the deliberately non-catalog `image_transcription.v1` case set), across 359 labelled samples.

So the rule is: `--arm M-CITATION` with the **frozen** dataset; `--arm M-EXTRACT|M-ENTITY|M-CONSISTENCY|
M-CAPABILITY|M-TOOL` with the **companion**. Running every component arm against one file makes the arms
whose labels live in the other report `INSUFFICIENT_SAMPLES`, which is a statement about the pairing, not
about the system.

Run in round 39, offline (`--transport fake`, so every number below is tagged
`NON_INTERPRETABLE_PLUMBING_ONLY` — these say the arms compute numbers where labels exist, never that the
quality is good):

| Arm | Metric | Value | Labels for the decision | Rate denominator |
|---|---|---|---|---|
| `M-EXTRACT` | extraction_false_acceptance | 1.0 | 7 | 4 |
| | extraction_false_rejection | 0.0 | 7 | 2 |
| `M-ENTITY` | entity_false_merge | 1.0 | 7 | 4 |
| | entity_missed_alias | 1.0 | 7 | **1** |
| | entity_conflict_false_positive | 0.0 | 7 | 4 |
| `M-CONSISTENCY` | condition_distinction | 0.0 | 7 | 4 |
| `M-CAPABILITY` | capability_misroute | 0.2 | 7 | 5 |
| `M-TOOL` | tool_false_allow | 1.0 | 7 | 3 |
| | tool_false_block | 0.0 | 7 | 2 |

Two column meanings that are easy to confuse, stated because they disagree on purpose: **labels for the
decision** is how many labelled samples exist for the definition that metric reads (7 for
`tool.intent.v1`), while **rate denominator** is the population the rate divides by (3 for
`tool_false_allow`, because only three of the seven cases are ones that should have been blocked). The
runner publishes both (`component.metrics.*.samples` and `metric_denominators`), and neither may be read
alone — `entity_missed_alias`, for instance, has a denominator of **1**, so its value carries almost no
information yet and should not be quoted as a rate.

Evidence: `work/current-change/semantic-arms-companion-r39.json` (companion run) and
`work/current-change/semantic-arms-r39.json` (frozen run), both produced by
`scripts/run_jev_semantic_ablation.py --arm all-components --transport fake`.

**Before running this CLI live, read this.** `--transport live` on
`run_jev_semantic_ablation.py` now **refuses** (exit 3, no output written): the CLI has no live predictor
wiring, and until round 40 it fell through to the fake transport while labelling the artefact `live` — with
both credentials present and `--allow-billable`, which is exactly the live-gate condition. The live Jev
transport exists for the A–E arms in `scripts/run_jev_ablation.py`; the six component arms need live
predictors that do not exist yet, so a live component-arm run has to be built first rather than faked. Every
ablation artefact now records `transport_used` beside the requested `transport`, and the CLI refuses to write
if the two disagree.

## 7. What is needed to produce a real result

1. `TYPESAFE_API_KEY` in the backend env (owner) **and** `typesafe-sdk==0.7.0` installed in the service
   venv — the key alone was not wired until round 38 (the adapter never read it) and the package is an
   optional dependency that is commented out in `requirements.txt`, so both halves are required. The
   adapter's usage of that package was verified against the real wheel in round 39, which corrected two
   values: the model override is `TYPESAFE_DEFAULT_MODEL` (not `TYPESAFE_MODEL`) and the default model is
   the SDK's `jev-latest` (not `jev`).
2. DeepSeek key in the backend env plus an approved batch ceiling.
3. A labelled run on the frozen splits, calibration fitted on the calibration split only, then a
   single evaluation on the test split.
4. **Corrected in round 39:** the five module definitions no longer need labels invented — the companion
   dataset supplies 7 each and their arms are measurable offline today (§6.3). What is still needed for
   those arms is a **live** run, and the citation arm needs the frozen dataset rather than the companion.
   The remaining thin spot is population size (`entity_missed_alias` divides by 1), not missing labels.
5. Only then may a definition leave `shadow` — and the promotion is per definition, with the
   non-inferiority evidence recorded here. Coverage and assessment stay advisory even when enabled.

## 8. The live A–E run, measured 2026-09-24 (calibration split only)

**Setup.** `--transport live --allow-billable`, the real `SdkTransport`, the calibration split of
the frozen manifest written out as its own dataset file
(`work/current-change/jev-calibration-split.dataset.json`, 47 samples taken by sample id from
`benchmarks/jev-calibration.split.json`; train and test excluded, asserted in the builder). The test
split was **not** touched, because thresholds are tuned on calibration and the test set is looked at
once.

**53 live calls, every one answered** (arm A 0, B 0, C 9, D 17, E 27), latency p50 745–784 ms, max
1,421 ms. Evidence: `work/current-change/jev-ablation-live-abcde.json` (+`.log`), and every call's
raw answer is recorded inside it next to the label it was compared with.

| metric | A | B | C | D | E |
|---|---|---|---|---|---|
| `intent_accuracy` | 0.000 | 0.000 | **0.667** | 0.667 | 0.667 |
| `pedagogy_accuracy` | 0.000 | 0.000 | **1.000** | 1.000 | 1.000 |
| `context_compaction` | 0.000 | 0.000 | **1.000** | 1.000 | 1.000 |
| `criterion_error` | 1.000 | 1.000 | 1.000 | **0.333** | 0.333 |
| `coverage_confusion` (tp/fn) | 0/3 | 0/3 | 0/3 | **2/1** | 2/1 |
| `citation_support_accuracy` | 0.000 | 0.000 | 0.000 | 0.000 | **0.833** |
| `span_selection_accuracy` | 0.000 | 0.000 | 0.000 | 0.000 | **0.750** |
| `unsupported_claim_rate` | 1.000 | 1.000 | 1.000 | 1.000 | **0.500** |

Each arm improves exactly the metric its added definition owns, which is the nesting behaving as
designed rather than a coincidence of one definition lifting everything.

**What this is not.** The comparison verdict is `NOT_INTERPRETABLE`, with the harness's own reason:
`placeholder baseline (no production predictor injected)`. Arm A abstains on every sample, so the
gaps above are **not** "Jev beats DeepSeek" — they are "the definition answers correctly where
nothing answered before". Reading them as lift over DeepSeek would be exactly the substitution the
task forbids.

**Three honest limits of these numbers.**

1. **No live DeepSeek baseline predictor exists**, so arms A and B cannot yet produce a comparable
   number. Wiring one is the next step; until then the A/B rows are abstention baselines.
2. **`locator_accuracy = 0.000`, `corpus_quality_mae = 3.0`, `key_fact_retention = 0.000` are
   abstention baselines too**, not failures: the calibration split carries no locator samples
   (those are `source.select_span`/locator families in other splits), and `corpus.quality.v1` is an
   ingestion-time definition that no A–E arm turns on. Arm B is empty for the same reason: the
   calibration split has no `retrieval.support.v1` samples (all 58 are in train/test).
3. **The continuous Score value is discretised by rounding to the nearest declared level** in the
   predictor, and `noul` is binarised at 0.5. Both are the *comparison's* mapping, stated in the
   predictor's docstring and recorded in each call, not calibrated boundaries. The measured
   separation lives in the "Live evidence" section of `JEV_CALLSITE_MATRIX.md` (3.99 vs 0.0 on
   `retrieval.support.v1`; 1.77–1.82 vs 0.95–1.05 on `corpus.quality.v1`; 2.0 vs 0.03 on
   `feedback.severity.v1`).

**What it takes to finish this measurement.** A production/DeepSeek baseline predictor, then the
same run on the calibration split to fit thresholds, and one evaluation on the test split — after
which the per-definition promotion decision in §14 of the task can be taken on evidence.
