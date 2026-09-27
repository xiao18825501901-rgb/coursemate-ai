# Learning Loop Integration Changelog

Date: 2026-09-28

## Application changes

- Added migration 060 with append-only cycle, command/event, assignment/exposure, canonical
  submission, evaluation-job, feedback, diagnosis/intervention, follow-up, correction and
  reliability ledgers. Immutable rows have database triggers; existing authorities are referenced
  rather than copied.
- Added `LearningLoopService` for idempotent cycle start, unseen allocation, server-ordered exposure,
  frozen help snapshot, durable evaluation, evidence cards, optional diagnostic, D7, corrections
  and dependency scanning.
- Changed practice submission from synchronous grade projection to save-first/outbox evaluation.
  A 15-minute lease prevents concurrent workers; upstream/model ambiguity becomes `UNKNOWN` and is
  not hidden by an automatic paid retry.
- Registered exposure before returning hints, reveal, explanations and other eligible help. Private
  history and authorized share scope remain enforced by the existing UI-extension boundary.
- Added course-scoped loop endpoints and admin metrics/dependency/correction endpoints. No new main
  navigation item or second production API was created.
- Added optional diagnostic configure/skip/UNSURE behavior. Formal assessment stays `N >= 5`.
- Added an evidence card, asynchronous evaluation reconciliation and explicit 7-day follow-up in the
  existing learning workspace. The final fix imports the real `getExercise` poll function and
  re-enables reconciliation after React StrictMode remounts.
- Made Task Agent creation idempotent using `request_key` and schema 2. This avoids duplicate D7
  tasks after retry/restart.
- Added real-authority seed preflight/apply tooling. It rejects synthetic IDs and activates only
  courses whose source/publication/question authorities pass preflight.

## Key real handlers and hooks

- RAG/domain: `services/rag-api/app/learning/learning_loop.py`,
  `learning_loop_reporting.py`, `learning_loop_seeds.py`, `question_runtime.py`.
- HTTP/domain boundary: `services/rag-api/app/cm_update/app.py` and
  `services/rag-api/app/ui_extension/domain.py`.
- Web: `apps/web/src/ui/api.js`, `apps/web/src/ui/pages.jsx`.
- Task Agent: `services/agent-api/src/app.ts`, `repositories/tasks.ts`, `db.ts`.
- Migration: `services/rag-api/migrations/060_learning_loop_delivery.sql`.
- Seed tool: `scripts/learning_loop_seed_packs.py`.

## Commits

- `478185d` — evidence-first backend, reporting, seed adapter and migration.
- `8e01781` — UI-extension, student workspace and Task Agent integration.
- `2df1279` — wait for Clerk load and avoid signed-out protected-session probes.
- `420d205` — reliable asynchronous evaluation polling and updated multi-file browser contract.

## Compatibility and data treatment

- Additive migrations only; existing course, document, node, Teaching Spec, Pair, grade and learning
  IDs are unchanged.
- Existing assessments keep their frozen questions/spec/rubric.
- Corrections and withdrawals append; they do not rewrite historical answers or grades.
- Synthetic reference SQLite, users, questions, packs and Task Agent rows were not imported.
- Existing highest-quality/null-dollar-cap and Thinking behavior was not changed.
