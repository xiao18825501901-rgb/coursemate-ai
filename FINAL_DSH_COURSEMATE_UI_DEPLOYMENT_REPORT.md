# FINAL DSH COURSEMATE UI DEPLOYMENT REPORT

**报告时间**：2026-09-14（Asia/Hong_Kong）
**执行者**：DSH（DeepSeek Harness）
**仓库**：`C:\Users\Hp\Documents\Codex\2026-08-11\files-mentioned-by-the-user-coursemate\outputs\coursemate-ai`
**分支**：`feature/dsh-ui-refresh-integration`
**接手前基线**：`64e57501b380ffaefb55db92ef0fc328c39b0928`
**本次最终 SHA**：见 §10（本文件随最终提交一并入库）

```text
SOURCE INTEGRATION:               PASS
LOCAL TEST SUITE:                 PASS  (455 rag-api + 49 web)
MODERN REACT PRODUCTION BUILD:    PASS  (React 19.2.8 + Vite 8.2.1 + tsc 5.9.3)
NATIVE BROWSER ACCEPTANCE:        PASS  (9/9 real Chromium journeys)
LIVE QWEN TWO-STAGE:              NOT RUN   (no paid authorization available)
REAL CLERK SIGN-IN:               NOT VERIFIED
PRODUCTION DEPLOYMENT:            NOT PERFORMED
AUTHENTICATED PRODUCTION ACCEPTANCE: NOT VERIFIED
OVERALL: SOURCE-COMPLETE AND LOCALLY VERIFIED — NOT PUBLISHED
```

---

## 0. 必须放在最前面的两件事

### 0.1 开发执行模型与用户要求不一致

用户指定 DSH 的开发执行模型应为 `deepseek-v4-pro`。**Harness 的实际设置不是它。**
`C:\Users\Hp\.dsh\settings.yaml`：

```yaml
agent-default-model:
  provider: deepseek-official
  model: deepseek-v4-flash
  reasoningEffort: max
```

本会话运行在 `deepseek-v4-flash`。会话中没有收到系统提示词声明的模型标识，因此以
Harness 配置文件为准。本会话**没有修改**该设置——改模型配置属于需授权动作。
如需 `deepseek-v4-pro`，请在 DSH 设置中切换后重启会话。

**这条不影响网站教学模型**：网站教学链路用的是 `qwen3.8-max`
（`services/rag-api/app/config.py:v3_model`，`Literal["qwen3.8-max"]`），
本次接线让新 UI 复用**同一个**模型凭据，没有新增第二份 key，也没有用 DeepSeek
生成任何教学内容。

### 0.2 本会话无法弹出授权框，因此生产动作一步都没有做

会话策略为 `approval_policy: never`——**批准提示被禁用，需要批准的动作会被自动拒绝**。
因此本会话没有、也不可能取得生产部署 / 真实付费模型 / 凭证变更的授权。

所以：**没有付费调用、没有生产写入、没有迁移、没有重启服务、没有 Git push、
没有 Netlify 发布。** 这不是省略步骤，而是在无授权通道时的唯一正确行为。

需要在生产执行时，请使用包内真实 Windows 弹窗
`scripts/Request-DeploymentApproval.ps1`（默认 No、正数金额 + ISO 币种、唯一记录、
10 分钟内开始、本身不部署），或在可用时使用 DSH 原生授权提示框。

---

## 1. 源码整合

**把交付包作为真实增量合入原仓库，而不是发布它的独立实现。**

| 项 | 结果 |
|---|---|
| 交付包后端模块 | `services/rag-api/app/cm_update/`（15 个文件） |
| 与包 `FILE_MANIFEST.json` 的 hash 比对 | **13 个逐字节一致**，2 个有意修改（见 §1.1），0 个缺失 |
| 交付包前端模块 | `apps/web/src/ui/`（8 个文件） |
| 与包 `web/src` 的 hash 比对 | **6 个逐字节一致**（`App.jsx`、`api.js`、`icons.jsx`、`utils.js`、`richtext.jsx`、`styles.css`），2 个**纯新增式**修改（`pages.jsx`、`styles-extra.css`，见 §1.1） |
| 真实 `DomainPort` 适配器 | `services/rag-api/app/ui_extension/domain.py`，实现全部 **22** 个 operation |
| 注入式身份桥 | `app/ui_extension/identity.py`，绑定宿主 Clerk 验证器 |
| 宿主挂载 | `app/ui_extension/mount.py` + `app/main.py`（默认关闭） |
| 新 React 壳 | `apps/web/src/ui/*`、`src/CourseMateUi.tsx`、`src/main.ui.tsx`、`ui.html` |
| Node 任务桥 | `domain.py` 的 `task.list/create/update/delete/plan` |
| 旧 V3 问答历史只读入口 | `mount.py:_prepend_legacy_history` + `domain.py:legacy.*` |
| 恢复单元扩展 | `ops/backup_v2.py`、`ops/restore_v2.py` |
| 变更规模 | 63 个文件，+8612 / −20 行 |

