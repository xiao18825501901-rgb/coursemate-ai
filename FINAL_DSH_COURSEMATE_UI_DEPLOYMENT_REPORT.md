# FINAL DSH COURSEMATE UI DEPLOYMENT REPORT

**报告时间**：2026-09-15（Asia/Hong_Kong，本地收尾轮）
**执行者**：DSH（DeepSeek Harness）
**仓库**：`C:\Users\Hp\Documents\Codex\2026-08-11\files-mentioned-by-the-user-coursemate\outputs\coursemate-ai`
**分支**：`feature/dsh-ui-refresh-integration`
**接手前基线**：`64e57501b380ffaefb55db92ef0fc328c39b0928`
**本次最终 SHA**：见 `git rev-parse HEAD`（本报告随最终提交入库，SHA 由该提交自身决定）

```text
SOURCE INTEGRATION:               PASS
LOCAL TEST SUITE:                 PASS  (486 rag-api + 55 web + 66 agent)
MODERN REACT PRODUCTION BUILD:    PASS  (React 19.2.8 + Vite 8.2.1 + tsc 5.9.3)
NATIVE BROWSER ACCEPTANCE:        PASS  (17/17 real Chromium journeys, new shell)
LEGACY SITE E2E:                  PASS  (coursemate.spec.ts 4/4, learning.spec.ts 3/3)
LIVE QWEN TWO-STAGE:              NOT RUN   (no paid authorization available)
REAL CLERK SIGN-IN:               NOT VERIFIED
PRODUCTION DEPLOYMENT:            NOT PERFORMED
AUTHENTICATED PRODUCTION ACCEPTANCE: NOT VERIFIED
OVERALL: SOURCE-COMPLETE AND LOCALLY VERIFIED — NOT PUBLISHED
```

---

## 0. 必须放在最前面的两件事

### 0.1 开发执行模型已与用户要求一致（本轮核对）

`C:\Users\Hp\.dsh\settings.yaml`：

```yaml
agent-default-model:
  provider: deepseek-official
  model: deepseek-v4-pro
  reasoningEffort: max
```

用户在本轮切换后，本会话执行模型为 **deepseek-v4-pro**，与要求一致。
**网站教学模型不变**：仍是 `qwen3.8-max`
（`services/rag-api/app/config.py:v3_model`，`Literal["qwen3.8-max"]`），
新 UI 复用**同一个**模型凭据，没有新增第二份 key，也没有用 DeepSeek
生成任何教学内容。

### 0.2 本会话无法弹出授权框，因此生产动作一步都没有做

会话策略为 `approval_policy: never`——**批准提示被禁用，需要批准的动作会被自动拒绝**。
因此本会话没有、也不可能取得生产部署 / 真实付费模型 / 凭证变更的授权。

所以：**没有付费调用、没有生产写入、没有迁移、没有重启服务、没有 Git push、
没有 Netlify 发布。** 这不是省略步骤，而是在无授权通道时的唯一正确行为。
恢复授权通道的最小操作卡见 §7.1 与 `docs/ui-refresh/RELEASE_CLOSURE_CHECKLIST.md` §三。
`scripts/Request-DeploymentApproval.ps1` 默认只产生业务同意记录；除非真实代码证明它接入
Harness 审批决策，否则它不能改变 `never`（见 §7.1 的四项区分）。

---

## 1. 源码整合

**把交付包作为真实增量合入原仓库，而不是发布它的独立实现。**

