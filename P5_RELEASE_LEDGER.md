# CourseJesus P5 release ledger

Updated: 2026-09-25
Branch: `fix/codex-dsh-audit-20260919`
Frozen application candidate: `a24fac535eda85358965f516964df0c40510e7a0`

P5 started from P4 application `df8694b0b4d97347f1c75baaca70c7e725e94a6e`. It added
metered practice roles, uncertain-operation reconciliation, migration 039, strict release recovery
metadata and a bounded live runner. Local acceptance and production recovery rehearsal are green;
live content quality and human review are not.

## Items

| Item | Existing evidence | Current gap | Next action | Close condition |
|---|---|---|---|---|
| Frozen candidate | Full regression at `a24fac5`: 1838 pass, 2 environmental skips, 0 fail; Web 115; Agent 92; five browser suites green | none for source/local level | preserve exact SHA and versioned evidence | exact candidate remains reproducible |
| Four Jev gates | source/offline contracts require ambiguity=`CLEAR`, agreement=`AGREE`, MCQ=`ACCEPTABLE`, rule=`SUPPORTED` | no required live positive receipts | only after explicit real-model resumption, run one new bounded linked attempt | exact durable `on` receipts match each revision/input |
| C1–C5 live Question Engine | bounded real runner and three immutable attempt records | no live READY revision; one possible DeepSeek call has unknown charge | new operation id linked to unknown predecessor; no automatic retry | live author→blind→hard gates→Jev→READY plus C2/C5 journeys pass |
| Human review | empty protected review card exists | no reviewable live content | populate only from successful exact revisions | authorized human signs exact card/revision hashes |
| Unknown paid result | reconciliation `8e0b9add...6c70b`; corrective metering and replay refusal tests | provider offers no proven query result for the possible call | retain UNKNOWN and never reuse old id | provider evidence reconciles it, or UNKNOWN remains permanently explicit |
| Recovery unit | fresh backup manifest `2b3f0f...f4b63`; release descriptor `af57a54a...c870c`; isolated restore green | no final post-quality cutover backup | take a new drained final backup only after quality gates pass | final backup is restored once and coupled to exact release/deploy/config |
| Schema migration | actual production schema 25 copy migrated through 39; old rows unchanged; integrity/FK/invariants green | no production migration was run | repeat against final drained backup at cutover | live migration and matched single-instance startup pass |
| Old-runtime rollback | actual release `4ef5064` started against disposable schema-39 copy; before/after fingerprint identical | not every new P5 feature is available under old config | retain degraded-feature warning | old runtime/schema compatibility remains verified and rollback plan protects new writes |
| Production release | serving release remains `4ef5064`, Qwen and schema 25; monitor healthy after backup permission repair | live model and human gates not passed | do not deploy | all preceding gates plus signed-in production journeys pass |
| Campus expansion | frozen 1,921-file batch, growth fail-closed, zero published | 1,715 rights decisions pending | keep paused; no rescans | withheld content remains unpublished |

## Current production reality

- `qqttai.com` is the observed older CourseMate site; the CourseJesus domain was not a usable
  deployed service.
- `coursemate-prod-new` (`47.114.34.175`) serves immutable release `4ef5064`; RAG, Agent and nginx
  are active.
- Production uses Qwen `qwen3.8-max`; required Jev production modes and a TypeSafe credential were
  not present. A frontend/model-name edit alone cannot satisfy P5.
- Databases remain production schema 25/13/1. No live migration or release switch occurred.

## Status boundary

| Layer | Status |
|---|---|
| `SOURCE_IMPLEMENTED` | **PASS** |
| `LOCAL_VERIFIED` | **PASS** |
| `LIVE_DEEPSEEK_QUESTION_ENGINE` | **NOT PASSED** |
| `LIVE_JEV_BASE_SIGNALS` | **PARTIAL / NOT ACCEPTED** |
| `LIVE_JEV_SPECIALIZED_SIGNALS` | **NOT VERIFIED** |
| `HUMAN_CONTENT_REVIEW` | **PENDING / EMPTY** |
| `PRODUCTION_SNAPSHOT_RESTORED` | **PASS** |
| `MIGRATION38_RUNTIME_VERIFIED` | **PASS VIA TARGET SCHEMA 39** |
| `ROLLBACK_RUNTIME_VERIFIED` | **PASS IN ISOLATION** |
| `UNCERTAIN_OPERATION_RECOVERY` | **SOURCE + LOCAL PASS** |
| `PRODUCTION_DEPLOYED` | **NO** |
| `SIGNED_IN_STUDENT_ACCEPTANCE` | **NOT RUN** |
| `POST_RELEASE_BACKUP_AND_MONITORING` | **NOT RUN** (pre-release backup/monitor pass) |
| `CAMPUS_EXPANSION_PAUSED` | **PASS / ENFORCED** |

Primary report: `FINAL_COURSEJESUS_QUESTION_ENGINE_PRODUCTION_REPORT.md`.
