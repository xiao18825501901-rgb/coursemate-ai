# RELEASE CLOSURE CHECKLIST — 本地收尾与真实发布准备

**更新日期**：2026-09-15（Asia/Hong_Kong）
**HEAD**：以 `git rev-parse HEAD` 为准（本文件随提交更新，不写自引用 SHA）
**模型**：开发执行 `deepseek-v4-pro`（`C:\Users\Hp\.dsh\settings.yaml` 已切，本会话一致）；网站教学 `qwen3.8-max`（未变）。
**权限**：本会话审批策略已由用户切为 **`ask`**；本轮所有仓库写入均经真实批准回执（多次 received/decided，无生产影响、无模型费用）。文件 sandbox `danger-full-access`（经逐次批准）。**没有任何动作被"当作已批准"：真实千问/生产操作/发布仍未被批准。**

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

### 2. 学习状态闭环：新教学 → V3 权威覆盖（最终提示 P0，本轮完成）

| 审计项 | 结论与证据 |
|---|---|
| 覆盖权威 | `_atomic_learning` 按 `teaching_delivery_evidence` 计数（`VALIDATED`/`LEGACY_PRESERVED`/`REVIEWED`）；迁移 022 新增 `REVIEWED` 通道（plan 列 NULL、content_hash 64 位 hex、作用域触发器锚定 journey/node/spec/section） |
| 新教学 → 覆盖 | run 完成的条件式最终写入后才 `knowledge.submit_delivery`：单事务写入 `teaching_units`（正文可恢复 section）+ 每条评审确认 item 一条 `REVIEWED` 证据 + `learning_coverage` + journey 状态一致更新；UI 库 `cmui_delivery_submissions` 回执（Schema 4）+ 重启恢复（只重放幂等记账、零 Provider 调用） |
| 覆盖认定不由模型自报 | 可注入 `CoverageReviewer`：Null（默认，不确认）、Deterministic（acceptance 全句规则，生产被拒）、模型评审（收费第三次调用，未实现未授权）。Spec 要求进入第一阶段规划（自由文本不变，无数据库授权） |
| 正反验收 | `test_ui_extension_coverage_submission.py` **8 项**从零覆盖：0/2→LEARNING→2/2→LEARNED、测评低分不影响 LEARNED、仅提关键词/失败/截断/取消不计、重放不重复、跨库中断恢复零 Provider 调用、错课程/旧 Spec/跨用户隔离、旧入口读到 REVIEWED |
| Problem/Step/Bridge 绑定 | `cmui_bridges` 是壳内导航；新壳题目/解法映射进 V3 账本（`learning_problems`/`problem_revisions` VALIDATED+hash/`learning_solutions`/`learning_steps`，幂等 `shell-<run>` id）；桥接 7 列追溯 + `GET /courses/{id}/bridges`；`test_ui_extension_bridge_trace.py` **5 项**（全链路、重复点击、跨用户、伪步骤/取消、未绑定节点零记账） |
| 测评全流程与独立性 | start/view/submit/abandon 委托 V3 AssessmentService；评分独立于覆盖（正反均有断言） |

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
| 生产树的真实发布路径（空态如实） | 无 PUBLISHED 官方树时新壳如实空态；管理员用真实资料生成/检查/发布的最小路径已写入 `INTEGRATION_MAP.md` §3（V3 管理面 7 步：生成草案 → 组装 DRAFT 官方树 → 提交申请 → 快照检查 → 审核 approve 留痕 → 生效 → 撤回/supersede）。**测试 fixture 不得冒充发布**；真实模型生成与公开审核分别需要预算与用户动作 |

### 4. 单 worker 生成约束 + 静默取消看门狗（§5 恢复边界）

| 防护 | 证据 |
|---|---|
| 每进程唯一 worker 身份 + run 租约（`lease_worker`/`lease_heartbeat`） | `app/cm_update/db.py`；`tests/test_ui_extension_single_worker.py`（4 项双进程测试） |
| 启动清理只回收失去拥有者的 run（心跳缺失/超 grace 120s） | 同套件：第二个进程启动不再杀第一个进程的进行中 run |
| 生成期间心跳（每 5s，条件更新） | 同套件 |
| 跨进程取消：取消写库优先，生成循环复读状态 | 同套件：取消后不产出消息 |
| **Provider 完全静默时取消有界生效** | 生成循环新增数据库看门狗（2s 轮询终态）；`test_cancel_effective_during_provider_silence` 实测 <8s 断言 |
| 完成/取消竞争由数据库裁决（条件式最终写入） | 同套件 |
| 失败不自动重试、不重复计费 | 既有 provider 测试 |
| 仍为明确限制 | 单实例/单 worker 仍是部署前提（内存任务表 ≠ 多 worker）；扩容需 V3 侧尚不存在的持久化 worker |

### 5. 数据归属表 + 首次启用 A/B/C + 回滚 A/B 拆分（最终提示 4.2）

