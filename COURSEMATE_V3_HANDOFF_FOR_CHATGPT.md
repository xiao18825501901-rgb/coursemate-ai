# CourseMate V3 — Final Engineering Handoff for ChatGPT

更新时间：2026-09-12

用途：把当前 CourseMate V3 本地 Release Candidate 交给下一位 ChatGPT/项目 Owner，继续完成真实模型、完整恢复和生产验收。
结论：**SOURCE / LOCAL RELEASE CANDIDATE；不是 LIVE MODEL VERIFIED，也不是 PRODUCTION ACCEPTED。**

## 1. 先读结论，不要继承错误的 PASS

```text
Repository root:
C:/Users/Hp/Documents/Codex/2026-08-11/files-mentioned-by-the-user-coursemate/outputs/coursemate-ai

Branch:
feature/coursemate-v3-persistent-learning

Stage 8 implementation baseline:
7c6c54cdf479ceddaf308f41df786a98540a6900

V3 migration head in source:
21

Active local RAG database:
versions 1–18; integrity ok; FK violations 0; unchanged by Stage 8 rehearsal

SOURCE_IMPLEMENTED:
PARTIAL — the recorded Stage 1–8 slices exist; residual product gaps are listed below

LOCAL_CONTRACT_VERIFIED:
PASS for the recorded deterministic scope

LOCAL_FAKE_PROVIDER_VERIFIED:
PASS for the recorded browser/API scope

REAL-CURRENT-RAG-DATA COPY MIGRATION:
PASS — isolated 1–18 → 1–21, source unchanged

COMPLETE CURRENT RAG + AGENT DB + UPLOADS RESTORE:
BLOCKED / NOT VERIFIED — authoritative Agent DB path is absent/unknown

LIVE_MODEL_VERIFIED:
NOT VERIFIED — no billable call or account access

PRODUCTION_VERIFIED:
NOT VERIFIED — no production access, migration, deploy or smoke
```

Owner 原有未跟踪文件 `ACTUAL_IMPLEMENTED_CHANGES_AUDIT.md` 与 `curl` 不是本次产物。它们始终未修改、未暂存；后续也不得用 `git add .` 把它们带入提交。

## 2. 生产现实校准

### Last verified production state

只有历史报告在各自日期记录过线上状态；它们不能证明 2026-09-12 当前运行状态。仓库没有本轮可核验的服务器、Netlify、Clerk、Alibaba Cloud 或生产数据库会话。

### Current V3 source intent

- V3 主智能模型固定为 `qwen3.8-max`；Embedding 独立配置。
- FastAPI RAG/learning 服务持有学习事实、权限、事务和迁移。
- Node Task Agent 只持有 Todo 工具职责，不写学习进度或成绩。
- `V3_ENABLED=false` 与 `VITE_V3_ENABLED=false` 是默认安全状态。
- Source 迁移为 1–21；V2 flag-off 只要求 1–10。

### Current deploy-template intent

部署模板表达 V3/Task Agent 使用 `qwen3.8-max`、手工 secret endpoint、默认关闭 V3 的意图；V2 RAG 角色仍保留旧模型配置。模板不是当前生产 Provider、地域、版本或 flag 的证明。

### Unknown current runtime facts

以下全部为 `UNKNOWN — REQUIRES OWNER/RUNTIME VERIFICATION`：

- 线上前后端 release SHA 与运行目录；
- Alibaba Cloud 实际账号、workspace、region、endpoint、模型权限、余额、配额和现价；
- Netlify site/deploy SHA、API origin、环境变量；
- Clerk instance、authorized origins、测试身份和 Admin role mapping；
- 生产 RAG DB、Agent DB、uploads 的真实绝对路径、Schema、WAL、备份健康度；
- 线上错误率、p50/p95、磁盘、备份年龄、Provider 使用量；
- 生产是否仍运行历史 OpenAI/V2 版本。

不要从 README、环境变量名、`render.yaml` 或旧报告补全这些事实。

## 3. 当前架构与事实所有者

