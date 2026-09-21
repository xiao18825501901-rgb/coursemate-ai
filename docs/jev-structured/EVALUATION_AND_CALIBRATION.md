# EVALUATION_AND_CALIBRATION

How the Jev layer and the six structured-enhancement modules are measured, and what may and may not
be concluded from each kind of run.

**Current state: `ABLATION = NOT_RUN`.** No TypeSafe credential and no DeepSeek key exist in this
environment, so no live and no labelled run has happened. Nothing below is a quality claim.

---

## 1. Data

| Asset | Detail |
|---|---|
| Judgment dataset | `benchmarks/jev-judgments.dataset.json` — 310 samples over the catalog's definitions plus trajectory, image and locator families |
| Split manifest | `benchmarks/jev-calibration.split.json` — train 196 / calibration 47 / test 67, assigned by `(document_id, node_id, question_family)` so a question variant cannot leak across splits; content hash recorded and recomputed by the builder |
| Label tiers | `OBJECTIVE_VERIFIED` (a rule, id or sum decides it), `SOURCE_REVIEWED` (course source + review reason recorded), `SILVER_DEEPSEEK` (a model suggestion, explicitly not human gold), `DISPUTED` (both readings written down) |
| Threshold policy | fitted on the **calibration** split only; the test split is opened once for the final evaluation. No global `0.8`-style acceptance constant |

Component sets for the six enhancement modules extend the same dataset with module-specific families
(extraction fields, entity pairs, evidence pairs, citation claims, capability requests, tool
proposals). Each module ships its own switch so a component ablation can turn it off without touching
the main arms.

## 2. Arms

Main ablation (frozen; historical definitions unchanged):

| Arm | Contents |
|---|---|
| A | DeepSeek + deterministic only, **no Jev** |
| B | A + `retrieval.support.v1` rerank |
| C | B + context / intent / pedagogy |
| D | C + coverage / assessment criterion review |
| E | D + citation support / span selection |

Component ablations (each module on/off against the same A baseline): `ExtractionVerification`,
`EntityResolution`, `EvidenceConsistency`, `ClaimCitationAudit`, `CapabilityRouter`, `ToolIntentCheck`.

## 3. Metrics

Retrieval and evidence: Recall@K, MRR, NDCG, exact-locator accuracy, citation support accuracy and
unsupported-claim rate, context anchor retention, condition distinction, conflict false-positive rate.
Routing and capability: intent accuracy, capability misroute rate, `NO_SKILL` quality.
Extraction: field false-acceptance and false-rejection (a wrong value accepted is worse than a value
sent for review).
Tools: tool false-allow and false-block; unnecessary-approval count.
Learning and assessment: coverage false-confirm/false-miss, criterion error, score error, pending-review
rate. Cost and time: end-to-end success rate, p50/p95 latency, Jev calls/tokens/cost, DeepSeek
calls/cost, failure rate.

Hard invariants that any run must also satisfy, checked deterministically rather than scored: no
permission leak, no plan disclosure, no hidden-answer exposure, no duplicate grade write on replay, no
node-id or file mutation.

## 4. Honesty rules (enforced in code, not by convention)

1. Metrics read **labels only**; a model's own confidence or probability is never ground truth.
2. A `fake` transport run is tagged `NON_INTERPRETABLE_PLUMBING_ONLY`; `compare_jev_arms` returns
   `NOT_INTERPRETABLE` and raises if a quality claim is requested.
3. A live run is interpretable only on a labelled dataset — never on the shipped example.
4. A family whose non-Jev baseline is a placeholder (abstention or a service default) is named in
   `placeholder_baselines` and blocks an interpretable verdict until the real baseline is injected.
5. A passing test set means "these samples passed", not "the system can never misjudge".

## 5. Promotion gate

Per definition, never as a group. The intended first promotions are `retrieval.support.v1` plus at
least one of context/intent/pedagogy, each only after a documented non-inferiority result on the
calibration and test splits. Citation support, extraction verification and the tool-intent check may
influence behaviour only with an acceptable error rate; coverage and assessment remain advisory even
when enabled — the deterministic backend keeps the final word. A definition that does not clear the
gate stays `shadow`, and the final report must say so rather than lower the bar.

## 6. Reproducing a run

```
services\rag-api\.venv\Scripts\python.exe scripts\build_jev_dataset.py --validate --stats
services\rag-api\.venv\Scripts\python.exe scripts\run_jev_semantic_ablation.py --arm all --transport fake --out <fresh path>
services\rag-api\.venv\Scripts\python.exe scripts\calibrate_jev.py --help
```

The offline run proves wiring only. Producing a real result additionally needs
`TYPESAFE_API_KEY` (+ the pinned `typesafe-sdk`) and the DeepSeek key with an approved ceiling, as
listed in `MINIMAL_OWNER_ACTION_CARD.md`.
