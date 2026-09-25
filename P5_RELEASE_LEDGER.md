# CourseJesus P5 release ledger

Updated: 2026-09-25
Branch: `fix/codex-dsh-audit-20260919`
Frozen application candidate: `978e3f714ee9a1a39a34e1969c82615346a60f82`
Test-harness checkpoint: `c36782e69a51becd1fd690f782b0ae458115c987`

P5 started from P4 application `df8694b0b4d97347f1c75baaca70c7e725e94a6e`. It added
metered practice roles, uncertain-operation reconciliation, migration 039, strict release recovery
metadata and bounded live runners. Local acceptance and the bounded real-model C1-C5 workflow are
green. Exact review material exists; Owner human review and production release remain open.

## Items

| Item | Existing evidence | Current gap | Next action | Close condition |
|---|---|---|---|---|
| Frozen candidate | Current application `978e3f7`; backend 1,854 + 2 platform skips, Web 117 and Agent 92 green; TypeScript green; production-shaped local build and PAT scan green | no source-level blocker known; `c36782e` is test-harness-only | preserve exact application SHA separately from the test/document HEAD | exact candidate remains reproducible |
| Four Jev gates | ambiguity, answer agreement, MCQ distractor quality and rule-violation definitions each have real `on + ok + jev-latest` receipts | human judgment is still independent | do not rerun; retain exact receipts and input hashes | **closed for bounded live workflow** |
| C1–C5 live Question Engine | exact C1/C2 revisions, five-slot C5 assessment and C4 revision completed; 21 DeepSeek + 18 Jev real transports; zero automatic retry | production has not run these exact journeys | hold for Owner review, then deploy only this reviewed candidate | **closed for bounded live workflow** |
| Human review | Owner PASS recorded at `2026-09-25T11:26:39.9319867Z` against private 1,080-line card and manifest SHA `fc917044...3d7ad4` | none | retain the signed decision and proceed through production gates | **closed** |
| Unknown paid result | reconciliation `8e0b9add...6c70b`; corrective metering and replay refusal tests | provider offers no proven query result for the possible call | retain UNKNOWN and never reuse old id | provider evidence reconciles it, or UNKNOWN remains permanently explicit |
| Recovery unit | fresh backup manifest `2b3f0f...f4b63`; release descriptor `af57a54a...c870c`; isolated restore green | no final post-quality cutover backup | take a new drained final backup only after quality gates pass | final backup is restored once and coupled to exact release/deploy/config |
| Schema migration | actual production schema 25 copy migrated through 39; old rows unchanged; integrity/FK/invariants green | no production migration was run | repeat against final drained backup at cutover | live migration and matched single-instance startup pass |
| Old-runtime rollback | actual release `4ef5064` started against disposable schema-39 copy; before/after fingerprint identical | not every new P5 feature is available under old config | retain degraded-feature warning | old runtime/schema compatibility remains verified and rollback plan protects new writes |
| Production release | last verified serving release remains `4ef5064`, Qwen and schema 25; Owner review now passed | fresh backup/migration and production journeys remain | execute the authorized controlled cutover | all preceding gates plus signed-in production journeys pass |
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
| `LIVE_DEEPSEEK_QUESTION_ENGINE` | **PASS — BOUNDED SYNTHETIC C1-C5** |
| `LIVE_JEV_BASE_SIGNALS` | **PASS — REAL ON RECEIPTS** |
| `LIVE_JEV_SPECIALIZED_SIGNALS` | **PASS — REAL MCQ + RULE RECEIPTS** |
| `HUMAN_CONTENT_REVIEW` | **PASS — OWNER-SIGNED MANIFEST** |
| `PRODUCTION_SNAPSHOT_RESTORED` | **PASS** |
| `MIGRATION38_RUNTIME_VERIFIED` | **PASS VIA TARGET SCHEMA 39** |
| `ROLLBACK_RUNTIME_VERIFIED` | **PASS IN ISOLATION** |
| `UNCERTAIN_OPERATION_RECOVERY` | **SOURCE + LOCAL PASS** |
| `PRODUCTION_DEPLOYED` | **NO** |
| `SIGNED_IN_STUDENT_ACCEPTANCE` | **NOT RUN** |
| `POST_RELEASE_BACKUP_AND_MONITORING` | **NOT RUN** (pre-release backup/monitor pass) |
| `CAMPUS_EXPANSION_PAUSED` | **PASS / ENFORCED** |

Primary report: `FINAL_COURSEJESUS_QUESTION_ENGINE_PRODUCTION_REPORT.md`.