| 项 | 证据 |
|---|---|
| 数据归属表（上传分元数据/字节/题目图片三处；覆盖与题目账本入表） | `MIGRATION_AND_ROLLBACK.md` §2：课程/文件/旧问答/覆盖/测评/题目账本在 RAG 库；任务在 Agent 库；评论/通知/私信/新壳对话/Bridge 在 UI 库；`cmui_*` 镜像表仅 standalone |
| 首次启用 A/B/C 顺序（区分两个进程的 `CMUI_DATA_DIR`） | 同文档 §4：A 备份进程 `unset CMUI_DATA_DIR` 先一致备份 → B 应用进程独立路径自动建库（不跑 seed）→ C 备份进程再 `export`，三库两组上传纳入新恢复单元；空目录/建库/纳入备份发生在哪一步明确无循环依赖 |
| 回滚 A/B 拆分 | 同文档 §7：**A** 代码/路由/配置撤回（保留全部数据；核查旧代码对 Schema 22/5 的兼容性；前后端分别撤回）；**B** 数据灾难恢复（独立审批 + 先快照当前库 + 损失窗口说明 + 成套恢复 + 跨库抽查）。禁止机械用陈旧数据覆盖生产 |
| 恢复后跨库引用抽查 | 同文档 §5：目录重映射、引用可读性、任务回执、桥接的 problem_revision/unit/证据可解析、孤引用 404/空列表 |

### 6. 发布构建预检与产物校验（最终提示 4.1，已接入 Netlify 构建命令）

| 项 | 证据 |
|---|---|
| 生产构建预检 | `scripts/preflight_release_build.mjs`（production 上下文强制：真实 `pk_live_` key、三个 https API origin、`VITE_V3_ENABLED=true`、禁 `VITE_AUTH_TEST_TOKEN`；非生产 no-op）；**本地演练**：缺 key/假 key/localhost origin/test token 四个负向全部正确失败，正向通过 |
| 产物校验 | `scripts/verify_release_build.mjs`：扫描测试身份与端口限定 localhost API 兜底（排除 react-router 库内裸字符串误报），写 `build-info.json`（环境摘要+release SHA+产物 hash 同一构建）；**演练**：干净生产形态通过、烘入 `localhost:8000/8001` 的构建被正确拒绝 |
| 后端测试身份守卫 | agent 新增 `NODE_ENV=production` 时 `AUTH_TEST_USER_ID`/`AGENT_PROVIDER_MODE=deterministic` 直接退出；rag-api 既有生产 validate 拒绝 test provider/dev 登录 |
| 无 key fail-closed 仍可本地测试 | 两种文档（legacy 与 shell）无 key 构建都只渲染配置缺失页；生产构建则直接失败并提示，不能发布一个只显示"认证未配置"的站点 |

### 7. 回归与构建（本轮全部实跑）

| 套件 | 结果 |
|---|---|
| rag-api 全量 | 本轮全量重跑（两处过期断言修复后；新增覆盖闭环 8 项 + 桥接追溯 5 项已并入，数字见运行结果） |
| 新壳浏览器验收（含树层级、双模式、键盘/触屏、覆盖状态行与覆盖闭环） | **17 passed**（1.3m；用例 15：树节点教学 → 状态行"已计入覆盖" → API LEARNED 2/2） |
| 旧站 E2E `coursemate.spec.ts` | **4 passed**（本会话复跑） |
| V3 学习 E2E `learning.spec.ts` | **3 passed**（本会话复跑） |
| Node Agent 单测 / typecheck / build | **66 passed** / 通过 / 通过（生产守卫后复跑） |
| web 单测（含真实 Clerk 桥 6 项） | **55 passed**（verbose 复跑亦全绿） |
| 正式 React 构建三形态 + 全资源扫描 | 同前 §6；新增生产预检/产物校验演练见上 |
| 回滚/flaky 文档纠错 | canary 预算统一为整批总预算；operation 程序枚举 28 个；flaky 捕捉命令路径实测修正（apps/web 到仓库根是两级） |

### 8. flaky 状态

`apps/web` vitest 此前出现 1 次 1/49 失败（未定位到用例名），随后连续 6+ 次全绿
（本轮会话 55/55 多次，含 `--reporter=verbose` 一次）。本轮没有复现；保留
"未定位低频风险"并落成**捕捉机制**（`UI_AND_BACKEND_TEST_REPORT.md` §7：路径已
实测修正的 `vitest run --reporter=verbose` + `Tee-Object` 落盘 + 关并发单独重跑），
未写"已彻底解决"。本轮 Playwright 各套件（16 + 4 + 3）全部一次或修复后通过，无 flaky。

---

## 二、授权后 DSH 可执行的外部任务（按顺序，各自单独授权范围）

1. **生产只读核验**：线上 release、服务单元、进程数（确认 rag-api 单进程）、配置名、
   数据路径、备份与 Netlify 当前 deploy（不打印 secrets）。
2. **千问 canary（需预算授权；CNY 5.00 是整批 canary 的保守总预算建议，不是每次
   调用各 5 元，也不是上线后持续费用授权——先按实时价格估算全部计划调用的总费用，
   超限即停、不自动加钱/换模型/重试）**：先最小两阶段教学 → 题目/Bridge →
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
| 4 | 预算决策 | 对 CNY 5.00（整批 canary 总预算，或调整后金额）给出明确批准；上线后的持续费用需另行批准 | 付费调用前置条件 | 批准记录 + canary 后账单与 usage 一致 |
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
