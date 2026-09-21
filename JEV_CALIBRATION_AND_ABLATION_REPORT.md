# JEV_CALIBRATION_AND_ABLATION_REPORT

How the Jev decision layer is measured: the judgment dataset, the calibration procedure, the
A/B/C/D/E arms and the honesty rules that stop a plumbing run from being read as a quality result.

**Ablation result: `NOT_RUN`.** There is no TypeSafe credential and no DeepSeek key in this
environment, so no live and no labelled run has happened. Nothing in this report is a quality claim,
and the harness raises rather than emit one from fake or unlabelled data.

---

## 1. What is real today

| Asset | Path | State |
|---|---|---|
| Judgment dataset (310 samples) | `benchmarks/jev-judgments.dataset.json` | real, self-describing, validated by the builder |
| Frozen split manifest | `benchmarks/jev-calibration.split.json` | real; group-level splits + content hash |
| Calibration maths | `services/rag-api/app/evaluation/jev_calibration.py` | real, 43 tests |
| A/B/C/D/E ablation harness | `services/rag-api/app/evaluation/jev_semantic_ablation.py` | real, arms run offline |
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

## 6. Optional components added later

`FakeJevTransport`-backed optional modules (extraction verification, entity resolution, evidence
consistency, citation audit, capability routing, tool-intent check) get their own component ablation
switches. Like the main arms, they report `NOT_INTERPRETABLE` without real labels and a real Jev.

## 7. What is needed to produce a real result

1. `TYPESAFE_API_KEY` in the backend env (owner), `typesafe-sdk` pinned and installed.
2. DeepSeek key in the backend env plus an approved batch ceiling.
3. A labelled run on the frozen splits, calibration fitted on the calibration split only, then a
   single evaluation on the test split.
4. Only then may a definition leave `shadow` — and the promotion is per definition, with the
   non-inferiority evidence recorded here. Coverage and assessment stay advisory even when enabled.
