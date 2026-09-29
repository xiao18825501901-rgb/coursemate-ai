# P0 · Provider, citation and ambiguity-policy fixes (2026-09-30)

This records what was changed, what was measured before the change, and what
remains unverified.  It is one of the seven required documents and replaces
nothing: the earlier round keeps its own report.

## 1. Provider failures are now attributable

### What was wrong, measured

The stored qualification artifacts persisted only `code`, `row_id` and `step` for
a provider failure.  Across the seven stored runs that is **32 failures over 366
rows and about 798 reviewer calls, 4.01 % per call**, and not one of them could be
attributed to a layer -- although `provider.py` had already computed
`error_class`, the terminal status, the latency and the usage, and
`deepseek_reviewer` carried them on the exception.

The whole-response path had the same gap: the complete response body existed in
memory and was discarded before the schema check that then failed.

### What changed

* `app/learning/provider_failure_ledger.py` and migration **066** add an
  append-only `hybrid_provider_failures` table. 065 is not modified.
* `LearningProvider` now records `error_class`, terminal status, HTTP status,
  timeout kind, the exception chain, response arrival, latency, usage and -- for a
  failure only -- the complete response text and a value-free list of the schema
  fields that were rejected.
* `classify_failure_layer()` names ten layers, including the two that the earlier
  runs could not distinguish: `RESPONSE_SCHEMA` (a complete response that did not
  match) and `UPSTREAM_TRANSPORT` (a timeout or connection failure).
* `HybridQualityService.review()` persists the failure before re-raising.

### What the live probes proved

The probe that first exercised the live path found four separate defects before
any of them reached production, including one that would have failed **every** live
call: diagnostic keys written into the run dict, which is the receipt shape
`AuthorProviderRun` validates with `extra="forbid"`.  The details are in
`P0_CURRENT_EXECUTION_STATE.md`.

### Not claimed

No new measurement of the failure rate has been taken under the new code, so the
rate is still the historical 4.01 % over the old artifacts.  The layer composition
of those 32 failures remains **UNKNOWN** and is recorded as such; the ledger makes
the *next* run answerable, it does not retroactively attribute the old ones.

## 2. Citation: the model selects, the server restores

### What was wrong, measured

`JudgeSourceRef.quote` was mandatory, so a reviewer that had correctly selected a
span still failed the item when it did not re-transcribe a long sentence
character for character.  The prompt already told reviewers to omit an inexact
quotation, which the schema made impossible.

### What changed

* `quote` is optional.  `claim`, `evidence_kind` and `checker_ref` were added, and
  `CHECKER_RESULT` requires its checker reference, so a derived number is evidence
  of a declared form rather than a missing quotation.
* `verify_references` resolves every cited span against the frozen material and
  records the resolved digest, character count and locator on the receipt.  The
  citation of record is now server-owned.
* A supplied quotation is still matched exactly, apart from line wrapping.  No
  case folding, no symbol folding, no similarity threshold: making the quotation
  optional removes transcription, not verification.

### Evidence

A bounded live run reached `unknown_span_ids: []` and `untraceable_quotes: []`,
where an earlier run on a different item had refused a control item on an
unverified reference.

## 3. Ambiguity: a checkable witness, and no approval by absence

### What was wrong, measured

Nine runs and five rule iterations established that the under-specification
judgement is not separable for this configuration: the reviewer over-reports an
absent condition on sound items, and detection and coverage move together, so no
point on the measured frontier was both safe and usable.

### What changed

* A `StudentVisibleTaskSpec` states, in typed form, every element the answer turns
  on with its role -- `GIVEN`, `EXERCISE_ASSUMPTION`, `SOURCE_RULE` or
  `CLAIM_TO_CRITIQUE` -- and the student-visible projection is **rendered from**
  it, so a condition cannot live in a private rubric and be invisible in the stem.
* Three bounded profiles (`P-SQL`, `P-DISCRETE`, `P-COURSE-RULE`) let code issue a
  completeness certificate: required roles present, required conventions stated,
  cited spans existent, premises in the projection, renderer and language in
  profile, declared conventions recognised.  Outside every profile the answer is
  `NOT_SUPPORTED`, which is never a pass.
* A material objection is a witness: two admissible readings with their answers and
  the graded difference between them.  The server refuses a reading that adds data
  the item does not supply or contradicts a stated condition, refuses two readings
  whose answers are equal under the declared equivalence, and executes both when
  they carry an executable form.
* The asymmetry is kept: a **confirmed** witness fails the item, an unverified
  objection holds it, and approval needs the certificate **and** an active
  qualification.  Not finding a witness is never an approval.

### Two deliberate policy decisions, with their risk

1. **A bare ambiguity refusal no longer decides the case.**  It is answered by the
   certificate.  The accepted risk is a real defect the reviewer failed to
   substantiate on an item a registered profile nonetheless certifies; it is
   bounded by the certificate checks, the six hard gates and the oracle, and it is
   why the registry is narrow.
2. **A blocking enumeration entry holds rather than fails.**  It names one
   consequence, not two admissible readings, so it is a specific doubt and not a
   witness.  Safety is unchanged -- a held item is not released, and only a
   certificate can pass one -- while the measured over-triggering stops refusing
   sound items.

## 4. Verified by a live probe rather than by inspection

```
task_contract:        true
profile:              P-DISCRETE v1
declared conventions: ANSWER_FORM, BOUNDARY_INCLUSION, DATA_COMPLETENESS
certificate_status:   COMPLETE_FOR_REGISTERED_PROFILE
projection digest:    3c48deea9e87926817d9180135522c6d34c85d804af20db9e6d7de4034b82bbd
```

That is the first item whose completeness the server certifies for a registered
profile.  It is **not published**: publication needs a scoped qualification
installed through the normal management entry point, which has not happened.

## 5. Still unverified

* The provider failure rate under the new code and the layer composition.
* The frozen evaluation under the new policy: running.
* Whether the generator produces good items at the pre-registered rate.  The first
  control item reviewed live failed the author/blind agreement case, which is a
  real signal about that item and not evidence about the rate.
* `QUALITY_NONINFERIORITY_EVIDENCE` remains **UNKNOWN**.