### 1.1 对交付包源码的六处修改（全部为可移植性/正确性/纯新增，无功能删减）

| 文件 | 修改 | 为什么必须改 |
|---|---|---|
| `app/cm_update/provider.py:20` | `read_text()` → `read_text(encoding='utf-8')` | Windows 中文 locale 是 GBK，会在**真实付费调用**路径上抛 `UnicodeDecodeError`；Linux 上看不到 |
| `app/cm_update/config.py:48` | 同上，读 build 标记 | 同一类缺陷，且位于 production 启动门 |
| `app/cm_update/seed.py` | 新增可选 `documents` 参数 | 原实现从包根 `sample-documents/` 读示例 PDF；本仓库不发布示例课程资料 |
| `apps/web/src/ui/pages.jsx` | 历史弹窗**新增**"旧版问答记录"分组；**新增** `Assessment` 组件 | 原 V3 问答历史要在新壳内可读；节点测评原本是 `JSON.stringify` 原始 JSON。纯新增，未改动既有页面布局、类名或交互 |
| `apps/web/src/ui/styles-extra.css` | **追加** `.legacy-*` / `.assessment-grid` 规则 | 只追加，未修改既有规则 |

**未改动**交付包的 `App.jsx` / `api.js` / `icons.jsx` / `utils.js` / `richtext.jsx` /
`styles.css` / `provider.py` 两阶段逻辑 / `sse.py` / `steps.py`。

### 1.2 用户确认的产品方向全部保留

* **六个**全局入口（账户、控制面板、课程、日历、收件箱、帮助），浏览器断言按钮数精确为 6 + 品牌。
* 首次控制面板只有虚线创建框；真实数据库实测 `pinned` 课程数为 0。
* 课程在"所有课程"通过加号加入面板；**服务端按用户保存**，刷新后仍在，另一账号看不到。
* 课程卡底部三个入口（评论、文件、学习）与课程二级导航指向同一路由，浏览器已断言 URL 与 active 状态。
* 学习页保留**两条**左导航；知识树**默认折叠**、展开后覆盖内容区、显示真实空状态
  "还没有课程知识树"；左知识学习 / 右题目应对；分隔条可拖动（`aria-valuenow` 变化）；
  整体全屏保留左右两栏；Esc 恢复；两条历史入口存在。
* **没有**加入待办事项、最近反馈、切换新版面板等被排除的区域。

### 1.3 千问流程没有被改回死板 JSON

* 第一阶段仍是**自由文本 Prompt**：`planner_messages()` 的指令明确"直接输出 Prompt 正文，
  不要输出 JSON，不要回答学生问题"，system 消息内嵌 7422 字节的完整 CS3481 Word 模板。
* 生成的 Prompt 落库 `cmui_runs.generated_prompt`，前端"查看生成的 Prompt"可读。
* 第二阶段把第一阶段文本放进 system 消息执行教学。
* 浏览器实测侧边栏显示"模型未连接"（`provider_mode=disabled`），**没有用预设回答假装千问**。

---

## 2. 正式 React 生产构建

```
> tsc -b && vite build
dist/index.html                  0.67 kB │ gzip:  0.39 kB
dist/ui.html                     0.68 kB │ gzip:  0.44 kB
dist/assets/main-jxvg7O-T.css   31.36 kB │ gzip:  6.48 kB
dist/assets/ui-ra_uQrdw.css     53.05 kB │ gzip: 11.81 kB
dist/assets/main-sCqwwDOm.js     0.59 kB │ gzip:  0.41 kB
dist/assets/ui-BvjeJCl0.js     264.25 kB │ gzip: 77.75 kB
dist/assets/dist-YiqoSCPN.js   309.62 kB │ gzip: 90.63 kB
✓ built in 272ms
```

