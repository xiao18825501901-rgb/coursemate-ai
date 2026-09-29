# HYBRID_QUALIFICATION_AND_REGRESSION

Status: `DEEPSEEK_REVIEW_A_B` **live-verified** ·
`HYBRID_SCOPED_QUALIFICATION` **NOT ESTABLISHED** ·
`QUALITY_NONINFERIORITY_EVIDENCE` **UNKNOWN**

This is the round's most important honest result: the hybrid mechanism is
implemented, its providers really work, and the reviewers **failed** their own
held-out qualification, so the gate refused to qualify them and nothing can be
published through it.  The fail-closed design did its job.

## 1. Regression

| Suite | Result |
|---|---|
| Full RAG suite, first pass | 1957 passed, 3 skipped, **49 failed** |
| Root cause of the 49 | migration 065 used bare `CREATE TABLE`/`CREATE TRIGGER`; migrations are replayed on every startup |
| Fix | every statement in 065 is `IF NOT EXISTS`, so the file is replay-safe |
| All 49 re-run | **221 passed, 0 failed** |
| New hybrid tests | `test_hybrid_review_policy.py` 20, `test_hybrid_publication.py` 10, `test_hybrid_qualification.py` 10 — **40 passed, 0 failed** |
| Skips | 3 platform/optional-SDK skips (Windows symlink privilege, POSIX permission bits, `typesafe-sdk` not installed) — all pre-existing |

The three skips are the same three reported by the previous round and are not
related to this change.

## 2. Live verification of the two reviewer roles

Run on the application host with the production protected credential and the
configured `V3_MODEL=deepseek-flash` / `https://api.deepseek.com` role.  Exactly
two billable requests; no retry.

| Fact | Observed |
|---|---|
| roles | `evidence_audit`, `adversarial_audit` |
| distinct provider response ids | **yes** |
| distinct input hashes | **yes** |
| terminals | both `completed` |
| template versions | `judge-evidence-audit.v1`, `judge-adversarial-audit.v1` |
| schema version | `coursejesus-judge-findings.v1` (strict JSON schema accepted by the configured role) |
| reference verification | `case_set_exact=true`, `quotes_traceable=true`, `steps_exist=true` |
| tokens | 5 171 input / 736 output for the pair |
| combined verdicts | `ambiguity=PASS`, `answer_agreement=PASS` → projected `CLEAR`, `AGREE` |

So the pipeline is real: the model returns traceable, quoted, schema-valid
findings, and the server verifies the references rather than trusting them.

## 3. The qualification run

