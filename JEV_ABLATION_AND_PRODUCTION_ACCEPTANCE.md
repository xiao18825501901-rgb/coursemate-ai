# JEV_ABLATION_AND_PRODUCTION_ACCEPTANCE

Status of the A/B/C/D ablation and of production acceptance for this release. **No PASS is
claimed without evidence**; everything not executed is listed as NOT_RUN with the exact
authorization it needs.

---

## 1. Deterministic acceptance (required to go green from a real failure)

| # | Requirement | Evidence | Status |
|---|---|---|---|
| 1 | started + zero coverage = `LEARNING`; no start = `NOT_STARTED`; all REQUIRED = `LEARNED`; stale spec does not impersonate the current spec | `tests/test_jev_deepseek_gap_regressions.py` (written first, **failed on the pre-fix tree**) | **PASS** |
| 2 | official+private candidates merge into one global ranking; a private candidate can win a slot | same file, `…merges_private_candidates_before_top_k` (failed before) + `tests/test_retrieval_fusion_unit.py` (7 tests) | **PASS** |
| 3 | exact file/page/question locator is not displaced by a semantically similar hit | `…exact_target_is_not_replaced_by_rank` | **PASS** |
| 4 | `grade_label` empty but `raw_score` present → real score shown (`78/100 · AI自测`), never 未测评; latest vs independent results separated | `_atomic_assessment`/`_knowledge_tree` DTO + `test_ui_extension_learning_closure.py`, `test_codex_knowledge_snapshot.py` | **PASS** (backend); UI rendering is part of the assessment workstream |
| 5 | insufficient pool produces a real, completable preparation path; five questions are not seeded; verification levels recorded honestly | assessment workstream tests (migration 027 + preparation jobs) | **PASS** per its suite; see the final report for the exact test names |
| 6 | 16 templates load by hash; 题目/详解 and `exercise.v2` unchanged | `work/current-change/verify_template_v2.py` → 16/16 hashes match; `tests/test_jev_deepseek_template_v2.py` (21 passed) | **PASS** |
| 7 | no new Qwen generation egress; Qwen-only fields never sent to DeepSeek | `tests/test_deepseek_provider_roles.py` (+ capability matrix) | **PASS** (contract level) |
| 8 | Jev Choice/Noul/Score separated; illegal candidate rejected; timeout/unavailable → deterministic fallback; no state write on failure; cache invalidation + cross-user isolation | `tests/test_jev_gateway.py`, `test_jev_service.py`, `test_jev_wiring.py` (23 passed) | **PASS** |
| 9 | plan text never public; hidden answers never leak before submit; draft ≠ submission | existing plan-privacy suite + assessment workstream tests | **PASS** (asserted in both suites) |
| 10 | same request id is not billed or written twice; grading failure keeps the previous valid result | coverage/idempotency suites + assessment workstream | **PASS** |

## 2. Local regression evidence (commands actually run in this workspace)

| Command | Result |
|---|---|
| `pytest tests/test_jev_deepseek_gap_regressions.py tests/test_retrieval_fusion_unit.py -q` | 11 passed |
| `pytest tests/test_ui_extension_coverage_submission.py tests/test_ui_extension_learning_closure.py -q` | 49 passed |
| `pytest tests/test_knowledge_registry.py tests/test_publication_v3.py tests/test_teaching_profiles_api.py tests/test_ui_extension_integration.py tests/test_codex_knowledge_snapshot.py -q` | 42 passed |
| `pytest tests/test_jev_catalog.py tests/test_jev_gateway.py tests/test_jev_service.py tests/test_jev_wiring.py -q` | 23 passed |
| `pytest tests/test_deepseek_contract.py tests/test_deepseek_provider_roles.py tests/test_jev_deepseek_template_v2.py -q` | 53 passed |
| `pytest tests/test_current_change_features.py -q` | 13 passed |
| `pytest tests/test_assessment_preparation_contract.py -q` | 10 passed |
| `pytest tests/test_codex_template_integrity.py -q` → `tests/test_v3_migration_rehearsal.py -q` | 16 failures → **22 passed**; 1 failure → **4 passed** (both causes fixed and pinned; see the final report §4.1) |
| `work/current-change/mig_probe.py` (fresh init + replay) | `integrity=ok`, `fk_violations=0`, no `*_old`/`*_new`, max migration 28, all 17 assessment triggers present |
| Full backend regression (all files) | **789 passed / 17 failed** before the two fixes → **808 passed / 0 failed** in 2074.86s (exit 0) after them; details in `FINAL_COURSEMATE_JEV_DEEPSEEK_RELEASE_REPORT.md` §4 |
| Web build + vitest | build exit 0, 17 files / 64 tests passed |
| Agent build + vitest | build exit 0, 10 files / 72 tests passed |

