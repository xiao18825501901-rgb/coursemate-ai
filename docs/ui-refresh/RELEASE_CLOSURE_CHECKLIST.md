# RELEASE CLOSURE CHECKLIST — 本地收尾与真实发布准备

**更新日期**：2026-09-14（Asia/Hong_Kong）
**HEAD**：`47b150a`（本清单随提交更新；最新以 `git rev-parse HEAD` 为准）
**模型**：开发执行 `deepseek-v4-pro`（`C:\Users\Hp\.dsh\settings.yaml` 已切，与本会话系统设定一致）；网站教学 `qwen3.8-max`（未变）。
**权限**：本会话记录为 `approval_policy: never`（批准提示禁用）；sandbox `danger-full-access`（文件操作不受限）。**没有任何动作被"当作已批准"。**

---

## 一、本轮已完成的本地工作（含证据）

### 1. 新 UI 成为默认入口（本地实现 + 测试，未上线切换）

| 项 | 证据 |
|---|---|
| `/` 服务新壳文档并进入新控制面板；登录返回目标即新控制面板 | `netlify.toml` 决策表；`tests/e2e/ui-refresh.spec.ts` 用例 1（根地址断言 ui bundle + 控制面板标题） |
| `/app` 兼容别名保留 | 同上，用例 2 |
| 旧深链（/qa /learn /courses /tasks /documents /admin /about）仍服务旧文档且可渲染 | 用例 3；旧套件 `coursemate.spec.ts` 4/4、`learning.spec.ts` 3/3 |
| 哈希深链刷新/后退 | 用例 4 |
| 静态服务器、Vite dev 与 Netlify 三处路由一致 | `scripts/serve_web_dist.mjs` 导出 `documentFor` 同表；`apps/web/vite.config.ts` 插件；`netlify.toml` |
| dev 中间件不再吞 Vite 预打包模块（此前旧应用 dev 整页崩溃） | 修复后旧套件由 1/4 失败 → 4/4 |
| 上线切换仍为受控发布步骤 | `netlify.toml` 只是配置文件；**未 push、未发布** |

### 2. 学习状态闭环审计与最小真实接线

| 审计项 | 结论与证据 |
|---|---|
| 新教学 → REQUIRED 覆盖 | **不直接写覆盖**。`app/learning/knowledge.py:_atomic_learning` 只用 `teaching_delivery_evidence` 计算进度；新壳自由文本教学只写 journey 起步 + `cmui_run_v3` 交叉引用，进度如实保持 NOT_STARTED。证据：`tests/test_ui_extension_learning_closure.py`（5 项，断言 delivery_evidence=0、进度 NOT_STARTED） |
| 新教学 → V3 journey | 已接线：run 带 `node_id` 时先创建/复用 `learning_journeys`（幂等，与 V3 `teach()` 同一张表），失败不留下 queued 脏行；UI 库 Schema 2→3 新增 `cmui_run_v3` |
| Problem/Step/Bridge 绑定 | UI Bridge（`cmui_bridges`）是壳内返回原步骤的 UX 上下文（服务端抽取真实步骤编号）；V3 `LearningBridge` 是 V3 运行时权威记录，二者是**两个独立系统**，未冒充同名接通（文档已写明） |
| 测评全流程 | **已接通**：start/view/submit/abandon 委托真实 V3 AssessmentService；view 契约保证提交前答案键不可见；submit 带 revision 与一次 REVISION_CONFLICT 重试；成绩写入 `grade_snapshots`。浏览器用例 12 完整走完 开始→5 题→提交→已评阅→每题反馈 |
| 学习与测评独立 | 用例 12 断言评分后进度仍 NOT_STARTED；无成绩不显示伪造分数（fixture 课程无 GradePolicy 时 letter grade 如实为 null，raw_score 存在） |

### 3. 回归与构建（本轮全部实跑）

| 套件 | 结果 |
|---|---|
| rag-api 全量 | **463 passed**（399.94s） |
| 交付包契约（迁入后） | 71 passed |
| 新壳浏览器验收 | **13 passed** |
| 旧站 E2E `coursemate.spec.ts`（首次补齐） | **4 passed** |
| V3 学习 E2E `learning.spec.ts` | **3 passed** |
| Node Agent 单测 / typecheck / build | **66 passed** / 通过 / 通过 |
| web 单测（含真实 Clerk 桥 6 项） | 55 passed |
| 正式 React 构建（Clerk 形态） | 通过；产物无 `test-session-token`、含 Clerk |

E2E 产物与正式产物隔离方式：E2E 用 `VITE_AUTH_TEST_TOKEN`+`VITE_UI_API_BASE` 构建
（仅本地），随后用 Clerk 形态重建正式 `dist`；两者都经扫描确认。

### 4. flaky 状态

`apps/web` vitest 此前出现 1 次 1/49 失败（未定位到用例名），随后 3+ 次连续 55/55。
本轮没有复现；保留"未定位低频风险"，未写"已彻底解决"。

---

## 二、授权后 DSH 可执行的外部任务（按顺序，各自单独授权范围）

1. **生产只读核验**：线上 release、服务单元、进程数、配置名、数据路径、备份与
   Netlify 当前 deploy（不打印 secrets）。
2. **千问 canary（需预算授权，当前建议 CNY 5.00 仅为建议）**：先最小两阶段教学 →
   题目/Bridge → 图片与 Node 工具；记录真实 Prompt、非敏感示例、usage、延迟、
   估算/账单证据；人工判定质量与图片识别。
3. **备份与隔离恢复**：按 `MIGRATION_AND_ROLLBACK.md` 的 A/B/C 顺序（首次无 UI 库
   时先做一致备份，再初始化独立 UI 库，启用后三库两组上传同一恢复单元）。
4. **受控部署**：后端新 release（`UI_EXTENSION_ENABLED=false`）→ 验证 → 开开关 →
   正式前端；根路径进入新控制面板。
5. **双用户 + 管理员验收**：评论/通知/私信/文件/课程/历史/知识树/测评/双模式学习。

## 三、必须用户亲自完成的操作

| # | 位置 | 操作 | 原因 | 验证 |
|---|---|---|---|---|
| 1 | DSH 设置（`C:\Users\Hp\.dsh\settings.yaml` 或对应 UI 选择器） | 把审批策略改为可提问（ask）或对等可用通道 | 本会话 `never` 下模型无法自行弹出批准 | 收到一次真实工具审批提示并能回答 |
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
| 生产多用户隔离与管理员边界 | NOT VERIFIED（本地真实库已测） |
| P0-3 非空知识树（父子层级、LEARNING/LEARNED 状态、双状态入口 + 教学→返回原步骤的数据库事实） | 部分完成：评估节点与孤儿节点渲染已测；**带层级的 published tree fixture 与 teach→step→return 的 DB 断言仍待下轮** |
| P0-5 单 worker 约束（启动清理、取消/完成竞争、重启恢复的进程级测试） | 未实现（下轮做最小可测方案） |
| P0-8 数据归属表 + 首次启用 A/B/C 手册修订 | 未完成（下轮做文档修正） |
| 生产数据/备份现场核验 | NOT RUN |