```text
React Web
  ├─ V2 QA / citations / history / private courses / Task board
  └─ V3 LearningPage: Knowledge + Teaching + Problem + Assessment + Overlay review
          │ authenticated HTTP
          ▼
FastAPI RAG + Learning service  ← authoritative user×course learning writer
  ├─ workspace/private source ACL and retrieval
  ├─ canonical/private trees and dual-axis projections
  ├─ Planner → major Compiler → bounded Teacher
  ├─ Problem/SolutionRevision/StepKnowledgeLink/LearningBridge
  ├─ Assessment/PerformanceEvidence/GradeSnapshot
  ├─ immutable publication snapshots and releases
  └─ model-call reservation before Provider I/O
          │ explicit compatible endpoint; zero SDK retry
          ▼
qwen3.8-max target (account/live behavior still unverified)

Node Task Agent
  └─ Todo tools + independent per-minute/per-day limits; no learning-grade authority
```

Learning Progress 和 Assessment Grade 是两条独立轴。`LEARNED` 只由当前固定 Teaching Spec 中所有 `REQUIRED` items 的有效交付覆盖决定；低分、未测或 PRACTICE 不会把它改回去，也不能把测评通过当作 LEARNED。

## 4. 已实现的主要能力

### Data and privacy

- 官方课程内的新上传默认进入 owner×course 私人 workspace/private course；原件、版本、派生物、chunks、引用均保持 owner/course/source-version provenance。
- 资料联合检索范围为公开官方资料 + 当前 Owner 私人资料；其他用户资料和普通 Admin 私人浏览被拒绝。
- 文本、CSV、静态 Notebook、PDF、图片和 Office fallback 有明确预览/下载策略；不执行 Notebook，不伪造 Office 预览。
- `DocumentVersion` 与 `DerivedArtifact` 不覆盖原件；删除/撤权后的历史只保留最小审计信息。

### Knowledge and teaching

- Course-scoped canonical Registry、ATOMIC/COMPOSITE、TreeVersion、Membership 与 prerequisite DAG 已持久化。
- 官方树必须经独立审核发布；个人树引用规范/私人节点与同一学习状态，不复制成绩。
- `services/rag-api/app/learning/prompts/v3.2/` 已进入真实调用链：Planner、Common Teaching Contract、四专业策略、CASE_A/CASE_B、Problem Solver、Assessment Grader。
- TeachingPlan 缓存键包含 Owner/workspace/course/node/Spec/preferences/model/protocol/policy/source versions/Bridge revision；只有定义好的变化或显式 replan 才重建。
- Provider 输出是提议；Pydantic/compiler 校验通过后才允许后端提交事实。

### Problem, Bridge and persistence

- Problem Mode 默认返回完整参考答案、条件、步骤、公式/单位/检查/错点/来源和显式模型免责声明。
- 每个 Step 的 `StepKnowledgeLink` 绑定精确 node/spec/item；无法验证的 legacy/unresolved link 不产生覆盖。
- `LearningBridge` 显式固定 Problem、SolutionRevision、Step、node、Teaching journey、context 与 return anchor。
- 已验证 Problem-first 和 Knowledge-first 两条路径；刷新、新 browser context 后仍能恢复到原题原 Step。

### Assessment and long-term state

- 默认冻结 Blueprint 恰好 5 题，分值 10/15/20/25/30，总分 100；不是等权。
- 题源支持官方、本人私人、已验证生成与外部启发原创，并执行 source diversity、owner ACL、答案暴露 family 排除。
- 正式 Assessment 提交前不下发答案/rubric；查看帮助会降为 PRACTICE，不产生独立能力证据。
- 每个 rubric criterion 产生细粒度 `PerformanceEvidence`；弱项只建立 pending replan trigger，用户显式继续时才触发 Planner。
- GradePolicy 缺失的 A- 数值和百分比分界保留 null/empty；raw score 可用，但 letter/numeric 显示 mapping pending，不能冒充 CityU 官方 GPA。

### Publication, cost and operations

- Course、official tree/Spec/derived resources、private Overlay 使用不同的精确不可变审核快照。
- Admin 只能看被 Owner 明确选中并同意的 Overlay 版本；未选私人文件、聊天和 workspace 不进入通用 Admin 视图。
- migration 021 在每次 Provider 调用前原子预留 owner/day 与 owner×course/day 配额；UNKNOWN/FAILED 也 fail-closed 占位，明确本地配置 `BLOCKED` 不冒充付费调用。
- V3 canary 固定 8 个合成专业/场景、合成图、Model Studio endpoint allowlist、费用/调用上限、零重试和逐次 checkpoint；自动绿灯仍是 `PENDING_HUMAN_QUALITY_REVIEW`。

