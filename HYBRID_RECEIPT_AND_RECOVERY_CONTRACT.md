# HYBRID_RECEIPT_AND_RECOVERY_CONTRACT

What a hybrid publication records, how it is re-verified, and how every
failure/abstention/cancellation path recovers.  This describes behaviour that is
implemented and covered by tests, not a proposal.

## 1. Tables (additive migration 065, idempotent, replay-safe)

The migration is registered in `V3_MIGRATIONS` and replayed on every startup, so
every statement uses `IF NOT EXISTS`; `LATEST_V3_SCHEMA_VERSION` is now `65`.
Nothing in `028_jev_decision_receipts.sql` changes: the historical
`jev_decision_receipts` rows keep their identity, their decoding and their
`model_version` values (all 117 are `jev-latest`, produced by the retired
TypeSafe SDK path).  They are **not** relabelled as hybrid reviews.

### `hybrid_review_calls` — one row per strong-reviewer provider call

`id`, `question_revision_hash`, `blueprint_hash`, `evidence_pack_hash`,
`policy_revision`, `role` (`evidence_audit` | `adversarial_audit`), `call_id`,
`model`, `provider`, `protocol`, `region`, `template_version`, `schema_version`,
`input_hash`, `response_digest`, `response_json`, `findings_json`,
`verification_json`, `references_verified`, `terminal`, `input_tokens`,
`output_tokens`, `latency_ms`, `provider_response_id`, `created_at`.
`UNIQUE(question_revision_hash, role, input_hash)`.

The full response text is stored **before** the content is used, so a paid call
is never silently re-asked: a failed call fails the row and there is no retry in
this path (`LearningProvider` is constructed with `max_retries=0`).

Append-only triggers reject `UPDATE` and `DELETE`.

### `hybrid_local_observations` — advisory-only local signals

`id`, `question_revision_hash`, `case_key`, `status`
(`OBSERVED` | `SKIPPED` | `UNAVAILABLE`), `verdict`, `probabilities_json`,
`model_revision`, `dtype`, `tokenizer_hash`, `transform_version`,
`model_input_hash`, `state_tokens`, `reason`, `latency_ms`, `qualification`
(default `UNQUALIFIED_ADVISORY`), `created_at`.

There is deliberately no column that grants or vetoes a decision.

### `hybrid_quality_receipts` — the final receipt

`id`, `question_revision_hash`, `blueprint_hash`, `evidence_pack_hash`,
`policy_revision`, `method_identity`, `qualification_id`, `owner_scope_hash`,
`course_id`, `workspace_id`, `node_id`, `spec_version`, `language`, `domain`,
`required_cases_json`, `case_outcomes_json`, `projected_verdicts_json`,
`review_call_ids_json`, `local_observation_ids_json`, `local_status`,
`deterministic_report_json`, `deterministic_digest`, `reasons_json`, `status`
(`QUALITY_ACCEPTED` | `QUALITY_NOT_ACCEPTED`), `created_at`.
`UNIQUE(question_revision_hash, policy_revision, method_identity)`.

Append-only triggers reject `UPDATE` and `DELETE`: a published hybrid receipt is
audit history and survives later policy revisions rather than being rewritten.

### `hybrid_qualifications` — the scoped qualification registry

`id`, `policy_revision`, `method_identity`, `status`
(`DRAFT` | `SCOPED_QUALITY_ACCEPTED` | `WITHDRAWN`), `reviewer_label`,
`languages_json`, `domains_json`, `cases_json`, `roles_json`,
`sample_counts_json`, `metrics_json`, `evidence_manifest_digest`,
`observed_model_facts_json`, `expires_at`, `active`, `created_at`.

`reviewer_label` is constrained to `SCOPED_QUALITY_ACCEPTED` or
`PROVEN_IDENTICAL_TO_JEV`; the record also refuses the identical claim unless the
status is the accepted one, so a draft cannot be dressed up as an accepted
qualification.

## 2. Publication re-verification

A `hybrid` signal is accepted only when, **inside the same `BEGIN IMMEDIATE`
transaction** that inserts the revision, all of the following hold:

1. `_recomputed_report` re-runs the unchanged validator over the supplied signals
   and refuses on any mismatch (`QUESTION_VALIDATION_MISMATCH`);
2. every semantic signal has `used_jev = True`, a receipt id and a path in
   `{jev, hybrid}` — a fallback can claim neither;
3. for `hybrid`, `hybrid_quality_receipts.status = QUALITY_ACCEPTED` for this
   exact revision, workspace, course, node, spec version and owner scope;
4. the receipt's `projected_verdicts_json[dimension]` equals the signal's verdict;
5. the receipt names exactly two distinct `hybrid_review_calls` rows, one per
   role, each `terminal='completed'`, `references_verified=1`, with a stored
   response body and digest;
6. the referenced qualification still exists, is `SCOPED_QUALITY_ACCEPTED`,
   `active=1`, unexpired, and its `method_identity`/`policy_revision` match the
   receipt;
7. the six deterministic hard gates still pass and the author/blind provenance is
   still current for this revision.

