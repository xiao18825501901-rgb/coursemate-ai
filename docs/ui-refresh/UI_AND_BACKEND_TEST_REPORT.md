# UI AND BACKEND TEST REPORT — 整合后的真实测试

**测试日期**：2026-09-15（含 2026-09-14 的历史轮次；本表为当前总表）
**被测对象**：`feature/dsh-ui-refresh-integration` 上的整合结果（不是交付包的独立实现）
**结论口径**：只有本文件列出的、本次真实运行过的结果才算通过；交付包原有结论一律不继承。

---

## 1. 结果总表

| 套件 | 命令 | 结果 | 证据 |
|---|---|---|---|
| rag-api 全量回归（含原 329 项 + 新增） | `services/rag-api/.venv/Scripts/python.exe -m pytest -q` | **473 passed**, 455.28s | 本次运行 |
| 交付包契约测试（迁入后） | `pytest tests/ui_extension -q` | **71 passed** | 本次运行 |
| 新增 V3 DomainPort 集成测试 | `pytest tests/test_ui_extension_integration.py -q` | **16 passed** | 本次运行 |
| 新增任务 Agent 桥测试 | `pytest tests/test_ui_extension_task_agent.py -q` | **15 passed** | 本次运行 |
| 新增 CORS / 凭证契约测试 | `pytest tests/test_ui_extension_cors.py -q` | **13 passed** | 本次运行 |
| 新增恢复单元测试（含新增 UI 库） | `pytest tests/test_backup_ui_extension.py -q` | **4 passed** | 本次运行 |
| 新增旧版问答历史测试 | `pytest tests/test_ui_extension_legacy_history.py -q` | **7 passed** | 本次运行 |
| 新增课程生命周期测试 | `pytest tests/test_ui_extension_course_lifecycle.py -q` | **3 passed** | 本次运行 |
| 新增学习状态闭环测试（journey 写入 + 完整测评） | pytest tests/test_ui_extension_learning_closure.py -q | **5 passed** | 本次运行 |
| 新增单 worker 生成安全测试（租约回收/取消竞争/不重试） | pytest tests/test_ui_extension_single_worker.py -q | **4 passed** | 本次运行 |
| 新增非空知识树 + 双模式流程测试（层级/双状态/Problem→Step→Bridge→Teach→Return） | pytest tests/test_ui_extension_tree_and_dual_mode.py -q | **3 passed** | 本次运行 |
| 新增 `test` 模式确定性 Provider 测试（选择路径 + 生产拒绝） | pytest tests/test_ui_extension_test_provider.py -q | **3 passed** | 本次运行 |
| 原备份/恢复测试（回归） | `pytest tests/test_backup_restore.py -q` | **9 passed** | 本次运行 |
| web 单元测试（含真实 Clerk 桥） | `vitest run`（`apps/web`） | **55 passed** | 本次运行（复跑） |
| Node Agent 单元测试 | `npm test`（`services/agent-api`） | **66 passed** | 本次运行（复跑） |
| Node Agent 类型检查 + 正式构建 | `npm run typecheck` + `npm run build` | **通过** | 本次运行（复跑） |
| 正式 React 生产构建 | `tsc -b && vite build`（Clerk 形态） | **通过**；产物无测试令牌、含 Clerk | 本次运行（重建后重新扫描） |
| 原生 Chromium 端到端验收（新壳） | `playwright test --config playwright.ui.config.ts` | **17 passed**, 1.3m | 本次运行（含覆盖闭环用例） |
| 原仓库既有 E2E（`coursemate.spec.ts`） | `npx playwright test` | **4 passed** | 本次运行（复跑） |
| 原 V3 学习 E2E（`learning.spec.ts`） | `npx playwright test --config playwright.v3.config.ts` | **3 passed** | 本次运行（复跑） |
| 真实千问两阶段 | — | **NOT RUN** | 无预算授权 |

**接手前基线对照**：rag-api 原为 329 passed；新增套件按上表累计
（71 + 16 + 15 + 13 + 4 + 7 + 3 + 5 + 4 + 3 + 3 = 144 个新增 UI-extension 测试），
且原 329 项全部保持通过。