| 项 | 结果 |
|---|---|
| 交付包后端模块 | `services/rag-api/app/cm_update/`（15 个交付文件） |
| 与包 `FILE_MANIFEST.json` 的 hash 比对 | **9 个逐字节一致**，6 个有意修改（`app.py`、`db.py`、`config.py`、`integration.py`、`provider.py`、`seed.py`，见 §1.1），0 个缺失 |
| 交付包前端模块 | `apps/web/src/ui/`（8 个文件） |
| 与包 `web/src` 的 hash 比对 | **6 个逐字节一致**（`App.jsx`、`api.js`、`icons.jsx`、`utils.js`、`richtext.jsx`、`styles.css`），2 个**纯新增式**修改（`pages.jsx`、`styles-extra.css`，见 §1.1） |
| 真实 `DomainPort` 适配器 | `services/rag-api/app/ui_extension/domain.py`，实现全部 **26** 个 operation（22 个交付 ops + `knowledge.begin_learning`、`knowledge.assessment.start/view/submit/abandon`、`legacy.conversations/conversation`） |
| 注入式身份桥 | `app/ui_extension/identity.py`，绑定宿主 Clerk 验证器 |
| 宿主挂载 | `app/ui_extension/mount.py` + `app/main.py`（默认关闭） |
| 新 React 壳 | `apps/web/src/ui/*`、`src/CourseMateUi.tsx`、`src/main.ui.tsx`、`ui.html` |
| 默认入口路由 | `netlify.toml` + `scripts/serve_web_dist.mjs` + `apps/web/vite.config.ts` 三处共享同一决策表：`/` 与 `/app` → `ui.html`（新壳），旧深链前缀 → `index.html` |
| Node 任务桥 | `domain.py` 的 `task.list/create/update/delete/plan` |
| 旧 V3 问答历史只读入口 | `mount.py:_prepend_legacy_history` + `domain.py:legacy.*` |
| 恢复单元扩展 | `ops/backup_v2.py`、`ops/restore_v2.py` |

### 1.1 对交付包源码的修改（全部为可移植性/正确性/纯新增，无功能删减）

| 文件 | 修改 | 为什么必须改 |
|---|---|---|
| `app/cm_update/provider.py` | `read_text()` → `read_text(encoding='utf-8')`；新增 `TestProvider` | Windows 中文 locale 是 GBK，会在**真实付费调用**路径上抛 `UnicodeDecodeError`；`TestProvider` 是 `provider_mode='test'` 的确定性本地/浏览器验收 Provider，生产被 `validate()` 拒绝 |
| `app/cm_update/config.py` | 同上，读 build 标记 | 同一类缺陷，且位于 production 启动门 |
| `app/cm_update/seed.py` | 新增可选 `documents` 参数 | 原实现从包根 `sample-documents/` 读示例 PDF；本仓库不发布示例课程资料 |
| `app/cm_update/app.py` | ① run 带 `node_id` 时先走 `knowledge.begin_learning` 并写 `cmui_run_v3` 交叉引用；② Schema 3 单 worker 租约（`lease_worker`/`lease_heartbeat`、心跳、只回收过期租约、跨进程取消复读、条件式最终写入）；③ `provider_mode='test'` 选择 `TestProvider` | 学习闭环接线（journey 起步，不伪造覆盖）；把单 worker 从口头约定变成可执行防护；浏览器验收需要一个不收费、不冒充千问的确定性 Provider |
| `app/cm_update/db.py` | `SCHEMA_VERSION=3`、`cmui_run_v3` 表、`cmui_runs` 租约列幂等 `ALTER` | 上述两条的持久化；旧库首次以新代码启动自动补列 |
| `app/cm_update/integration.py` | `install_ui_extension(..., provider=None)` 测试接缝 | 宿主挂载时注入测试 Provider 的唯一入口；生产挂载不传 |
| `apps/web/src/ui/pages.jsx` | 历史弹窗**新增**"旧版问答记录"分组；**新增** `Assessment` 组件；`backToProblem()` 返回后清除本地 bridge 状态 | 旧 V3 问答历史要在新壳内可读；节点测评原本是 `JSON.stringify` 原始 JSON；返回原题后桥接横幅必须消失（浏览器测试发现）。纯新增/单行修复，未改动既有布局或交互 |
| `apps/web/src/ui/styles-extra.css` | **追加** `.legacy-*` / `.assessment-grid` 规则 | 只追加，未修改既有规则 |

**未改动**交付包的 `App.jsx` / `api.js` / `icons.jsx` / `utils.js` / `richtext.jsx` /
`styles.css` / `sse.py` / `steps.py` / `models.py` / `retrieval.py` / `filesystem.py` /
`auth.py` / `main.py`，两阶段千问逻辑 `planner_messages()`/`stream()` 未改一行。

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
* 浏览器验收用 `provider_mode='test'` 的确定性 Provider（侧边栏如实显示
  "测试 Provider · 非真实千问"），跑通 run/SSE/步骤/Bridge 全路径；真实千问状态
  仍为 NOT RUN（§4），**没有用预设回答假装千问**。

