# DSH 执行状态（会话交接与恢复用）

**最后更新**：2026-09-15（会话内）
**本文件是跨上下文压缩 / 换会话的唯一恢复依据。**

## 1. 真实工作区

| 项 | 值 |
|---|---|
| 仓库 | `C:\Users\Hp\Documents\Codex\2026-08-11\files-mentioned-by-the-user-coursemate\outputs\coursemate-ai` |
| 分支 | `feature/dsh-ui-refresh-integration` |
| 接手前基线 SHA | `64e57501b380ffaefb55db92ef0fc328c39b0928` |
| 交付包位置 | `D:\UserData\Downloads\CourseMate_DSH_Implementation\CourseMate_DSH_Implementation` |
| 开发执行模型 | `deepseek-v4-pro`（`C:\Users\Hp\.dsh\settings.yaml` 的 `agent-default-model.model`；用户已切换，本会话一致） |
| 网站教学模型 | `qwen3.8-max`（`services/rag-api/app/config.py:v3_model` / `app/cm_update` 复用同一凭据） |
| DSH 版本 | `@deepseek-ai/dsh 0.1.1-rc.2`（全局 npm 安装） |
| 会话权限 | **`approval_policy: ask`**（用户已切换；本轮所有仓库写入均经真实批准回执，无生产/付费批准）；文件 sandbox `danger-full-access`（逐次批准） |

实际提交（HEAD 以 `git rev-parse HEAD` 为准）：

```
359da39  feat(ui-extension): mount delivered new UI on real V3 domain
c87eb23  feat(ui-extension): real React shell, agent task bridge, wider recovery unit
e8e4e58  fix(ui-extension): browser-verified CORS, caching and agent task contract
7804608  docs(ui-refresh): handover baseline, integration map, migration, test and Qwen reports
a5d5f1b  feat(ui-extension): keep the original V3 question history readable in the shell
72619f2  docs: refresh report hashes, counts and execution state after the legacy-history round
8e16fbf  docs: record the final SHA and change size in the deployment report
0e94fd6  docs: point the report at git rev-parse HEAD instead of a self-referential SHA
4023986  (default-entry routing round)
47b150a  (closure round)
dd710b3  feat(ui-extension): enforce single-worker safety for generation runs
2e8c508  docs: mark P0-5 complete and refresh counts after the single-worker round
（P0-3/P0-8 轮提交见后续 commit 记录）
```

## 2. 已合入模块

| 模块 | 位置 | 状态 |
|---|---|---|
| 交付包后端 | `services/rag-api/app/cm_update/` | 已合入，**9/15 文件 hash 与包 manifest 一致**，6 处有意修改（`app.py`/`db.py`/`config.py`/`integration.py`/`provider.py`/`seed.py`） |
| 真实 DomainPort 适配器 | `services/rag-api/app/ui_extension/domain.py` | 已实现 **28** 个 operation（程序枚举；含 `knowledge.submit_delivery`/`knowledge.record_problem`） |
| 注入式身份桥 | `services/rag-api/app/ui_extension/identity.py` | 已实现，绑定宿主 Clerk 验证器 |
| 宿主挂载 | `services/rag-api/app/ui_extension/mount.py` + `app/main.py` | 已实现，默认关闭 |
| 新 React 壳 | `apps/web/src/ui/*`、`src/CourseMateUi.tsx`、`src/main.ui.tsx`、`ui.html` | 已合入真实 Vite 构建；`/` 默认入口 + `/app` 别名 |
| Node 任务桥 | `domain.py` 的 `task.*` | 已实现并测试 |
| 恢复单元扩展 | `ops/backup_v2.py`、`ops/restore_v2.py` | 已实现并测试 |
| 确定性测试 Provider | `app/cm_update/provider.py:TestProvider`（`provider_mode='test'`） | 已实现并测试；生产拒绝该模式 |

## 3. 剩余 DomainPort 映射缺口

**无未实现的 operation（26 个全部实现）**。已知语义限制：

1. `knowledge.tree` 依赖 `learning_workspaces`：首次进入课程自动创建 workspace；
   无已发布 OFFICIAL 树时返回空数组（如实空态）。
2. `task.*` 的 `version` 由 Agent 的 `updatedAt` 派生（Agent Schema 1 无 version 列）。
3. `context.retrieve` 只返回 `top_k` 条，与 V3 学习链路 `evidence()` 上限一致。
4. **生成 run 是单进程内存任务表**：单 worker 约束已升级为实际防护（Schema 3 租约 +
   心跳 + 只回收过期租约 + 跨进程取消 + 条件式最终写入），但**不是**多 worker 支持；
   扩容需 V3 侧尚不存在的持久化 worker（见 `MIGRATION_AND_ROLLBACK.md` §8）。
5. 旧 V3 问答历史只读入口：已实现（`legacy.conversations` / `legacy.conversation`）。
6. 生产 Clerk 桥（`AuthBridge`）已由 `apps/web/src/CourseMateUi.test.tsx` 6 项覆盖；
   浏览器侧真实 Clerk 会话流程仍未跑（需真实 Clerk 应用与账号）。
7. UI Bridge 与 V3 LearningBridge 是**两个独立系统**（未冒充同名接通）：UI
   `cmui_bridges` 是壳内返回原步骤的 UX 上下文，V3 `LearningBridge` 是 V3 运行时权威记录。

