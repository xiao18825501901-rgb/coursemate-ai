# Final CourseMate production acceptance

**Assessment time:** 2026-09-20 16:48 CST

**Application release:** `46415bde81df28f4dc18629219bc9ddc50e4c215`

**Netlify production deploy:** `6aaf951c45a27f7ea503df44`

**Public site:** <https://qqttai.com>

## Final verdict

```text
OFFICIAL / CAMPUS COURSE CONTENT: PRODUCTION ACCEPTED
EXERCISE + PROBLEM STEPS + LEARNINGBRIDGE: PRODUCTION ACCEPTED
COURSEMATE FULL CONTENT + FUNCTION: PRODUCTION ACCEPTED
OVERALL: PASS
```

The two user-facing defects that previously kept this report at PARTIAL FAILURE are repaired and
verified in production. “做一题” now uses the strict `exercise.v2` structured contract, keeps the
answer hidden until explicit reveal and supports persisted step explanation. Ordinary Problem
solutions retain visible step-level knowledge links; clicking one opens real Teaching context and
returns to the original Problem step.

## Final acceptance matrix

| Area | Result | Current evidence |
| --- | --- | --- |
| Public frontend / RAG / integrated UI / Agent | PASS | Four public HTTPS endpoints returned 200 |
| Authentication boundary | PASS | Protected RAG and Agent endpoints returned 401 without identity |
| Exact frontend/backend release | PASS | Public build identity and active backend both `46415bd` |
| Full backend regression | PASS | 692 passed, no failures/errors/skips |
| Web / Agent regression | PASS | 60 / 66 passed; typecheck and builds passed |
| Browser regression | PASS | Main gate 4 passed; complete audit 14 passed |
| CS3481 official content | PASS | PUBLISHED tree, 22 nodes, 15 published Specs, ACTIVE release |
| GE2324 official content | PASS | PUBLISHED tree, 21 nodes, 14 published Specs, ACTIVE release |
| “做一题” generation | PASS | Real CS3481 and GE2324 `qwen3.8-max` production canary |
| Hidden answer / explicit reveal | PASS | Answer absent before reveal; saved steps returned after reveal |
| Saved step explanation | PASS | Real provider explanation persisted and rendered |
| Ordinary Problem full solution | PASS | Four server-persisted and browser-visible steps |
| Per-step knowledge links | PASS | Four visible actions in production browser |
| LearningBridge / teaching / return | PASS | Real teaching run completed and original step restored |
| Internal-plan confidentiality boundary | PASS | Stored plan fields absent from normal inspected payloads |
| Backup / isolated restore | PASS | Eight checksums; three DBs integrity ok / FK 0; uploads restored |
| Old-server writer isolation | PASS | Singapore RAG and Agent inactive |
| Monitoring | PASS | Enabled active timer; last service result success |
| Temporary identity and code cleanup | PASS | Actors deleted; full Clerk sync; unused codes disabled |

All broader content and product checks in the previous acceptance remain valid; the hotfix did not
republish content, change schemas, reset data or relax a security boundary.

## Cost

The Owner approved a combined USD 1.50 ceiling. Sixteen recorded provider calls, including every
failed or superseded harness attempt, used 49,265 input and 16,136 output tokens. The official
list-price estimate is **USD 0.195346**. No automatic provider retry was used. Actual invoice charge
is unknown because the provider billing console was not queried.

## Recovery and rollback

- Post-release backup:
  `/srv/coursemate/backups/post-hotfix-46415bd/coursemate-v2-20260920T084554.355828Z`
- Verified isolated restore:
  `/srv/coursemate/restore-tests/post-hotfix-46415bd-20260920T084554Z`
- Backend rollback:
  `/srv/coursemate/rollback/current-before-46415bd`
- Frontend rollback deploy: `6aaef108d89499d9a5e52722`

No rollback is indicated. The active production site is accepted at release `46415bd`.
