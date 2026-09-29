# HYBRID_REVIEW_ADR_AND_SCOPE

Decision record for the Question Engine publication gate in this round.

## Context

The deployed release (`916b76ce…`, Schema 64) is fail-closed: a new question can
only become `READY` when the pre-existing semantic gate holds a durable,
currently-scoped receipt for every required dimension.  The only configured
semantic provider is the self-hosted OpenJev candidate, whose recorded
qualification is `UNSET`, so **no** new question has been publishable.  That was
correct behaviour and it is why the private SQL course's two 0/5 configurations
are still genuinely empty, and why campus/private "do one question" cannot
complete.

Two ways out were rejected up front:

* **Relax the gate.**  Setting the four OpenJev definitions to `on` would publish
  questions judged by a constant predictor.  Not acceptable.
* **Wait for the local model to become good.**  The measurement says there is no
  signal, not that it is 50 % of the way there (see
  `OPENJEV_50PCT_ROOT_CAUSE_AND_LOCAL_SCOPE.md`).

## Decision

Introduce a second, *additive* reviewed method — `hybrid-strict-v1` — and let the
Question Engine's original four quality requirements be satisfied by it when, and
only when, it is qualified for the exact scope in question:

```text
existing Author → existing Blind Solver → deterministic hard gates
    → OpenJev local observation (advisory, skippable, never decisive)
    → DeepSeek evidence_audit (A)  ‖  DeepSeek adversarial_audit (B)   [two isolated calls]
    → server-side hybrid-strict-v1 gate (+ scoped qualification)
    → unchanged Question Engine READY / revise / needs-review
```

The four original semantic cases are **not** relaxed, renamed or merged:
`question.ambiguity.v1`, `question.answer_agreement.v1`,
`question.mcq_distractor_quality.v1` and `question.rule_violation_quality.v1`
keep their existing verdict vocabularies
(`CLEAR`/`AMBIGUOUS`/`UNDER_SPECIFIED`/`CONTRADICTORY`/`UNCERTAIN`,
`AGREE`/`DISAGREE`/`AMBIGUOUS`/`UNCERTAIN`,
`ACCEPTABLE`/`WEAK`/`AMBIGUOUS`/`UNCERTAIN`,
`SUPPORTED`/`UNSUPPORTED`/`AMBIGUOUS`/`UNCERTAIN`), and the chosen case set is
derived server-side from the blueprint's question type and rule policy.

## Consequences

### Additive, never subtractive

`SemanticSignal` keeps `used_jev` as "a receipted semantic review decided this
dimension" and gains the reviewed path name.  `jev` remains the historical
local/TypeSafe chain; `hybrid` is the new one.  Both are receipt-bound; a
fallback can claim neither.  With `HYBRID_QUALITY_ENABLED` unset the pipeline is
byte-identical to before.

### The weak local model is demoted, not deleted

OpenJev keeps its pinned snapshot, its single q4 process, its loopback bearer
auth and its resource caps.  It contributes recorded observations on short
English fragments; it cannot publish, cannot veto, cannot delete evidence, cannot
lower a target, cannot trigger regeneration and cannot write grades.  Its outage
does not block a qualified strong review.  Its four OpenJev definition modes are
**not** a publication condition under this policy.

### Deterministic results are inputs, never outputs

The six hard gates (`INPUT_IDENTITY`, `MARKS_MATCH`, `SOURCE_SCOPE`,
`CONDITIONS_PRESENT`, `QUESTION_SHAPE`, `BLIND_SOLVE_CURRENT`) are unchanged.  A
`REJECTED` report never reaches the reviewers at all (`_apply_hybrid_review`
returns before any call), so two favourable model votes cannot resurrect a
deterministic failure.  `acceptance_required`-style overrides do not exist in
the schema.

### Two reviewers, process-isolated, honestly labelled

Role A (`evidence_audit`) reviews the frozen item, sources, rubric, anonymised
solutions and trusted deterministic results.  Role B (`adversarial_audit`) is a
second, stateless request that receives the same material with the anonymised
solution order **reversed** and receives no verdict, explanation or local label
from A.  `ReviewerInputs` has no field for a peer verdict or a local label, so
the isolation is structural rather than prompt-based.  Both calls complete
before either result is read, so no reviewer can be re-asked until it agrees.

The two requests use the same underlying model.  That is **process separation,
not statistical independence**: no probability is multiplied, no "two experts"
claim is made, and no two-vote majority is used as evidence of quality.

### Publication requires a qualified scope

A hybrid receipt is accepted only when a `hybrid_qualifications` row matches the
exact `method_identity` (model alias, provider, protocol, both prompt revisions,
schema revision, policy revision), is `SCOPED_QUALITY_ACCEPTED`, is `active`, is
not expired, and covers the item's detected language, its source-kind domain and
every required case.  The qualification is re-checked **inside the publication
transaction**, so a scope withdrawn between review and publication blocks the
publication instead of being carried by a stale receipt.

The label is `SCOPED_QUALITY_ACCEPTED`.  It is explicitly **not**
`PROVEN_IDENTICAL_TO_JEV`.

### Costs are real and reported

Two extra DeepSeek calls per new candidate are billable.  They are metered per
call in `hybrid_review_calls` (input/output tokens, latency, provider response
id) and the requirement is recorded as
`extra_deepseek_review_calls_are_billable: true`.  The self-hosted local
inference has no per-call vendor fee, but the chain as a whole is **not** free
and is not described as free.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Enable the four OpenJev modes and accept 0.50 | Would publish questions judged by a fixed-label classifier. |
| Raise/lower thresholds until the local model passes | No threshold repairs a constant predictor; the recorded report says the same. |
| One reviewer instead of two | Removes the adversarial falsification attempt; the required case set would then have a single point of failure. |
| Majority vote between A and B | A concrete `FAIL` would be outvotable; the policy is conjunctive instead. |
| Prompt A and B differently and call them independent | Same weights, correlated errors; only the *claim* would change. |
| Keep `TYPESAFE_API_KEY` as a fallback | TypeSafe is retired; restoring it would reintroduce a dead dependency as an availability crutch. |
| Publish directly from the deterministic gates | The original four requirements exist precisely because the deterministic gates cannot judge semantics. |

## Scope boundary of this decision

* This decision covers the **Question Engine publication gate only**.  Ordinary
  teaching, user problem explanations and image answers are unchanged and are
  not forced through the dual review.
* It does **not** claim measured student-learning improvement, and it does not
  claim all domains/languages are covered.  Coverage is exactly what a
  qualification record says it is.
* Thirteen Map50 trees remain paused and are unaffected.