---

## 2. 正式 React 生产构建

```
> tsc -b && vite build（@coursemate/web，Clerk 正式形态）
dist/index.html                  0.67 kB │ gzip:  0.39 kB
dist/ui.html                     0.68 kB │ gzip:  0.44 kB
dist/assets/main-jxvg7O-T.css   31.36 kB │ gzip:  6.48 kB
dist/assets/ui-CZNEynfi.css     54.70 kB │ gzip: 12.11 kB
dist/assets/main-sCqwwDOm.js     0.59 kB │ gzip:  0.41 kB
dist/assets/ui-C60rpF3L.js     264.26 kB │ gzip: 77.75 kB
dist/assets/dist-YiqoSCPN.js   309.62 kB │ gzip: 90.63 kB
✓ built in 239ms
```

* 使用**原仓库的**工具链：React 19.2.8、Vite 8.2.1、TypeScript 5.9.3、`@clerk/react` 6.x。
  没有引入新框架，没有降级到离线运行时。
* 新增唯一运行时依赖 `katex@0.16.22`，替代交付包 265 KB 的离线 vendor 副本。
* 依赖审计：`npm install` 输出 `found 0 vulnerabilities`。
* **交付包 `web/dist` 从未被使用、复制或发布**；`app/cm_update/config.py` 的
  production 门会拒绝带 `not_for_production` 标识的产物，该门**未被删除或绕过**。
* **构建形态如实区分三种（本轮更正了此前"正式产物包含 Clerk"的不准确说法）**。
  `VITE_CLERK_PUBLISHABLE_KEY` 是**构建期**变量：没给 key 时 `CourseMateUi` 的 Clerk
  分支被 tree-shake，产物只会渲染"认证未配置"（fail-closed）。因此：
  * **E2E 形态**（`VITE_AUTH_TEST_TOKEN` + `VITE_UI_API_BASE`）：`ui-rTcXnucO.js`
    （348.42 kB）——含 TestAuthBridge，只服务浏览器验收，绝不可发布；
  * **Clerk 验证形态**（无 test token，构建期给一个假 `pk_test_...` key，
    仅本地扫描用）：`ui-Bckh22_y.js`（348.59 kB，SHA 前 16 位 `B4BA950D3047F0A6`）
    ——实测含 `window.CourseMateAuth` 桥、`openSignIn({fallbackRedirectUrl: origin+'/'})`
    （登录后落回新控制面板）、**不含** `test-session-token`/`TestAuthBridge`，
    证明真实 Clerk 分支能完整进入生产形态产物；
  * **fail-closed 形态**（无任何 key/token）：`ui-C60rpF3L.js`（264.26 kB，
    SHA 前 16 位 `9C9214A661399002`）——渲染"认证未配置"。**此前报告的"正式产物含
    Clerk"实际指的是这一形态 + 共享 chunk 里的 Clerk 库**；特此更正：真实 Clerk
    分支只存在于带 key 的构建里，生产 Netlify 构建必须设置真实的
    `VITE_CLERK_PUBLISHABLE_KEY`（见 `MIGRATION_AND_ROLLBACK.md` 环境变量表）。
* 双文档 + 路由决策表（`netlify.toml` / `scripts/serve_web_dist.mjs` /
  `apps/web/vite.config.ts` 三处共享同一张表）：
  `/` → `ui.html`（新壳，**默认入口**）；`/app` → `ui.html`（兼容别名）；
  旧深链前缀（`qa,learn,courses,tasks,documents,admin,about`）→ `index.html`（旧站）；
  真实静态资源永远优先于任何重写。

---

## 3. 本地测试

