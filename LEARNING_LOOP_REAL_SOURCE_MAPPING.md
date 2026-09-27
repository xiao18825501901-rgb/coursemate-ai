# CourseJesus Learning Loop — Real Source Mapping

Date: 2026-09-28

Branch: `feature/learning-loop-20260928`

Integrated backend SHA: `8e01781e18d6fc86c431ffe17c372712b6ec27b2`

Final frontend/application SHA: `420d20522ed2aff33759f5dc13a4231963e9e85c`

The package's 172 passing tests are reference evidence only. This table records the state of the
real CourseJesus repository after adaptation and deployment. `ReferenceStore` and both synthetic
fixture courses remain outside production databases and metrics.

| Workstream | Final state | Real authority and wiring | Evidence boundary |
|---|---|---|---|
| 1. Learning cycles, reliability and actual metrics | **EXISTS_AND_USABLE** | `learning_loop.py`, `learning_loop_reporting.py`, migration 060, Question Engine submission/evaluation receipts, admin metrics route | Production observation has 0 eligible users/cycles; it proves instrumentation, not uplift. Signup activation and monetary cost remain `UNKNOWN` where no authoritative ledger is connected. |
| 2. Optional three-item entry diagnostic | **EXISTS_AND_USABLE** | Existing READY Question Engine pool; configure/skip/UNSURE routes; evidence-card projection | It is separate from formal `N >= 5`; `UNSURE` is not a zero, grade, assessment submission, or `LEARNED`. |
| 3. Versioned packs for two seed courses | **EXISTS_NEEDS_WIRING** | `learning_loop_seeds.py` and `learning_loop_seed_packs.py` reference existing documents, nodes, Teaching Specs, READY questions and rubrics | CS3481 is activated from real published authorities. CS4335 remains draft because it has no READY question revisions and is not a published campus course. |
| 4. Evidence-backed misconception candidate and one intervention | **EXISTS_AND_USABLE** | Frozen answer/rubric/question/source references, candidate diagnoses, intervention ledger and feedback projection | A candidate is not a learner trait or formal grade. Model text cannot directly write grades or `LEARNED`. |
| 5. Unseen transfer, independent attempt, evidence card and optional D7 | **EXISTS_AND_USABLE** | Ordered exposures across help surfaces, unseen assignment, canonical submission, frozen help facts, durable evaluation job, feedback/evidence card and Task Agent idempotency | Local real call chain is verified. Production D7 accumulation is not yet mature; authenticated student use was not impersonated. |
| 6. Lightweight correction and operating view | **EXISTS_AND_USABLE** | Append-only corrections/withdrawals, dependency scan, historical/current validity split, privacy-minimal metrics | Withdrawal preserves attempts, grades, exposure history and cohort anchor. Small/zero cohorts are not presented as outcomes. |

## Reused production authorities

- Question source/family/rubric: `question_engine_provenance`, `assessment_question_revisions`,
  `assessment_rubric_criteria`, `assessment_reference_solutions`.
- Practice and receipts: `QuestionEngineRuntime`, existing exercise/hint/reveal routes, canonical
  grade/provider receipts and model reservation records.
- UI history and context: existing Pair, conversation, Teaching/Problem panes and share scope.
- Scheduling: existing Node Task Agent with a new idempotent `request_key`; no second scheduler.
- Identity and privacy: existing Clerk subject, course membership and private/share authorization.
- Formal learning/grade truth: existing assessment and V3 learning evidence; the loop does not
  overwrite `grade_snapshots`, `performance_evidence` or `LEARNED`.

## First complete vertical path

`initial substantive attempt -> delivered feedback -> unseen transfer assignment -> canonical
submission with server-frozen help facts -> durable asynchronous evaluation -> evidence card`.

Help exposures from the other pane, history, explanations, hints, reveal and authorized shared
content are ordered before assignment/submission decisions. A valid incorrect transfer closes
participation but remains incorrect in correctness metrics. Reveal is recorded by the server;
students cannot submit after seeing the answer as an unseen independent attempt. Corrections add
new facts and never erase the historical submission.
