# LAST MILE STATUS — 生产评审器补齐、迁移/回滚证据与外部授权状态

**更新**：2026-09-15（随本轮提交）
**口径**：外部状态只能由真实用户决定、原生审批回执与访问验证更新；本文件只记录。
机器可读摘要见 `docs/ui-refresh/release-manifest.json`。

## 分项状态（本轮口径）

```text
DELIVERY_ACCOUNTING_LOCAL               = DONE（022 REVIEWED 通道、回执、恢复、已覆盖跳过）
PRODUCTION_REVIEWER_CODE                = DONE_LOCAL（ModelCoverageReviewer + qwen_review_invoke，默认关闭，未启用）
REVIEWER_CONTRACT_TESTS                 = DONE（9 项，假上游零计费；非 live）
MIGRATION_AND_ROLLBACK_COPY_TESTS       = DONE（5 项：21→22 保数据/幂等、重复数据响亮报错、UI 关闭仍迁移、旧 release 就绪与旧查询、旧 UI release 拒开 Schema 5）
REAL_MODEL_CANARY                       = NOT_RUN（LIVE_CANARY_BUDGET = NOT_APPROVED）
LIVE_COVERAGE_ACCEPTANCE                = NOT_RUN（依赖 canary + 真实评审启用授权）
PRODUCTION_DEPLOYMENT                   = NOT_PERFORMED（PRODUCTION_WRITE_APPROVAL / PUSH_AND_PUBLISH_APPROVAL = NOT_APPROVED）
AUTHENTICATED_MULTIUSER_ACCEPTANCE      = NOT_PERFORMED
```

当前评审器实际状态：**生产默认仍为 Null**——新壳教学显示"覆盖待确认/未启用"，
不自动确认覆盖；`Deterministic` 仅测试；`ModelCoverageReviewer` 已实现并通过
合同测试，但**未启用**（需要单独的付费批准：第三次调用的整批预算）。

## DONE_LOCAL — 已实现且本地测试

| 项 | 证据 |
|---|---|
| 生产模型覆盖评审器（代码） | `coverage_review.py`：async 协议 + `ReviewOutcome`（状态/逐项判定/理由/证据引文/评审器与 policy 版本）；`ModelCoverageReviewer` 独立第三次调用（默认关闭、候选判定、fail-closed）；`qwen_review_invoke` 计费门在请求前、无自动重试、finish_reason 校验；`resolve` 生产只接受 `model` 且要求 allow_billable + 站点同一凭据 |
| 服务端逐项校验与评审持久化 | `shell_delivery.py`：评审在写事务外运行；`covered` 判定必须带**逐字存在于已保存正文**的证据引文；逐项写入；评审结果（含失败状态）随 teaching_units 持久化；重放只重放记账，模型调用次数不增；评审失败不撤销教学、覆盖待评审 |
| 合同测试 | `tests/test_coverage_reviewer_contract.py` **9 项**：合理改写+真实引文计入、关键词/验收回显拒绝、partial/uncertain/not_covered 逐项、非法 JSON/伪造 id/越界拒绝、默认关闭零请求+计费门前置（MockTransport 计数为 0）、评审失败保教学、持久化后重放零模型调用、部分覆盖只提交确认项 |
| 迁移/回滚副本测试 | `tests/test_ui_extension_schema_compat.py` **5 项**：Schema-21 历史副本升级 22 保 VALIDATED/LEGACY 行且幂等（integrity/FK/索引核查）；预存重复 (journey_id, operation_id) 时升级**响亮失败**不静默删除；`UI_EXTENSION_ENABLED=false` 仍执行 RAG 迁移；旧 release 就绪探针在 22 库上仍 READY、旧覆盖查询不计 REVIEWED 但正常运行；旧 UI release 拒开 Schema 5 库 |
| 旧摘要修正 | 残留的"RAG Schema 未变""批准提示被禁用"等表述已按 Schema 22/5 与 ask 通道现状修正（`FINAL` §4/§6.1、`MIGRATION` §7、`QWEN` §4） |
| 机器可读 manifest | `docs/ui-refresh/release-manifest.json`：SHA、Schema、operation 数、评审器模式、构建门、测试范围与外部状态（外部状态字段只能由真实决策更新） |
| 生产只读核验脚本 | `scripts/production_readonly_check.mjs`：HTTPS GET 只读（health/文档形状），不写、不打印 secrets、不调用模型；缺端点时零连接并输出访问清单 |