| 套件 | 结果 |
|---|---|
| rag-api 全量回归 | **486 passed**（554.20s；含新增覆盖闭环 8 项 + 桥接追溯 5 项 + 两处过期断言修复） |
| 交付包契约测试（迁入后） | **71 passed** |
| 新增 V3 DomainPort 集成测试 | **16 passed** |
| 新增任务 Agent 桥测试 | **15 passed** |
| 新增 CORS/凭证契约测试 | **13 passed** |
| 新增恢复单元测试 | **4 passed** |
| 新增旧版问答历史测试 | **7 passed** |
| 新增课程生命周期测试 | **3 passed** |
| 新增学习状态闭环测试 | **5 passed** |
| 新增单 worker 生成安全测试 | **4 passed** |
| 新增非空知识树 + 双模式流程测试 | **3 passed** |
| 新增 `test` 模式确定性 Provider 测试 | **3 passed** |
| 新增覆盖闭环测试（从零覆盖正反验收 + 静默取消看门狗） | **8 passed** |
| 新增桥接全链路追溯测试（V3 题目账本映射 + 教学链） | **5 passed** |
| 原备份/恢复测试（回归） | **9 passed** |
| web 单元测试（含真实 Clerk 桥 6 项） | **55 passed** |
| Node Agent 单测 / typecheck / build | **66 passed** / 通过 / 通过 |
| 原生 Chromium 端到端（新壳） | **17 passed**（1.3m；含"树节点教学 → 状态行已计入覆盖 → API LEARNED 2/2"用例） |
| 原仓库既有 E2E `coursemate.spec.ts` | **4 passed** |
| 原 V3 学习 E2E `learning.spec.ts` | **3 passed** |

细节、命令与逐项覆盖见 `docs/ui-refresh/UI_AND_BACKEND_TEST_REPORT.md`。

### 3.1 原生浏览器测试发现的 6 个真实缺陷（服务端测试看不到）

1. 宿主 CORS 只允许 `WEB_ORIGIN`，其他已批准站点的预检被 400 拒绝。
2. `PUT` 不在宿主允许方法内，而收藏课程用 `PUT /courses/{id}/pin`。
3. Starlette 为被挂载子应用应答预检时不带 `Access-Control-Allow-Credentials`，
   而交付客户端固定发 `credentials:'include'`，浏览器因此拒绝一切请求。
4. 交付包的 `no-store` 中间件按字面 `/api/` 前缀判断，挂载后永不匹配。
5. 日历新建任务 400：适配器把空课程发成 `courseId: ""`、把可选项发成 `priority: null`，
   而 Node Agent 的 JSON Schema 两者都不接受。
6. 教学 Pane 的"返回原题"横幅在服务端把 Bridge 置为 `returned` 之后仍留在页面上：
   `backToProblem()` 只改 `mobile` 状态、不清除本地 bridge 状态。修复后横幅随返回消失
   （浏览器用例 14 断言返回后横幅数 0 + 服务端 layout.bridge 为 null）。

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
  代码层证据已齐（桥 6 项单测 + 登录返回目标 `fallbackRedirectUrl: '/'` +
  生产形态产物扫描，§2）；浏览器侧真实 Clerk 会话流程仍未跑。
* 生产双用户隔离、管理员边界（NOT VERIFIED）。

---

## 6. 生产部署

**状态：`NOT PERFORMED`。生产环境未被触碰。**

* 早期 V3 报告记录生产为 `qqttai.com` + 后端 release `cd8c121` + Netlify deploy
  `6aa70f2b5a330d5a8ae4be56`——这是**历史快照，本会话未做现场复核**，不能当作
  当前已核验生产状态（复核属于授权后只读核验步骤）。
* 本次**没有**执行备份、迁移、重启、DNS 变更、Git push 或 Netlify 发布。
* 新入口在生产上**不存在**：`UI_EXTENSION_ENABLED` 默认 `false`，且在生产部署前必须保持 `false`。

### 6.1 数据与恢复单元（已备份工具化，未在生产执行）

* 原 RAG `rag.sqlite3`（Schema 21）与 Agent 库 **Schema 未变**：没有新增表、列或迁移文件。
* 新增数据在**独立文件** `<CMUI_DATA_DIR>/ui.sqlite3`（**Schema 3，26 张 `cmui_*` 表**，
  含 `cmui_run_v3` 交叉引用与 `cmui_runs` 租约列）与 `<CMUI_DATA_DIR>/uploads/`。
  `Database.initialize()` 在检测到 `courses`/`chunks`/`tasks`/`schema_migrations` 时
  **拒绝初始化**，不可能覆盖原库；检测到更高版本时**拒绝降级**；
  Schema 3 租约列升级是幂等的（缺列才 `ALTER`）。