## 3. A/B/C/D ablation

| Arm | Definition | Current state |
|---|---|---|
| A | DeepSeek + V2 templates + deterministic fixes, **no Jev** | available: this is the shipped configuration (all 12 decisions in `off`/`shadow` with the deterministic path authoritative) |
| B | A + Jev retrieval re-rank | implemented and wired in **shadow** (reorder-only, exact-target protected); the harness can execute B by switching the key to `on` |
| C | B + Jev context/intent/pedagogy | helpers implemented and tested; no live `on` call site yet |
| D | C + Jev coverage/assessment review | coverage signal recorded in provenance (shadow); assessment review helper implemented, not enabled |

**Ablation result: NOT_RUN.** Reasons, stated plainly:

* No TypeSafe credential/credit in this session → no real Jev judgements, so B/C/D cannot be
  measured.
* No DeepSeek credential/budget → arm A cannot be measured on a real model either; measuring A
  against a fake provider would be meaningless and is exactly what the rules forbid.
* The plan's dataset (200 labelled semantic judgements, 40 multi-turn trajectories, 30 image
  cases) is a **plan**, not a result; no part of it has been run.

Because of that, the rule "do not claim quality improvement from typed Jev output" is honoured:
no improvement claim is made anywhere in this release.

### 3.1 Metrics and how they will be produced (frozen plan, no numbers invented)

| Metric | Source of truth |
|---|---|
| Recall@K, MRR/reranking quality | labelled retrieval set; deterministic baseline vs B |
| exact question locator accuracy | explicit file/page/question cases with known targets |
| citation support accuracy, unsupported-claim rate | span-level human labels (never model self-scores) |
| multi-turn mainline recovery rate | 40 labelled trajectories; anchor preservation checked deterministically first |
| coverage FP/FN | frozen spec items vs accepted evidence, reviewer decisions recorded |
| assessment per-criterion error | rubric labels with acceptable-alternative answers |
| image transcription/answer accuracy | synthetic multi-page image answers with a known ground truth |
| latency P50/P95 | deployment-region measurement, not demo numbers |
| cost split (DeepSeek / Jev / embedding) | per-role token and call receipts |
| total failure rate | receipt outcomes across the run |

Thresholds stay centralized and `UNSET` until calibrated on the labelled split; the release gate
is frozen **before** looking at the final holdout, and one definition switches from `shadow` to
`on` only with a documented non-inferiority result.

### 3.2 Ablation harness (implemented; result still NOT_RUN)

The A/B/C/D harness now exists and runs offline with zero credentials:

```
services\rag-api\.venv\Scripts\python.exe scripts\run_jev_ablation.py --arm all --transport deterministic_fake --out work\current-change\jev-ablation-offline.json
```

* Arm resolution, case schema/loader, the twelve metric functions, the runner and the honesty
  guardrails live in `services/rag-api/app/evaluation/jev_ablation.py`; the CLI is
  `scripts/run_jev_ablation.py`; the self-contained example is
  `benchmarks/jev-ablation-cases.example.json` (`dataset_status`
  `EXAMPLE_NOT_LABELLED_FOR_RESULTS`); the tests are `services/rag-api/tests/test_jev_ablation.py`.
