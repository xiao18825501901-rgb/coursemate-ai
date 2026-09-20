# CourseMate 四项产品改造：生产发布与验收报告

发布日期：2026-09-20（Asia/Shanghai）  
应用发布版本：`4ef50642c0b2336e64c384752ea262901a32d81d`  
发布分支：`fix/codex-dsh-audit-20260919`

## 结论

**生产部署已完成。** Hangzhou 生产主机和 `qqttai.com` 前端均已切换到本次候选版本；公开健康检查、数据库一致性检查、Schema 13 迁移、备份校验，以及隔离数据库上的真实 Qwen Canary 均有实际证据。

**完整的已登录真实用户验收尚未完成，不能写为 Production Accepted。** Clerk 注册页在自动化浏览器中要求 Cloudflare 人机验证；用于受控合成用户的 Clerk 后端创建请求返回 403。没有绕过验证、没有伪造账户、没有把这个缺口标为通过。

## 实际发布状态

| 项目 | 实际结果 |
|---|---|
| 后端运行版本 | `/srv/coursemate/current -> /srv/coursemate/releases/4ef5064` |
| RAG / Agent 服务 | `active` / `active` |
| 公网 RAG 健康检查 | `200 {"status":"ok","service":"rag-api"}` |
| 公网集成 UI 健康检查 | `200`，`mode=integrated`，`provider=qwen` |
| 公网 Agent 健康检查 | `200 {"status":"ok","service":"agent-api"}` |
| 主站 | `https://qqttai.com/` 返回 200 |
| Netlify 生产部署 | `6ab02278b7fae664934df25d`，发布于 2026-09-20 18:14:19 +08:00 |
| 公开构建信息 | `release_sha=4ef50642…`，`context=production`，8 个构建产物 |
| 未认证 API 边界 | `/ui-extension/api/ui/v1/me` 返回 401 |

`4ef5064` 相对于已验证的预算修复提交 `c484bb9` 没有 `apps/`、`services/` 或 package 文件差异；其唯一差异是受控备份工具。应用行为测试证据可对应使用 `c484bb9` 的测试记录，不能将工具提交误写为新的未测应用行为。

## 四项改造的上线内容

| 改造 | 生产配置 / 数据状态 | 已有验证 | 尚未验证 |
|---|---|---|---|
| 删除跨栏提问 | 旧 LearningBridge 数据、教学覆盖、步骤和引用仍保留；粉色跨栏触发控件已从产品流程移除，详解保留为独立浮窗 | 本地组合与浏览器回归 | 已登录生产课程、历史 SSE、全屏和小屏人工回归 |
| 三档推理强度 | `medium=$0.20`、`high=$0.40`、`max=null`；左右 Pane 独立持久化 | 单元、集成、浏览器与真实 Qwen 隔离 Canary | 真实账号在生产 UI 中切换、刷新和取消 run |
| 注册自动学生资格 | `CMUI_CAMPUS_QUALIFICATION_POLICY=registered_active`；活动普通用户在首次有效请求内获得 `registered` 资格 | 本地服务端和隔离集成验证 | Cloudflare 完成后的真实新注册、首次加入校园课程 |
| 全站浅色/深色 | 默认浅色；Schema 13 已迁移主题偏好和强度字段 | 本地 Playwright 深浅主题截图 | 已登录生产页面、Portal 与全屏人工截图 |

## 数据、迁移和备份

- 已运行 UI Schema 13；完整性与外键检查均为 `ok` / `0`。RAG 和 Agent 数据库也均为 `ok` / `0`。
- 发布前备份：`/srv/coursemate/backups/20260921-four-changes-final-before-schema13/coursemate-v2-20260920T175807.651970Z`。
- 该备份的 RAG、Agent、UI SQLite 校验通过；RAG 上传文件 67 个，UI share 文件 16 个。备份保留原始资料、会话、Bridge、课程、资格、进度和文件；本次没有清库或重建生产数据。
- 已准备兼容 Schema 13 的后端回退版本：`/srv/coursemate/releases/c484bb9-fallback`。不能把不支持 Schema 13 的旧构建直接连到已迁移数据库。

详见 [生产执行记录](docs/four-changes/PRODUCTION_EXECUTION.md)、[验收矩阵](docs/four-changes/PRODUCTION_ACCEPTANCE_MATRIX.md) 和 [回滚说明](docs/four-changes/PRODUCTION_ROLLBACK.md)。

## 真实模型费用与结果

本次已授权不超过 USD 2.00；实际只执行 4 次隔离合成数据的 `qwen3.8-max` 调用，没有读取生产课程资料或写入生产学习记录。

| 操作 | 档位 | 输入 / 输出 token | 按 $2/M 输入、$6/M 输出估算 |
|---|---:|---:|---:|
| normal teaching | medium | 122 / 142 | $0.001096 |
| thinking teaching | medium | 4,495 / 5,563 | $0.042368 |
| problem | high | 1,766 / 923 | $0.009070 |
| normal teaching | max | 121 / 30 | $0.000422 |
| **合计** |  |  | **$0.052956** |

结果文件为本地未提交证据 `artifacts/four-changes/production-live-ui-qwen-canary-result.json`（SHA-256 `0afbe8f7206b083f79d4fccbb303280e1324a5c20c8eadbb5485a9d8fd5b61af`）。Canary 还证明 Thinking 的生成 Prompt 保存了 3,803 字符且不出现在公开响应中，`high` 上限为 `0.40`，`max` 上限为 `null`，并且没有新建 Bridge 行。

定价依据为 [Alibaba Cloud Model Studio qwen3.8-max 文档](https://www.alibabacloud.com/help/en/model-studio/qwen3-8-max)。这只是本次 token 用量估算，不是云账户账单结算金额。

## 最后待人工完成的一项操作卡

1. 在隔离浏览器中打开 `https://qqttai.com/`，走“注册”，并**人工完成 Cloudflare 验证**；不要把密码、验证码、私钥或 Token 发到聊天中。
2. 以新注册的普通账号首次加入一门校园课程，确认账户显示“注册自动开通”。
3. 在该课程学习页确认：跨栏粉色问题条不存在；详解浮窗可拖动、缩放、关闭；左右强度可分别选择；主题刷新后保留。
4. 发送“普通 / Thinking / 题目”各一条低成本消息，确认答案、Plan 保密、停止/取消与历史恢复。
5. 仅反馈通过/失败及非敏感截图；失败时附时间、页面路径和可见错误文字。

在上述操作未完成前，状态应保持：`DEPLOYED — LOGIN-STATE ACCEPTANCE BLOCKED BY PROVIDER HUMAN VERIFICATION`。
