# Question Engine student practice journey

Updated: 2026-09-25

## Status and evidence boundary

This document records the local CourseJesus implementation that connects one scoped, `READY`
Question Engine revision to the existing **做一题** experience. It is not a live-model or production
acceptance record.

| Layer | Status | Evidence |
|---|---|---|
| Source implementation | implemented locally | Question Engine runtime, integrated domain adapter, UI API and practice UI |
| Offline provider contract | verified | labelled fake provider only; no network or billable call |
| Backend integration | verified | 78 related tests before final hardening; 18 Question Engine/persistence/API tests after it |
| Frontend unit | verified | 115 tests in 25 files, including the new practice journey test |
| Browser | verified locally | 14 Playwright tests in real Chrome with synthetic DB and labelled fake semantic/provider transport |
| Live DeepSeek | not verified for this journey | no paid request was made |
| Production | not deployed or verified | production was not contacted |

The prior `READY` status remains `AI_REVIEWED`; it is not presented as deterministic correctness.
TypeSafe Jev remains a non-authoritative semantic signal and does not decide access, persistence,
grades, performance evidence, learning coverage, or `LEARNED`.

## Student flow now implemented

For a user-owned course/workspace and a `READY` Question Engine revision, the integrated path now
supports:

1. **做一题** displays the public question without the private answer or solution.
2. The learner can write an answer, request one persisted hint, or reveal the immutable answer.
3. Submitting an answer produces criterion-specific diagnostic feedback against the frozen rubric.
4. Hint and answer-reveal state is explicit; an assisted attempt is never labelled independent.
5. Refresh reloads the latest learner-visible hint and feedback without returning the submitted
   private answer or the reference solution.
6. **同目标再练一题** asks the existing pipeline for a new question family while retaining the
   same objective.
7. **详解** remains the independent detail window. The removed pink cross-pane question controls
   were not restored, and practice actions do not change the left Teaching Pane.

## Runtime and API boundaries

The browser uses the existing UI extension endpoints:

- `POST /exercises/{exercise_id}/hints`
- `POST /exercises/{exercise_id}/attempts`
- `POST /exercises/{exercise_id}/reveal`
- `GET /exercises/{exercise_id}` for recovery of the learner-visible projection
- the existing create-exercise endpoint for re-practice

The UI service rechecks exercise ownership and course access before forwarding an operation. The
integrated domain then resolves the exact owner workspace and calls `QuestionEngineRuntime`. A
historical exercise without a Question Engine revision fails explicitly instead of fabricating
feedback.

The runtime loads only a `READY` question with matching question owner, workspace owner, workspace
id, immutable rubric, and immutable reference solution. The public state projection never returns
the submitted answer or private reference answer.

## Persistence and replay safety

Migration `037_practice_question_interactions.sql` adds three owner-scoped tables:

- `practice_interaction_operations`: claim-first, immutable operation ledger;
- `practice_hint_events`: immutable hint evidence;
- `practice_question_attempts`: immutable submitted answer, assistance state, feedback, and provider
  receipt.

Each hint/attempt row must match a still-`CLAIMED` operation with the exact workspace, question,
owner, kind, and input hash. Database triggers also recheck that the revision is `READY` in the same
owner workspace. A completed operation replays its saved public result. A failed or in-progress
operation does not make a second provider call under the same operation id.

These records are diagnostic practice evidence only. They do not create `grade_snapshots`,
`performance_evidence`, or `learning_coverage`, and they cannot mark a node `LEARNED`.

## Model and answer-leak controls

- Production provider configuration remains DeepSeek-only; no Qwen fallback was introduced.
- Local tests use explicit labelled fake output.
- The hint prompt forbids returning the answer, final result, worked solution, or answer-equivalent
  strategy.
- A deterministic post-generation gate scans both hint text and strategy against the normalized
  private reference answer and fails closed on a leak.
- Feedback must cover every criterion in the frozen rubric exactly; missing or extra criteria fail
  closed.
- Billable operations retain rate, authorization, cancellation, and upstream technical limits.
  Choosing a UI reasoning strength does not bypass those controls.

An unexpected process death after a claim can leave an operation `CLAIMED`. That state deliberately
prevents an automatic duplicate paid call. Operator reconciliation for a truly abandoned claim is a
future recovery tool, not an implicit retry in this slice.

## Local browser evidence

The integrated Playwright test uses a temporary database, injected test identity, real Chrome, the
actual UI, the real Question Engine orchestration, and labelled fake provider/Jev transports. The
synthetic teaching spec cites an immutable synthetic course chunk so the real evidence gate remains
active.

Screenshots inspected for layout, readability, persistence, and absence of cross-pane controls:

- `work/codex-audit/browser-1790283402147-23660/.../practice-light.png`
- `work/codex-audit/browser-1790283402147-23660/.../practice-dark.png`
- `work/codex-audit/browser-1790283402147-23660/.../practice-reveal-repractice.png`

The paths above are local test artifacts; they are not production screenshots.

## Migration and rollback

Migration 037 is additive and registered explicitly in `V3_MIGRATIONS`; the local latest schema is
37. No existing question, rubric, reference, grade, progress, course, user, or history id is changed.

Before production, the normal verified backup and isolated restore rehearsal remain mandatory. A
code rollback can leave the additive tables unused. If compatibility verification for the exact
release reports otherwise, restore the verified pre-migration database and uploads according to the
release runbook; never drop the tables ad hoc from the live database.

## Remaining acceptance work

- Live DeepSeek quality and billing evidence for hint and feedback.
- The five-complementary-slot assessment generation flow and its unified five-answer journey.
- Final candidate regression/build after the next slice.
- Authorised production backup, migration, deployment, one real sign-in, and real student journey.

