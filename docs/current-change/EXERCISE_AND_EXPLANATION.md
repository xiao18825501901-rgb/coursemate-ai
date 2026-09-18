# EXERCISE_AND_EXPLANATION

## 做一题 (exercise generation)

- `POST /courses/{cid}/exercises {request_id, node?}` (202) → run; SSE on
  `/runs/{run}/events`. Only the QUESTION is streamed to the student.
- Target-node selection (`pick_exercise_node`): the pair's bound node first; otherwise
  the earliest NOT_STARTED/LEARNING atomic node in tree order; otherwise review of the
  first atomic node; no tree → explicit 409 (never invents nodes).
- The provider produces question + standard answer in ONE call using the owner's
  做一题 Word prompt; the delivery-format line (implementation decision, recorded)
  requires `【标准答案】` before the stepped answer. The answer is split server-side:
  question → visible assistant message; answer → `cmui_exercises.answer_steps`
  (never streamed, never in REST until revealed).
- Step ids are stable server-derived anchors (`steps.answer_steps_parse`), not array
  positions.

## 显示答案 (reveal)

- `POST /exercises/{id}/reveal` returns the stored steps of the SAME generation;
  repeated clicks are idempotent (no re-generation, no extra billing). Reveal state
  persists per owner (`cmui_answer_reveals`) and survives refresh.
- Seeing the answer is recorded as answer-exposure only — never auto-LEARNED,
  never EXAM READY.

## 详解 (step explanation)

- `POST /exercises/{id}/steps/{step_id}/explanation {request_id}` → creates/reuses a
  `cmui_step_explanations` row; streams via a dedicated run (hidden conversation).
  Inputs: the exercise question, full answer context, the specific step text, course
  evidence, and the 详解 Word prompt. Only the current step is explained.
- Multiple windows per step-set are allowed (draggable, resizable, closable, staggered,
  z-index managed); clicking the same step toggles its window; reopening a completed
  explanation reads the cached result (no new model call).
- Follow-ups: `POST /explanations/{id}/messages` appends a sub-conversation
  (`cmui_explanation_messages`) belonging to the unified history — never mixed into the
  teach lane and never into the plan. 停止 generation via `POST …/cancel`.
- Mobile: windows become a bottom-sheet with the same close control.

## Storage

`cmui_exercises` (question, answer_steps JSON, references, verification_status,
generation_version, target_node), `cmui_answer_reveals`, `cmui_step_explanations`,
`cmui_explanation_messages`. Deterministic verification of computational answers is
limited: `verification_status` is recorded; the model's self-claim of correctness is
never treated as verified.