> 注：本表为**当前总表**。历史轮次的 448/455/458 等数字不再作为当前结论，
> 只作为当时的阶段记录保留在旧提交历史里。

## 2. 新增测试覆盖了什么（真实行为，不是 mock 断言）

### 2.1 `test_ui_extension_integration.py` — 挂载在真实 V3 上的新 UI

用 `app.main.create_app(v3_enabled=True, ui_extension_enabled=True)` 构建真实宿主应用，
经 `app.ui_extension.mount` 挂载交付的新 UI，再用 HTTP 驱动。数据全部来自真实
`courses` / `documents` / `document_versions` / `chunks` 表。

* 宿主路由 `/health` 与 UI 路由 `/ui-extension/...` 同时可用；宿主 lifespan 保留。
* `/config` 报告 `integration_mode=integrated`、`auth_mode=injected`，且响应字段集合被
  精确断言——不泄露任何模型凭据。
* 未登录 / 未知 token → 401。
* `course.list` 返回真实 V3 课程，并带回 `name`、`code`、`requirements`
  （后两者是两阶段千问的硬索引键）。
* 私人课程对其他用户 404，且不出现在其课程列表。
* 上传落到**调用者自己的 workspace 私有语料课程**，列表带 `scope=private`、
  `status=indexed`，且 DTO 里没有 `storage_key` / `owner`；其他用户看不到。
* 文件内容就是授权的原件字节；`Range: bytes=0-9` → 206 且 10 字节；`HEAD` 空体；
  共享课程资料任何登录用户可读，**私人上传对他人 404**。
* `file.text` 返回真实 `chunks` 文本。
* `context.retrieve` 用 V3 `HybridRetriever`（FTS5 + 向量 + RRF）返回课程语料，
  来源编号严格 `S1..Sn`；**另一用户的私有内容不进入结果**。
* 无已发布知识树时 `knowledge.tree` 返回 `[]`（不伪造节点）。
* 未知节点测评 → 404（不伪造成绩）。
* 未配置任务 Agent 时 `/tasks` → 503，带明确说明，不返回假数据。
* 双用户收藏互相独立；评论回复生成对方通知、自己无通知；私信跨账号可读、第三人不可读。
* 未实现的 operation → 501。

### 2.2 `test_ui_extension_task_agent.py` — Node 任务 Agent 真实接线

用一个严格复刻 `services/agent-api` 契约的本地 HTTP 桩（含 `validateCreateTask` 的
JSON Schema 校验）验证：

* 创建/列出/改名/完成/删除全部经 Agent REST 完成，**转发调用方原始 Bearer 凭据**。
* 日期只发 `YYYY-MM-DD`（Agent 只接受这个格式）。
* `task.list` 按凭据隔离；B 看不到 A 的任务。
* 陈旧 `version` → 409，且 Agent 侧记录不变。
* 他人任务 → 404（update 与 delete 均如此）。
* `task.plan` 走 `POST /api/agent/chat`（原 Function Calling Agent），
  不做正则、不返回假成功。
* **未选择的课程被规范化为 null 而不是空字符串**（对应真实 400 缺陷）。
* **未设置的可选字段被省略而不是发 `priority: null`**（对应真实 400 缺陷）。
* 引用不存在的课程 → 404，Agent 侧零写入。
* Agent 不可达 → 502；未配置 → 503。

### 2.3 `test_ui_extension_cors.py` — 浏览器可用性契约

交付的 `api.js` 固定发送 `credentials: 'include'`，所以浏览器要求预检与响应都带
`Access-Control-Allow-Credentials: true`。参数化覆盖 `GET/PUT/DELETE/POST/PATCH`
共 10 条真实路径；未列入白名单的 origin 得到 400 且**没有** allow-origin 与
allow-credentials；扩展响应强制 `private, no-store`。

### 2.4 `test_backup_ui_extension.py` — 恢复单元

* 设置 `CMUI_DATA_DIR` 时，`ui.sqlite3` 与 `ui-uploads.tar.gz` 进入同一恢复单元，
  写进 `manifest.json`，并通过校验和、完整性、外键、上传清单四重校验后恢复。