* 使用**原仓库的**工具链：React 19.2.8、Vite 8.2.1、TypeScript 5.9.3、`@clerk/react` 6.x。
  没有引入新框架，没有降级到离线运行时。
* 新增唯一运行时依赖 `katex@0.16.22`，替代交付包 265 KB 的离线 vendor 副本。
* 依赖审计：本次 `npm install` 输出 `found 0 vulnerabilities`。
* **交付包 `web/dist` 从未被使用、复制或发布**；`app/cm_update/config.py:48` 的
  production 门会拒绝带 `not_for_production` 标识的产物，该门**未被删除或绕过**。
* 正式产物中**不含** `test-session-token`，且包含 Clerk 客户端（已实测校验）。
* 双文档 + 路由：`/` → `index.html`（现有站点），`/app` → `ui.html`（新壳）；
  `netlify.toml` 已加两条 `/app` 重写，排在 SPA 回退之前；Vite 开发服务器用插件复现同一 URL 形状。
* 产物 SHA-256（前 16 位）：`ui-BvjeJCl0.js` = `537D4C77D477C8D3`，
  `ui-ra_uQrdw.css` = `2024EDFB9F8192BA`，`dist-YiqoSCPN.js` = `456CB1E39F7CD904`。

---

## 3. 本地测试

| 套件 | 结果 |
|---|---|
| rag-api 全量回归 | **455 passed**（接手前基线 329，新增 126） |
| 交付包契约测试（迁入后） | **71 passed** |
| 新增 V3 DomainPort 集成测试 | **16 passed** |
| 新增任务 Agent 桥测试 | **15 passed** |
| 新增 CORS/凭证契约测试 | **13 passed** |
| 新增恢复单元测试 | **4 passed** |
| 新增旧版问答历史测试 | **7 passed** |
| 原备份/恢复测试（回归） | **9 passed** |
| web 单元测试 | **49 passed** |
| 原生 Chromium 端到端 | **9 passed** |

细节、命令与逐项覆盖见 `docs/ui-refresh/UI_AND_BACKEND_TEST_REPORT.md`。

### 3.1 原生浏览器测试发现的 5 个真实缺陷（服务端测试看不到）

1. 宿主 CORS 只允许 `WEB_ORIGIN`，其他已批准站点的预检被 400 拒绝。
2. `PUT` 不在宿主允许方法内，而收藏课程用 `PUT /courses/{id}/pin`。
3. Starlette 为被挂载子应用应答预检时不带 `Access-Control-Allow-Credentials`，
   而交付客户端固定发 `credentials:'include'`，浏览器因此拒绝一切请求。
4. 交付包的 `no-store` 中间件按字面 `/api/` 前缀判断，挂载后永不匹配。
5. 日历新建任务 400：适配器把空课程发成 `courseId: ""`、把可选项发成 `priority: null`，
   而 Node Agent 的 JSON Schema 两者都不接受。

全部已修，并各配了回归测试（`test_ui_extension_cors.py` 13 项、
`test_ui_extension_task_agent.py` 中 3 项、加浏览器用例）。

---

## 4. 真实模型

**状态：`NOT RUN`。真实千问调用次数 0，实际费用 CNY 0.00。**

原因：真实付费调用需要授权，而本会话的批准提示被禁用（§0.2）。

* 两阶段链路的 HTTP 契约由 `MockTransport` 覆盖（2 次调用、Word 全文入第一阶段、
  生成的 Prompt 入第二阶段、截断不进入第二阶段、`allow_billable=False` 时零出网请求）。
  **这些只证明"程序发出了正确的请求"，不证明千问教得好，也不证明模型可用。**
* `mount.py` 复用 V3 已部署的同一模型凭据（`V3_MODEL_API_KEY` / `V3_MODEL_BASE_URL`），
  模型固定 `qwen3.8-max`；未新增第二份密钥，未改动已部署的 endpoint 或预算。
* 授权后要跑的 canary（含预算上限建议 CNY 5.00、取消、超时、图像题）与判定标准见
  `docs/ui-refresh/QWEN_LIVE_TWO_STAGE_REPORT.md`。

---

## 5. 认证与多用户验证