## 5. Schema 和关键代码入口

| 主题 | 真实入口 |
|---|---|
| feature flag / endpoints / quotas | `services/rag-api/app/config.py`, `services/agent-api/src/config.ts` |
| migration activation/readiness | `services/rag-api/app/db.py` |
| workspace ACL and files | `services/rag-api/app/learning/workspaces.py`, `uploads.py`, `previews.py` |
| knowledge trees and progress | `services/rag-api/app/learning/knowledge.py` |
| prompt compiler/provider | `services/rag-api/app/learning/compiler.py`, `provider.py`, `prompts/v3.2/` |
| shared orchestration/plans | `services/rag-api/app/learning/orchestrator.py`, `plans.py` |
| Problem and Bridge | `services/rag-api/app/learning/problems.py` |
| Assessment/GradePolicy | `services/rag-api/app/learning/assessments.py` |
| publication snapshots/workflows | `services/rag-api/app/services/publication_snapshots.py`, `knowledge_publication.py`, `overlay_publication.py` |
| HTTP APIs | `services/rag-api/app/api/learning.py`, `api/publication.py` |
| V3 Web | `apps/web/src/pages/LearningPage.tsx`, `KnowledgeTrees.tsx`, `AssessmentPanel.tsx`, `OverlayPublicationPanel.tsx` |
| Task Agent | `services/agent-api/src/services/agent.ts`, `rate-limit.ts`, `tools/` |
| migration/canary/backup | `scripts/rehearse_v3_migration.py`, `scripts/run_v3_model_canary.py`, `ops/backup_v2.py`, `ops/restore_v2.py` |

Migrations:

```text
011 workspace/private corpus
012 journey/problem/bridge/operation base
013 immutable document versions/artifacts/chunk provenance
014 Registry, Specs, official/personal trees, prerequisite graph
015 preferences, TeachingPlan, delivery and model evidence
016 Problem/Solution revisions, attempts, normalized Step/Bridge context
017 Assessment/rubric/blueprint/session/performance/replan
018 GradePolicy bindings and immutable GradeSnapshot
019 scoped immutable publication review snapshots/releases/audit
020 pending/approved resource locks and private snapshot lifecycle
021 atomic daily model-call reservations and legacy evidence backfill
```

已执行过的迁移不能删除、重编号或改写；后续修正只能使用 022+ 前向迁移。

## 6. Stage 8 最终验证证据

实现基线 `7c6c54c`：

```text
Python pytest:
327 passed, 1 known Starlette/httpx deprecation warning, 125.93s

Ruff:
All checks passed

mypy:
Success, no issues in 63 source files

Web Vitest:
12 files / 49 tests passed

Task Agent Vitest:
10 files / 66 tests passed

TypeScript:
both workspaces typecheck passed

Production build:
passed; Web 118 modules; JS 310.12 kB (gzip 90.85 kB)

V3 Playwright:
3 passed, 46.0s

V2 Playwright:
4 passed, 30.1s

npm audit --json:
0 vulnerabilities

npm audit --omit=dev --json:
0 vulnerabilities
```

V3 Browser 具体证明：

1. 私人合成图片 → 完整解法 → Step 问题 → Teaching coverage → LEARNED → 新 browser context 回到同一 Step；
2. Knowledge tree → text Problem → Step 问题 → Teaching → LEARNED → 同一 Step；
3. Owner、第二位学生和 Admin 共享一个合成测试 DB：第二位学生看不到 Owner node/file，Admin 不能直接访问 workspace，只能看到 Owner 明确提交的 node snapshot；
4. 375px 无横向溢出，桌面/移动截图已目检；可见控件有名称，Tab 可离开 BODY。

这不是完整 WCAG、真实 Clerk、真实 Provider 或生产并发证明。

## 7. 真实数据副本迁移与恢复边界

`work/v3-migration-rehearsal-stage8-20260912-01/` 是包含本地私人数据的忽略目录，不得提交、上传或把原始 JSON/DB 贴给 ChatGPT。可分享的聚合结论：

```text
source: active local data/rag.sqlite3, versions 1–18
target: isolated online-backup copy, versions 1–21
old_rows_unchanged=true
integrity=ok
foreign_key_violations=0
v3_invariants_ok=true
documents/document_versions=69/69
unbound_chunks=0
model evidence/reservations=6/6
missing required 019–021 schema objects=[]
```