* 未设置时产物与原恢复单元**逐项一致**（原 9 项备份测试仍通过）。
* 声明了扩展目录但缺少 `ui.sqlite3` → 备份**失败**，不产出"看起来完整"的备份。
* 只声明一半扩展产物 → 恢复拒绝，且不创建目标目录。

### 2.8 `test_ui_extension_learning_closure.py` — 新 UI 到 V3 学习状态的写入闭环

这 5 项测试用真实数据库断言回答"新教学是否进入 V3 状态"：

* 带 `node_id` 的教学 run 先创建 V3 `learning_journeys` 行（与 V3 `teach()` 同一张表、
  同一幂等键），再落 UI 行；`cmui_run_v3` 记录 run→journey 交叉引用。
* **不伪造覆盖**：run 完成后 `teaching_delivery_evidence` 仍为 0 行，节点进度保持
  `NOT_STARTED`（V3 状态推导只认 delivery evidence）。同一节点第二次教学复用同一
  journey（幂等），不会多建行。
* 未知节点 → 404，且**在写任何 UI 行之前**拒绝，不留下 queued 脏行。
* 完整测评往返：start → 5 题 view（题目可见、答案键在提交前**不可见**）→ 提交 5 个
  答案 → `GRADED` + `grade_snapshots` 1 行 + `assessment_sessions.status='GRADED'` →
  节点测评状态更新为 GRADED，而学习进度保持不变（两个状态独立）。
* 弃考后可重新开局；他人对该会话 404（跨用户隔离）。

浏览器侧第 12 号用例把同一流程走了一遍：树中节点 → 测评结果 → 开始测评 → 5 题作答
→ 提交 → "已评阅" + 每题反馈，随后 API 复查节点状态 GRADED 且进度 NOT_STARTED。

### 2.9 默认入口与旧站兼容的浏览器证据

16 号套件前 4 个用例断言：`/` 服务新壳文档并渲染新控制面板；`/app` 兼容别名；
`/qa`、`/courses`、`/admin` 等旧深链仍服务旧文档且可渲染；哈希深链刷新后视图不变、
后退回到控制面板。旧套件 `coursemate.spec.ts`（4/4）与 `learning.spec.ts`（3/3）
验证旧站业务与 V3 学习链路不受影响。

### 2.10 `test_ui_extension_tree_and_dual_mode.py` — 非空层级知识树 + 完整双模式流程（P0-3）

`scripts/seed_tree_fixture.py` 通过真实触发器（DRAFT→PUBLISHED 转换、`teaching_specs`
扇出、`LEGACY_PRESERVED` delivery evidence）种出复合根 + 两个原子子节点。3 项测试断言：

* 层级与真实状态：root COMPOSITE、children `parent=root`；LEARNING 节点
  `required_total=2, covered_required=1`，LEARNED 节点 `1/1`；assessment 独立
  NOT_ASSESSED、grade 为 null（不伪造）。
* 双模式全流程的数据库事实：Problem 生成编号步骤 → Bridge 绑定服务端步骤 →
  Teach 带 bridge 上下文进 Provider（`original_question`/`solution_excerpt`/`step`）
  并写 `cmui_run_v3` journey 链接（journey 状态 LEARNING）→ Return 后 layout 不再
  暴露 bridge。
* 伪造步骤编号 422（"编号步骤"在错误详情里），不产生任何 bridge 行。

### 2.11 `test_ui_extension_test_provider.py` — `test` 模式的确定性 Provider（P0-3 支撑）

浏览器验收需要一个不收费、不冒充千问的确定性 Provider。3 项测试断言：

* `CMUI_PROVIDER_MODE=test` 时挂载扩展的 `/config` 报告 `provider_mode=test`；
* problem/teach run 都能完整跑通（problem 输出两个 step 标题，teach 输出正文）；
* `environment='production'` 下 `validate()` 直接拒绝 `test` 模式——浏览器验收形态
  无法被部署到生产。

## 3. 原生 Chromium 端到端验收（本次实测，替换交付包的 in-memory harness）

**运行形态**：真实 Chromium + 三个真实服务——RAG API（挂载扩展、指向真实 V3 库副本、
`CMUI_PROVIDER_MODE=test`）、既有 Node Agent（`dist/src/server.js`）、以及按 Netlify
规则服务 `apps/web/dist` 正式产物的静态服务器。身份走项目自带的测试验证器
（与生产同一条 `subject_resolver` 代码路径）。config 先注入旧 V3 会话与层级知识树
fixture（`seed_legacy_conversation.py` / `seed_tree_fixture.py`，只写 `work/e2e-*` 副本）。

