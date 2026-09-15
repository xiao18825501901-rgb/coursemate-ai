# LAST MILE STATUS — 冻结版本、公开只读核验与后续授权

**更新**：2026-09-15（冻结 SHA `f5c1efe5935fe9b75bf01f4abe88c8a1db2e6268`）
**口径**：外部状态只能由真实用户决定、原生审批回执与访问验证更新；本文件只记录。
机器可读摘要见 `docs/ui-refresh/release-manifest.json`。

## 分项状态（本轮口径）

```text
LOCAL_RELEASE_VERIFIED           = PASS（冻结 SHA f5c1efe：rag-api 全量 500、web 55、
                                  agent 66、新壳浏览器 17、旧站 4/3 同 SHA 复跑）
PUBLIC_HTTP_OBSERVED             = PASS（本机无身份 HTTPS GET，四个端点全部取得真实响应，
                                  2026-09-15T15:59:51Z；详情见 manifest.public_http_observations）
CONTROL_PLANE_OBSERVED           = EXTERNAL_ONLY（ChatGPT 会话 Netlify 只读连接器：
                                  current production deploy 6aa70f2b5a330d5a8ae4be56，
                                  ready/production；commit_ref=null，标题非源码 SHA 证明；
                                  标注为非 DSH 回执）
SERVER_RUNTIME_VERIFIED          = NOT_YET（需要受保护 SSH/运维盘点：进程数、目录、
                                  service unit、三库 Schema、上传目录、备份、模型 endpoint；
                                  health 200 不证明这些）
LIVE_QWEN_VERIFIED               = NOT_RUN（LIVE_CANARY_BUDGET = NOT_APPROVED）
LIVE_COVERAGE_VERIFIED           = NOT_RUN（依赖 canary + 评审启用授权）
DEPLOYMENT_PERFORMED             = NOT_PERFORMED（写/发布批准 NOT_APPROVED）
REAL_AUTH_MULTIUSER_VERIFIED     = NOT_PERFORMED
```

## 本轮公开只读核验结果（用户同意的固定范围，本机执行）

| 端点 | 结果 | 解释 |
|---|---|---|
| `https://rag.qqttai.com/health` | **200** application/json `{"status":"ok","service":"rag-api"}` | 后端存活 |
| `https://rag.qqttai.com/ui-extension/health` | **404** application/json `{"detail":"Not Found"}` | **EXPECTED_ABSENT**：扩展未启用（`UI_EXTENSION_ENABLED` 默认 false），宿主在且应答；不是宕机 |
| `https://agent.qqttai.com/health` | **200** application/json `{"status":"ok","service":"agent-api"}` | Agent 存活 |
| `https://qqttai.com/` | **200** text/html，title=CourseMate AI | 生产仍服务**旧版 V3 文档**（`/` 尚未是新壳），与未部署阶段一致 |

每个请求记录：时间戳、URL、HTTP 状态、Content-Type、受限正文摘要、错误阶段（本轮无错误）。
范围外（未执行）：SSH/数据库访问、任何写入、模型付费、重启、push、Netlify 发布。

## 已完成的本地收口（冻结版本证据）

- **冻结 SHA**：`f5c1efe5935fe9b75bf01f4abe88c8a1db2e6268`（HEAD，工作树干净）。
- **同 SHA 回归**（本轮实跑，日志 `work/pytest-freeze.log`）：
  rag-api 全量 **500 passed**（610.06s，`--ignore=work` 跳过历史 checkpoint 目录）、
  web **55**、agent **66**、新壳浏览器 **17 passed**（1.3m）、旧站 4 / V3 学习 3。
  500 = 旧 486 + 合同测试 9 + Schema 兼容测试 5（同一冻结 SHA 下）。
- **文档校准**：manifest `head_at_generation`/`frozen_release_sha` 指向 f5c1efe；
  `INTEGRATION_MAP` 的"模型评审器未实现"改为"已实现、合同测试通过、未启用"；
  `MIGRATION` §6 的"逐字节相同"改为"扩展不挂载但 RAG 022 迁移仍执行，不等同旧版"；
  `FINAL` §7.1 按当前事实（用户切回 `never` + 本轮公开 GET 为消息内同意的固定范围）。
- 评审器/桥接/迁移机制未重写；`ModelCoverageReviewer` 为 implemented-not-enabled。

## 尚缺的受保护访问条件（分层，不与公开 GET 混淆）

| 层 | 现状 | 需要 |
|---|---|---|
| 公开 GET | ✅ 已核验 | — |
| Netlify 控制面板只读 | 仅 ChatGPT 连接器核验过 | DSH 侧需要 Netlify 只读令牌/登录态（受保护环境）才能现场重读 current deploy 与构建规则 |
| GitHub 仓库 | 未连接（连接器 404） | push 权限/远程配置核验（发布前确认 push 是否触发自动构建） |
| SSH 运行环境 | 无凭据/无别名 | 受保护 SSH agent/配置别名；只读盘点：进程数、service unit、目录、三库 Schema、上传目录、备份、模型 endpoint（仅非敏感值） |
| 模型调用 | 未授权 | 整批预算批准 + 账户/地域/endpoint/价格核验 |
| 真实 Clerk 浏览器身份 | 未验证 | 用户登录/验证码 + 生产 publishable key 构建 |

## Canary 预算申请（C1/C2 优先，整批，未批准）

**价格输入**（2026-09-15 官方公开页，仅预算输入，非账单）：
CN 北京 in 12 / out 36 CNY·1M tokens；新加坡 International in 14.988 / out 44.965。
按**新加坡**（较高档）保守估算，实际账户地域/价格在首次调用前核验：

| 阶段 | 内容 | 保守估算 |
|---|---|---|
| C1+C2 合并 | 一次两阶段教学（Word 模板自由文本；输入≤30k、输出≤10k 上限）+ 独立覆盖评审（输入≤8k、输出≤0.8k）+ 真实覆盖提交（从零、两条 REQUIRED） | ≤ CNY 1.20 |
| C3 | 题目→步骤→教学→返回（复用已覆盖 run 以省费） | ≤ CNY 0.60 |
| C4 | 一张已知答案题图（人工确认读题） | ≤ CNY 0.40 |
| C5 | Node Agent 一次真实多轮工具调用（专用测试任务） | ≤ CNY 0.50 |
| 未知用量/失败预留 | 超时未知用量保守记账、人工重试从总额扣 | ≤ CNY 1.80 |
| **整批上限（提案）** | | **CNY 5.00** |

规则：整批累计上限，不是每次 5 元；超限即停，不自动加钱/换模型/重试；评审启用与
上线后持续费用分别征求；估计≠账单，有免费额度也记录实际 tokens 与原价估算。
**请批准该整批预算（或调整金额/先批 C1+C2 子集）。**

## 下一步（等待用户回答，不空转）

1. 批准整批 canary 预算（或 C1+C2 子集）；
2. 提供受保护 SSH/Netlify/GitHub 访问以完成 SERVER_RUNTIME 与发布前控制面板盘点；
3. 之后：canary → 备份/恢复演练 → 受控部署 → 真实 Clerk 多用户验收。
