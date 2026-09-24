# Question Engine five-slot assessment

Updated: 2026-09-25

## Evidence boundary

This document records the local CourseJesus implementation that prepares the existing node
assessment from five complementary Question Engine intents. It is not live-DeepSeek or production
acceptance evidence.

| Layer | Status | Evidence |
|---|---|---|
| Source implementation | implemented locally | QuestionSlot policy, Question Engine runtime, preparation orchestration, frozen Assessment selection |
| Offline provider contract | verified | labelled deterministic provider and labelled fake Jev transport only |
| Backend integration | verified | 54 related assessment, Question Engine, migration and rollback tests passed |
| Browser integration | verified locally | 15 real-Chrome Playwright journeys passed; one starts from an empty pool and displays the generated five-question session |
| Live DeepSeek | not verified for this slice | no network, credential or billable call was made |
| Production | not deployed or verified | production was not contacted |

## Object boundaries

The implementation keeps the three required objects distinct:

- `AssessmentQuestionSlot` is server-owned pre-generation intent. It contains no generated prompt,
  answer, empirical difficulty or learner result.
- `QuestionRevision` is the immutable generated question that passed authoring, blind solve, the six
  deterministic hard gates and the two independently receipted semantic gates.
- `AssessmentBlueprintItem` remains the frozen reference used by one started assessment. It is
  created by the existing `AssessmentService`; no parallel assessment or grade system was added.

The five default intents are:

| Order | Slot | Bloom target | Type | Marks |
|---:|---|---|---|---:|
| 1 | concept recognition | REMEMBER | single-choice MCQ | 10 |
| 2 | concept explanation | UNDERSTAND | short text | 15 |
| 3 | bounded application | APPLY | worked explanation | 20 |
| 4 | method analysis | ANALYZE | worked explanation | 25 |
| 5 | reasoned evaluation | EVALUATE | worked explanation | 30 |

They total 100 and deliberately cover five distinct Bloom targets and three public question types.
The difficulty values are design targets, not claims about measured learner ability. Empirical
difficulty remains `null` until real calibrated response data exists.

## Runtime flow

When the existing Assessment pool cannot supply five eligible families, preparation now does this:

1. Resolve every current `REQUIRED` item from the node's current Teaching Spec.
2. Cycle the five slot intents across those objectives without inventing a new objective.
3. Build the existing exact, authorization-checked Evidence Pack for each selected objective.
4. Create a deterministic blueprint from the preparation job id, slot, objective and evidence.
5. Run the existing Question Engine author, blind-solve, validation and scoped READY transaction.
6. Persist an immutable preparation-slot binding to the exact READY revision and family.
7. Mark the preparation job READY only after all five current families are eligible.
8. Let the existing Assessment service freeze those exact five revisions, in slot order, into the
   session. Legacy preparation jobs created before migration 038 keep their historical pool behavior.

The public session contains prompts, options, types and marks. It contains neither answer keys nor
reference solutions before submission. `AI_REVIEWED` remains a model-review label; it is not
deterministic correctness, human approval or an institutional grade.

## Recovery and charging behavior

The preparation job id is the stable generation key. A completed slot is reused only when its
blueprint hash, Evidence Pack hash, READY status and exact validation receipts still match. Explicit
resume therefore reuses completed slots and generates only the missing slots. Tests interrupt the
third author call, prove two slots remain durable, and prove the resumed result keeps both existing
revision ids. A separate regression deletes one frozen semantic receipt and proves resume fails
closed instead of silently reusing a no-longer-verifiable slot.

There is no unbounded retry. A refusal, insufficient source, invalid model output, stale evidence,
failed semantic gate or cancellation produces a recoverable BLOCKED/CANCELLED preparation state.
A process failure after an upstream response but before local persistence is an uncertain external
call and still requires operator reconciliation; this implementation does not pretend that uncertain
request is safely replayable.

## Persistence and rollback

Migration `038_assessment_question_slots.sql` adds
`assessment_preparation_questions` and widens the existing model-call ledger role constraints for
`QUESTION_AUTHOR` and `QUESTION_BLIND_SOLVER`. It also permits multiple independently identified
reservations with the same role inside one claimed learning operation, which is required for five
slots. Every call is therefore still counted against the existing daily per-user and per-course
limits and receives its own reservation and run-evidence row. Database constraints bind each slot row to the same preparation job,
workspace, node, Teaching Spec, objective, blueprint, READY provenance, family and generated
question revision. The order-to-marks mapping is enforced in the table itself. Rows are immutable.

No existing question, assessment, grade, progress, course, user or history id is rewritten. Before
production, the exact release still requires the normal consistent backup, isolated restore,
migration rehearsal and rollback-compatibility gate. A code rollback can ignore the additive table
only if that exact compatibility check passes; otherwise restore the verified pre-migration data.

## Local verification

- Related backend suite: `54 passed`, one dependency deprecation warning.
- Real Chrome combined audit suite: `15 passed` in an isolated synthetic workspace.
- The assessment browser fixture starts with no question pool, cites a real immutable synthetic
  source chunk, uses labelled local provider/Jev transports, waits for the actual preparation and
  asserts five questions, marks `10/15/20/25/30`, three question types and no pre-submit answer.
- Final-code combined browser artifact: `work/codex-audit/browser-1790287445900-36528/`.
- Inspected five-question screenshot:
  `work/codex-audit/browser-1790287445900-36528/browser-results/codex-audit-empty-assessme-8bafe-ntary-Question-Engine-slots/five-question-slots.png`.
- The targeted run database contains exactly five slot bindings, five completed
  `QUESTION_AUTHOR` reservations and five completed `QUESTION_BLIND_SOLVER` reservations.

## Remaining gates

- Live DeepSeek quality, refusal, truncation and cost evidence for all five roles.
- Human review of representative generated questions and their reference solutions.
- Exact-candidate migration/restore rehearsal and required wider regression.
- Authorized production deployment, real sign-in and a real student assessment journey.
