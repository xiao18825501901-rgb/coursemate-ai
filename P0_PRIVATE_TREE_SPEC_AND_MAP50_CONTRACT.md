# P0 Private Tree Spec and Map50 Contract

## Scope

Only a newly created owner-private course with newly READY authorized documents is eligible. The 13 grandfathered active over-limit trees remain untouched and legacy backfill remains disabled.

## Source and job identity

The existing durable auto-map service binds owner, course/workspace, immutable document versions, chunk evidence, corpus fingerprint, source snapshot, builder version and job receipt. GET/status paths are read-only.

## Generation budget

- Project constant: `MAX_EFFECTIVE_COURSE_NODES = 50`.
- Whole-course outline maximum: 8 modules and 36 atomic learning units.
- Evidence is reduced through bounded, resumable course-level outline passes; raw chunks are not projected one-for-one as nodes.
- Over-budget candidates are reorganized/merged before validation, not randomly truncated.

## Readiness and validation

- At least one authorized READY document version and indexed evidence item are required.
- Candidate map and Teaching Specs are schema validated before publication.
- Stable node ids, owner/course/workspace binding, authorized evidence ids, node budget, graph reachability, prerequisites and Teaching Spec evidence are checked before activation.
- Activation writes the immutable revision and switches the active pointer transactionally; a failed candidate cannot replace the active tree.

## Prompt event behavior added by P0

- Ordinary worker polls reconcile only new durable source events and do not sweep legacy targets.
- Full recovery/reconciliation remains on its configured interval.
- A consumed batch-seal `RECONCILIATION` event is a release fence for older quiet-window events.
- Status ignores older pending events superseded by that consumed release fence, so a READY target is not falsely projected as QUEUED.

## Recovery and cost controls

The same target key and corpus fingerprint reuse the durable job. Completed provider artifacts and receipts are reconciled; UNKNOWN is not blindly resent. Source changes produce a new immutable fingerprint/revision while the old active tree remains readable until successful activation.