* 数据归属以 integrated 模式为准（见 `MIGRATION_AND_ROLLBACK.md` §2 归属表）：
  课程/文件/检索/知识树/教学覆盖/测评在 RAG 库，任务在 Agent 库，
  评论/通知/私信/新壳对话/Bridge 在 UI 库；`cmui_*` 镜像表只在 standalone 模式使用。
* `ops/backup_v2.py` 在设置 `CMUI_DATA_DIR` 时把 `ui.sqlite3` 与 `ui-uploads.tar.gz`
  并入同一恢复单元并写入 manifest；缺少 `ui.sqlite3` 时**备份直接失败**。
  **首次启用必须按 A/B/C 顺序**：A 未设置 `CMUI_DATA_DIR` 时先做一致备份 →
  B 独立路径初始化 UI 库（不运行任何 seed）→ C 设置 `CMUI_DATA_DIR` 后三库两组上传
  纳入新恢复单元（详见 `MIGRATION_AND_ROLLBACK.md` §4）。
* `ops/restore_v2.py` 在发布目标目录**之前**校验：校验和覆盖完整性、未知 artifact 名、
  每个 artifact 的 sha256、`integrity_check`/`foreign_key_check`、
  两个上传归档的成员数与字节数与 manifest 一致，并拒绝 `\\`、绝对路径、`..`、重复路径。
* **跨库原子性限制如实保留**：三个 SQLite `backup` 调用之间没有分布式事务，
  必须在维护窗口内进行。`ui.sqlite3` 与 RAG 之间没有跨库外键，恢复后最坏表现为 404/空列表；
  **跨库无外键 ≠ 数据关联正确**，恢复后必须抽查课程/文件/节点引用、旧对话可读性与任务回执。

### 6.2 部署顺序与回滚

见 `docs/ui-refresh/MIGRATION_AND_ROLLBACK.md`。要点：

1. 首次启用按 A/B/C：先备份（未设 `CMUI_DATA_DIR`）→ 独立路径初始化 UI 库 → 启用后纳入新恢复单元；
2. 先发后端但保持 `UI_EXTENSION_ENABLED=false`（行为与原 V3 完全相同）并确认健康；
3. 再开开关并设置 `CMUI_DATA_DIR` / `UI_TASK_AGENT_URL`；
4. 最后发前端并确认 `/` 与 `/app` 都是新壳文档、旧深链仍回旧站。
5. 最小回滚是 `UI_EXTENSION_ENABLED=false` + 重启；**这只关后端入口，不会回滚 Netlify 前端**，
   前端要单独按**发布前现场记录**的 deploy id 回滚（早期报告里的 id 只是历史快照）。
6. **只回滚代码与配置，不回滚新库**，否则会丢掉用户在新 UI 里产生的评论、私信与对话；
   同理不能因 RAG Schema 未变就随意恢复旧 RAG 库，否则丢掉新课程/新上传/真实覆盖与测评。

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
| Git push | 无（全部提交仅在本地分支） |
| Netlify 发布 | 无 |
| 生产数据库访问 | 无 |
| 服务重启 | 无 |
| 模型配置 / endpoint / 预算变更 | 无 |
| 真实模型费用 | **CNY 0.00** |

会话中检查过 `C:\Users\Hp\.dsh\.credentials.yaml` 的**键名结构**，取值为 `<REDACTED>`，
未读取任何值。

### 7.1 审批通道诊断（closure prompt §9 的四项区分）

| # | 项 | 本轮读到的实际状态 |
|---|---|---|
| 1 | 用户是否批准具体动作/费用 | **未批准**：CNY 5.00 只是报告中的建议；没有任何预算/部署/发布批准记录 |
| 2 | DSH 是否有可回答的原生审批通道 | 本会话有效策略为 `never`（批准提示禁用，需批准的动作被自动拒绝）。GUI 客户端自带 ApprovalPanel 组件（`dsh-client-ui-conversation`），但本会话没有弹出过一次；模型**不能**自行把策略从 `never` 改掉 |
| 3 | 执行工具是否有网络/文件/进程能力 | 文件操作 `danger-full-access`（不受限）；本机命令可执行（受限于执行策略/沙箱规则）；**没有**生产 SSH/托管平台凭据用于线上操作 |
| 4 | GitHub/Netlify/SSH/Clerk/模型账户凭据与角色 | 未验证可用性；本会话**没有**读取任何凭据值（`~/.dsh/.credentials.yaml` 只查键名结构，值为 `<REDACTED>`） |

