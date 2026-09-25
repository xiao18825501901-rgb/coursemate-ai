# Final CourseJesus Question Engine P5 production report

Date: 2026-09-25
Branch: `fix/codex-dsh-audit-20260919`
Frozen application candidate: `978e3f714ee9a1a39a34e1969c82615346a60f82`
Test-harness checkpoint: `c36782e69a51becd1fd690f782b0ae458115c987`
Production acceptance: **NOT YET ACCEPTED / CUTOVER AUTHORIZED**

P5 source correction, local regression and a bounded real DeepSeek/Jev C1-C5 workflow are complete.
The workflow produced exact READY revisions and all four required Jev gates returned real `on + ok`
receipts, and the Owner has approved the exact content manifest. Production is still unchanged
because no new candidate backup, migration, deployment or signed-in production acceptance has run
after that decision.

## Current status matrix

| Layer | Status | Evidence |
|---|---|---|
| `SOURCE_IMPLEMENTED` | **PASS** | canonical blueprint construction, zero-network preflight, durable transport ledger, explicit no-retry policy and completed-response recovery are committed in application `978e3f7` |
| `LOCAL_VERIFIED` | **PASS** | backend 1,854 pass + 2 platform skips; Web 117; Agent 92; typechecks and production-shaped builds pass |
| `LIVE_DEEPSEEK_QUESTION_ENGINE` | **PASS — BOUNDED SYNTHETIC C1-C5** | 21 completed transports, full response/usage persisted before parsing, zero automatic retry |
| `LIVE_JEV_BASE_SIGNALS` | **PASS** | ambiguity and answer-agreement receipts are real `on + ok + jev-latest` for the generated revisions |
| `LIVE_JEV_SPECIALIZED_SIGNALS` | **PASS** | real MCQ distractor-quality and rule-violation-quality receipts |
| `HUMAN_CONTENT_REVIEW` | **PASS** | Owner approved manifest `fc917044...3d7ad4` at `2026-09-25T11:26:39.9319867Z` |
| `PRODUCTION_SNAPSHOT_RESTORED` | **PASS — EARLIER REHEARSAL** | three-database/file snapshot restored in isolation with checksums, integrity and FK checks green |
| `MIGRATION38_RUNTIME_VERIFIED` | **PASS VIA TARGET SCHEMA 39 — EARLIER REHEARSAL** | actual schema-25 snapshot migrated through schema 39; old rows stayed unchanged |
| `ROLLBACK_RUNTIME_VERIFIED` | **PASS IN ISOLATION — EARLIER REHEARSAL** | old runtime served health against a disposable schema-39 copy without changing its fingerprint |
| `UNCERTAIN_OPERATION_RECOVERY` | **SOURCE + LOCAL PASS** | old UNKNOWN is immutable; same id was not retried; new ids and reconciliation links are durable |
| `PRODUCTION_DEPLOYED` | **NO** | the subsequent backup, migration and cutover gates are in progress |
| `SIGNED_IN_STUDENT_ACCEPTANCE` | **NOT RUN** | local synthetic identity is not production Clerk evidence |
| `POST_RELEASE_BACKUP_AND_MONITORING` | **NOT RUN** | no P5 release has occurred |
| `CAMPUS_EXPANSION_PAUSED` | **PASS / ENFORCED** | no Canvas roots were scanned and no withheld campus content was published |

## Three original attempts: corrected interpretation

1. Attempt `20260925T060137Z` was blocked locally by missing mounted-UI price inputs. DeepSeek sent
   zero requests; two unrelated Jev shadow calls had already happened. It was not a content-quality
   result.
2. Attempt `20260925T061320Z` may have sent one author request outside the durable ledger. Its
   outcome, usage and charge remain `UNKNOWN` under reconciliation SHA-256
   `8e0b9addcc61a837906866e5b67bdd581567cd37fafd4c2a5d76ad398766c70b`. It was not retried or
   rewritten and contains insufficient evidence for a quality judgment.
3. Attempt `20260925T063014Z` failed local `objective_text` blueprint validation before DeepSeek or
   Jev transport. It was a field-construction defect, not a model result.

Detailed paths, constructor sources and correction proof are in
`docs/coursejesus/P5_RECOVERY_ROOT_CAUSES.md`.

## New bounded live evidence

### C1/C2 practice

- Revisions: `qe_2b66a37d422649c3b0157c202bab0c49` and
  `qe_1fdf1412e5c34304bbf60678a771a36a`.
