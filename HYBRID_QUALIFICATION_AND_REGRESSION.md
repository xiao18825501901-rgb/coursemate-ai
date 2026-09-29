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

## 3. The qualification runs (three measured iterations)

* Runner: `scripts/run_hybrid_qualification.py`
* Data: a restored **copy** of the live database (the live file was only read).
* Target: workspace `0f364c85-3010-4b91-811c-2e6333111a18` (the blocked private
  SQL course's own workspace), node `auto-node-9e012c6325c909bff3a56780b804`,
  evidence `WORKSPACE_PRIVATE`, detected language `en`.
* Items: server-authored NUMERIC / MCQ_SINGLE / rule-policy EXPLANATION items
  produced by the same production author + blind-solver pair.

Each iteration changed only the *measurement* or the *reviewer instructions*, and
each was re-measured end to end against real DeepSeek calls.

| | run 1 | run 2 | run 3 | run 4 | run 5 | run 6 | run 7 | run 8 |
|---|---|---|---|---|---|---|---|---|
| prompt revision | v1 | v2 | v2 | v2 | v2 | v2 | v3 | **v4** |
| base items per kind | 4 | 4 | 4 | 4 | 8 | 8 | 8 | 8 |
| evaluation rows | 43 | 43 | 27 | 30 | 67 | 64 | 69 | 67 |
| positives / negatives | 11 / 29 | 12 / 30 | 10 / 16 | 10 / 18 | 24 / 40 | 22 / 33 | 24 / 41 | 19 / 41 |
| **release false accept** | 9 (31.0 %) | 3 (10.0 %) | 1 (6.25 %) | **0 (0 %)** | 3 (7.5 %) | 4 (12.1 %) | **0 (0 %)** | 4 (9.8 %) |
| release precision | 0.50 | 0.667 | 0.875 | **1.00** | 0.85 | 0.80 | **1.00** | 0.75 |
| release recall | 0.818 | 0.50 | 0.70 | 0.70 | 0.708 | 0.727 | 0.375 | **0.632** |
| caught `MISSING_CONDITION` | 8 / 10 | 8 / 11 | *no rows* | 1 / 1 | 2 / 3 | **0 / 3** | **5 / 5** | 2 / 5 |
| caught `DISAGREEING_SOLUTION` | 5 / 12 | 11 / 11 | 9 / 10 | 11 / 11 | 20 / 22 | 18 / 19 | 21 / 21 | 21 / 21 |
| caught `DUPLICATE_CORRECT_OPTION` | 4 / 4 | 4 / 4 | 4 / 4 | 3 / 3 | 8 / 8 | 7 / 7 | 8 / 8 | 7 / 7 |
| caught `UNSUPPORTED_RULE` | 3 / 3 | 4 / 4 | 2 / 2 | 3 / 3 | 7 / 7 | 4 / 4 | 7 / 7 | 7 / 8 |
| decision (current gate) | DRAFT | DRAFT | DRAFT | DRAFT | DRAFT | DRAFT | DRAFT | DRAFT |

### 3.00 Corpus diagnosis (run 6's precondition)

Before spending more review calls, the item population itself was measured with
`--diagnose-only`, which authors the items and reports their *shape* without
recording any stem text (the stems are private course material):

```text
items 23 (one blind-solve failure), MISSING_CONDITION applicable 2 / 23
  NUMERIC        n=7  digit_groups per stem = [0,0,0,0,0,0,0]
  MCQ_SINGLE     n=8  digit_groups per stem = [0,0,0,0,0,0,0,0]
  EXPLANATION    n=8  digit_groups per stem = [0,0,1,0,0,0,0,0]
  condition-marker present in 0 / 23 stems
```

**Every numeric question the author writes states its givens in prose, not as
digits.** That is why the ambiguity defect could be injected on only 2 items in
23: the mutation had nothing to remove.  The blocker was the corpus, not the
prompt -- which is what the earlier runs had already suggested and this
measurement settled.

### 3.00.1 Run 6: the ambiguity case is not detectable at all

Run 6 generalised the mutation to prose constraints (dropping the clause that
states a requirement: `only if`, `at least`, `must be`, `cannot be`, …) and made
the prose-answer disagreement state its rejection outright instead of wrapping
the original text.

* The prose-answer fix **worked**: `DISAGREEING_SOLUTION` 20/22 → **18/19**.
* The ambiguity defect is **not detected at all**: `MISSING_CONDITION` caught
  **0 of 3**, and all three under-specified items were released.

Across three different ambiguity-defect designs the catch rate is 2/3, 1/1 and
0/3.  `question.ambiguity.v1` is present in **every** required case set, so this
single case keeps the entire gate closed, and no prompt wording has moved it.

Run 6 also exposed a second, independent reliability problem: **9 of 64 rows
(14 %) failed with `HYBRID_REVIEW_PROVIDER_FAILED`** — up from 1–3 in earlier
runs, on the same procedure and prompt revision.  Those rows are recorded as
failures and never retried, so the rate costs coverage rather than corrupting a
result, but a 14 % provider-failure rate is itself disqualifying for an
unattended publication path.

### 3.01 Run 7: the enumeration fixes detection, and over-corrects

Prompt/schema revision v3 changes the ambiguity case from a bare judgement into
an **enumeration the server reads**: the reviewer lists each datum, unit,
convention or prerequisite the answer depends on and marks it `stated_in_stem`,
and the server derives the verdict.  Any unstated entry is a `FAIL` whatever
verdict was written; a `CLEAR` with an empty enumeration is an abstention, not an
approval.

The effect on detection is decisive:

| defect | run 6 | run 7 |
|---|---|---|
| `MISSING_CONDITION` (under-specified stem) | **0 / 3** | **5 / 5** |
| `DISAGREEING_SOLUTION` | 18 / 19 | 21 / 21 |
| `DUPLICATE_CORRECT_OPTION` | 7 / 7 | 8 / 8 |
| `UNSUPPORTED_RULE` | 4 / 4 | 7 / 7 |
| release false accept | 4 / 33 | **0 / 41** |
| independent negative families | 12 | 24 |
| zero-false-accept 95 % upper bound | n/a | **0.117** |

**Every injected defect of every kind was caught**, and the one-sided bound over
24 independent negative families is 11.7 %.  This is the first run in which the
ambiguity case — the one that gates every question — is demonstrably detectable.

The over-correction is equally clear and is the reason run 7 does **not**
qualify:

* **`release_recall = 0.375`** — 13 of 24 sound controls were refused, 11 of them
  on ambiguity with `HYBRID_UNSTATED_DEPENDENCY`.  The reviewers now find
  "unstated dependencies" in good items too: the enumeration rule fires on
  conventions a competent reader would supply (a rounding convention, an implicit
  ordering) as readily as on genuinely absent data.
* A procedure that refuses most sound items reaches zero false accepts trivially,
  and "everything is blocked, therefore nothing bad was released" is explicitly
  **not** an acceptable quality baseline.  A release-recall floor of 0.5 was
  therefore added to the gate in the same round, with the decision record
  carrying `coverage_sufficient`, `min_release_recall` and the measured
  `release_recall`.

### 3.02 Re-evaluating a stored run under a corrected gate

Run 7's artifact recorded `SCOPED_QUALITY_ACCEPTED` under the pre-floor gate.
`scripts/re_evaluate_qualification.py` recomputes the decision from the stored
row outcomes with no provider call, and gives:

```text
recorded_status      SCOPED_QUALITY_ACCEPTED
re_evaluated_status  DRAFT
sample_sufficient    true      (24 independent negative families)
coverage_sufficient  false     (release_recall 0.375 < 0.5)
false_accept         0 / 41    zero-false-accept 95% bound 0.117
```

The qualification row was written into the **staging copy** and was never
promoted, so production never held it and no retraction is needed.  The offline
re-evaluation exists precisely so that a gate change can be applied to already
measured evidence instead of re-spending ~150 provider calls to learn the same
thing.

### 3.0 The decisive finding: run 4's pass was a small-sample artifact

Run 4 recorded a real qualification (`hybrid-qual-live-v1`, covering
`answer_agreement`, `mcq_distractor_quality` and `rule_violation_quality`) on
30 rows and 18 negatives with zero false accepts.  Run 5 then ran **the same
procedure with the same prompt revision**, simply authoring 8 items per kind
instead of 4, and recorded **three false accepts in 40 negatives**.

A clean small sample is therefore **not** evidence of a clean procedure.  Both
readings are true and both must be reported:

* the chain did once measure clean at 18 negatives;
* the same chain is not clean at 40.

Because run 4's qualification was written into the **staging copy** of the
database and never promoted, production never held it, and no retraction is
needed.  What it did prove is that the floor was too low, so it was raised in
the same round: a per-case minimum of 8 negatives, and a **global** minimum of 16
independent negative families.  Under those floors run 4's measurement cannot
qualify, and a test now pins that (`test_a_thin_but_clean_sample_cannot_qualify_a_method`
asserts the same measurements qualify with the floor removed and do not qualify
with it in place).

### 3.0.1 What run 5 says about the reviewers

| case | positives | negatives | false accept rate | false rejects |
|---|---|---|---|---|
| `question.ambiguity.v1` | 24 | 3 | **1 / 3 (33 %)** | 6 |
| `question.answer_agreement.v1` | 24 | 22 | 2 / 22 (9.1 %) | 1 |
| `question.mcq_distractor_quality.v1` | 8 | 8 | 0 / 8 | 1 |
| `question.rule_violation_quality.v1` | 8 | 7 | 0 / 7 | 1 |

`DUPLICATE_CORRECT_OPTION` (8/8) and `UNSUPPORTED_RULE` (7/7) are reliably
detected.  `DISAGREEING_SOLUTION` is detected 20/22.  `MISSING_CONDITION` is
detected 2/3 but only three rows could be built at all, and the ambiguity case
carries **six** false rejects against **one** false accept -- i.e. the reviewers
are not discriminating under-specification, they are leaning towards refusing
and still missing the injected cases.  Ambiguity is in **every** required case
set, so this alone keeps the gate closed.

### 3.1 What each iteration actually fixed

**Run 1 → run 2 — a measurement defect, not a reviewer weakness.**
The `DISAGREEING_SOLUTION` mutation wrote its sentinel into an unused payload key
while the blind solution's steps still showed the original result, so a reviewer
reading those steps could legitimately report agreement.  The mutation now
derives a concrete contradicting result from the author's answer and rewrites
the final step as well.  The effect was decisive: `5/12 → 11/11` caught.  The
earlier 58 % "false accept" on that defect was **the mutation's fault, and it is
withdrawn as a statement about the reviewers**.  The prompt was also strengthened
with explicit under-specification and disagreement checklists and an exact-quote
discipline.

**Run 2 → run 3 — two corrections.**

1. *Metric attribution.* A negative row was being counted as a negative for
   **every** case it reported, so an under-specified stem that correctly passed
   `answer_agreement` still counted as an agreement false accept.  Per-case
   tallies are now attributed only to the case a row's defect targets.  The
   run-1/run-2 per-case rates quoted in the previous revision of this document
   were inflated by that error.
2. *Mutation substantiation.* `MISSING_CONDITION` was firing on prose stems by
   deleting a trailing sentence, which does not make an item under-specified.  It
   now fires only when it removes something the answer depends on -- an explicit
   condition clause or a numeric given -- and otherwise produces **no row**.

### 3.2 Run 3 in full (the most recent measurement)

* 27 rows: 10 `POSITIVE_CONTROL`, 16 `INJECTED_DEFECT`; 2 authoring failures and
  1 provider row failure, none retried.
* Dataset digest `5816518a6269102a025a08ecade587a1b87cfd534c3cab6581eab40ddcfd6dd8`.
* Reviewer method identity `bec75861e73e597d9cb5a02c4d98c0c99db6165567cc422af895e5ed707ebaef`
  (prompt revisions `judge-evidence-audit.v2` / `judge-adversarial-audit.v2`).

| metric | value |
|---|---|
| true accept (positive rows released) | 7 / 10 |
| false reject | 3 / 10 |
| **false accept (negative rows released)** | **1 / 16** |
| true reject | 15 |
| abstain | 0 |
| release precision | 0.875 |
| release recall | 0.70 |
| false-release rate | 0.0625 |

Per case, correctly attributed:

| case | positives | negatives | false accepts | false rejects |
|---|---|---|---|---|
| `question.ambiguity.v1` | 10 | **0** | 0 | 0 |
| `question.answer_agreement.v1` | 10 | 10 | 2 | 1 |
| `question.mcq_distractor_quality.v1` | 4 | 4 | 1 | 0 |
| `question.rule_violation_quality.v1` | 3 | 2 | 0 | 0 |

The single escaped row was `rule_explanation-0:DISAGREEING_SOLUTION`.

### 3.03 Run 8: the precision/recall dial, measured at both ends

Prompt/schema v4 adds the discriminating field: each dependency is marked
`stated_in_stem` **and** `answer_changes_if_absent`, and the reviewer must state
the concrete different answer as `consequence` whenever the second is true.  An
entry blocks the item only when it is unstated **and** changes the answer.

Two measured points on the same axis, with the same corpus, procedure and model:

| | run 7 (unstated blocks) | run 8 (unstated **and** answer-changing blocks) |
|---|---|---|
| release recall | 0.375 | **0.632** |
| release precision | **1.00** | 0.75 |
| false accepts | **0** | 4 / 41 |
| false rejects | 13 / 24 | 7 / 19 |
| `MISSING_CONDITION` caught | **5 / 5** | 2 / 5 |
| `DISAGREEING_SOLUTION` caught | 21 / 21 | 21 / 21 |
| `DUPLICATE_CORRECT_OPTION` caught | 8 / 8 | 7 / 7 |
| `UNSUPPORTED_RULE` caught | 7 / 7 | 7 / 8 |
| gate verdict | DRAFT (recall 0.375 < 0.5) | DRAFT (4 false accepts) |

Both ends are honest and both are unacceptable, for opposite reasons:

* run 7 is safe and unusable — it refuses 62.5 % of sound items, and refusing
  most items is not a quality standard;
* run 8 is usable and unsafe — asking "would the answer change?" let the
  reviewers mark genuinely-missing data as harmless, and under-specification
  detection fell from 5/5 to 2/5.

So the dial moved exactly as designed and neither setting qualifies.  The
information needed to pick a middle is **not present in a single verdict**: the
three other defect kinds are stable and reliable across both runs
(`DISAGREEING_SOLUTION` 21/21, `DUPLICATE_CORRECT_OPTION` 7–8/8,
`UNSUPPORTED_RULE` 7/7–8), and only under-specification is unstable.

What this rules out, and what it points to:

* It rules out finding a good wording.  Eight runs and four prompt revisions have
  moved this case between "never detects" and "detects everything, refuses
  everything" without landing in between.
* It points at the decomposition rather than the wording.  Under-specification is
  being asked of the same two passes that also judge correctness and rules, and
  it is the only case whose answer depends on a *judgement about the reader*
  rather than about the item.  A dedicated pass whose only job is to answer "is
  every quantity the answer needs present in the stem or the supplied sources,
  and if not, what different answer results" — with the two existing roles
  unchanged — is the next thing to measure, not another revision of these two
  prompts.

### 3.04 What is stable and what is not

After eight runs the picture is separable and worth stating plainly:

| case | status across runs |
|---|---|
| `question.answer_agreement.v1` | **reliable** — 21/21 in the last two runs, 0 false accepts for agreement in run 8 |
| `question.mcq_distractor_quality.v1` | **reliable** — 7–8/8, 0 false accepts for MCQ in runs 7 and 8 |
| `question.rule_violation_quality.v1` | **reliable** — 7/7 and 7/8 |
| `question.ambiguity.v1` | **unstable** — the only case that moves the gate, and the only one that never settled |

Three of the four original quality requirements are met by this reviewer pair
with no measured false accept in the last two runs.  The fourth is the whole of
the remaining problem, and it is in every required case set.

## 4. Four quality requirements — status

| Original requirement | Status |
|---|---|
| `question.answer_agreement.v1 → AGREE` | **reliable** — 20–21/21 injected disagreements caught in each of the last three runs |
| `question.mcq_distractor_quality.v1 → ACCEPTABLE` | **reliable** — 7–8/8 caught; 0 MCQ false accepts in the last three runs |
| `question.rule_violation_quality.v1 → SUPPORTED` | **reliable** — 5/5 and 7/8 caught |
| `question.ambiguity.v1 → CLEAR` | **frontier mapped, no qualifying setting** — 5/5 at recall 0.375, 4/5 at 0.238, 2/5 at 0.632 |

The semantics of all four are unchanged and no gate was relaxed.  Three are
measurably met; ambiguity gates every question and no measured configuration makes
it both safe and usable, so the hybrid chain still may not satisfy any of them.

### 3.3 The remaining blockers, precisely

1. **Under-specification is unstable, and it gates everything.**  Run 7 detects
   it perfectly and refuses too much; run 8 accepts too much and is usable.  Both
   are DRAFT, for opposite reasons.  The next step is a **dedicated pass** for
   this one case rather than a fifth revision of the two general prompts
   (§3.03).
2. **Provider reliability.**  7 of 67 rows failed at the provider in run 8 and 9
   of 64 in run 6, on the same procedure.  Those failures are recorded and never
   retried, so they cost coverage rather than corrupting results, but the cause
   still needs separating (schema rejection, output-token ceiling, transient
   upstream error) before the chain carries an unattended publication path.
3. **The strict verbatim-quote check** blocked 5–10 rows per run.  It is correct
   -- a paraphrase is not evidence -- but it costs real false rejects and needs
   either an exact character window for the reviewers to copy, or a comparison
   that still refuses paraphrase while tolerating re-wrapping.

### 3.05 Run 9: the dedicated pass, and the third point on the curve

The dedicated specification pass (§3.06) is a third call with its own prompt,
its own schema and **no verdict field at all** — it can only return the
enumeration, and the server turns it into the ambiguity verdict.  Its blocking
entries are decisive over both general roles, and a missing pass abstains the
case rather than approving it.

| | run 7 | run 8 | run 9 |
|---|---|---|---|
| who decides under-specification | roles A/B | roles A/B | **dedicated pass** |
| rule | unstated | unstated **and** answer-changing | unstated **and** answer-changing, from the dedicated pass |
| release false accept | **0 / 41** | 4 / 41 | 2 / 39 |
| release precision | **1.00** | 0.75 | 0.714 |
| release recall | 0.375 | **0.632** | **0.238** |
| false rejects | 13 / 24 | 7 / 19 | 15 / 21 |
| `MISSING_CONDITION` caught | **5 / 5** | 2 / 5 | 4 / 5 |
| `DISAGREEING_SOLUTION` caught | 21 / 21 | 21 / 21 | 20 / 21 |
| `DUPLICATE_CORRECT_OPTION` caught | 8 / 8 | 7 / 7 | 8 / 8 |
| `UNSUPPORTED_RULE` caught | 7 / 7 | 7 / 8 | 5 / 5 |
| verdict | DRAFT (recall) | DRAFT (false accepts) | DRAFT (recall) |

The dedicated pass **improved detection** over run 8 (2/5 → 4/5) but **crashed
recall** to 0.238: 15 of 21 sound controls were refused, essentially all of them
because the specification pass reported a blocking entry on a good item.

### 3.06 What the three points together establish

Three rule designs, three measurements, no acceptable setting:

| | detection of under-specification | coverage |
|---|---|---|
| strict (unstated) | 5/5 | 0.375 |
| moderate (answer-changing, A/B) | 2/5 | 0.632 |
| dedicated (answer-changing, separate pass) | 4/5 | 0.238 |

The pattern is consistent and it is not a wording problem: **the reviewer
systematically over-reports "a different answer would result" on sound items.**
Every attempt to raise detection raises that over-reporting with it.  Five rule
iterations across three designs have now mapped the frontier, and the frontier
does not contain a qualifying point.

That is a calibration property of the model on this task, not a prompt defect,
and it is the honest end state of this line of work: the hybrid chain is built,
its receipts are real, three of the four cases are reliable, and the fourth
cannot be made both safe and useful by instruction alone.  Closing it needs
either a different instrument for this one case (an executable check, a human
review step, or a model with calibrated under-specification judgement) or an
explicitly accepted, *measured* risk level — which is a product decision, not an
engineering one, and is not taken here.

### 3.07 The dedicated specification pass is kept

Even though run 9 does not qualify, the dedicated pass stays in the
implementation, because it is the right decomposition and it produced the best
under-specification detection of any non-degenerate configuration (4/5 at 0.238
recall, against 5/5 at 0.375 for the strict rule applied to the general roles).
It is additive and safe: it can only ever *refuse* an item or abstain, never
approve one, and a missing pass abstains the ambiguity case instead of passing
it.  Its over-triggering is now a measured, attributable quantity rather than an
unknown.

### 3.08 The substantiation rule added in this round

A bare verdict is not evidence, so two internal contradictions are now resolved
server-side before the two roles are combined, using only what the reviewer
itself reported:

* a `FAIL` with **no** counterexample and **no** missing condition is downgraded
  to `UNCERTAIN` -- an unsubstantiated refusal must not be able to block a sound
  item, which is indistinguishable from a reviewer that is guessing;
* an `ambiguity` `PASS` whose own finding lists missing conditions is
  self-contradictory and is downgraded to `UNCERTAIN`.

This can never create a `PASS`; it can only remove an unsupported decision and
leave the item under review.  It is covered by four tests.

### 3.5 Decision recorded by the harness

```json
{"status": "DRAFT", "cases": [], "languages": [], "domains": [],
 "unmeasured_cases": ["question.ambiguity.v1", "question.answer_agreement.v1",
                      "question.mcq_distractor_quality.v1",
                      "question.rule_violation_quality.v1"]}
```

`recorded_qualification_id = null` in runs 1, 2, 3 and 5.  Run 4 recorded a
qualification in the staging copy only; it was never promoted, and the raised
floors now make that measurement non-qualifying.  **Production holds no
qualification row at all** (`hybrid_qualifications` does not exist in the live
database), so `_resolve_qualification` returns `HYBRID_QUALIFICATION_MISSING`
for every candidate and the gate stays closed.  This is the designed outcome: the
code path that would have published was exercised end to end five times and it
refused.

The one-sided zero-false-accept bound is now reported as `null` whenever a false
accept occurred, with an explicit note, because a bound on an event that did
occur is not a risk statement.  Run 4, the only clean run, reported
`0.2384` over 10 independent negative families -- a bound that the run-5 result
shows was not safe to rely on.

## 3.6 Corpus integrity

Across all five runs the target was a **restored copy** of the live database.
The live file was only ever opened read-only, and it was re-checked afterwards:

| check | value |
|---|---|
| live `schema_migrations` rows | 64 (unchanged) |
| hybrid tables in the live database | **none** |
| live question revisions / provenance | 58 / 58 (unchanged) |
| blocked assessment preparations | 7 (unchanged) |
| release symlink | `/srv/coursemate/releases/916b76c` (unchanged) |
| services | `coursemate-rag`, `coursemate-agent`, `coursejesus-openjev` all active |
| disk on `/` | 3.8 GiB free after cleanup |

Run artifacts contain private course material, so they live only in a root-only
directory at mode 0600 and were never copied anywhere world-readable:

```text
/srv/coursemate/validation/hybrid-strict-v1/qualification-run-20260929.json              (run 1)
/srv/coursemate/validation/hybrid-strict-v1/qualification-run3-20260929.json             (run 3)
/srv/coursemate/validation/hybrid-strict-v1/qualification-run4-20260929.json             (run 4)
/srv/coursemate/validation/hybrid-strict-v1/qualification-run6-20260929.json             (run 6)
/srv/coursemate/validation/hybrid-strict-v1/qualification-run7-enumeration-20260929.json (run 7)
```

Run 5's raw artifact was overwritten by a filename collision in the cleanup
helper before it was renamed correctly; its measurements are preserved in the
table above but the raw file is gone.  The helper now names artifacts by run.

## 4. Four quality requirements — status

| Original requirement | Status |
|---|---|
| `question.ambiguity.v1 → CLEAR` | **implemented, UNSTABLE** — 5/5 detected at recall 0.375 (run 7), 2/5 at recall 0.632 (run 8) |
| `question.answer_agreement.v1 → AGREE` | **reliable** — 21/21 injected disagreements caught |
| `question.mcq_distractor_quality.v1 → ACCEPTABLE` | **reliable** — 8/8 and 7/7 caught |
| `question.rule_violation_quality.v1 → SUPPORTED` | **reliable** — 7/7 and 7/8 caught |

The semantics of all four are unchanged and no gate was relaxed.  Three are
measurably met; ambiguity is unstable and gates everything, so the hybrid chain
still may not satisfy any of them.

## 5. Quality non-inferiority

`QUALITY_NONINFERIORITY_EVIDENCE = UNKNOWN`.

There is no paired, same-sample comparison against a healthy historical reviewer:
the previous chain's 117 receipts are `choice` strings from the retired TypeSafe
SDK with no probability distribution and no held-out labels, and the local
OpenJev candidate has no signal at all.  Nothing in this round establishes that
the hybrid reviewers are as good as anything.  What can be said honestly is:

* the four requirements were not lowered;
* the deterministic hard gates are unchanged and were never overridden;
* no question was published on unqualified evidence, and production holds no
  qualification row;
* three of the four cases are now measurably reliable, and the fourth moves
  between "detects nothing" and "refuses everything" depending on one prompt
  field.

## 6. What has to change before this can qualify

1. **Change the instrument, not the instruction, for under-specification.**
   Five rule iterations across three designs (`strict`, `moderate`, `dedicated`)
   have mapped the frontier — detection 5/5 at recall 0.375, 4/5 at 0.238, 2/5
   at 0.632 — and no point on it qualifies.  The reviewers systematically
   over-report "a different answer would result" on sound items, so raising
   detection raises refusals with it.  Closing this needs an executable check
   (for the arithmetic and query items where one exists), a human review step
   for this single case, or a model whose under-specification judgement is
   calibrated — not a sixth wording.
2. **Diagnose the provider-failure rate.**  6 of 66 rows failed in run 9 (one of
   them in the specification pass).  Those failures are recorded and never
   retried, so they cost coverage rather than corrupting a result, but the cause
   still needs separating (schema rejection, output-token ceiling, transient
   upstream error) before the chain carries an unattended publication path.
3. **Make citations survive the strict check** (9 rows blocked in run 9).  It is
   correct — a paraphrase is not evidence — but it costs real false rejects.
4. **Keep the sample large** — floors are 8 negatives per case, 16 independent
   families globally, and a release-recall floor of 0.5.
5. If the residual risk is to be accepted instead of eliminated, that is a
   product decision and it must be taken explicitly and with the measured number
   attached; it is not taken here, and no question was published.

## 7. Cost

Across the nine iterations the qualification made 132 authoring + 132
blind-solve + roughly 680 reviewer requests, plus 23 authoring calls for the
corpus diagnosis.  Run 9 added a third call per row, so its per-row cost is 50 %
higher than the earlier runs.  These are real billable DeepSeek requests; the
chain is **not** free, and the limit is not an application-level USD cap.

Artifacts (private course material, therefore root-only mode 0600 on the
application host):

```text
/srv/coursemate/validation/hybrid-strict-v1/qualification-run-20260929.json               (run 1)
/srv/coursemate/validation/hybrid-strict-v1/qualification-run3-20260929.json              (run 3)
/srv/coursemate/validation/hybrid-strict-v1/qualification-run4-20260929.json              (run 4)
/srv/coursemate/validation/hybrid-strict-v1/qualification-run6-20260929.json              (run 6)
/srv/coursemate/validation/hybrid-strict-v1/qualification-run7-enumeration-20260929.json  (run 7)
/srv/coursemate/validation/hybrid-strict-v1/qualification-run8-answer-changing-20260929.json (run 8)
/srv/coursemate/validation/hybrid-strict-v1/qualification-run9-specification-pass-20260929.json (run 9)
```
