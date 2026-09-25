# Final CourseJesus Question Engine P5 production report

Date: 2026-09-25
Branch: `fix/codex-dsh-audit-20260919`
Frozen application candidate: `978e3f714ee9a1a39a34e1969c82615346a60f82`
Test-harness checkpoint: `c36782e69a51becd1fd690f782b0ae458115c987`
Deployment source/document checkpoint: `e0980c81050c90ec91ba981bdbec8f2111f60fd1`
Production acceptance: **PASS WITH RECORDED LIMITATIONS**

P5 source correction, local regression and a bounded real DeepSeek/Jev C1-C5 workflow are complete.
The workflow produced exact READY revisions and all four required Jev gates returned real `on + ok`
receipts. The Owner approved the exact content manifest, the matched backend and frontend were
deployed, real Clerk sessions completed the two-user acceptance, and a post-release recovery unit
was restored in isolation. Two strict blind-solver schema failures and the assessment preparation
state described below remain visible rather than being rewritten as success.

## Current status matrix

| Layer | Status | Evidence |
|---|---|---|
| `SOURCE_IMPLEMENTED` | **PASS** | canonical blueprint construction, zero-network preflight, durable transport ledger, explicit no-retry policy and completed-response recovery are committed in application `978e3f7` |
| `LOCAL_VERIFIED` | **PASS** | backend 1,854 pass + 2 platform skips; Web 117; Agent 92; typechecks and production-shaped builds pass |
| `LIVE_DEEPSEEK_QUESTION_ENGINE` | **PASS — BOUNDED SYNTHETIC C1-C5** | 21 completed transports, full response/usage persisted before parsing, zero automatic retry |
| `LIVE_JEV_BASE_SIGNALS` | **PASS** | ambiguity and answer-agreement receipts are real `on + ok + jev-latest` for the generated revisions |
| `LIVE_JEV_SPECIALIZED_SIGNALS` | **PASS** | real MCQ distractor-quality and rule-violation-quality receipts |
| `HUMAN_CONTENT_REVIEW` | **PASS** | Owner approved manifest `fc917044...3d7ad4` at `2026-09-25T11:26:39.9319867Z` |
| `PRODUCTION_SNAPSHOT_RESTORED` | **PASS** | drained cutover backup and post-release backup were each restored in isolation; checksums, SQLite integrity and FK checks are green |
| `MIGRATION38_RUNTIME_VERIFIED` | **PASS VIA TARGET SCHEMA 39** | live RAG/UI/Agent schemas are 39/14/1; restored post-release copies match |
| `ROLLBACK_RUNTIME_VERIFIED` | **PASS IN ISOLATION — EARLIER REHEARSAL** | old runtime served health against a disposable schema-39 copy without changing its fingerprint |
| `UNCERTAIN_OPERATION_RECOVERY` | **SOURCE + LOCAL PASS** | old UNKNOWN is immutable; same id was not retried; new ids and reconciliation links are durable |
| `PRODUCTION_DEPLOYED` | **PASS** | backend source `e0980c8`, Netlify deploy `6ab6650875f30b0bb26558f0`, DeepSeek and the four approved Jev gates are serving |
| `SIGNED_IN_STUDENT_ACCEPTANCE` | **PASS** | two real Clerk users proved qualification, CS3481 access, private-file isolation and learning-state isolation; synthetic users were then deleted upstream and marked inactive locally |
| `POST_RELEASE_BACKUP_AND_MONITORING` | **PASS** | backup `coursemate-v2-20260925T130253.544550Z` restored to a new directory; HTTPS monitor and Singapore relay checks passed |
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

Production now serves immutable backend source `e0980c81050c90ec91ba981bdbec8f2111f60fd1`
from `/srv/coursemate/releases/e0980c8` and frontend deploy
`6ab6650875f30b0bb26558f0`. RAG/UI/Agent schemas are `39/14/1`; the active model is
`deepseek-flash` at `api.deepseek.com`. Exactly the four reviewed Question Engine Jev definitions
are `on`; the other 19 definitions remain `off`.

The frontend is `https://qqttai.com/`. Because the original API hostnames are intercepted at the
mainland ICP boundary, production currently uses the controlled Singapore TLS relay
`rag.47-237-179-69.sslip.io` and `agent.47-237-179-69.sslip.io`, backed by a restricted pinned-key
SSH tunnel to the Hangzhou loopback services. Caddy, the tunnel and both application services are
active; public health, unauthenticated 401 and allowed-origin CORS checks passed.

## Human review gate

Private content is deliberately not committed. The exact card is:

`D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY\work\p5-owner-review-20260925T103415Z\OWNER_REVIEW_CARD_PRIVATE.md`

- Review-card SHA-256: `0335ba2079a5f046c584947c4c6d38091aafed04ec7a43723746aa5ad0dcb862`
- Manifest SHA-256: `fc91704466ef1b1082d7833dc9965e9a587d462da89cdd88118b18a4993d7ad4`
- Current decision: **PASS**

The Owner signed this exact bundle PASS. The authorized sequence has completed: fresh consistent
backup → restore verification → schema migration → immutable backend/front-end deployment → real
Clerk student flows → two-user isolation → post-release backup and monitoring.

## Production acceptance and recorded limitations

- A new production exercise completed as `exercise.v2+question-engine.v1`; the answer stayed hidden
  before reveal, four steps rendered, independent explanation completed, and unified history
  survived reload.
- The first production generation is a durable known failure: the blind solver returned a paid
  complete response that failed strict schema validation. A new operation ID, explicitly linked to
  that failure, succeeded on an earlier live-validated atomic node. No implicit paid retry occurred.
- Assessment preparation persisted four new slots, then a fifth blind-solver response failed strict
  validation. The job correctly remains `BLOCKED`. Five distinct immutable READY families were
  nevertheless available, so a model-free start created a real five-question session with
  10/15/20/25/30 marks and a persisted draft. The current UI does not automatically recover this
  specific `BLOCKED + sufficient pool` state; this is a recorded non-blocking product limitation.
- Production acceptance used 14 DeepSeek calls and 11 Jev receipts. It recorded 47,330 input and
  17,460 output tokens with estimated cost USD `0.0383397`. Together with the pre-production
  bounded workflow, recorded P5 cost is approximately USD `0.0733908`; the historical Attempt 2
  UNKNOWN amount is excluded and remains UNKNOWN.
- Light theme, persisted dark theme, the dual pane, four steps, independent explanation window and
  five-question assessment were rendered in the production browser with zero console errors.
- The post-release recovery unit is
  `/srv/coursemate/backups/post-e0980c8-p5-20260925/coursemate-v2-20260925T130253.544550Z`.
  Manifest SHA-256 is `1aa1a71e890f1ef9b7582c49dc78c0ea524d2e3449791859bd8b48285f584fa9`;
  its isolated restored databases are schema 39/14/1, integrity `ok`, FK 0.

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
- `docs/coursejesus/evidence/p5/production-cutover-summary.json`

The accurate disposition at this checkpoint is: **production deployed and accepted with the two
strict model-output limitations above retained as evidence, not hidden or retried**.