活动源库保持版本 1–18，SHA-256：

```text
48852f977ebf37b1a9b77df1a03e5d3549bebc71ec77401673ba60f5bd6d906b
```

活动 uploads 为 70 files / 124,209,888 bytes；固定算法摘要：

```text
008ae984d98b4248f970eb53a351cea9068e6f6fbaabb784387e97f75ab07b23
```

算法：按 relative POSIX path 逐字排序；每行 `path|size|sha256lower`；LF、无末尾换行；UTF-8 SHA-256。

完整恢复仍未通过，因为 `data/agent.sqlite3` 不存在，且本任务可访问的 repository/runtime 证据不能把 `work/` 中任何 smoke/E2E DB 认定为真实 Agent DB。备份脚本用明确缺失路径运行时安全返回 exit 2，且未创建 backup root。下一位执行者必须：

1. 在当前实际 runtime 查出 Agent DB 绝对路径，或用当前服务配置证明 Agent 无持久 DB；
2. 不能创建 dummy DB 来获取绿灯；
3. drain writers；
4. 使用 `ops/backup_v2.py` 同一 recovery unit 捕获两 DB + uploads；
5. 校验 manifest/SHA/integrity/FK；
6. 用 `ops/restore_v2.py` 恢复到全新隔离目录；
7. 只对恢复目录启动实例，跑 V2 flag-off + V3 owner smoke；
8. 未通过前不得迁移/切换生产。

## 8. 仍然存在的源码/产品缺口

这些项目没有被本地绿灯掩盖：

- `AUTO` 语义路由和用户可解释原因尚未完成；
- Teaching pause UI/完整恢复交互仍不完整；
- Problem delivery 直接计入可靠 coverage 的完整政策尚未实现；
- 官方 source tree 草稿 author/import UI 尚未完成；
- 正式 Assessment question author/reviewer UI 尚未完成；
- COMPOSITE 节点综合考试执行尚未完成；
- `NEEDS_REVIEW` 人工终审流程尚未完成；
- public citation provenance/lifecycle 的更广 API 硬化尚未完成；
- 删除后物理对象 outbox/retry 与生产存储/Office converter 尚未实现/验证；
- per-reviewer expiring publication assignment 尚未实现；
- 完整 screen-reader、axe、color contrast、320px 与 race audit 尚未完成；
- GradePolicy 的 A- 数值/百分比分界仍需要 Owner 提供可验证政策；
- 官方 CS3481/其他课程树、Spec 和正式题库内容仍需要授权人工审核，不可把合成 fixture 发布为官方内容。

如果 Owner 的下一目标是“先部署当前安全闭环”而不是“补完全部产品能力”，上述源码缺口必须在 release notes 中明确，且不能称 V3 全功能完成。

## 9. 下一位 ChatGPT 的执行顺序

### Gate A — 冻结候选与重新验证

从 reviewed checkout 执行：

```powershell
git status --short --branch
git rev-parse HEAD

Set-Location services/rag-api
.venv/Scripts/python.exe -m pytest -q -o cache_dir=../../work/pytest-cache
.venv/Scripts/python.exe -m ruff check app tests ../../scripts
.venv/Scripts/python.exe -m mypy app ../../scripts/run_model_benchmark.py ../../scripts/run_v3_model_canary.py
Set-Location ../..

npm test
npm run typecheck
npm run build
npm audit --json
npm audit --omit=dev --json
npm run test:e2e
npm exec playwright test -- --config=playwright.v3.config.ts
```

任何行为代码、依赖、迁移或配置变化都会使本报告中的 PASS 过期；必须按影响面重跑。

### Gate B — Owner/runtime 完成真实拓扑盘点和恢复

Owner 必须亲自提供或在可信屏幕中核验：

```text
backend/frontend release SHA
RAG DB absolute path
Agent DB absolute path or proof of no deployed persistent Agent DB
uploads absolute root
active writer/process inventory
Schema/integrity/FK/WAL/free disk
protected off-host backup destination
Netlify/Clerk/API origins
V3 flag and rollback owner
```

完整隔离恢复通过前停止部署。

### Gate C — Owner 授权的最小 live model canary

先读 `docs/MODEL_BENCHMARK_2026.md` 与 `docs/v3/DEPLOYMENT_RUNBOOK.md`。Owner 在 Alibaba Cloud 控制台核验账号/workspace/region/endpoint、`qwen3.8-max` entitlement、Responses、image、streaming、tool calling、quota 和当天价格；只使用新的合成 PNG/JPEG。

