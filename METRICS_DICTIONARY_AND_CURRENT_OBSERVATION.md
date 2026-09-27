# Learning Loop Metrics Dictionary and Current Observation

Date: 2026-09-28

## Counting rules

- **Eligible user:** real, non-internal actor in an enabled course/pack and authorized course scope.
- **Cycle closure:** same user/course/target/pack/spec has a substantive initial attempt, delivered
  feedback, later eligible unseen transfer, substantive independent submission and valid evaluation.
- **Participation closure:** may include an incorrect valid transfer. It is not correctness.
- **Transfer correctness:** correct valid transfer submissions / valid transfer submissions; null if
  denominator is zero.
- **Current validity:** excludes a dependency invalidated by an append-only correction. Historical
  closure remains queryable and the original cohort anchor is not rewritten.
- **D7 eligible:** explicit opt-in plus a matured seven-day window and a valid recheck assignment.
  Before maturity the state is `IMMATURE`, not failure or zero retention.
- **Reliability:** first successful render and recovery success are separate. Resume success cannot
  replace a failed first attempt.
- **Activation:** requires a signup authority joined to eligible actors. Without it the value is
  `UNKNOWN_SIGNUP_AUTHORITY_NOT_CONNECTED`.
- **Cost:** uses authoritative monetary receipts. Token counts or estimates are not silently turned
  into actual dollars; without amounts it is `UNKNOWN_NO_BILLING_AMOUNT_LEDGER`.
- **Internal/synthetic:** excluded from business denominators even when technically valid tests.

## Production observation after release

| Metric | Value | Interpretation |
|---|---:|---|
| Unique eligible users | 0 | No authenticated real learner has entered the released loop yet. |
| Current valid closures | 0 | Instrumentation is live; no outcome sample exists. |
| Transfer correctness | null | Denominator is zero. |
| D7 denominator | 0 | No matured opted-in cohort. |
| Activation | UNKNOWN | Signup authority is not connected to this reporting projection. |
| Monetary cost | UNKNOWN | No authoritative amount ledger is connected. |
| Student validation | NOT_YET_MATURE | Do not state improvement, retention or product moat. |

Snapshot status: `CURRENT_OBSERVATION_NOT_STUDENT_UPLIFT`. The server copy is stored at
`/srv/coursemate/backups/learning-loop-current-observation-8e01781.json`.

## Privacy projection

The operating view returns aggregates and reference IDs. It does not expose answer text, chats,
hidden plans, course bodies or private source documents. Small cohorts remain visibly immature or
empty instead of being rounded into success claims.