## 4. 最新测试结果（本会话实测）

| 套件 | 命令 | 结果 |
|---|---|---|
| rag-api 全量 | `.venv\Scripts\python.exe -m pytest -q` | **486 passed**（554.20s；含覆盖闭环 8 项、桥接追溯 5 项、两处过期断言修复） |
| web 单测 | `vitest run`（`apps/web`） | **55 passed**（含真实 Clerk 桥 6 项） |
| 正式构建 | `tsc -b && vite build`（三种形态） | 通过：E2E 形态（test token）`ui-rTcXnucO.js`；Clerk 验证形态（假 key）`ui-Bckh22_y.js`=B4BA950D3047F0A6 含 AuthBridge+fallbackRedirectUrl、无测试令牌；fail-closed 形态（无 key）`ui-C60rpF3L.js`=9C9214A661399002。**生产构建必须给真实 `VITE_CLERK_PUBLISHABLE_KEY`** |
| 原生浏览器验收（新壳） | `playwright test --config playwright.ui.config.ts` | **16 passed**（1.1m，含树层级、双模式、键盘/触屏用例） |
| 旧站 E2E `coursemate.spec.ts` | `playwright test`（默认 config） | **4 passed**（本轮复跑） |
| V3 学习 E2E `learning.spec.ts` | `playwright test --config playwright.v3.config.ts` | **3 passed**（本轮复跑） |
| Node Agent 单测/typecheck/build | `vitest run` / `tsc --noEmit` / `tsc` | **66 passed** / 通过 / 通过（本轮复跑） |
| 真实 Clerk 桥单测 | `vitest run src/CourseMateUi.test.tsx` | **6 passed**（含于 web 55 项） |

## 5. 授权记录

**本会话未弹出任何权限提示框，也未执行任何需要授权的动作。**

未执行：真实千问付费调用、生产访问、数据库迁移、重启服务、修改真实凭证、Git push、
Netlify 发布。

已执行且不需要授权：本地读文件、本地改代码、本地非计费测试、本地构建、本地浏览器测试。

> 注意：本会话的批准提示被禁用（`approval_policy=never`），因此**不存在**"已获批准但未执行"
> 的待办授权项。`scripts/Request-DeploymentApproval.ps1` 只产生业务同意记录，不接入
> Harness 审批决策（closure prompt §9 已区分四项，见最终报告 §7.1）。

## 5.1 阻塞与解除路径

**阻塞项**：真实千问两阶段 canary、生产部署 + 双用户验收——都要求在动作**之前**
取得原生授权；本会话批准通道被禁用（`approval_policy: never`），模型无法自行弹出提示框。

**解除阻塞所需的最小动作**（用户侧）：
在 DSH Web GUI（`http://127.0.0.1:3080`）把会话审批策略从 `never` 切到 `ask` 或
对等可用模式（`settings.yaml` 无审批字段，不要凭猜测写 YAML）；
验证方式是随后一次无生产影响、无费用且确实需要原生审批的测试动作收到真实审批提示。

## 6. 部署 / 回滚状态

* 生产：**未触碰**。早期报告记录 `qqttai.com` + `cd8c121` + Netlify
  `6aa70f2b5a330d5a8ae4be56` 是**历史快照，未现场复核**。
* 回滚：无需回滚，因为未发布。
* `UI_EXTENSION_ENABLED` 在新 release 部署前保持 `false`，新入口在生产上不存在。

## 7. 恢复步骤

1. 读本文件与 `docs/ui-refresh/HANDOVER_BASELINE.md`、`docs/ui-refresh/RELEASE_CLOSURE_CHECKLIST.md`。
2. `git rev-parse HEAD` 确认 HEAD；工作树应为空改动（未提交项已入库）。
3. 全量回归：见 §4 命令；关键数字 rag-api 全量、web 55、agent 66、
   新壳浏览器 16、旧站 4、V3 学习 3。
4. 原生浏览器验收前，先按 `playwright.ui.config.ts` 前缀用部署形态构建前端：
   设置 `VITE_AUTH_TEST_TOKEN=test-session-token` 与
   `VITE_UI_API_BASE=http://127.0.0.1:8100/ui-extension/api/ui/v1` 后 `vite build`
   （config 自带 `CMUI_PROVIDER_MODE=test` + 树 fixture 注入 + `hasTouch`）。
   **产物形态扫描**：E2E 产物含测试令牌（预期）；Clerk 验证形态用假
   `VITE_CLERK_PUBLISHABLE_KEY=pk_test_...` 构建并扫描（含 AuthBridge、
   无测试令牌）；生产 Netlify 构建必须设置真实 key，否则发布 fail-closed 形态。
5. 需要真实千问验证时：先取得授权（见 §5.1），再设置
   `CMUI_PROVIDER_MODE=qwen` 与 `CMUI_ALLOW_BILLABLE=true`，
   并按下述顺序部署：先发后端但保持 `UI_EXTENSION_ENABLED=false` 验证无回归，
   再开开关并设置 `CMUI_DATA_DIR` / `UI_TASK_AGENT_URL`，最后发前端
   （首次启用 A/B/C 备份顺序见 `MIGRATION_AND_ROLLBACK.md` §4）。
