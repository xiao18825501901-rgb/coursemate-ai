# DSH 执行状态（会话交接与恢复用）

**最后更新**：2026-09-14（会话内）
**本文件是跨上下文压缩 / 换会话的唯一恢复依据。**

## 1. 真实工作区

| 项 | 值 |
|---|---|
| 仓库 | `C:\Users\Hp\Documents\Codex\2026-08-11\files-mentioned-by-the-user-coursemate\outputs\coursemate-ai` |
| 分支 | `feature/dsh-ui-refresh-integration` |
| 接手前基线 SHA | `64e57501b380ffaefb55db92ef0fc328c39b0928` |
| 交付包位置 | `D:\UserData\Downloads\CourseMate_DSH_Implementation\CourseMate_DSH_Implementation` |
| 开发执行模型 | `deepseek-v4-flash`（`C:\Users\Hp\.dsh\settings.yaml` 的 `agent-default-model`）。**用户要求的是 `deepseek-v4-pro`，当前 Harness 实际设置不是它**，本会话未改动该设置 |
| 网站教学模型 | `qwen3.8-max`（`services/rag-api/app/config.py:v3_model` / `app/cm_update` 复用同一凭据） |

实际提交：

```
359da39  feat(ui-extension): mount delivered new UI on real V3 domain
c87eb23  feat(ui-extension): real React shell, agent task bridge, wider recovery unit
e8e4e58  fix(ui-extension): browser-verified CORS, caching and agent task contract
7804608  docs(ui-refresh): handover baseline, integration map, migration, test and Qwen reports
a5d5f1b  feat(ui-extension): keep the original V3 question history readable in the shell
72619f2  docs: refresh report hashes, counts and execution state after the legacy-history round
8e16fbf  docs: record the final SHA and change size in the deployment report
0e94fd6  docs: point the report at git rev-parse HEAD instead of a self-referential SHA
```


## 2. 已合入模块

| 模块 | 位置 | 状态 |
|---|---|---|
| 交付包后端（逐字节除 3 处修正） | `services/rag-api/app/cm_update/` | 已合入，13/15 文件 hash 与包 manifest 一致 |
| 真实 DomainPort 适配器 | `services/rag-api/app/ui_extension/domain.py` | 已实现 20 个 operation |
| 注入式身份桥 | `services/rag-api/app/ui_extension/identity.py` | 已实现，绑定宿主 Clerk 验证器 |
| 宿主挂载 | `services/rag-api/app/ui_extension/mount.py` + `app/main.py` | 已实现，默认关闭 |
| 新 React 壳 | `apps/web/src/ui/*`、`src/CourseMateUi.tsx`、`src/main.ui.tsx`、`ui.html` | 已合入真实 Vite 构建 |
| Node 任务桥 | `domain.py` 的 `task.*` | 已实现并测试 |
| 恢复单元扩展 | `ops/backup_v2.py`、`ops/restore_v2.py` | 已实现并测试 |

## 3. 剩余 DomainPort 映射缺口

**无未实现的 operation（22 个全部实现）**。但以下是已知的语义限制：

1. `knowledge.tree` 依赖 `learning_workspaces`：用户首次进入课程时自动创建 workspace。
   真实 corpus 若没有已发布的 `knowledge_tree_versions`，返回空数组（已实测）。
2. `task.*` 的 `version` 由 Agent 的 `updatedAt` 派生（Agent Schema 1 没有 version 列）。
3. `context.retrieve` 只返回 `top_k` 条，与 V3 学习链路的 `evidence()` 上限一致。
4. 生成 run 是单进程内存任务表，多 worker 部署必须改造。
5. ~~新壳未提供旧 V3 会话历史的只读入口~~ → 已在 `a5d5f1b` 实现：`legacy.conversations` / `legacy.conversation` 两个 operation + 宿主两条只读路由 + 历史弹窗"旧版问答记录"分组。
6. **生产 Clerk 桥**（`AuthBridge`）此前零覆盖，现由 `apps/web/src/CourseMateUi.test.tsx` 6 项覆盖；浏览器侧真实 Clerk 会话流程仍未跑。
7. **多 worker 生成**仍未接线：`app.py:49` 无条件启动清理会杀掉其他 worker 的 run；`app.py:757` 取消是进程内语义。已核实 V3 当前单 worker，故不会触发；最小修法见 `MIGRATION_AND_ROLLBACK.md` §7。

## 4. 最新测试结果（本会话实测）