Any miss produces `NEEDS_REVIEW` with the existing reason vocabulary; the only
`READY` outcome remains `VALIDATION_COMPLETE_AI_REVIEWED`.

The scope check is repeated at publication rather than trusted from review time,
so a qualification withdrawn between the review and the commit blocks the commit
(covered by `test_a_withdrawn_qualification_blocks_publication`).

## 3. Determinism and non-overridability

* A `REJECTED` deterministic report is returned **before** the reviewer chain is
  consulted, so two favourable model votes cannot resurrect a hard-gate failure
  (`test_a_deterministic_hard_gate_failure_is_never_sent_to_the_reviewers`
  asserts zero provider calls).
* The combination rule is conjunctive: both roles `PASS` → `PASS`; **either**
  role `FAIL` → `FAIL`; otherwise `UNCERTAIN`.  There is no majority vote and no
  "re-ask until it agrees".
* A reviewer output whose required case set is incomplete, whose span id was not
  supplied, whose quotation is not a verbatim fragment of the cited span, or
  whose step id does not exist makes the whole review unverifiable and therefore
  unpublishable.

## 4. Reviewer isolation

* Two provider calls with distinct `role` strings, distinct instruction
  documents (`judge-evidence-audit.v1`, `judge-adversarial-audit.v1`), distinct
  `template_version` and distinct `input_hash`.
* `ReviewerInputs` has no field for a peer verdict, a local label, an acceptance
  flag or author chat history, so material cannot leak by construction.
* The anonymised solution order is frozen from the immutable question revision
  hash (`balanced_solution_order`) and **reversed** for role B, rather than
  chosen after seeing an answer.
* Both calls complete before either result is read.
* The two requests use the same underlying model.  This is recorded as process
  separation, not statistical independence; no probability is multiplied.
* Live evidence (2026-09-29, production host, protected credential): two
  distinct provider response ids, two distinct input hashes, both terminals
  `completed`, references verified, 5 171 input / 736 output tokens for the pair.

## 5. Local (OpenJev) observation contract

* Advisory only: no field grants or vetoes a decision; a positive cannot publish
  and a negative cannot veto.
* `UNAVAILABLE` / `SKIPPED` never block a complete qualified strong review.
* Non-English (including mixed) items, over-long items and images are skipped
  with a recorded reason instead of being translated, compressed or truncated.
* An over-long state is refused by the pinned service (`truncation` is the string
  `"error"`), never cut and then scored.
* Observations are recorded under their own `UNQUALIFIED_ADVISORY`
  qualification; the four OpenJev definition modes are not a publication
  condition under this policy.

## 6. Recovery matrix

| Situation | Action | Never |
|---|---|---|
| A question-engine run's SSE drops | The browser reconciles the **same** run id with bounded `GET`s; the server result stands | No timer ever issues a generation `POST` |
| Reviewer provider error after send | `StrongReviewError` with the recorded run; the candidate stays `NEEDS_REVIEW` | No automatic re-send; no hidden retry; no "the tool timed out so assume it failed" |
| Provider response complete, schema invalid | The full response is persisted first, then the row fails | The response is not discarded and the call is not repeated |
| Reviewer verdict `FAIL`/`UNCERTAIN` | Structured defect list; a new immutable revision may be authored for the same slot, bounded to the initial candidate plus at most two revisions | No downgrade of objective/type/difficulty, no family swap to launder exposure, no unbounded loop |
| Qualification missing / withdrawn / expired / out of scope | `QUALITY_NOT_ACCEPTED` with a reason; the revision is stored for audit as `NEEDS_REVIEW` | The status is not forced to `READY`; the receipt is not edited |
| Local observer unavailable | Recorded `UNAVAILABLE`; the strong path continues | The local model is not allowed to block, veto, delete evidence or trigger regeneration |
| Assessment slot already bound to a `READY` revision | The existing revision is reused after a per-dimension receipt re-check (hybrid reuse is verified per dimension because one receipt legitimately covers all cases) | The slot is not re-authored, and a `NEEDS_REVIEW` row is never reused |
| Assessment preparation interrupted | The lease expires, the job re-claims, and **only missing slots** are filled; partial progress is retained | Completed slots are not regenerated; a `MODEL_REQUEST_UNCERTAIN` reservation blocks automatic resends |
| Configuration becomes fully bound after a `BLOCKED` state | `COMPATIBLE_POOL_COMPLETE` recovery receipt with `model_calls_added = 0` | The original failure is not erased; the reason is appended, not overwritten |
| Run cancelled | `QUESTION_CANCELLED`; the observer for the old run is invalidated | A late result cannot revive a cancelled run or overwrite a newer pane |

## 7. What is deliberately absent

* No `hybrid_quality_receipts` update path, no delete path, and no "force pass"
  column.
* No fallback from the hybrid chain to the local chain, or the reverse: the two
  reviewed methods are independent evidence, and a question either has a
  qualified chain or it does not.
* No cross-owner reuse: `owner_scope_hash` is a server-derived digest of
  (owner user id, authorization scope), and the receipt is checked against it at
  publication.
