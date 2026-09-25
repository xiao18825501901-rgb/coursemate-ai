# Final CourseJesus Question Engine P5 production report

Date: 2026-09-25
Branch: `fix/codex-dsh-audit-20260919`
Application candidate: `a24fac535eda85358965f516964df0c40510e7a0`
Production acceptance: **NOT ACCEPTED / NOT DEPLOYED**

The source, local regression, real production snapshot migration and old-runtime rollback rehearsal
are complete. The live DeepSeek Question Engine chain did not complete, the four required live Jev
receipts were not produced, and there is no exact live content for a human reviewer. Those are
mandatory release gates, so the production release was correctly withheld.

## Final status matrix

| Layer | Status | Evidence |
|---|---|---|
| `SOURCE_IMPLEMENTED` | **PASS** | P5 runner, metered practice calls, immutable uncertain-operation reconciliation, migration 039 and release metadata are committed; final test-isolation fix at `a24fac5` |
| `LOCAL_VERIFIED` | **PASS** | 1838 passed / 2 environmental skips / 0 failed; Web 115; Agent 92; typechecks pass; browser 15 + 23 + 4 + 3 + 12 pass, with 5 honest JEV configuration skips |
| `LIVE_DEEPSEEK_QUESTION_ENGINE` | **NOT PASSED** | no live author→blind→READY result; one possible author transport has outcome/usage/charge UNKNOWN |
| `LIVE_JEV_BASE_SIGNALS` | **PARTIAL, NOT ACCEPTED** | three real calls occurred only for retrieval/source/prototype definitions; required ambiguity/agreement positive receipts absent |
| `LIVE_JEV_SPECIALIZED_SIGNALS` | **NOT VERIFIED** | required MCQ/rule positive live receipts absent |
| `HUMAN_CONTENT_REVIEW` | **PENDING / EMPTY** | no live question revision exists for review |
| `PRODUCTION_SNAPSHOT_RESTORED` | **PASS** | fresh three-database/file backup restored in isolation; checksums, integrity and FK checks pass |
| `MIGRATION38_RUNTIME_VERIFIED` | **PASS via target schema 39** | actual schema 25 snapshot migrated through 38 to 39; old rows unchanged; invariants green |
| `ROLLBACK_RUNTIME_VERIFIED` | **PASS IN ISOLATION** | actual old release initialized and served health against migrated snapshot; before/after fingerprints identical |
| `UNCERTAIN_OPERATION_RECOVERY` | **SOURCE + LOCAL PASS** | unknown call preserved, same id never retried, new attempts require linked IDs; no provider status API invented |
| `PRODUCTION_DEPLOYED` | **NO** | live quality and human gates failed/not run |
| `SIGNED_IN_STUDENT_ACCEPTANCE` | **NOT RUN** | no P5 production release; local synthetic identity is not production login evidence |
| `POST_RELEASE_BACKUP_AND_MONITORING` | **NOT RUN** | no release occurred; fresh pre-release backup and healthy monitor are recorded separately |
| `CAMPUS_EXPANSION_PAUSED` | **PASS / ENFORCED** | no Canvas roots were scanned and no withheld campus content was published |

## Verification on the frozen candidate

- Backend: 1,838 passed, 2 skipped, 0 failed in 1,095.270 s. The skips are Windows-only
  symlink privilege and POSIX permission-bit checks, not hidden passes.
- Web: 115 passed across 25 files; Agent: 92 passed across 12 files.
- TypeScript: Web and Agent both pass.
- Browser: Codex audit 15/15; refreshed UI 23/23; base 4/4; V3 3/3; JEV 12 passed and
  5 intentionally skipped because real promoted TypeSafe modes were absent.
- Production-shaped local build: preflight, Vite build, 7-file PAT scan and 16-artifact verifier
  pass at `a24fac5`. The local `pk_live_`-shaped value proves only the build gate shape, not a Clerk
  account or deploy.
- Focused Ruff, Python compilation and runner-isolated mypy pass. Repository-wide Ruff and strict
  mypy retain pre-existing debt (strict mypy: 1,032 errors in 30 files); no global-clean claim is made.

The first full run on `4305955` had 17 failures because the P5 environment contract test leaked
DeepSeek settings into later UI tests. Each failure passed alone; the exact two-test sequence
reproduced the leak. `a24fac5` wraps all 15 environment keys in a bounded restoration context; the
sequence then passed 4/4, the related suite 32/32, and the complete frozen regression passed. The
original failing XML remains preserved under `work/p5-final-regression/pytest.xml`.

## Production rehearsal

Production remains release `4ef50642...`, schema 25 and Qwen `qwen3.8-max`; no candidate or model
switch was made. A fresh verified backup captured all three databases and file stores and restored
successfully. Its disposable copy migrated 25→39 with unchanged old data. The actual old release
then started against a separate migrated copy with unchanged before/after fingerprints. The
monitor's backup permission defect was repaired without changing the serving release, and its final
result is healthy.

## Live-quality stop condition

Three bounded attempts were preserved. Attempt 1 made two unrelated Jev shadow calls then failed
the UI budget gate. Attempt 2 made one prototype Jev call and may have sent one unmetered DeepSeek
author request; its result and charge remain `UNKNOWN`. Attempt 3 was rejected before all
transports. No automatic retry or fourth paid attempt was made.

Because no READY revision exists, the human review card is necessarily empty. Deployment would
violate the required ordering `live model → human content → migration/rollback → release`; therefore
the correct final disposition is **release blocked at the live-quality gate, production unchanged**.

## Evidence index

- `docs/coursejesus/QUESTION_ENGINE_P5_LIVE_ACCEPTANCE.md`
- `docs/coursejesus/QUESTION_ENGINE_P5_HUMAN_REVIEW_CARD.md`
- `docs/coursejesus/QUESTION_ENGINE_P5_PRODUCTION_MIGRATION.md`
- `docs/coursejesus/QUESTION_ENGINE_P5_RECOVERY_AND_ROLLBACK.md`
- `docs/coursejesus/evidence/p5/live-attempt-summary.json`
- `docs/coursejesus/evidence/p5/production-rehearsal-summary.json`
- `docs/coursejesus/evidence/p5/local-verification-summary.json`
- `docs/coursejesus/evidence/p5/pytest-a24fac5-summary.xml`

To resume later, explicitly authorize/resume one new bounded real-model run. It must use a new
operation id linked to the unknown attempt and must complete C1–C5 before presenting the populated
review card to an authorized human. Only after that decision may a new final consistent backup and
production cutover begin.
