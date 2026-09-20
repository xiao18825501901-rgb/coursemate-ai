# CourseMate exercise and Problem-step production hotfix — 2026-09-20

Status: **DEPLOYED AND PRODUCTION ACCEPTED**

Application release: `46415bde81df28f4dc18629219bc9ddc50e4c215`

Branch: `fix/codex-dsh-audit-20260919`

Netlify production deploy: `6aaf951c45a27f7ea503df44`

## Runtime identity

- Public site: `https://qqttai.com`
- Active host: Hangzhou `47.114.34.175`
- Backend: `/srv/coursemate/current -> /srv/coursemate/releases/46415bd`
- Application rollback: `/srv/coursemate/rollback/current-before-46415bd ->
  /srv/coursemate/releases/aa3ffc2-recovery-pairfix`
- Frontend rollback deploy: `6aaef108d89499d9a5e52722`
- Active data: `/srv/coursemate/data/releases/20260919T202006Z`
- RAG / UI / Agent schemas: 25 / 11 / 1
- Provider/model: Alibaba Model Studio / `qwen3.8-max`

The old Singapore RAG and Agent services remain inactive. On the new host, RAG, Agent, nginx and
`coursemate-monitor.timer` are active; the timer is enabled and its last service result is success.

## Cutover and restart incident

The first candidate switch exposed a pre-existing restart migration defect: a teaching-only Pair
with `problem_conversation=NULL` was not recognized as already satisfied and startup attempted a
duplicate knowledge-node binding. The candidate automatically rolled back, but the old application
had the same latent behavior against the now-existing data shape. A minimal recovery release restored
service while the repair was test-driven locally.

Application SHA `46415bd` treats a missing lane as satisfied and only adds non-null lane IDs to the
existing-conversation set. Its regression uses the production-shaped teaching-only Pair. The exact
candidate then passed restored-data startup and the full 692-test backend suite before the second,
successful switch. No schema, course content or user data was deleted or rebuilt.

## Recovery evidence

Pre-cutover recovery point:

`/srv/coursemate/backups/pre-hotfix-6e0b8d7/coursemate-v2-20260920T074449.298243Z`

Post-cutover recovery point:

`/srv/coursemate/backups/post-hotfix-46415bd/coursemate-v2-20260920T084554.355828Z`

Post-cutover isolated restore:

`/srv/coursemate/restore-tests/post-hotfix-46415bd-20260920T084554Z`

The post-cutover backup was taken with both writers stopped and immediately restarted. All eight
artifacts passed SHA-256 verification. The restore contains 67 RAG upload files / 124,236,993 bytes,
zero UI uploads and 16 share snapshots / 181,408 bytes. RAG, UI and Agent SQLite databases each
report `integrity_check=ok` and zero foreign-key violations.

## Acceptance

- Public site, RAG health, integrated UI health and Agent health: HTTP 200.
- Unauthenticated RAG `/me` and Agent `/api/tasks`: HTTP 401.
- Public `build-info.json`: exact release SHA, `production` context and production origins.
- CS3481 tree remains PUBLISHED with 22 nodes and 15 published teaching specs; its release remains
  ACTIVE.
- GE2324 tree remains PUBLISHED with 21 nodes and 14 published teaching specs; its release remains
  ACTIVE.
- Generated-exercise and ordinary-Problem live canaries passed.
- Browser displayed four ordinary Problem steps, a saved detail, real LearningBridge teaching and
  return to the original step.
- Internal generated-plan fields were absent from normal payloads inspected by the acceptance.

The complete live-call ledger is in `EXERCISE_AND_STEPS_TEST_REPORT.md`: 16 calls, USD 0.195346
estimated total, below the USD 1.50 approved ceiling. Actual billed cost is unknown without provider
invoice access.

## Identity cleanup

Every short-lived Clerk acceptance actor was deleted in a `finally` path. A fresh supported complete
Clerk directory sync returned seven active upstream records and applied no verification grants. Two
unused acceptance codes were disabled; four redeemed code rows remain as audit tombstones. No
plaintext code, password, token or API key is present in Git or this report.

## Rollback

1. Backend: atomically repoint `/srv/coursemate/current` to
   `/srv/coursemate/rollback/current-before-46415bd`, restart both services and re-run health and
   startup checks.
2. Frontend: restore Netlify deploy `6aaef108d89499d9a5e52722`.
3. Data restoration is independent and destructive. Use the verified post/pre recovery unit only
   for an actual data incident after accepting its RPO; do not remove additive schemas manually.

No rollback is indicated by the final evidence.
