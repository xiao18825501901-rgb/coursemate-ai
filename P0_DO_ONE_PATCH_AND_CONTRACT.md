# P0 Do-One Patch and Contract

## Contract

Do-One is a one-question consumer of the existing Question Engine, not a second question system.

- Scope: exact owner, workspace, course, node, active Teaching Spec revision, objective and authorized evidence set.
- READY path: reuse an unexposed READY/AI-reviewed/validated immutable question revision with zero author or blind-solver calls.
- Empty-pool path: execute the existing author, blind solver, semantic review, persistence and receipt chain once.
- Idempotency: repeated equivalent active requests return the same run; different payloads conflict.
- Privacy: public run events contain only the stem; answer steps remain private until explicit reveal.
- Revision binding: stem, answer steps, hint, attempt, evaluation and detail all use the same `question_revision_id`.
- Exposure: assignment-owned questions use the learning-loop assignment exposure; other questions receive one idempotent STEM exposure on actual display.
- Recovery: SSE loss and refresh observe the same persisted run using GET; no observer resubmits generation.
- Cancellation/unknown: terminal cancellation cannot be revived; provider-unknown state is reconciled from ledgers/artifacts and is never blindly resent.

## Files changed

- `services/rag-api/app/learning/question_runtime.py`
- `services/rag-api/app/ui_extension/domain.py`
- `services/rag-api/app/cm_update/app.py`
- corresponding unit, mounted integration and Playwright tests

No schema migration was required. Existing exercise/run/question provenance, learning operation, model reservation, exposure, Pair and history records express the session durably.

