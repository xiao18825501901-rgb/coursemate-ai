# RELEASE CLOSURE CHECKLIST — 本地收尾与真实发布准备

**更新日期**：2026-09-15（Asia/Hong_Kong）
**HEAD**：以 `git rev-parse HEAD` 为准（本文件随提交更新，不写自引用 SHA）
**模型**：开发执行 `deepseek-v4-pro`（`C:\Users\Hp\.dsh\settings.yaml` 已切，本会话一致）；网站教学 `qwen3.8-max`（未变）。
**权限**：本会话 `approval_policy: never`（批准提示禁用，需批准的动作自动拒绝）；文件 sandbox `danger-full-access`。**没有任何动作被"当作已批准"。**

---

## 一、本轮已完成的本地工作（含证据）

### 1. 新 UI 成为默认入口（本地实现 + 测试，未上线切换）

| 项 | 证据 |
|---|---|
| `/` 服务新壳文档并进入新控制面板；**登录完成后也回到新控制面板** | `netlify.toml` / `scripts/serve_web_dist.mjs` / `apps/web/vite.config.ts` 三处共享同一决策表；`tests/e2e/ui-refresh.spec.ts` 用例 1；`CourseMateUi.tsx` 的 `openSignIn({fallbackRedirectUrl: origin+'/'})` + 单测断言（6 项之一）；Clerk 验证形态产物实测含该调用（§一.6） |
| `/app` 兼容别名保留 | 同上，用例 2 |
| 旧深链（/qa /learn /courses /tasks /documents /admin /about）仍服务旧文档且可渲染 | 用例 3；旧套件 `coursemate.spec.ts` 4/4、`learning.spec.ts` 3/3 |
| 哈希深链刷新/后退 | 用例 4 |
| 静态服务器、Vite dev 与 Netlify 三处路由一致 | 三处共享 `documentFor` 决策表 |
| dev 中间件不再吞 Vite 预打包模块（此前旧应用 dev 整页崩溃） | 修复后旧套件 4/4 |
| 上线切换仍为受控发布步骤 | 只改配置与产物；**未 push、未发布** |

### 2. 学习状态闭环审计与最小真实接线

| 审计项 | 结论与证据 |
|---|---|
| 新教学 → REQUIRED 覆盖 | **不直接写覆盖**。`app/learning/knowledge.py:_atomic_learning` 只用 `teaching_delivery_evidence` 计算进度；新壳自由文本教学只写 journey 起步 + `cmui_run_v3` 交叉引用。证据：`tests/test_ui_extension_learning_closure.py`（5 项：delivery_evidence=0、进度 NOT_STARTED） |
| 新教学 → V3 journey | 已接线：run 带 `node_id` 时先创建/复用 `learning_journeys`（幂等），失败不留下 queued 脏行；UI 库 Schema 3 的 `cmui_run_v3` 存 workspace/journey/node 交叉引用 |
| Problem/Step/Bridge 绑定 | UI Bridge（`cmui_bridges`）是壳内返回原步骤的 UX 上下文（服务端抽取真实步骤编号）；V3 `LearningBridge` 是 V3 运行时权威记录，二者是**两个独立系统**，未冒充同名接通 |
| 测评全流程 | **已接通**：start/view/submit/abandon 委托真实 V3 AssessmentService；submit 带 revision 与一次 REVISION_CONFLICT 重试；成绩写入 `grade_snapshots`。浏览器用例 12 走完 开始→5 题→提交→已评阅→每题反馈 |
| 学习与测评独立 | 用例 12 断言评分后进度仍 NOT_STARTED；无成绩不显示伪造分数（无 GradePolicy 时 letter grade 如实为 null） |

### 3. 非空知识树与完整双模式流程（P0-3，本轮补齐）

