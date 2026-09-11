# V3 基线与需求追踪（持续更新，不是完成声明）

> 历史说明（2026-09-12）：本文件记录上一版规格下的基线和目标映射。新版主规格现已收到并成为当前依据；当前状态与规范矩阵见 [v3/REQUIREMENTS_AND_TRACEABILITY.md](v3/REQUIREMENTS_AND_TRACEABILITY.md)，切换差异见 [V3_SPEC_REALIGNMENT.md](V3_SPEC_REALIGNMENT.md)。本文件不再单独授权实施。

## Stage 0 / 2026-09-12

- 输入：完整读取 Owner 的 `COURSEMATE_V3_CODEX_IMPLEMENTATION_PROMPT.md`，621 行；该规格与本次消息共同为实施契约。Q1–Q10 不重议，SG 为工程默认而非逐项用户确认。
- 基线分支 `feature/coursemate-v2-ai-tutor`，SHA `846138e891b3e036c74feecc0be594426090fe25`；创建 `feature/coursemate-v3-persistent-learning`。
- 既有未跟踪文件 `ACTUAL_IMPLEMENTED_CHANGES_AUDIT.md`、`curl` 不修改、不提交。未发现项目 AGENTS.md。
- SOURCE：React/TS + FastAPI/Python + Node Task Agent，SQLite；V2 独立模型角色配置、Responses 流、混合检索、Clerk、发布审核与旧会话保留。
- LOCAL DB：只读打开 `data/rag.sqlite3`；版本 1–10，integrity=ok；3 courses / 67 documents / 1937 chunks / 31 conversations / 78 messages；原件当前路径可读取 66/67。无原件文件不得伪造下载。未读取或输出用户正文。
- LOCAL TEST：基线 pytest 194 passed / 1 Starlette 弃用 warning（45.51s）；npm 首次失败因 node_modules 缺 vitest，按 lockfile `npm ci --ignore-scripts` 恢复，待重新执行。安装 audit 报 1 high / 3 moderate，尚未审定可达性，不是发布通过。
- HISTORY：本仓库缺 `FINAL_PRODUCTION_DEPLOYMENT_COMPLETION_REPORT.md`。已读的 `PRODUCTION_DEPLOYMENT_CHANGELOG_AND_FINAL_STATE.md` 与 V2 Runbook 最后声明生产未知。规格描述的后续新加坡/Caddy 部署缺相应本地证据。
- LIVE MODEL / PRODUCTION：UNKNOWN — REQUIRES MANUAL VERIFICATION。无本轮批准预算，不发付费请求、不 SSH 写生产、不部署。
- 模型官方文档当日确认 qwen3.8-max 及 Responses 新路径；账户能力仍 MODEL_LIVE_BLOCKED。Embedding 保持独立且不触发重嵌入。

## 依赖与阶段

Stage 0 基线 → Stage 1 workspace/文件 ACL/模型适配 → Stage 2 规范节点与 Spec → Stage 3 黄金闭环 → Stage 4 双 Pane/四专业两场景 → Stage 5 Assessment → Stage 6 生命周期/重规划 → Stage 7 回归/模型评测 → Stage 8 受控发布。

优先沿 Stage 1–4 的最小纵向路径实现；不等管理功能全部完成才测闭环。每小片先失败测试，再实现，再运行相关测试。旧 QA/Task Agent 不移除。新路由由显式 V3 flag 控制，默认关闭。