| # | 用例 | 结果 |
|---|---|---|
| 1 | `/` 提供新壳文档（不是旧文档）、进入新控制面板、无 console 错误 | PASS |
| 2 | `/app` 兼容别名、六个全局入口精确、扩展健康 `mode=integrated`、无 5xx | PASS |
| 3 | 旧深链 `/qa` `/courses` `/admin` 仍服务旧文档且可渲染 | PASS |
| 4 | 哈希深链刷新保持视图、后退回到控制面板 | PASS |
| 5 | 首次控制面板只有虚线创建框；从"所有课程"加号收藏后出现课程卡，刷新后仍在；课程导航与卡片入口指向同一路由 | PASS |
| 6 | 真实课程资料按文件夹列出；上传私有 MD → 201 `scope=private` `status=indexed`；`/content` 返回 200 原件与 `inline`；`Range` → 206 且 10 字节；预览弹窗可用；下载为 `attachment` | PASS |
| 7 | 真实发帖入库、其他账号可见、无 console 错误 | PASS |
| 8 | 学习页保留全局与课程两条左导航；知识树默认折叠、展开覆盖内容区、双 Pane、拖动分隔条、全屏 Esc、两条历史入口 | PASS |
| 9 | 手动新增计划 → 201；同一记录出现在 Node Agent 自己的 REST 列表；壳内完成后 Agent 记录变为 `completed` | PASS |
| 10 | 原 V3 问答历史在新壳内可读且只读（无重命名/删除/输入框） | PASS |
| 11 | 节点测评入口返回真实 V3 结果（不存在节点 → 404） | PASS |
| 12 | 测评全流程：开始 → 5 题 → 提交 → 已评阅 + 每题反馈；评分后进度仍 NOT_STARTED | PASS |
| 13 | **层级知识树**：根组"数据科学基础"+ 子节点"聚类分析/学习中"、"K-means 聚类/教学已完成"、测评入口"未测评"；API 复读同一批 DB 事实 | PASS |
| 14 | **双模式流程**：题目生成 2 个步骤按钮 → 点第 1 步 → 教学 Pane 出现"返回原题 · 第 1 步"横幅并完成教学 → 返回后横幅消失、回到 step 锚点、服务端 bridge 置 returned | PASS |
| 15 | **覆盖闭环（浏览器级）**：树节点"聚类分析"从 LEARNING(1/2) 教学 → 状态行"已计入覆盖" → 挂载 API 读回 LEARNED(2/2)（确定性评审器确认第二项，REVIEWED 证据） | PASS |
| 16 | **知识树键盘与触屏可达**：Enter 展开树 → Tab/焦点揭示节点两个状态入口 → Enter 学习进度开始教学并收拢树；390px 下 tap 节点 → tap 学习进度 → 切到知识学习 tab 并生成教学（`hasTouch` 上下文） | PASS |
| 17 | 390px 视口下无横向溢出 | PASS |

### 2.5 `test_ui_extension_legacy_history.py` — 旧记录不丢失
新壳的历史在 `cmui_conversations`/`cmui_messages`，旧 V3 历史在
`conversations`/`messages`。**没有**做任何把旧记录复制进新表的迁移（复制会产生两份会
各自漂移的历史）。改为在原表上做只读投影：

* 列出一个课程下**本人**的旧对话，带真实 `title`、`message_count`、`updated_at`；
* 另一用户得到空列表；私人课程对他人 404；
* 详情返回真实消息（role 顺序、正文、引用 JSON）；
* 他人不可读；不存在的 id → 404；未登录 → 401。

### 2.6 `CourseMateUi.test.tsx` — 真实 Clerk 桥（此前零覆盖）

所有浏览器用例都用后端的测试验证器，走的是 `TestAuthBridge` 分支。
**生产分支 `AuthBridge`（真实 Clerk）此前从未被执行过**，包括一个真实的上线风险。
本组测试用 mock 的 `@clerk/react` 直接驱动它：