`scripts/Request-DeploymentApproval.ps1` 默认只产生业务同意记录。除非真实代码证明它
接入 Harness 的审批决策，否则运行它**不能改变 `never`**，也不能当作绕过平台限制的凭证。

**给用户的最小操作卡（就一条）：**

| 字段 | 内容 |
|---|---|
| 位置 | DSH Web GUI（`http://127.0.0.1:3080`）的会话权限/审批预设选择器（GUI 自带 ApprovalPanel，说明通道存在于客户端；`C:\Users\Hp\.dsh\settings.yaml` 里**没有**审批字段，不要凭猜测写 YAML） |
| 操作 | 把当前会话的审批策略从 `never`（禁用）切到 `ask`（询问）或对等可用模式；优先保留其余保护，不必全关 |
| 生效 | 现有会话或新会话（以 GUI 提示为准）；切换后本会话收到一次真实工具审批提示即视为生效 |
| 验证 | 之后我可以发起**一个**无生产影响、无费用、确实需要原生审批的测试动作；只有收到真实审批结果才能宣称通道有效 |

DSH 安装版本：`@deepseek-ai/dsh 0.1.1-rc.2`（`C:\Users\Hp\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh\package.json`）。
开发模型已为 `deepseek-v4-pro`（§0.1），网站模型仍为 `qwen3.8-max`。

---

## 8. 未完成事项（明确保留，不改成 PASS）

1. **真实千问两阶段教学** — `NOT RUN`，需预算授权（建议 CNY 5.00 并非已批准）。
2. **真实 Clerk 登录全流程** — `NOT VERIFIED`，需真实 Clerk 应用与账号（桥已 6 项单测覆盖）。
3. **真实图像题视觉正确率** — `NOT VERIFIED`（传输契约已测）。
4. **真实 Node 工具调用的模型侧选择** — `NOT VERIFIED`。
5. **多 worker 生成支持** — **仍未实现，且如实保留为明确限制**。单 worker 约束已从
   口头约定升级为可执行防护（worker 租约 + 心跳 + 只回收过期租约 + 跨进程取消 +
   条件式最终写入，UI Schema 3；4 项双进程测试 + 浏览器 16 项回归），但内存任务表意味着
   这**不是**多 worker 支持：生产部署检查必须是 rag-api 单进程、单一 `CMUI_DATA_DIR`
   只挂一个实例。要扩容必须把生成搬到 V3 侧尚不存在的持久化 worker。
   详见 `MIGRATION_AND_ROLLBACK.md` §8。
6. **原仓库既有浏览器 E2E** — 本轮已补跑：`coursemate.spec.ts` 4/4、`learning.spec.ts` 3/3
   （两套隔离端口/数据，均不调用付费模型）。
7. **生产多用户隔离、管理员边界、公开审核线上验收** — `NOT VERIFIED`（本地真实库已测）。
8. **生产只读核验、备份现场、受控部署、双用户验收** — `NOT PERFORMED`，需分别授权。

### 8.1 本会话新闭环的四项

**（1）旧 V3 问答历史在新壳内可读**（goal round 1）：`mount.py:_prepend_legacy_history`
新增两条只读路由，`domain.py` 新增 `legacy.conversations` / `legacy.conversation`，
学习页历史弹窗新增"旧版问答记录"分组与只读阅读器。**没有把旧记录复制进新表**。
证据：7 项 Python 测试 + 浏览器用例 10。