先运行不读 key、不创建客户端、不计费的 `--preflight-only`。最小 V3 CASE 为 3 calls；再分别预检 streaming `zh-01` 和 tool `tool-03`。只有 Owner 对打印出的币种、单价、最大费用与调用数单独授权后，才设置私有 shell key 并改用 `--allow-billable`；V3 图片还必须加 `--confirm-synthetic-image`。

禁止：私人课程资料/图片、自动 retry/resume、覆盖旧结果、在 Git/ChatGPT 粘贴 key 或原始 Provider body。Schema 通过仍只写 `PENDING_HUMAN_QUALITY_REVIEW`；Owner 必须逐条审核学科正确性、教学深度、grounding、语言/偏好、视觉转录/符号和 uncertainty 后，才能写 `LIVE_MODEL_VERIFIED`。

### Gate D — 隔离 preview/staging

1. 后端用 exact reviewed SHA、`V3_ENABLED=false` 部署；
2. 验证 health、V2 QA/citation/history/private course、Task Agent 与真实 Clerk A/B/Admin；
3. 只在完整恢复已通过的维护窗口，由一个实例应用 011–021；
4. 复查 versions/integrity/FK/count/publication/budget reservations；
5. 仅 internal Owner 启用后端 V3；
6. Web `VITE_V3_ENABLED=true` 只发 preview/canary；
7. 跑真实身份的两用户/Admin、文件隔离、双树、Problem/Bridge/Teaching/Assessment、reload/relogin 和 Task 回归。

### Gate E — 生产 canary 与回滚

上线前记录 baseline：error rate、p50/p95、Provider failure/UNKNOWN、token/cost、401/403/404、SQLite lock、disk、ingestion、client JS、backup age。任何授权泄漏、integrity/FK 错误、重复扣费风险立即关闭 V3；错误率 >2× 或 p95 >50% 立即回滚。普通 UI/质量问题先关 `VITE_V3_ENABLED`；backend/provider/cost 问题关 `V3_ENABLED`。不要 drop 011–021；加性表默认保留。恢复旧数据库是 Owner 授权的最后手段。

## 10. Owner 需要保存并发给下一位 ChatGPT 的证据

只发脱敏文本/截图，不发 key、DB、uploads、学生资料、prompt/response body：

```text
timestamp + operator
exact commit/release/deploy SHA
service host and region label
redacted endpoint host/category
Clerk instance/origin/role result
RAG and Agent schema versions + integrity/FK aggregate
upload count/bytes/manifest digest
backup ID/time + isolated restore PASS/FAIL
health and authenticated A/B/Admin smoke matrix
live canary case IDs/model/protocol/region/usage/cost ceiling
human quality rubric disposition
monitoring baseline/canary values
flag values + rollback owner/result
```

## 11. 学习与接手 packages（每包 1–5 个真实文件）

### Package 1 — Feature gate 与迁移启动

1. `services/rag-api/app/config.py`
2. `services/rag-api/app/db.py`
3. `services/rag-api/app/main.py`
4. `services/rag-api/tests/test_database.py`

目标：理解 V2 1–10 / V3 1–21 activation、readiness 与默认关闭边界。

### Package 2 — 私人资料、版本与预览

1. `services/rag-api/migrations/013_document_versions_and_artifacts.sql`
2. `services/rag-api/app/learning/workspaces.py`
3. `services/rag-api/app/learning/uploads.py`
4. `services/rag-api/app/learning/previews.py`
5. `services/rag-api/tests/test_learning_safety.py`

目标：理解 original/version/artifact/chunk provenance、owner ACL 与文件生命周期。

### Package 3 — Registry、双树与双轴

1. `services/rag-api/migrations/014_knowledge_registry_and_trees.sql`
2. `services/rag-api/app/learning/knowledge.py`
3. `apps/web/src/components/KnowledgeTrees.tsx`
4. `services/rag-api/tests/test_knowledge_registry.py`

目标：理解 canonical/private identity、ATOMIC/COMPOSITE、hierarchy/prerequisite 以及 progress/grade 分离。

### Package 4 — Planner/Compiler/Teaching runtime