* `getToken()` 真的委托给 Clerk 的 `useAuth().getToken()`，返回会话 token；
* `subscribe()` 返回可安全调用的退订函数；
* `signIn()` 调到 Clerk 自己的 `openSignIn()`（不是自己造登录界面）；
* `signOut()` 调到 Clerk 的 `signOut()` 且 resolve；
* 卸载时 `window.CourseMateAuth` 被移除，不留悬空桥；
* **没有 publishable key 时失败关闭**：显示"认证未配置"，且**不安装** `window.CourseMateAuth`、
  不渲染壳。

> 第 6 项的第一次运行是失败的：测试环境没有 `VITE_CLERK_PUBLISHABLE_KEY`，
> 组件正确地走了失败关闭分支。这既证明该分支生效，也说明**不能**在没有该变量的构建里
> 悄悄渲染出未认证的壳。

### 2.7 `test_ui_extension_course_lifecycle.py` — 课程不会被删一半

进入课程的文件/学习视图会按设计创建调用者的 `learning_workspaces` 行
（及其私有语料课程）；原 V3 ingestion 服务在 workspace 存在时拒绝删除该课程。

* 没有 workspace 的私人课程：正常删除，之后 404；
* 确认名称不匹配：422，课程保持不变；
* **有 workspace 的课程：409 + 明确说明，且课程与私有语料都原样保留**——
  不是 500，也不是删一半。

（本轮先怀疑这里会抛未处理的上游错误，实测确认适配器已正确翻译为 409；
记录为"已实测的正确行为"而非缺陷。）

### 浏览器测试发现并修复的真实缺陷（6 项）

这些都是任何服务端测试都看不到的问题：

1. **宿主 CORS 只允许 `WEB_ORIGIN`**，来自其它已批准站点的预检在扩展看到请求之前
   就被 400 拒绝。修复：挂载扩展时把扩展允许的 origin 并入宿主策略。
2. **`PUT` 不在宿主允许的方法里**，而收藏课程用 `PUT /courses/{id}/pin`。
   修复：仅当扩展挂载时加入 `PUT`。
3. **`Access-Control-Allow-Credentials` 缺失**：Starlette 为被挂载的子应用应答预检时
   不带该头，浏览器因此拒绝一切请求。修复：在宿主对扩展路径补该响应头
   （仅响应头，不含任何 cookie 或凭据；白名单外 origin 仍拿不到 allow-origin）。
4. **`no-store` 未生效**：交付包的中间件按字面 `/api/` 前缀判断，挂载后路径是
   `/ui-extension/api/...`，永不匹配。修复：宿主对扩展响应统一设置
   `Cache-Control: private, no-store`。
5. **日历创建任务 400**：适配器把空课程发成 `courseId: ""`、把可选项发成
   `priority: null`，而 Agent 的 JSON Schema 两者都不接受。修复：未选择发 null、
   未设置则省略字段。这一条只有把真实 Agent 接上才会暴露。
6. **"返回原题"后桥接横幅不消失**（P0-3 双模式浏览器用例首跑发现）：
   `backToProblem()` 把服务端 bridge 置为 `returned` 但不清除本地 `state.bridge`，
   横幅一直留在教学 Pane。修复：返回时同时清空本地 bridge 状态。
   用例 14 断言返回后横幅数 0 + 服务端 `layout.bridge` 为 null。

## 4. 正式 React 生产构建（三种形态如实区分，本轮更正）

`VITE_CLERK_PUBLISHABLE_KEY` 是**构建期**变量：不给 key 时 `CourseMateUi` 的 Clerk
分支被 tree-shake，产物只渲染"认证未配置"（fail-closed）。因此产物分三种形态：