### 5.1 已本地实测（真实 V3 数据库，双用户）

* 注入式身份桥：`subject_resolver` 绑定宿主 `auth_verifier`，身份**只**取自
  `Authorization` 头；未登录 → 401；未知 token → 401。
* 私人课程对他人 404 且不出现在其课程列表。
* 私人上传：本人可见且 `scope=private`，他人**看不到也读不到**（404）。
  实测别人检索同一关键词得不到该内容。
* 收藏按用户隔离：A 收藏后 B 的面板为空。
* 评论回复生成**对方**通知；自己回复自己无通知。
* 站内私信：双方可读，第三人 `threads` 为空。
* `context.retrieve` 始终带 `RetrievalAccess`，另一用户的 workspace 私有 chunk
  不会进入结果。
* `/config` 响应字段集合被精确断言：只暴露 `clerk_publishable_key`，不含任何模型凭据。

### 5.2 未验证

* **真实 Clerk 登录/登出/刷新/恢复（NOT VERIFIED）**：需要真实 Clerk 应用与账号。
  provider 侧的注入 resolver 与宿主 `ClerkAuthVerifier` 走通，但浏览器侧真实 Clerk 流程未跑。
* 生产双用户隔离、管理员边界（NOT VERIFIED）。

---

## 6. 生产部署

**状态：`NOT PERFORMED`。生产环境未被触碰。**

* 生产仍是 `qqttai.com` + 后端 release `cd8c121` + Netlify deploy `6aa70f2b5a330d5a8ae4be56`。
* 本次**没有**执行备份、迁移、重启、DNS 变更、Git push 或 Netlify 发布。
* 新入口在生产上**不存在**：`UI_EXTENSION_ENABLED` 默认 `false`，且在生产部署前必须保持 `false`。

### 6.1 数据与恢复单元（已备份工具化，未在生产执行）

* 原 RAG `rag.sqlite3`（Schema 21）与 Agent 库 **Schema 未变**：没有新增表、列或迁移文件。
* 新增数据在**独立文件** `<CMUI_DATA_DIR>/ui.sqlite3`（Schema 2，21 张 `cmui_*` 表）
  与 `<CMUI_DATA_DIR>/uploads/`。`Database.initialize()` 在检测到
  `courses`/`chunks`/`tasks`/`schema_migrations` 时**拒绝初始化**，不可能覆盖原库；
  检测到更高版本时**拒绝降级**。
* `ops/backup_v2.py` 在设置 `CMUI_DATA_DIR` 时把 `ui.sqlite3` 与 `ui-uploads.tar.gz`
  并入同一恢复单元并写入 manifest；缺少 `ui.sqlite3` 时**备份直接失败**。
* `ops/restore_v2.py` 在发布目标目录**之前**校验：校验和覆盖完整性、未知 artifact 名、
  每个 artifact 的 sha256、`integrity_check`/`foreign_key_check`、
  两个上传归档的成员数与字节数与 manifest 一致，并拒绝 `\\`、绝对路径、`..`、重复路径。
* **跨库原子性限制如实保留**：三个 SQLite `backup` 调用之间没有分布式事务，
  必须在维护窗口内进行。`ui.sqlite3` 与 RAG 之间没有跨库外键，恢复后最坏表现为 404/空列表。

### 6.2 部署顺序与回滚

见 `docs/ui-refresh/MIGRATION_AND_ROLLBACK.md`。要点：

1. 先备份并在副本上恢复演练；
2. 先发后端但保持 `UI_EXTENSION_ENABLED=false`（行为与原 V3 完全相同）并确认健康；
3. 再开开关并设置 `CMUI_DATA_DIR` / `UI_TASK_AGENT_URL`；
4. 最后发前端并确认 `/` 与 `/app` 都正确。
5. 最小回滚是 `UI_EXTENSION_ENABLED=false` + 重启；**只回滚代码与配置，不回滚新库**，
   否则会丢掉用户在新 UI 里产生的评论、私信、任务与上传。

---

## 7. 权限确认记录