* Runner: `scripts/run_hybrid_qualification.py`
* Data: a restored **copy** of the live database (the live file was only read).
* Target: workspace `0f364c85-3010-4b91-811c-2e6333111a18` (the blocked private
  SQL course's own workspace), node `auto-node-9e012c6325c909bff3a56780b804`,
  evidence `WORKSPACE_PRIVATE`, detected language `en`.
* 12 server-authored items (4 NUMERIC, 4 MCQ_SINGLE, 4 rule-policy EXPLANATION),
  authored by the same production author + blind-solver pair; 0 authoring
  failures.
* 43 evaluation rows: 11 `POSITIVE_CONTROL`, 29 `INJECTED_DEFECT`.
* 3 rows failed with `HYBRID_REVIEW_PROVIDER_FAILED` and were **not retried** —
  the recorded-run contract working as designed.
* Dataset digest `28847c47d17867189545c6628aaf1626da66796ea5100c9f20fb3e77d8e5501b`.

### 3.1 The release decision (what actually gates publication)

An item is released only when **both** reviewers `PASS` **every** required case.

| Metric | Value |
|---|---|
| positive rows released (`true_accept`) | 9 / 11 |
| positive rows refused (`false_reject`) | 2 |
| negative rows released (**`false_accept`**) | **9 / 29** |
| negative rows refused (`true_reject`) | 18 |
| abstain | 2 |
| coverage | 0.95 |
| release precision | **0.50** |
| release recall | 0.818 |
| false-release rate | **0.310** |

### 3.2 Per-case false-accept (diagnostic only, not the release rule)

| case | positives | negatives | false accepts | abstain |
|---|---|---|---|---|
| `question.ambiguity.v1` | 11 | 29 | 19 (65.5 %) | 1 |
| `question.answer_agreement.v1` | 11 | 29 | 21 (72.4 %) | 0 |
| `question.mcq_distractor_quality.v1` | 4 | 10 | 6 (60.0 %) | 1 |
| `question.rule_violation_quality.v1` | 3 | 11 | 7 (63.6 %) | 1 |

### 3.3 By injected defect

| defect | rows | wrongly released |
|---|---|---|
| `DUPLICATE_CORRECT_OPTION` (a distractor restates the correct option) | 4 | **0** |
| `UNSUPPORTED_RULE` (cited rule loses its prerequisite) | 3 | **0** |
| `MISSING_CONDITION` (an operative condition is removed from the stem) | 10 | 2 |
| `DISAGREEING_SOLUTION` (the two solutions no longer agree) | 12 | **7** |

Two honest readings of that table:

* **The reviewers do catch some real defects every time.**  A duplicated correct
  option and a rule cited without its prerequisite were rejected 7 times out of
  7.  That is genuine, useful behaviour.
* **The `DISAGREEING_SOLUTION` number is partly a measurement artifact.**  The
  mutation writes a sentinel into an `answer` key of the blind payload, while the
  blind-solve contract's substantive fields are `conclusion` and `steps`; a
  reviewer that reads the conclusion sees it unchanged and can reasonably report
  agreement.  This mutation therefore does **not** cleanly separate "the reviewer
  is weak" from "the mutation is not the defect it claims to be", and the 7/12
  figure must not be reported as a pure reviewer error rate.
* The `MISSING_CONDITION` result (8/10 caught) and the MCQ/rule results are the
  least ambiguous signals available, and they are still far too weak:
  6/10 and 7/11 false accepts are not a basis for publishing.

### 3.4 Two independent weak points found

1. **Verbatim-quote strictness causes false rejects.**  8 rows were blocked by
   `HYBRID_REVIEW_REFERENCES_UNVERIFIED`.  Both positive controls that were
   "refused" show **all case verdicts `PASS`** yet were not released: the
   reviewers' findings were sound but a citation was not a byte-exact fragment
   of the cited span (reviewers re-wrap and lightly re-word quotations).  The
   strict check is doing what it was designed to do — a paraphrase is not
   evidence — but it currently costs real false rejects, and the reviewers need
   a citation style that survives it.
2. **The reviewers are far too permissive on under-specification and
   disagreement.**  Even taking the mutation caveat into account, 60–66 %
   false-accept on the MCQ and rule cases is a decisive failure.

### 3.5 Decision recorded by the harness

```json
{"status": "DRAFT", "cases": [], "languages": [], "domains": [],
 "unmeasured_cases": ["question.ambiguity.v1", "question.answer_agreement.v1",
                      "question.mcq_distractor_quality.v1",
                      "question.rule_violation_quality.v1"]}
```

`recorded_qualification_id = null`.  **No qualification row was written**, so
`_resolve_qualification` returns `HYBRID_QUALIFICATION_MISSING` for every
candidate and the gate stays closed.  This is the designed outcome: the code path
that would have published was exercised end to end and it refused.

The harness also prints `zero_false_accept_upper_bound_95 = 0.2209` over 12
independent negative families.  **That number is not applicable here** — the
one-sided bound is only defined for a *zero* false-accept observation, and this
run has nine.  It is reported for completeness, not as a risk claim.

## 4. Four quality requirements — status

| Original requirement | Status |
|---|---|
| `question.ambiguity.v1 → CLEAR` | **implemented, not qualified** (65.5 % false accept) |
| `question.answer_agreement.v1 → AGREE` | **implemented, not qualified** (72.4 % false accept, partly a mutation artifact) |
| `question.mcq_distractor_quality.v1 → ACCEPTABLE` | **implemented, not qualified** (60.0 % false accept) |
| `question.rule_violation_quality.v1 → SUPPORTED` | **implemented, not qualified** (63.6 % false accept) |

The semantics of all four are unchanged and no gate was relaxed.  None of them
may currently be satisfied by the hybrid chain, because no qualification covers
them.

## 5. Quality non-inferiority

`QUALITY_NONINFERIORITY_EVIDENCE = UNKNOWN`.

There is no paired, same-sample comparison against a healthy historical reviewer:
the previous chain's 117 receipts are `choice` strings from the retired TypeSafe
SDK with no probability distribution and no held-out labels, and the local
OpenJev candidate has no signal at all.  Nothing in this round establishes that
the hybrid reviewers are as good as anything.  What can be said honestly is:

* the four requirements were not lowered;
* the deterministic hard gates are unchanged and were never overridden;
* no question was published on unqualified evidence;
* the hybrid chain measurably rejects some real defects reliably and is
  measurably too permissive on others.

## 6. What has to change before this can qualify

1. **Fix the mutation, then re-measure.**  `DISAGREEING_SOLUTION` must mutate the
   blind contract's real conclusion/steps, not an unused key, before its
   false-accept count can be attributed to the reviewers.
2. **Make citations pass the strict check.**  Give the reviewers the exact
   character window they are asked to quote, or normalise only whitespace on both
   sides of the comparison while keeping comparison case- and word-exact.
3. **Strengthen the two weak cases.**  Under-specification and disagreement need
   prompts and worked counterexamples that explicitly enumerate the conventions
   that must be checked (units, NULL/duplicate/order assumptions, self-inclusion,
   scope limits) — the adversarial prompt already lists these, and the measured
   result says listing them was not enough.
4. **Grow the negative set.**  Ten to twenty-nine negatives per case is small;
   even a clean run at this size would leave a wide bound, and the qualification
   must report the bound rather than a claim.
5. Only then re-run the qualification.  Enabling publication before that would
   publish questions at roughly the measured false-release rate.

## 7. Cost

The qualification made 12 authoring + 12 blind-solve + ~86 reviewer requests.
The reviewer pair cost roughly 5 200 input / 740 output tokens per row on the
observed sample.  These are real billable DeepSeek requests; the chain is **not**
free, and the limit is not an application-level USD cap.