## NOT_IMPLEMENTED / 受限

| 项 | 状态 |
|---|---|
| 模型评审器的**实际启用** | 代码完成、未启用：需要整批 canary 预算批准（第三次调用）与 `CMUI_COVERAGE_REVIEWER=model` + `CMUI_ALLOW_BILLABLE=true`（生产环境） |
| 多 worker 生成平台 | 首发单实例（租约防护 + 看门狗），扩容需持久化 worker |

## WAITING_APPROVAL（按依赖顺序）

1. **生产只读核验**：已通过原生机制提出申请（范围见脚本头注释）；`PRODUCTION_READ_APPROVAL = REQUESTED_PENDING_USER_RESPONSE`。
2. **Canary 整批预算**：按实时价格估算 C1（两阶段教学）+ C2（教学+覆盖评审+实际提交）+ C3（题目→步骤→教学→返回，可与 C2 复用）+ C4（图像题）+ C5（Node 工具调用）的总费用后申请；含可选第三次评审、Embedding、图像 tokens、工具多轮上限与未知超时用量；人工重试从总额扣。
3. **模型评审启用授权**：与上线后持续模型费用分开征求。
4. **备份与隔离恢复演练**、**迁移 022/UI Schema 5 与受控部署**、**push/Netlify 发布**（先确认 push 是否触发自动构建）、**数据灾难恢复**（独立审批）。

## WAITING_ACCESS — 生产只读访问卡

| 字段 | 内容 |
|---|---|
| 访问方式 | HTTPS 只读（无需 SSH/密钥）：脚本只请求 `/health`、`/ui-extension/health` 与站点首页文档形状 |
| 目标 | `https://rag.qqttai.com`（后端+扩展）、`https://agent.qqttai.com`（Agent）、站点域名（`qqttai.com`） |
| 所需角色 | 无需账号角色；若端点仅内网可达，则需一台可达主机的受保护环境（SSH agent/key 或已登录会话，不要求明文密码/密钥进聊天） |
| 已配置 | 否（本机没有生产端点配置） |
| 你的操作 | 在受保护终端/CI 里 `export PROD_RAG_BASE_URL=… PROD_AGENT_BASE_URL=… PROD_SITE_URL=…` 后运行 `node scripts/production_readonly_check.mjs`，或授权我在你提供的受保护会话中执行 |
| 验证 | 输出三行 status（200/非 200）即完成；不需要发送任何 token 或密钥 |

## OWNER_ACTION — 必须用户本人操作

| 项 | 完成标志 |
|---|---|
| 预算决定（整批，含可选第三次评审） | 明确批准记录 + 账单/usage 一致 |
| 真实 Clerk 登录、验证码、OAuth/SSO 确认 | 真实浏览器登录成功并落回新控制面板 |
| 公开内容审核（真实知识树） | 审核通过 + 留痕 |
| canary 教学/评审质量人工评价 | 反馈写入报告 |

## LIVE / PRODUCTION 证据（必须本次真实）

| 项 | 状态 |
|---|---|
| 真实千问两阶段 / 覆盖评审 live | **NOT RUN**（零真实调用，费用 CNY 0.00） |
| 生产只读核验 | **NOT YET VERIFIED**（申请已提出，等待回答与端点配置） |
| 部署与多用户验收 | **NOT PERFORMED** |

## 下一步（等待用户回答，不空转）

1. 用户答复生产只读核验申请（并配置端点或提供受保护执行环境）；
2. 用户批准整批 canary 预算（含可选第三次评审）；
3. 依次：只读核验 → canary（C1/C2 优先）→ 备份演练 → 受控部署 → 真实 Clerk 多用户验收。
