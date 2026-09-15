# LAST MILE STATUS — 学习闭环接线、发布门与回滚校准后的收尾状态

**更新**：2026-09-15（随本轮提交）
**口径**：每项只标一个真实状态；`LIVE_VERIFIED` / `PRODUCTION_VERIFIED` 必须来自
本次真实证据，否则标 NOT。HEAD 以 `git rev-parse HEAD` 为准。

## DONE_LOCAL — 已实现且本地测试

| 项 | 证据 |
|---|---|
| 新教学 → 权威覆盖闭环 | 迁移 022（`REVIEWED` 证据通道 + 唯一索引）、`coverage_review.py`（可注入评审器：Null/确定性/未授权的模型评审）、`shell_delivery.py`（单事务 unit+evidence+learning_coverage+journey 状态；已覆盖 item 不重复记账）、壳侧完成回调/回执/重启恢复；`tests/test_ui_extension_coverage_submission.py` **8 项**从零覆盖正反验收；**浏览器用例 15**：树节点教学 → 状态行"已计入覆盖" → 挂载 API 读回 LEARNED 2/2（`CMUI_COVERAGE_REVIEWER=deterministic` + TestProvider 回显 Spec 验收句） |
| UI Bridge ↔ V3 全链路追溯 | `shell_problems.py` 把新壳题目/解法映射进 V3 账本（`learning_problems`/`problem_revisions` VALIDATED+content_hash/`learning_solutions`/`learning_steps`，稳定 id `shell-<run>` 幂等重放）；`cmui_bridges` 增加 7 个追溯列（Schema 5）+ `GET /courses/{id}/bridges`；教学 run 开始时链 `teach_run/journey/spec`、交付后链 `delivery_unit_id`；`tests/test_ui_extension_bridge_trace.py` **5 项**（全链路解析、重复点击复用记录、跨用户拒绝+列表作用域、伪步骤 422+取消不链交付、未绑定节点保持导航且零记账） |
| 生产构建预检与产物校验 | `scripts/preflight_release_build.mjs`（production 上下文强制：真实 `pk_live_` key、三个 https API origin、`VITE_V3_ENABLED=true`、禁 `VITE_AUTH_TEST_TOKEN`）+ `scripts/verify_release_build.mjs`（产物扫描测试身份/localhost API 兜底、`build-info.json` 耦合构建环境摘要+release SHA+产物 hash）；已接入 `netlify.toml` 构建命令；**本地演练**：4 个负向用例全部正确失败、正向通过、校验捕获烘入的 `localhost:8000/8001` 兜底 |
| 后端测试身份守卫 | rag-api：`provider_mode='test'`/`auth_mode='development'` 生产被拒（既有）；agent：新增 `NODE_ENV=production` 时 `AUTH_TEST_USER_ID` 与 `AGENT_PROVIDER_MODE=deterministic` 直接退出（`server.ts`）；agent 单测/typecheck/build 复跑通过 |
| 回滚手册 A/B 拆分 | `MIGRATION_AND_ROLLBACK.md` §7：A 代码/路由/配置撤回（保留全部数据 + 旧代码对 Schema 22/5 的兼容性核查）、B 数据灾难恢复（独立审批 + 先快照 + 损失窗口 + 成套恢复 + 跨库抽查）；§4 首次启用区分**应用进程**与**备份进程**的 `CMUI_DATA_DIR`；§1–§2 上传分元数据/字节/题目图片三处、覆盖与题目账本归属更新 |
| 单 worker 防护 + 静默取消看门狗 | 既有租约/心跳/回收/条件写；新增生成循环的**数据库看门狗**（Provider 完全静默时取消 ≤~2s 生效），`tests/test_ui_extension_coverage_submission.py::test_cancel_effective_during_provider_silence` 实测 <8s 断言 |
| 审批通道验证 | 会话策略已切 `ask`；本轮所有仓库写入均经真实批准回执（多次 received/decided），符合 closure §6 的验证要求；`never` 时代的诊断与最小操作卡保留在 `FINAL` 报告 §7.1 |
| 文档纠错（4.3） | operation 程序枚举 **28 个**（更新 INTEGRATION_MAP）；canary 预算统一为**整批总预算 CNY 5.00**（非每次调用，上线费用另批；QWEN 报告 + 清单）；flaky 捕捉命令路径实测修正（`apps/web` 到仓库根是两级）；构建三形态如实（无 key hash 不作 Clerk 成品） |

## NOT_IMPLEMENTED — 仍缺代码

| 项 | 说明 |
|---|---|
| 模型覆盖评审器（付费第三次调用） | 接口与 Null/确定性实现已就位；生产语义评审需 qwen3.8-max 追加调用，**未实现且未授权**。未启用前生产覆盖如实停在未确认（受限候选版本），不用关键词规则冒充评审 |
| 多 worker 生成平台 | 首发单实例约束（已有租约防护 + 看门狗）；扩容需持久化 worker，本轮不做 |

## WAITING_APPROVAL — 缺具体动作批准

| 项 | 需要的批准 |
|---|---|
| 千问 canary（含预算） | 整批总预算（建议 CNY 5.00，按实时价格估算总费用后批准）；canary 授权 ≠ 上线持续费用授权 |
| 生产只读核验 / 备份与隔离恢复 / 受控部署（含 push/发布） | 各自范围的部署/发布授权；Git push 若触发自动发布也属发布动作 |
| 数据灾难恢复演练（如需 B 流程） | 独立审批 + 损失窗口确认 |

## WAITING_ACCESS — 缺账号/凭据/可用工具

| 项 | 说明 |
|---|---|
| 生产 SSH/托管平台凭据与角色 | 本会话未持有；只读核验需要可用的生产访问通道（不与密钥索要混淆：凭据应由用户受保护地注入） |
| 真实 Clerk 生产应用 | 真实 `pk_live_...` key 由平台配置/授权操作提供；本会话不索取 Secret |

## OWNER_ACTION — 必须用户本人操作

| 项 | 完成标志 |
|---|---|
| 预算决定（CNY 5.00 整批或调整） | 明确批准记录 + canary 后账单/usage 一致 |
| 真实 Clerk 登录、验证码、OAuth/SSO 确认 | 真实浏览器登录成功并落回新控制面板 |
| 公开内容审核（真实知识树/官方发布） | 审核通过 + `reviewed_by_user_id`/`reviewed_at` 留痕 |
| canary 教学/图片识别质量人工评价 | 反馈写入报告 |

## LIVE_VERIFIED / PRODUCTION_VERIFIED — 必须本次真实证据

| 项 | 状态 |
|---|---|
| 真实千问两阶段 | **NOT RUN**（零真实调用，费用 CNY 0.00） |
| 真实 Clerk 登录全流程 | **NOT VERIFIED**（桥代码 6 项单测 + 产物层扫描，浏览器侧未跑真实会话） |
| 生产部署/双用户验收/管理员边界 | **NOT PERFORMED / NOT VERIFIED** |
| 生产数据/备份现场 | **NOT RUN**（未现场复核） |

## 下一步（按依赖顺序）

1. 用户批准整批 canary 总预算 → 只读核验 → canary → 备份/恢复演练；
2. 部署授权后：后端 disabled 验证 → 开开关 → 生产构建（真实 `pk_live_` key）→ 根路径发布；
3. 真实 Clerk 登录 + 双用户/管理员验收；
4. 如需官方知识树：真实资料草案 → 审核 → 发布（不用 fixture）。
