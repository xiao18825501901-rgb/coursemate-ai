# CourseJesus P5 release ledger

Updated: 2026-09-25
Branch: `fix/codex-dsh-audit-20260919`
Frozen application candidate: `978e3f714ee9a1a39a34e1969c82615346a60f82`
Test-harness checkpoint: `c36782e69a51becd1fd690f782b0ae458115c987`
Deployment source/document checkpoint: `e0980c81050c90ec91ba981bdbec8f2111f60fd1`

P5 started from P4 application `df8694b0b4d97347f1c75baaca70c7e725e94a6e`. It added
metered practice roles, uncertain-operation reconciliation, migration 039, strict release recovery
metadata and bounded live runners. Local acceptance and the bounded real-model C1-C5 workflow are
green. The Owner-approved production release and signed-in acceptance are complete. Known strict
model-output failures and the old UNKNOWN remain separately recorded.

## Items

| Item | Existing evidence | Current gap | Next action | Close condition |
|---|---|---|---|---|
| Frozen candidate | Current application `978e3f7`; backend 1,854 + 2 platform skips, Web 117 and Agent 92 green; TypeScript green; production-shaped local build and PAT scan green | no source-level blocker known; `c36782e` is test-harness-only | preserve exact application SHA separately from the test/document HEAD | exact candidate remains reproducible |
| Four Jev gates | ambiguity, answer agreement, MCQ distractor quality and rule-violation definitions each have real `on + ok + jev-latest` receipts | human judgment is still independent | do not rerun; retain exact receipts and input hashes | **closed for bounded live workflow** |
| C1–C5 live Question Engine | exact C1/C2 revisions, five-slot C5 assessment and C4 revision completed; 21 DeepSeek + 18 Jev real transports; zero automatic retry | production has not run these exact journeys | hold for Owner review, then deploy only this reviewed candidate | **closed for bounded live workflow** |
| Human review | Owner PASS recorded at `2026-09-25T11:26:39.9319867Z` against private 1,080-line card and manifest SHA `fc917044...3d7ad4` | none | retain the signed decision and proceed through production gates | **closed** |
| Unknown paid result | reconciliation `8e0b9add...6c70b`; corrective metering and replay refusal tests | provider offers no proven query result for the possible call | retain UNKNOWN and never reuse old id | provider evidence reconciles it, or UNKNOWN remains permanently explicit |
| Recovery unit | pre-cutover manifest `5060f48a...e135`; post-release manifest `1aa1a71e...4fa9`; descriptor `5844bc3a...4c73`; both isolation restores green | none | retain checksums and test restores; credentials remain external | **closed** |
| Schema migration | production RAG/UI/Agent migrated and serving at 39/14/1; restored post-release copies match with integrity ok/FK 0 | none | preserve migration and backup evidence | **closed** |
| Old-runtime rollback | actual release `4ef5064` started against disposable schema-39 copy; before/after fingerprint identical | not every new P5 feature is available under old config | retain degraded-feature warning | old runtime/schema compatibility remains verified and rollback plan protects new writes |
| Production release | backend `e0980c8`, frontend `6ab6650875f30b0bb26558f0`, DeepSeek and four approved Jev gates serve production; two real Clerk users passed isolation and learning journeys | assessment preparation UI does not auto-recover `BLOCKED + sufficient READY pool`; two strict blind-solver failures are retained | monitor; fix the recovery UX in a future reviewed application release | **closed with recorded non-blocking limitations** |
| Campus expansion | frozen 1,921-file batch, growth fail-closed, zero published | 1,715 rights decisions pending | keep paused; no rescans | withheld content remains unpublished |

## Current production reality

- `https://qqttai.com/` serves frontend deploy `6ab6650875f30b0bb26558f0` built from `e0980c8`.
- Hangzhou serves immutable backend release `/srv/coursemate/releases/e0980c8`; RAG and Agent are
  active. Singapore Caddy and the pinned-key restricted tunnel provide the temporary HTTPS API
  ingress while the original names remain subject to the ICP boundary.
- Production uses `deepseek-flash`; four reviewed Jev definitions are `on`, all other definitions
  are `off`.
- Databases serve schema 39/14/1. Post-release backup and isolated restore are verified.

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
| `PRODUCTION_DEPLOYED` | **PASS** |
| `SIGNED_IN_STUDENT_ACCEPTANCE` | **PASS — TWO REAL CLERK USERS, THEN CLEANED UP** |
| `POST_RELEASE_BACKUP_AND_MONITORING` | **PASS** |
| `CAMPUS_EXPANSION_PAUSED` | **PASS / ENFORCED** |

Primary report: `FINAL_COURSEJESUS_QUESTION_ENGINE_PRODUCTION_REPORT.md`.