| 项 | 证据 |
|---|---|
| 带层级的 published 官方树 fixture | `scripts/seed_tree_fixture.py`：复合根（数据科学基础）+ 两个原子子节点（聚类分析、K-means 聚类），走真实触发器（DRAFT→PUBLISHED 转换、`teaching_specs` 扇出、`LEGACY_PRESERVED` delivery evidence） |
| 层级与真实状态（DB 事实） | `tests/test_ui_extension_tree_and_dual_mode.py`：root COMPOSITE、children parent=root；LEARNING=1/2 REQUIRED covered、LEARNED=1/1；assessment 独立 NOT_ASSESSED |
| 双模式完整流程（DB 事实） | 同套件：Problem 生成编号步骤 → Bridge 绑定真实步骤 → Teach 带 bridge 上下文进 Provider + journey 链接 → Return 关闭 bridge、layout 不再暴露；伪造步骤 422 |
| 浏览器树层级与双状态入口 | `ui-refresh.spec.ts` 用例 13：树展开显示根组 + 两子节点，悬停弹层"学习中/教学已完成/未测评"，并用 API 复读同一批 DB 事实 |
| 浏览器双模式点击路径 | 用例 14：题目 → 2 个 step 按钮 → 点第 1 步 → 教学 Pane 出现"返回原题 · 第 1 步"横幅并生成教学 → 返回后横幅消失、回到 step 锚点、服务端 bridge 置 returned |
| 知识树键盘/触屏可达（closure §五.2） | 用例 15：Enter 展开树、焦点揭示两个状态入口、Enter 学习进度开始教学并自动收拢；390px 下 tap 节点 → tap 学习进度 → 切到知识学习 tab 并生成教学（`hasTouch` 上下文） |
| 为此新增的确定性 Provider | `provider_mode='test'` 现在选择 `TestProvider`（`app/cm_update/provider.py`），生产被 `validate()` 拒绝；`tests/test_ui_extension_test_provider.py`（3 项）锁住选择路径 |
| 顺手修复的真实缺陷 | "返回原题"后桥接横幅不消失（`pages.jsx:backToProblem` 未清本地 bridge 状态）——浏览器用例 14 首跑发现，修复后全绿 |

### 4. 单 worker 生成约束（P1-7：实际防护，不是文档提醒）

| 防护 | 证据 |
|---|---|
| 每进程唯一 worker 身份 + run 租约（Schema 3 `lease_worker`/`lease_heartbeat`） | `app/cm_update/db.py`；`tests/test_ui_extension_single_worker.py`（4 项双进程测试） |
| 启动清理只回收失去拥有者的 run（心跳缺失/超 grace 120s） | 同套件：第二个进程启动不再杀第一个进程的进行中 run |
| 生成期间心跳（每 5s，条件更新） | 同套件 |
| 跨进程取消：取消写库优先，生成循环复读状态 | 同套件：取消后不产出消息 |
| 完成/取消竞争由数据库裁决（条件式最终写入） | 同套件 |
| 失败不自动重试、不重复计费 | 既有 provider 测试 |
| 仍为明确限制 | 单实例/单 worker 仍是部署前提（内存任务表 ≠ 多 worker）；扩容需 V3 侧尚不存在的持久化 worker |

### 5. 数据归属表 + 首次启用 A/B/C + 回滚修正（P0-8，本轮补齐）

| 项 | 证据 |
|---|---|
| 数据归属表（10 类操作 → 权威库/目录 → 引用 → 备份 → 回滚影响） | `MIGRATION_AND_ROLLBACK.md` §2：课程/文件/旧问答/覆盖/测评在 RAG 库；任务在 Agent 库；评论/通知/私信/新壳对话/Bridge 在 UI 库；`cmui_*` 镜像表仅 standalone |
| 首次启用 A/B/C 顺序 | 同文档 §4：A 未设 `CMUI_DATA_DIR` 先一致备份 → B 独立路径初始化 UI 库（不跑 seed）→ C 设置后三库两组上传纳入新恢复单元 |
| 回滚修正 | 关后端开关**不会**自动回滚 Netlify 前端；前端回滚用**发布前现场记录**的 deploy id（早期报告 id 只是历史快照）；只回滚代码不回滚新库；不能因 RAG Schema 未变随意恢复旧 RAG 库 |
| 恢复后跨库引用抽查 | 同文档 §5：目录重映射、引用可读性、任务回执、孤引用表现为 404/空列表 |

### 6. 回归与构建（本轮全部实跑）

| 套件 | 结果 |
|---|---|
| rag-api 全量 | **473 passed**（455.28s；新增 `test_ui_extension_test_provider.py` 3 项、`test_ui_extension_tree_and_dual_mode.py` 3 项已并入） |
| 新壳浏览器验收（含树层级、双模式、键盘/触屏 3 项新用例） | **16 passed**（1.1m；本会话多跑：首跑暴露横幅缺陷与 tap 上下文缺失 → 修复 → 全绿） |
| 旧站 E2E `coursemate.spec.ts` | **4 passed**（本轮复跑） |
| V3 学习 E2E `learning.spec.ts` | **3 passed**（本轮复跑） |
| Node Agent 单测 / typecheck / build | **66 passed** / 通过 / 通过（本轮复跑） |
| web 单测（含真实 Clerk 桥 6 项） | **55 passed**（本轮复跑，13 文件） |
| 正式 React 构建 | 三种形态如实区分（本轮**更正**此前"正式产物含 Clerk"的不准确说法）：E2E 形态（test token）`ui-rTcXnucO.js`；**Clerk 验证形态**（假 `pk_test_...` key 构建，实测含 AuthBridge + `openSignIn({fallbackRedirectUrl: origin+'/'})`、无测试令牌）`ui-Bckh22_y.js`=B4BA950D3047F0A6；fail-closed 形态（无 key）`ui-C60rpF3L.js`=9C9214A661399002 只渲染"认证未配置"。生产 Netlify 构建必须设置真实 `VITE_CLERK_PUBLISHABLE_KEY` |
| E2E 产物与正式产物隔离 + 全资源扫描 | 源码中 `test-session-token` 只出现在 6 个预期位置（全部由测试环境显式启用）；发布形态产物均无该标记；agent 产物中的测试策略仅当操作员设置 `AUTH_TEST_USER_ID` 时启用 |