* An offline (`deterministic_fake`) run is tagged `NON_INTERPRETABLE_PLUMBING_ONLY`, and
  `compare_arms` refuses an improvement verdict (raising `ValueError` on a quality-claim
  request). A live run is tagged `INTERPRETABLE` only with a `LABELLED_DATASET` — never the
  example file.
* **Ablation result: still NOT_RUN.** No metric number from the offline plumbing run is a
  quality result, and no number is reported here. The real dataset (200 judgements /
  40 trajectories / 30 image cases) is not invented in this release; when it and the
  credentials/budget arrive, the same command with `--transport live --allow-billable` plus a
  labelled case file produces the numbers.

**Baseline fidelity — fixed in this round, because a comparison is only as honest as its
baseline.** Verifying the harness surfaced three ways it could have flattered Jev once a live
credential arrives; all three are fixed and pinned by tests
(`services/rag-api/tests/test_jev_ablation_baselines.py`, `tests/test_intent_commands.py`):

1. **Explicit commands both wasted a model call and depressed the baseline.** 继续 / 暂停 /
   只回答 / 做一题 / 回到主线 / 交卷 and their English equivalents are meant to be answered by
   deterministic code (requirement 6). They now go through
   `app/learning/intent_commands.py::route_explicit_command` — a conservative, I/O-free router
   that fires only when the message *is* the command (a command with a new object, e.g.
   "继续讲一下 K-means", is semantic and is deliberately not routed) — and never reach Jev. The
   run records how many turns took that path.
2. **Placeholder baselines could look interpretable.** For coverage, criterion and citation the
   non-Jev side used to be an abstention when no production predictor was injected, which is not
   what the product ships. `run_ablation` now accepts the real baselines (`coverage_baseline`,
   `criterion_baseline`, `citation_baseline`), names any remaining placeholder in
   `placeholder_baselines`, and `compare_arms` refuses to call such a comparison interpretable
   (`verdict="NOT_INTERPRETABLE"`, and `ValueError` on a quality-claim request).
3. **Fixed anchors were offered to Jev.** The harness asked whether to keep *the anchor itself*,
   so arms C/D scored 0.000 on the mainline metric purely because the transport answered "drop" —
   a penalty the product can never suffer, since anchors are fixed by construction and only the
   filterable class (resolved follow-ups, duplicate explanations, unrelated asides) may be
   dropped. The anchor is now preserved structurally, Jev is asked only about
   `filterable_segments` (recorded as informational, not a quality metric), and a test asserts the
   anchor survives even when the transport says drop.

Consequence for reading any future live result: arm A must be the shipped pipeline — the
deterministic fixes plus the deterministic command router — and the release gate is
non-inferiority against that baseline, never against an abstaining stub.

## 4. Production acceptance

| Item | Status | Required to proceed |
|---|---|---|
| Production database backup + isolated restore rehearsal | **NOT_RUN** | explicit authorization to touch the production host for this release |
| Migration 026–028 applied to production | **NOT_RUN** | same authorization (verified on isolated copies only) |
| Immutable release + backend/frontend deployment | **NOT_RUN** | same authorization (plus Netlify scope) |
| Real signed-in browser journeys (multi-user, private isolation, learning, five-question flow) | **NOT_RUN** | a real login; the earlier round recorded Cloudflare/Clerk blocking and no captcha bypass is attempted |
| Post-release backup + monitoring verification | **NOT_RUN** | follows the deployment authorization |
| DeepSeek live canary (text, structured, vision, tool replay) | **NOT_RUN** | `DEEPSEEK_API_KEY` + bounded budget |
| Jev live canary + calibration | **NOT_RUN** | TypeSafe access + bounded budget |

`health=200`, a fake provider, a local screenshot or an SDK success are **not** treated as
acceptance evidence anywhere in this report.

## 5. What the owner must provide (single card)

See `MINIMAL_OWNER_ACTION_CARD.md`: DeepSeek key + confirmed alias + bounded batch budget;
TypeSafe access + bounded budget + data-scope confirmation; production operations authorization
plus a real login for the browser journey.