| 任务 | 验收与验证 | 依赖/拟改文件（目标，不代表已有） |
|---|---|---|
| 1. 状态/契约 | additive migration；两次初始化、FK、旧行保持；pytest | app/learning/schema.sql, models.py, db.py, tests/test_learning_* |
| 2. 私人 workspace/文件 | A/B/Admin/匿名 GET/HEAD/Range 隔离；官方只读、私人检索 | learning/workspaces.py, api/learning.py, tests |
| 3. 节点/Spec | course-scoped ID、稳定版本、REQUIRED；非管理员不能发布 | learning/knowledge.py, tests |
| 4. 黄金闭环后端 | Problem→Step→Bridge→Unit→coverage→return；重启/幂等/冲突 | learning/orchestrator.py, provider.py, tests |
| 5. Prompt 编译 | 四专业×两情景；低信任字段不能升级 system；无效 ID 拒绝 | learning/prompts/*, compiler.py, tests |
| 6. 双 Pane | 恢复/键盘/移动布局、真实 HTTP 流程 | web learning types/client/page, E2E |
| 7. Assessment | 五题不等权100；独立证据/政策缺项不捏造 | learning/assessment.py, tests/UI |
| 8. 计划/生命周期 | diff/恢复/撤回、审核快照、版本迁移 | 独立增量，按上述约束实现 |
| 9. 验证发布 | 原有+新增测试/副本迁移/隔离恢复/live/production 分列 | ops/scripts/docs |

## Q 到实现和验收的目标映射

下列映射为计划；实际实现状态和结果以测试报告逐片记录为准，未执行不可标 PASS。

| Q | 代码域 | Schema | 必测 |
|---|---|---|---|
| Q1 | provider/配置 | operation usage | locked model / independent embedding / no retry or fallback |
| Q2 | orchestrator/Pane | workspace/journey/bridge | shared state / mode lock / restart |
| Q3 | progress/assessment | coverage vs performance | LEARNED + low grade / NOT_ASSESSED |
| Q4 | assessment | blueprint/rubric/policy | 5 unequal /100/invalid mapping |
| Q5 | question pool | origin/visibility/family | official+own priority/variant/exposure |
| Q6 | knowledge | nodes/relations | atomic/composite/DAG/de-dup aggregation |
| Q7 | resolver/plans | canonical nodes/private evidence | no name-only merge/cross-user/copy grades |
| Q8 | coverage | unit/step/coverage | REQUIRED only / saved complete body / invalid proposal |
| Q9 | orchestrator | operation/journey/cursor | bounded unit/pause/resume/no hidden retry |
| Q10 | compiler/knowledge | policy/spec/profile versions | four layers / review / pinned scope |

## SG 到实现与反例测试的目标映射

| SG | 模块/Schema | 验证目标 |
|---|---|---|
| SG01 | workspace/document content | ACL applies to metadata/HEAD/Range/download |
| SG02 | workspace/private corpus | official owner/content unchanged |
| SG03 | knowledge node identity | course+semantic scope, no global name merge |
| SG04 | generated artifacts | origin separate visibility, derived stays private |
| SG05 | plans/node progress | one node state shared by both trees |
| SG06 | relations | hierarchy vs prerequisites, cycles/orphans rejected |
| SG07 | immutable spec/journey | old coverage retained; updates pending |
| SG08 | coverage ledger | saved content/id/spec validation; no model state setter |
| SG09 | operations/events | replay, duplicate clicks, unknown provider outcome |
| SG10 | workspace revision | short transaction; stale concurrent update rejected |
| SG11 | bridge/step versions | exact return context persists |
| SG12 | attempts | ANSWER_EXPOSED not independent evidence |
| SG13 | solution provenance | no unpaired official answer claim |
| SG14 | problem prompt | proposed scoring points, no score guarantees |
| SG15 | rubric evidence | item-level concept/method/calculation/etc. |
| SG16 | frozen blueprint | comparable evidence only / uncertainty |
| SG17 | readiness | deterministic formula + insufficient evidence |
| SG18 | tree publication | candidates cannot mutate published version |
| SG19 | source lifecycle | revoke retrieval/artifacts/context/history links |
| SG20 | snapshot review | no generic admin bypass for private learning |
| SG21 | bounded operations | user action / caps / explicit continuation |
| SG22 | evaluations | fake/self-check not independent proof |
| SG23 | compiler | untrusted plan not system instructions |
| SG24 | GradePolicy | missing A-/thresholds blocks activation, not raw score |

## 已读取的源证据

`app/{main,config,db,auth,course_access}.py`、`api/ingestion.py`、`services/ingestion.py`、`rag/{answers,retrieval}.py`、`repositories/chunks.py`、Web `App.tsx`/`services/http.ts`、package/lock、测试、迁移文档、备份源码及 V2 部署 Runbook。继续随实现读取具体模块，不从 Atlas 猜函数。