| 套件 | 命令 | 结果 |
|---|---|---|
| rag-api 全量 | `.venv\Scripts\python.exe -m pytest -q` | **458 passed** |
| web 单测 | `vitest run`（`apps/web`） | **55 passed**（含真实 Clerk 桥 6 项） |
| 正式构建 | `tsc -b && vite build` | 通过，双文档产物 |
| 原生浏览器验收 | `playwright test --config playwright.ui.config.ts` | **9 passed**（真实 Chromium + 真三服务） |
| 真实 Clerk 桥单测 | `vitest run src/CourseMateUi.test.tsx` | **6 passed** |

## 5. 授权记录

**本会话未弹出任何权限提示框，也未执行任何需要授权的动作。**

未执行：真实千问付费调用、生产访问、数据库迁移、重启服务、修改真实凭证、Git push、
Netlify 发布。

已执行且不需要授权：本地读文件、本地改代码、本地非计费测试、本地构建、本地浏览器测试。

> 注意：本会话的批准提示被禁用（`approval_policy=never`），因此**不存在**"已获批准但未执行"
> 的待办授权项。

## 5.1 阻塞条件（连续 3 轮相同，已据此上报 blocked）

**阻塞项**：目标中最后两件事——真实千问两阶段 canary、生产部署 + 双用户验收——
都要求在动作**之前**取得原生授权确认。

**阻塞原因**：本会话的批准通道被禁用（会话策略 `approval_policy: never`），
任何需要批准的动作会被自动拒绝。模型**无法自行**弹出该提示框，
因此不存在可执行的取得授权路径。

**三轮记录**（同一条件，未变化）：

| 轮次 | 日期 | 证据 | 结果 |
|---|---|---|---|
| 1 | 2026-09-14 | 会话策略 `approval_policy: never`；本会话原生提示框弹出 0 次 | 未执行，改为推进非授权项（旧版问答历史只读入口） |
| 2 | 2026-09-14 | 同上，未变化 | 未执行，改为推进非授权项（真实 Clerk 桥测试、课程生命周期测试、多 worker 精确复核） |
| 3 | 2026-09-14 | 同上，未变化；非授权项已无剩余高价值工作 | 上报 blocked |

**不构成 blocked 的事项**（已全部完成，不是阻塞）：
DomainPort 22 个 operation 全部接线、Clerk 注入式身份桥、检索/Task Agent/知识树/Bridge 接线、
旧 V3 历史只读入口、原 React 工具链正式构建、本包 71 项 + 原仓库 458 项回归、
9 项原生浏览器验收、五份 `docs/ui-refresh/*` 报告与最终报告。

**解除阻塞所需的最小动作**（用户侧，二者之一即可）：
1. 重新启用 DSH 批准提示（或把本会话策略改为可批准）；或
2. 用户自行运行本包 `scripts/Request-DeploymentApproval.ps1` 完成确认。

## 6. 部署 / 回滚状态

* 生产：**未触碰**。生产仍是 `qqttai.com` + `cd8c121` + Netlify `6aa70f2b5a330d5a8ae4be56`。
* 回滚：无需回滚，因为未发布。
* `UI_EXTENSION_ENABLED` 在新 release 部署前保持 `false`，新入口在生产上不存在。

## 7. 恢复步骤

1. 读本文件与 `docs/ui-refresh/HANDOVER_BASELINE.md`。
2. `git rev-parse HEAD` 确认 HEAD 为 `6072588` 或其后；工作树应为空改动。
3. 全量回归：见 §4 命令（每次均应得到 458 / 55 / 9 这三个数字）。
4. 原生浏览器验收前，先按 `playwright.ui.config.ts` 前缀用部署形态构建前端：
   设置 `VITE_AUTH_TEST_TOKEN=test-session-token` 与
   `VITE_UI_API_BASE=http://127.0.0.1:8100/ui-extension/api/ui/v1` 后 `vite build`。
   **发布前必须用 Clerk 形态（不设 test token）重新构建**，并确认产物中
   不含 `test-session-token`、含 Clerk 客户端。
5. 需要真实千问验证时：先取得授权（见 §5.1），再设置
   `CMUI_PROVIDER_MODE=qwen` 与 `CMUI_ALLOW_BILLABLE=true`，
   并按下述顺序部署：先发后端但保持 `UI_EXTENSION_ENABLED=false` 验证无回归，
   再开开关并设置 `CMUI_DATA_DIR` / `UI_TASK_AGENT_URL`，最后发前端。