1. `services/rag-api/app/learning/prompts/v3.2/planner.md`
2. `services/rag-api/app/learning/prompts/v3.2/common.md`
3. `services/rag-api/app/learning/compiler.py`
4. `services/rag-api/app/learning/plans.py`
5. `services/rag-api/app/learning/orchestrator.py`

目标：跟踪 CASE_A/B、四专业策略、缓存键、bounded unit 与可靠 REQUIRED coverage。

### Package 5 — Problem 与 LearningBridge

1. `services/rag-api/migrations/016_problem_runtime_and_bridges.sql`
2. `services/rag-api/app/learning/prompts/v3.2/problem.md`
3. `services/rag-api/app/learning/problems.py`
4. `apps/web/src/pages/LearningPage.tsx`
5. `services/rag-api/tests/test_problem_runtime.py`

目标：复刻完整解法、StepKnowledgeLink、不可变 revisions、Bridge context 和精确返回。

### Package 6 — Assessment、GradePolicy 与重规划

1. `services/rag-api/migrations/017_assessment_runtime.sql`
2. `services/rag-api/migrations/018_grade_policy_and_snapshots.sql`
3. `services/rag-api/app/learning/assessments.py`
4. `apps/web/src/components/AssessmentPanel.tsx`
5. `services/rag-api/tests/test_assessment_runtime.py`

目标：理解五题冻结 Blueprint、答案保密、PRACTICE/独立证据、GradeSnapshot 和 weak-point trigger。

### Package 7 — 精确版本发布治理

1. `services/rag-api/migrations/019_scoped_publication_reviews.sql`
2. `services/rag-api/migrations/020_official_publication_resource_locks.sql`
3. `services/rag-api/app/services/publication_snapshots.py`
4. `services/rag-api/app/services/overlay_publication.py`
5. `services/rag-api/tests/test_publication_v3.py`

目标：理解 consent、exact snapshot、独立审核、资源锁、withdraw/supersede 与 Admin 最小可见面。

### Package 8 — Provider、成本与发布证据

1. `services/rag-api/app/learning/provider.py`
2. `services/rag-api/migrations/021_model_call_budget_reservations.sql`
3. `services/rag-api/app/evaluation/v3_model_canary.py`
4. `scripts/run_v3_model_canary.py`
5. `services/rag-api/tests/test_stage7_quality_controls.py`

目标：理解 call-before-I/O reservation、zero retry、safe evidence、固定合成 canary 与人工质量门槛。

## 12. 必读文档顺序

1. `docs/V3_SPEC_REALIGNMENT.md`
2. `docs/v3/REQUIREMENTS_AND_TRACEABILITY.md`
3. `docs/v3/ARCHITECTURE_AND_STATE_MACHINES.md`
4. `docs/v3/PERMISSIONS_AND_DATA_PROVENANCE.md`
5. `docs/v3/PROMPT_TEMPLATES_AND_CONTRACTS.md`
6. `docs/v3/GRADE_POLICY_GAPS_AND_CONFIGURATION.md`
7. `docs/v3/SELF_GRILL_DECISIONS.md`
8. `docs/v3/TEST_AND_MODEL_EVALUATION_REPORT.md`
9. `docs/v3/MIGRATION_AND_ROLLBACK.md`
10. `docs/v3/DEPLOYMENT_RUNBOOK.md`
11. `docs/MODEL_BENCHMARK_2026.md`

如果文档和当前源码/运行证据冲突，优先级仍是：当前可验证 production runtime > 当前 source/Schema/Git > 本文档 > 历史报告 > README/假设。

## 13. 最终交接判定

当前可以诚实宣布：

- V3 核心持久化学习闭环、数据隔离、双轴、五题 Assessment、版本化 Prompt、发布快照和成本闸门已有实际源码；
- 最终 deterministic unit/integration/build/browser 和 dependency audit 在实现基线通过；
- 当前活动 RAG 数据库的 1–18 → 1–21 隔离副本迁移通过，活动源未改变。

当前不能宣布：

- 所有 V3 产品功能都已完成；
- 完整 current-site backup/restore 已通过；
- `qwen3.8-max` 在真实账号/地域/协议/视觉/stream/tool 中已通过；
- 生产已部署、已迁移或已验收。

下一位 ChatGPT 应从 **发现真实 Agent DB/恢复拓扑** 开始；如果 Owner 先选择补源码缺口，则按第 8 节逐项建测试与 022+ 前向迁移，不能重建数据库或削弱现有 ACL。