### 7. flaky 状态

`apps/web` vitest 此前出现 1 次 1/49 失败（未定位到用例名），随后连续 5+ 次全绿
（本轮会话 55/55 连续 4 次）。本轮没有复现；保留"未定位低频风险"并落成**捕捉机制**
（`UI_AND_BACKEND_TEST_REPORT.md` §7：`vitest run --reporter=verbose` + `Tee-Object`
落盘 + 关并发单独重跑 + 复现则修复/不复现则如实保留），未写"已彻底解决"。
本轮 Playwright 各套件（16 + 4 + 3）全部一次或修复后通过，无 flaky。

---

## 二、授权后 DSH 可执行的外部任务（按顺序，各自单独授权范围）

1. **生产只读核验**：线上 release、服务单元、进程数（确认 rag-api 单进程）、配置名、
   数据路径、备份与 Netlify 当前 deploy（不打印 secrets）。
2. **千问 canary（需预算授权，CNY 5.00 仅为建议）**：先最小两阶段教学 → 题目/Bridge →
   图片与 Node 工具；记录真实 Prompt、非敏感示例、usage、延迟、估算/账单证据；
   人工判定质量与图片识别。取消/超时竞争已由本地模拟覆盖，不故意付费制造故障。
3. **备份与隔离恢复**：按 `MIGRATION_AND_ROLLBACK.md` 的首次启用 A/B/C 顺序执行，
   并在副本上完成恢复演练与跨库引用抽查。
4. **受控部署**：后端新 release（`UI_EXTENSION_ENABLED=false`）→ 验证 → 开开关 →
   正式前端（根路径进入新控制面板）；发布前记录现场 deploy id。
5. **双用户 + 管理员验收**：评论/通知/私信/文件/课程/历史/知识树/测评/双模式学习。

## 三、必须用户亲自完成的操作

| # | 位置 | 操作 | 原因 | 验证 |
|---|---|---|---|---|
| 1 | DSH Web GUI（`http://127.0.0.1:3080`）的会话权限/审批预设选择器 | 把审批策略从 `never` 切到 `ask` 或对等可用模式（保留其余保护） | 本会话 `never` 下模型无法自行弹出批准；GUI 自带 ApprovalPanel，说明通道在客户端；`settings.yaml` 无审批字段，不凭猜测写 YAML | 之后一次无生产影响、无费用且确实需要原生审批的测试动作收到真实审批提示并能回答 |
| 2 | （已完成）开发模型切换 | `agent-default-model.model: deepseek-v4-pro` | 目标模型 | 本会话系统设定已显示 deepseek-v4-pro |
| 3 | Clerk 控制台 | 确认生产应用的 publishable key、allowed origins/redirect URLs 与新域名形态一致 | 新壳为默认入口后登录/回调必须匹配 | 真实浏览器登录成功并落回新控制面板 |
| 4 | 预算决策 | 对 CNY 5.00（或调整后金额）给出明确批准 | 付费调用前置条件 | 批准记录 + canary 后账单与 usage 一致 |
| 5 | 登录/验证码 | 真实账号登录、任何验证码、OAuth 确认 | 本人凭据，不索取 | 会话建立且 401 不再出现 |
| 6 | 效果确认 | 对 canary 教学/图片识别质量给出人工评价 | Mock 不能代替质量验收 | 反馈记录写入报告 |

## 四、尚未证明、需进一步核验的事项

| 项 | 状态 |
|---|---|
| 真实千问两阶段质量/延迟/费用 | NOT RUN（缺预算授权） |
| 真实 Clerk 会话（浏览器侧完整流程） | NOT VERIFIED（桥代码已 6 项单测覆盖） |
| 真实图像题视觉正确率 / Node 工具模型侧选择 | NOT VERIFIED |
| 生产多用户隔离与管理员边界 | NOT VERIFIED（本地真实库已测） |
| 多 worker 生成支持 | **未实现且如实标注**：单 worker 防护已落地（§一.4），但扩容需持久化 worker |
| 生产只读核验 / 备份现场 / 部署 / 双用户验收 | NOT PERFORMED（需授权） |
| 生产部署快照（release/deploy id） | 未现场复核：早期报告 id 只是历史快照 |