- Result: READY, answer hidden before reveal, bounded hint, independent and assisted feedback,
  detail, refresh restore and different-family re-practice completed.
- Transports: 8 DeepSeek and 4 Jev; 16,061 input + 3,922 output tokens; estimated USD `0.0095247`.
- A 512-character completed feedback response was rejected by the old 500-character local parser.
  Recovery id `p5-attempt-assisted-recovery-0002` reused that durably saved response from
  `p5-attempt-assisted-0001` with zero additional paid calls.

### C3-C5 assessment and rule path

- Assessment: `4f89fe55378d44109c12ae39c121ce4e`, frozen at 10/15/20/25/30 marks.
- Five assessment revisions:
  `qe_47e5e607352741fd9864f06867d52447`,
  `qe_e9a097b438224c9493e967817cee3b33`,
  `qe_aacc5203bc274e05892ced0a57d33328`,
  `qe_35925afc03994be2916edead4de31ffc`,
  `qe_3197bbfaa1744489b18ad69574fa52b9`.
- Rule revision: `qe_2fd0b9a365e8441c83859d544d335b8d`.
- Result: MCQ mapping and rule analysis stayed private; learner answers stayed hidden before submit;
  assessment freeze, submit, grade and database integrity checks passed.
- Transports: 13 DeepSeek and 14 Jev; 38,380 input + 11,677 output tokens; estimated USD
  `0.0255264`.

Across both new slices: 21 completed DeepSeek transports, 18 Jev calls, no automatic retry and
estimated new-workflow cost USD `0.0350511`. This does not settle the old UNKNOWN amount.

## Verification on the frozen application

- Backend: 1,854 passed, 2 platform skips, 0 failed. The skips cover Windows symlink privilege and
  POSIX permission-bit behaviour.
- Web: 117/117; Agent: 92/92; both TypeScript checks passed.
- Browser: refreshed shell 23/23; core 4/4; V3 learning 3/3; structured Jev offline 12/12 runnable
  with 5 intentional live-only skips.
- Production-shaped Web and Agent builds passed; the built Web scan found no token field and kept
  the required credential notice.
- The structured Jev suite first exposed a test-only 429: the host set `APP_ENV=test`, while the
  mounted UI extension reads `CMUI_ENV`. Test checkpoint `c36782e` added the missing isolated test
  variable and a 2-case guard. It changes no application runtime source or production rate limit.

## Current production reality

Last verified production remains immutable release `4ef5064`, Qwen `qwen3.8-max`, schema 25. The
new CourseJesus P5 application is not deployed, production databases were not migrated during this
recovery, and no production model/provider switch was made. The earlier backup/migration/rollback
rehearsal is reusable evidence, but it does not replace a fresh consistent cutover backup after
Owner review.

## Human review gate

Private content is deliberately not committed. The exact card is:

`D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY\work\p5-owner-review-20260925T103415Z\OWNER_REVIEW_CARD_PRIVATE.md`

- Review-card SHA-256: `0335ba2079a5f046c584947c4c6d38091aafed04ec7a43723746aa5ad0dcb862`
- Manifest SHA-256: `fc91704466ef1b1082d7833dc9965e9a587d462da89cdd88118b18a4993d7ad4`
- Current decision: **PASS**

The Owner signed this exact bundle PASS. The authorized sequence is now: fresh consistent backup →
restore verification → schema migration → immutable backend/front-end deployment → real Clerk
student flows → two-user isolation → post-release backup and monitoring.

## Evidence index

- `P5_RELEASE_LEDGER.md`
- `docs/coursejesus/P5_RECOVERY_ROOT_CAUSES.md`
- `docs/coursejesus/QUESTION_ENGINE_P5_LIVE_ACCEPTANCE.md`
- `docs/coursejesus/QUESTION_ENGINE_P5_HUMAN_REVIEW_CARD.md`
- `docs/coursejesus/QUESTION_ENGINE_P5_PRODUCTION_MIGRATION.md`
- `docs/coursejesus/QUESTION_ENGINE_P5_RECOVERY_AND_ROLLBACK.md`
- `docs/coursejesus/evidence/p5/live-attempt-summary.json`
- `docs/coursejesus/evidence/p5/recovery-local-verification.json`
- `docs/coursejesus/evidence/p5/production-rehearsal-summary.json`

The accurate disposition at this checkpoint is: **bounded live-model and human content acceptance
passed; production cutover authorized but not yet accepted**.
