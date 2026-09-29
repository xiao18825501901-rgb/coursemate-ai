# P0 · Constructive ambiguity and the supported scopes (2026-09-30)

This is the document that says exactly what the new ambiguity gate accepts, what
it refuses, and what it does not claim.  The scope list is deliberately short and
is meant to grow only with evidence.

## 1. Why the previous instrument was replaced

The gate asked a reviewer whether an item was under-specified.  Nine measured runs
and five rule iterations established that the question is not separable for this
configuration:

```
strict    (abstain unless proven)    detection 5/5   recall 0.375
moderate  (block only if the answer changes, A/B)   2/5   recall 0.632
dedicated (block only if the answer changes, one pass)  4/5   recall 0.238
```

Detection and coverage move together, and no measured configuration is both safe
and usable.  The reviewer systematically over-reports an absent condition on sound
items.  That is a calibration property of this reviewer on this task, and it is why
the answer is a different instrument rather than a tenth prompt revision.

## 2. What replaced it

### 2.1 A student-visible task contract

`StudentVisibleTaskSpec` states every element the answer turns on, each with a role:

| role | meaning | refused when |
|---|---|---|
| `GIVEN` | a real premise of the exercise | -- |
| `EXERCISE_ASSUMPTION` | a convention the exercise stipulates | it conflicts with the course material |
| `SOURCE_RULE` | a rule taken from a supplied span | no `source_span_id` |
| `CLAIM_TO_CRITIQUE` | a statement the student judges | -- (it is never a premise) |

The public projection is **rendered from the contract**, so every premise and every
convention appears in the text the student sees, under a label that says what role
it plays.  A statement the student is asked to critique is rendered separately and
labelled as such, so its being wrong can never make the item self-contradictory --
which was one of the ways the old instrument mis-fired.

The roles are not labels a model may apply freely.  They decide what the server
checks: a `SOURCE_RULE` without a span is refused at construction, a fact bound to a
span outside the evidence pack is refused at authoring, and `is_premise` is derived
from the role rather than asserted.

### 2.2 Registered profiles, and a certificate issued by code

| profile | version | question types | required roles | required conventions | checker |
|---|---|---|---|---|---|
| `P-SQL` | 1 | MCQ_SINGLE, SHORT_TEXT, CODE, EXPLANATION | GIVEN | DIALECT, DATA_COMPLETENESS, DUPLICATE_ROWS, ROW_ORDER | `sql_oracle.v1` |
| `P-DISCRETE` | 1 | NUMERIC, SHORT_TEXT, EXPLANATION, MCQ_SINGLE | GIVEN | DATA_COMPLETENESS, BOUNDARY_INCLUSION | `bounded_discrete.v1` |
| `P-COURSE-RULE` | 1 | EXPLANATION, SHORT_TEXT, MCQ_SINGLE | SOURCE_RULE, CLAIM_TO_CRITIQUE | ANSWER_FORM | `source_span_binding.v1` |

`certify_completeness()` checks, and records each one by name:

* the named profile version is registered;
* the question type is one the profile covers;
* every role the profile requires is present;
* every convention the profile requires is stated;
* every declared convention key is one the server recognises;
* every cited span id exists in the frozen evidence pack;
* every premise is rendered into the public projection;
* the projection was produced from this contract by the registered renderer;
* the reviewable language is one the profile is registered for.

Status is `COMPLETE_FOR_REGISTERED_PROFILE`, `INCOMPLETE` or `NOT_SUPPORTED`, and
the last two are never a pass.  This is not a model-produced boolean: no field in
`CompletenessEvidence` can be set by a reviewer, and the certificate is bound to the
projection digest and the revision hash so a changed contract invalidates the
evidence that cited it.

### 2.3 A material objection is a witness, and the server checks it

A reviewer that claims a defect must produce:

```
problem_field_or_span, interpretation A and B (statement, why each is admissible,
answer, scored conclusion), material_difference, minimal_disambiguation,
supporting_span_ids, introduces_new_data, changes_stated_condition,
and per reading an optional executable_statement
```

The server refuses, by code:

* a reading that needs data the item does not supply (`introduces_new_data`);
* a reading that contradicts a condition the item states;
* a witness that cites a span the item was not given;
* two readings whose scored conclusions are equal, or equal up to the order of a
  result the declared equivalence treats as unordered -- the "different method,
  same result" case that must not block a sound item.

Where both readings carry an executable form, `SqlWitnessChecker` runs both through
the isolated bounded oracle against the rows the item itself declares and compares
them under the declared comparison.  A confirmed difference is `CONFIRMED_MATERIAL`;
two readings that agree are `REFUSED_NOT_MATERIAL`.  That is a bounded claim about
one instance and is never reported as a proof of general query equivalence.

### 2.4 The gate itself

```
a confirmed material witness          -> FAIL
an unresolved witness                 -> UNCERTAIN
a blocking enumeration entry          -> UNCERTAIN   (a doubt, not a witness)
no certificate                        -> UNCERTAIN
no active qualification               -> UNCERTAIN
sertificate + qualification, nothing open -> PASS
```

Two decisions in that table are policy, not mechanics, and both carry a stated
risk:

1. **A bare ambiguity refusal no longer decides the case.**  It is answered by the
   certificate.  The accepted risk is a real defect the reviewer failed to
   substantiate on an item a registered profile nonetheless certifies.  It is
   bounded by the certificate checks, the six hard gates and the oracle, and it is
   why the registry is narrow.
2. **A blocking enumeration entry holds rather than fails.**  It names one
   consequence, not two admissible readings with their answers, so it is not the
   counterexample the published rule requires.  Safety is unchanged -- a held item
   is not released and only a certificate can pass one -- while the measured
   over-triggering stops refusing sound items.

**Not finding a witness is never an approval.**  The only route to PASS is positive
completeness evidence plus an active qualification.

## 3. What is supported, and what is not

**Supported, in the sense that code can certify an item of this shape:** finite
relational tasks under a declared dialect with the rows stated in the item; finite
graph, counting and clustering tasks with their boundary and self-inclusion
conventions stated; and course-rule tasks whose answer is decided by a rule in a
supplied span with the claim under evaluation marked as such.

**Not supported:** free essays, unbounded proofs, unknown dialects, and any shape
outside the three profiles.  Those return `NOT_SUPPORTED`, which is a hold under
review and never a pass.  No claim is made that every subject or language is
qualified, and none is made that a certificate proves an item formally correct --
it proves that the stated requirements for its shape are satisfied in the learner-visible
text.

## 4. What has been verified, and what has not

**Verified.**  266 tests on the policy suites, 320 on the wider targeted set, and one
bounded live probe in which the author produced a contract, chose `P-DISCRETE` for a
NUMERIC item, stated exactly that profile's required conventions, and received
`COMPLETE_FOR_REGISTERED_PROFILE` with the projection digest recorded.  A bounded
live run of the whole chain, including both reviewers and the specification pass,
reached `unknown_span_ids: []` and `untraceable_quotes: []`.

**Not verified.**  The frozen evaluation under this policy is running; no rate,
yield or false-accept figure from it exists yet, and the numbers from the nine
earlier runs were produced by a different method and do not carry over.  No
qualification has been installed and nothing has been published.  The certificate
path has not been measured against items known to be defective by an independent
label.
