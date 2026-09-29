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

| | run 1 | run 2 | run 3 | run 4 | run 5 |
|---|---|---|---|---|---|
| reviewer prompt revision | v1 | v2 | v2 | v2 | v2 |
| base items per kind | 4 | 4 | 4 | 4 | 8 |
| evaluation rows | 43 | 43 | 27 | 30 | 67 |
| positives / negatives | 11 / 29 | 12 / 30 | 10 / 16 | 10 / 18 | 24 / 40 |
| **release false accept** | 9 (31.0 %) | 3 (10.0 %) | 1 (6.25 %) | **0 (0 %)** | 3 (7.5 %) |
| release precision | 0.50 | 0.667 | 0.875 | **1.00** | 0.85 |
| release recall | 0.818 | 0.50 | 0.70 | 0.70 | 0.708 |
| false rejects | 2 | 6 | 3 | 3 | 7 |
| provider row failures (no retry) | 3 | 1 | 1 | 2 | 3 |
| caught `DISAGREEING_SOLUTION` | 5 / 12 | 11 / 11 | 9 / 10 | 11 / 11 | 20 / 22 |
| caught `DUPLICATE_CORRECT_OPTION` | 4 / 4 | 4 / 4 | 4 / 4 | 3 / 3 | 8 / 8 |
| caught `UNSUPPORTED_RULE` | 3 / 3 | 4 / 4 | 2 / 2 | 3 / 3 | 7 / 7 |
| caught `MISSING_CONDITION` | 8 / 10 | 8 / 11 | *no rows* | 1 / 1 | 2 / 3 |
| decision | `DRAFT` | `DRAFT` | `DRAFT` | **`SCOPED_QUALITY_ACCEPTED`** | `DRAFT` |
| qualification row written | no | no | no | **yes** | no |

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

### 3.3 The two remaining blockers, precisely

1. **`question.ambiguity.v1` is the binding case, and it is in every required
   case set.**  Only three applicable negatives could be built even at 8 items
   per kind, because the mutation now refuses to manufacture under-specification:
   it fires only when it removes a stated given.  Against those three the
   reviewers produced one false accept *and* six false rejects -- they are not
   discriminating this case, and no qualification can cover a question type that
   requires it.  Fixing this needs **items that actually state parameters**
   (numeric givens, units, explicit conventions) so the mutation has something
   real to remove; the current SQL prose items mostly do not.
2. **Three false accepts and seven false rejects remain at 40 negatives.**  The
   escapes were 2 disagreement rows on prose rule items and 1 under-specified MCQ;
   the false rejects include several `HYBRID_CASE_FAIL:question.ambiguity.v1` on
   positive controls, which is the other face of blocker 1.

### 3.4 The substantiation rule added in this round

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
/srv/coursemate/validation/hybrid-strict-v1/qualification-run-20260929.json    (run 1)
/srv/coursemate/validation/hybrid-strict-v1/qualification-run3-20260929.json   (run 3)
/srv/coursemate/validation/hybrid-strict-v1/qualification-run4-20260929.json   (run 4)
/srv/coursemate/validation/hybrid-strict-v1/qualification-run5-20260929.json   (run 5)
```

## 4. Four quality requirements — status

| Original requirement | Status |
|---|---|
| `question.ambiguity.v1 → CLEAR` | **implemented, not measured** — only 3 applicable negatives; 1 false accept and 6 false rejects against them |
| `question.answer_agreement.v1 → AGREE` | **implemented, not qualified** — 20/22 injected disagreements caught, 2 escaped |
| `question.mcq_distractor_quality.v1 → ACCEPTABLE` | **implemented, not qualified** — 8/8 caught, but 1 other row escaped |
| `question.rule_violation_quality.v1 → SUPPORTED` | **implemented, not qualified** — 7/7 caught, but 3 other rows escaped |

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
* no question was published on unqualified evidence, and production holds no
  qualification row;
* across five measured iterations the release false-accept rate fell from 31.0 %
  to 7.5 % on a sample five times larger than the first, release precision rose
  from 0.50 to 0.85, and two named defect types are now caught 100 % of the time
  — but the rate is not zero, and the binding case is not measurable yet.

## 6. What has to change before this can qualify

1. **The corpus, not the prompt.**  Every wording change so far has failed to fix
   ambiguity, because the binding constraint is that the authored SQL items do
   not state removable parameters: only 3 ambiguity negatives could be built from
   24 items.  The qualification must run over a population that actually states
   numeric givens, units and explicit conventions — i.e. the calculation and
   parameterised questions the product really generates.
2. **Raise the sample further.**  Run 4 versus run 5 is the proof that 18
   negatives is not enough.  The floors are now 8 per case and 16 independent
   families globally; a real attempt should go well beyond them.
3. **Make citations survive the strict check.**  Three to five rows per run are
   blocked by the verbatim-quote requirement, which is correct but costs false
   rejects.  Give the reviewers an exact character window, or compare on a
   normalisation that still refuses paraphrase.
4. **Close the prose-rule disagreement escapes.**  Two of the three run-5 escapes
   were disagreement mutations on prose rule items, where the "result" is a
   judgement rather than a number and the checklist has no worked example.
5. Only then re-run the qualification.  Enabling publication before that would
   publish at the measured false-release rate, and would publish ambiguity
   decisions that were never measured.

## 7. Cost

Across the five iterations the qualification made 72 authoring + 72 blind-solve +
roughly 320 reviewer requests.  The reviewer pair cost roughly 5 200 input / 740
output tokens per row on the observed sample.  These are real billable DeepSeek
requests; the chain is **not** free, and the limit is not an application-level
USD cap.

Artifacts (private course material, therefore root-only mode 0600 on the
application host):

```text
/srv/coursemate/validation/hybrid-strict-v1/qualification-run-20260929.json    (run 1)
/srv/coursemate/validation/hybrid-strict-v1/qualification-run3-20260929.json   (run 3)
```