| 形态 | 构建变量 | 产物 | 实测内容 |
|---|---|---|---|
| E2E 形态 | `VITE_AUTH_TEST_TOKEN` + `VITE_UI_API_BASE` | `ui-rTcXnucO.js`（348.42 kB） | 含 TestAuthBridge；只服务浏览器验收，**绝不可发布** |
| Clerk 验证形态 | 无 test token + 假 `pk_test_...` key（仅本地扫描） | `ui-Bckh22_y.js`（348.59 kB，SHA 前 16 位 `B4BA950D3047F0A6`） | 含 `window.CourseMateAuth` 桥、`openSignIn({fallbackRedirectUrl: origin+'/'})`；**不含** `test-session-token`/`TestAuthBridge`——证明真实 Clerk 分支完整进入生产形态产物 |
| fail-closed 形态 | 无任何 key/token | `ui-C60rpF3L.js`（264.26 kB，SHA 前 16 位 `9C9214A661399002`） | 渲染"认证未配置" |

**更正**：此前报告"正式产物不含 test-session-token 且包含 Clerk 客户端"不准确——
当时的产物是 fail-closed 形态（shell 内无 Clerk 分支），"包含 Clerk"测得的是共享
chunk 里的 Clerk 库。生产 Netlify 构建必须设置真实的 `VITE_CLERK_PUBLISHABLE_KEY`，
否则发布的就是 fail-closed 形态（壳只显示"认证未配置"，不破坏数据但不可登录）。

* 使用**原仓库的** React 19.2.8 + Vite 8.2.1 + TypeScript 5.9.3 工具链，未新增框架。
* 新增唯一运行时依赖：`katex@0.16.22`（替代交付包 265 KB 的离线 vendor 副本）。
* 双文档产物：`index.html`（旧站深链）+ `ui.html`（新壳，`/` 默认入口与 `/app` 别名）。
* **交付包的离线 React16 `web/dist` 未被使用、未被复制、未被发布**；
  `app/cm_update/config.py` 的生产门仍然会在检测到 `not_for_production` 时拒绝启动。
* 依赖审计：`npm install` 报告 `found 0 vulnerabilities`。
* **全资源扫描**（closure §六.5）：`test-session-token` 在源码/配置中只出现在 6 个
  预期位置（`AuthProvider.tsx`、`CourseMateUi.tsx`、两个 playwright config、
  agent `auth.ts`、rag `auth.py`），全部由 `AUTH_TEST_USER_ID`/测试构建显式启用；
  发布形态产物（fail-closed 与 Clerk 验证形态）均不含该标记；agent 产物中的
  测试策略只在操作员设置 `AUTH_TEST_USER_ID` 时启用，不是生产旁路。

## 5. 未验证项（明确保留）

| 项 | 状态 | 说明 |
|---|---|---|
| 真实 Clerk 登录 / 登出 / 刷新 / 恢复 | **NOT VERIFIED** | 需要真实 Clerk 应用与真实账号。桥的**代码路径**已由 `CourseMateUi.test.tsx` 6 项覆盖（token 委托、订阅、登录、登出、卸载、失败关闭），但浏览器侧的完整 Clerk 会话流程（真实域名、Clerk 脚本、CORS、cookie）仍未跑 |
| 真实千问两阶段教学 | **NOT RUN** | 无付费授权，见 `QWEN_LIVE_TWO_STAGE_REPORT.md` |
| 图片题视觉正确率 | **NOT VERIFIED** | 传输契约已测，模型是否"看对题"未测 |
| Node 工具调用的真实模型选择 | **NOT VERIFIED** | Agent 侧桩与确定性客户端已测，真实模型多轮工具调用未测 |
| 生产双用户隔离 | **NOT VERIFIED** | 本地真实库双用户已测，生产未测 |
| 生产 PDF 内置查看器（CSP/插件） | NOT VERIFIED | 本地 Chromium iframe 预览通过 |
| 多 worker 生成 runner | **单 worker 防护已实现，多 worker 仍不支持** | Schema 3 租约/心跳/回收/条件写入已落地（4 项双进程测试）；内存任务表意味着扩容需持久化 worker，见 `MIGRATION_AND_ROLLBACK.md` §8 |
| 旧 V3 会话在新壳内的只读入口 | **已实现** | 见 §2.5 |

## 6. 环境

| 项 | 值 |
|---|---|
| OS / Shell | Windows，PowerShell 7（`pwsh`） |
| Python | 3.12.14（`services/rag-api/.venv`），pytest 9.1.1 |
| Node / npm | v24.19.0 / 11.17.0（必须用 `npm.cmd`，`npm.ps1` 被执行策略拦截） |
| 浏览器 | Google Chrome（`C:\Program Files\Google\Chrome\Application\chrome.exe`），Playwright 1.62.1 |
| 时间 | 2026-09-15 |