**（2）生产 Clerk 桥从零覆盖变为已覆盖**（goal round 2 + 本轮补强）：
之前所有浏览器用例都用后端测试验证器，走的是 `TestAuthBridge` 分支，
**生产分支 `AuthBridge` 从未被执行**——这是一个真实的上线风险。
现由 `apps/web/src/CourseMateUi.test.tsx` 6 项覆盖：token 委托给 Clerk、
退订函数、`signIn` 走 Clerk 弹窗且带 `fallbackRedirectUrl: origin+'/'`
（登录后落回新控制面板）、`signOut` 走 Clerk、卸载清理桥、
**无 publishable key 时失败关闭且不安装桥**。
（该项第一次运行失败，正是因为它正确地走了失败关闭分支。）
本轮进一步做实到**产物层**：用假 `pk_test_...` key 构建的生产形态产物
`ui-Bckh22_y.js` 实测包含 AuthBridge + `openSignIn({fallbackRedirectUrl})`、
不含任何测试令牌（§2），并更正了此前"正式产物含 Clerk"的不准确表述。

同时把课程删除的生命周期用 3 项测试固定下来：无 workspace 正常删除、
确认名称不符 422、**有 workspace 时 409 且课程与私有语料都不受影响**。

**（3）非空层级知识树 + 双模式流程（P0-3，本轮）**：
`scripts/seed_tree_fixture.py` 通过真实触发器（DRAFT→PUBLISHED 转换、
`teaching_specs` 扇出、`LEGACY_PRESERVED` delivery evidence）种出
复合根节点 + 两个原子子节点（LEARNING 1/2 与 LEARNED 1/1）；
`tests/test_ui_extension_tree_and_dual_mode.py`（3 项）断言层级、双状态、
Problem→Step→Bridge→Teach→journey→Return 的数据库事实与伪造步骤 422。
浏览器侧新增 2 个用例（树层级与状态、步骤桥接教学并返回），并因此
给 `provider_mode='test'` 接上确定性 `TestProvider`（生产拒绝该模式），
顺带修复"返回原题后横幅不消失"缺陷。浏览器套件 13 → 15 项。

**（4）单 worker 约束与手册修正（P0-5 / P0-8，本轮）**：
生成 run 增加 Schema 3 租约（`lease_worker`/`lease_heartbeat`）+ 心跳 +
只回收过期租约 + 跨进程取消复读 + 条件式最终写入（`tests/test_ui_extension_single_worker.py`
4 项双进程测试）；`MIGRATION_AND_ROLLBACK.md` 重写为：数据归属表（10 类操作）、
首次启用 A/B/C 顺序、前端独立回滚（现场 deploy id）、恢复后跨库引用抽查。

## 9. 关键产物

| 文件 | 内容 |
|---|---|
| `docs/ui-refresh/HANDOVER_BASELINE.md` | 接手前的真实工作区/Git/接口事实与复用结论表 |
| `docs/ui-refresh/INTEGRATION_MAP.md` | 每个 DomainPort operation 的真实落点与调用点约束 |
| `docs/ui-refresh/MIGRATION_AND_ROLLBACK.md` | 数据归属表、首次启用 A/B/C、部署顺序、环境变量、备份与回滚边界、单 worker 约束 |
| `docs/ui-refresh/UI_AND_BACKEND_TEST_REPORT.md` | 本次全部测试结果、浏览器发现的缺陷、未验证项 |
| `docs/ui-refresh/QWEN_LIVE_TWO_STAGE_REPORT.md` | 两阶段链路落点、密码学边界、授权后的 canary 方案 |
| `docs/ui-refresh/RELEASE_CLOSURE_CHECKLIST.md` | 收尾清单：已完成本地工作/授权后外部任务/用户操作/未证明项 |
| `DSH_EXECUTION_STATE.md` | 跨会话恢复用状态文件 |
| `services/rag-api/app/ui_extension/` | 真实 DomainPort（26 ops）/ 身份桥 / 宿主挂载 |
| `services/rag-api/app/cm_update/` | 交付包后端（合入，9 一致 6 修改） |
| `apps/web/src/ui/`、`ui.html`、`src/CourseMateUi.tsx` | 新壳源码与真实构建入口 |
| `tests/e2e/ui-refresh.spec.ts`、`playwright.ui.config.ts` | 原生浏览器验收（15 项） |
| `scripts/serve_web_dist.mjs` | 按 Netlify 规则服务正式产物的验收用静态服务器 |
| `scripts/seed_legacy_conversation.py`、`scripts/seed_tree_fixture.py` | 只向 `work/e2e-*` 副本注入旧 V3 会话与层级知识树，供浏览器验收 |