| 项目 | 状态 |
|---|---|
| 本会话弹出的原生授权提示框 | **0 次** |
| 已批准但未执行的动作 | **0 项** |
| 拒绝的动作 | **0 项**（因批准通道被禁用，无法申请） |
| 读取过的真实凭证 | **无**。没有打印、没有读取任何 API Key / 密码 / 私钥内容 |
| 请求用户提供密钥 | **无** |
| 新增云资源 / 套餐 | 无 |
| Git push | 无 |
| Netlify 发布 | 无 |
| 生产数据库访问 | 无 |
| 服务重启 | 无 |
| 模型配置 / endpoint / 预算变更 | 无 |
| 真实模型费用 | **CNY 0.00** |

会话中检查过 `C:\Users\Hp\.dsh\.credentials.yaml` 的**键名结构**，取值为 `<REDACTED>`，
未读取任何值。

---

## 8. 未完成事项（明确保留，不改成 PASS）

1. **真实千问两阶段教学** — `NOT RUN`，需预算授权。
2. **真实 Clerk 登录全流程** — `NOT VERIFIED`，需真实 Clerk 应用与账号。
3. **真实图像题视觉正确率** — `NOT VERIFIED`（传输契约已测）。
4. **真实 Node 工具调用的模型侧选择** — `NOT VERIFIED`。
5. **生成 runner 多 worker 支持** — **未实现**。`cm_update` 的生成任务表是单进程内存结构
   （启动时把残留 run 标记为 `failed/SERVER_RESTARTED`）。多 worker 生产必须把生成搬到
   既有持久化 worker。
6. **多 worker 生成支持** — **未实现**。`cm_update` 的生成任务表是单进程内存结构
   （启动时把残留 run 标记为 `failed/SERVER_RESTARTED`）。多 worker 生产必须把生成搬到
   既有持久化 worker。
7. **原仓库既有浏览器 E2E（`coursemate.spec.ts`）** — 本次**未运行**；
   既有站点由 455 项后端测试与 49 项前端测试回归覆盖。
8. **生产多用户隔离、管理员边界、公开审核线上验收** — `NOT VERIFIED`。
9. **开发执行模型仍为 `deepseek-v4-flash`**，与用户要求的 `deepseek-v4-pro` 不一致（§0.1）。

### 8.1 本轮（goal round 1）新闭环的一项

**旧 V3 问答历史在新壳内可读**：上一轮列为"未实现"，本轮已实现并验证。
`app/ui_extension/mount.py:_prepend_legacy_history` 新增两条只读路由，
`domain.py` 新增 `legacy.conversations` / `legacy.conversation` 两个 operation，
学习页历史弹窗底部新增"旧版问答记录"分组与只读阅读器。
**没有把旧记录复制进新表**——仍是原 `conversations`/`messages` 上的投影。
证据：7 项 Python 测试（含跨用户隔离、私人课程 404、未登录 401）+
浏览器用例 7（断言无重命名/删除按钮、无输入框）。

## 9. 关键产物

| 文件 | 内容 |
|---|---|
| `docs/ui-refresh/HANDOVER_BASELINE.md` | 接手前的真实工作区/Git/接口事实与复用结论表 |
| `docs/ui-refresh/INTEGRATION_MAP.md` | 每个 DomainPort operation 的真实落点与调用点约束 |
| `docs/ui-refresh/MIGRATION_AND_ROLLBACK.md` | 数据影响、部署顺序、环境变量、备份与回滚边界 |
| `docs/ui-refresh/UI_AND_BACKEND_TEST_REPORT.md` | 本次全部测试结果、浏览器发现的缺陷、未验证项 |
| `docs/ui-refresh/QWEN_LIVE_TWO_STAGE_REPORT.md` | 两阶段链路落点、密码学边界、授权后的 canary 方案 |
| `DSH_EXECUTION_STATE.md` | 跨会话恢复用状态文件 |
| `services/rag-api/app/ui_extension/` | 真实 DomainPort / 身份桥 / 宿主挂载 |
| `services/rag-api/app/cm_update/` | 交付包后端（合入） |
| `apps/web/src/ui/`、`ui.html`、`src/CourseMateUi.tsx` | 新壳源码与真实构建入口 |
| `tests/e2e/ui-refresh.spec.ts`、`playwright.ui.config.ts` | 原生浏览器验收 |
| `scripts/serve_web_dist.mjs` | 按 Netlify 规则服务正式产物的验收用静态服务器 |
| `scripts/seed_legacy_conversation.py` | 只向 `work/e2e-*` 副本注入一条旧 V3 会话，供浏览器验收 |