## 7. 已知的测试不稳定（如实记录）

`apps/web` 的 vitest 套件在本次会话中出现过 **1 次** `1 failed | 48 passed`（早期
49 项时代），随后立即重跑及连续多次均为全绿。失败出现时 vitest 未打印用例名，
且没有留下可复现的断言信息，因此**无法确认**具体用例。同一时间内本机还有
Playwright 的 Chromium 与两个 Node 服务在跑，最可能的原因是资源争用导致的超时。

**当前状态**：套件为 55 项，本轮会话连续 4 次全绿（55/55），未再复现。
**保留的捕捉机制**（closure §六.4，未定位风险不回写为"已解决"）：

```powershell
# 出现失败时，用详细 reporter 复现 5 次并保留完整输出与用例名：
# （路径已实测：apps/web 上一级是 apps/，仓库根在两级之上）
cd apps/web
& ..\..\node_modules\.bin\vitest.cmd run --reporter=verbose 2>&1 | Tee-Object ..\..\work\vitest-capture.log
# 若仅资源争用，关闭并发的 Playwright/Node 服务后单独重跑：
& ..\..\node_modules\.bin\vitest.cmd run
```

任何复现都必须记录：失败用例名、完整断言输出、当时并发负载；复现后修复并补回归，
未复现则保持"未定位低频风险 + 上述捕捉机制"的如实状态。

## 8. 原仓库既有 E2E（此前遗漏，本轮已运行）

`coursemate.spec.ts` 此前一直标为"未运行"。本轮补齐并**4/4 通过**；`learning.spec.ts`
（V3 学习/公开审核链路）也以 `playwright.v3.config.ts` 运行，**3/3 通过**。

运行时修的两处环境问题：

1. 旧套件的 vite 环境没有 `VITE_UI_API_BASE`，新壳在根地址引导时会打到 dev server
   （HTML 当 JSON 解析报错）。现在 `playwright.config.ts` 的三个 webServer 环境
   与 `playwright.ui.config.ts` 一致：RAG API 挂载扩展、vite 指向
   `http://127.0.0.1:8000/ui-extension/api/ui/v1`。
2. 根地址语义变了（新壳是默认入口），旧的"390px 移动端"用例原先断言旧落地页；
   已更新为：根地址断言新壳六入口 + 无横向溢出，旧站移动流程改在 `/tasks` 深链上断言。

另外修了一个由本套件暴露的 dev 服务器缺陷：开发路由中间件曾经把
`/node_modules/.vite/...` 的预打包模块请求也回成 HTML，导致旧应用在 dev 模式整页崩溃
（正是旧套件此前 3 个用例失败的根因——不是用例本身过期）。修复后 dev 与 Netlify 路由
表一致：只有干净的文档路径才重写，任何真实资源直接放行。

## 9. 如何复现

```powershell
$repo = "C:\Users\Hp\Documents\Codex\2026-08-11\files-mentioned-by-the-user-coursemate\outputs\coursemate-ai"

# 后端全量
Set-Location "$repo\services\rag-api"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider

# 前端单测 + 正式构建
Set-Location "$repo\apps\web"
& "$repo\node_modules\.bin\vitest.cmd" run
Set-Location $repo
& npm.cmd run build --workspace @coursemate/web

# 原生浏览器验收（需先按部署形态构建带测试令牌的验证包）
Set-Location "$repo\apps\web"
$env:VITE_AUTH_TEST_TOKEN = "test-session-token"
$env:VITE_UI_API_BASE = "http://127.0.0.1:8100/ui-extension/api/ui/v1"
$env:VITE_V3_ENABLED = "true"
& "$repo\node_modules\.bin\vite.cmd" build
Set-Location $repo
& "$repo\node_modules\.bin\playwright.cmd" test --config playwright.ui.config.ts
# 验收完必须恢复正式构建：
Remove-Item Env:VITE_AUTH_TEST_TOKEN, Env:VITE_UI_API_BASE, Env:VITE_V3_ENABLED
& npm.cmd run build --workspace @coursemate/web
```
