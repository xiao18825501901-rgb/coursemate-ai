# CourseJesus Learning Loop — Final Release Report

Date: 2026-09-28

## Outcome

The evidence-first learning loop is integrated and deployed. Its first real application path saves
the attempt before feedback work, freezes server-observed help facts, assigns an unseen transfer,
evaluates through a durable outbox and projects an evidence card. Existing RAG, Question Engine,
Pair/history/share permissions, Task Agent, assessment grading and learning evidence remain the
authorities. No synthetic reference data entered production.

Backend release is `8e01781e18d6fc86c431ffe17c372712b6ec27b2`; the final web release is
`420d20522ed2aff33759f5dc13a4231963e9e85c`, deployed by Netlify as
`6ab9ab09cd69077bf7e9a4da` to `https://coursejesus.com`.

## Eight-layer status

| Layer | Status | Meaning |
|---|---|---|
| DESIGN | **PASS** | Six workstreams and contracts are mapped to current authorities. |
| REFERENCE_CODE | **PASS** | Package reference implementation and synthetic examples were read, not promoted to authority. |
| REFERENCE_TESTS | **PASS** | 172 isolated tests. This is reference evidence only. |
| REPO_INTEGRATION | **PASS** | Additive schema, services, routes, workspace UI, Task Agent idempotency and seed adapter are implemented. |
| LIVE_MODEL | **NOT VERIFIED FOR THIS FEATURE** | No new paid model call was made; existing DeepSeek/Jev runtime is unchanged and healthy. |
| PRODUCTION | **PASS WITH PUBLIC/SIGNED-OUT BROWSER SCOPE** | Backend and frontend deployed; schemas and health verified; public browser clean. |
| STUDENT_VALIDATION | **NOT VERIFIED** | No real authenticated student cycle was executed or impersonated. |
| LONG_TERM_ACCUMULATION | **NOT MATURE** | D7 and outcome denominators are zero. No learning-improvement claim. |

## Verification evidence

- Reference package: 172 passed in its isolated environment.
- RAG integrated suite: 66 passed; one non-blocking Starlette deprecation warning.
- Web: 31 files / 143 tests passed; typecheck and production build passed.
- Agent: 13 files / 100 tests passed; typecheck and build passed.
- Browser: 15/15 Playwright tests passed against isolated integrated services in 2.6 minutes.
- Production build scanned 18 artifacts, including the existing Windows Canvas Bridge; release SHA
  in `build-info.json` matches `420d205...`.
- Production browser: HTTP 200, expected Login/Register screen, zero console issues and zero failed
  HTTP responses. Screenshot is under `docs/learning-loop/evidence/`.
- Production services: RAG, integrated UI-extension (`provider=deepseek`) and Agent health all 200.
- Production databases: schemas 60 / 15 / 2, integrity `ok`, foreign-key violations 0.

## Seed courses and current results

- CS3481: active real-authority pack with two eligible targets.
- CS4335: correctly remains draft/waiting because it has zero READY question revisions and is not
  currently published. This is an explicit exception, not a hidden success.
- Current production metrics: 0 eligible users, 0 closures, correctness null, D7 denominator 0,
  activation unknown, monetary cost unknown.

## Backup, restore and rollback

- Pre-release backup:
  `/srv/coursemate/backups/pre-learning-loop-8e01781-20260927T231108Z`.
- Post-release consistent backup:
  `/srv/coursemate/backups/post-learning-loop-8e01781-20260927T231742Z`, including three SQLite
  backups, 850 hard-linked uploads and checksums. An isolated restore passed schema/integrity/FK
  checks.
- Frontend receipt:
  `/srv/coursemate/backups/frontend-learning-loop-420d205-6ab9ab09cd69077bf7e9a4da.txt`.
- Backend rollback: stop services, restore the previous `/srv/coursemate/current` symlink and, only
  if required, restore the verified pre-release database copies; then re-run health/integrity checks.
- Frontend rollback: publish the previous known-good Netlify deploy `6ab9a6e2db1348518bb52e75`.
- Failed rehearsal/cutover copies were retained when not hash-identical; evidence was not discarded.

## Honest remaining work

1. A real Clerk test student must personally sign in and complete one bounded cycle to verify the
   authenticated production projection. This cannot be replaced by a synthetic row.
2. A separately bounded live DeepSeek/Jev case is needed to mark `LIVE_MODEL` for this feature.
3. CS4335 requires real READY question authorities and publication/permission before activation.
4. D7, activation, cost and outcome observations must accumulate over real time and denominators.

These are validation/authority boundaries. They do not invalidate the deployed source and public
runtime evidence, and they are intentionally not reported as complete.
