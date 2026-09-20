# 四项改造生产验收矩阵

状态定义：`PASS` 有对应层级实证；`BLOCKED` 受外部条件阻止；`NOT RUN` 尚未执行。任何低层级通过均不自动升级为生产已登录用户通过。

| 验收项 | 源码 | 本地 / fake | 真实 Qwen（隔离 DB） | 公开生产 | 已登录生产浏览器 |
|---|---|---|---|---|---|
| 删除粉色跨栏提问且详解浮窗仍可用 | PASS | PASS | 不适用 | 后端已部署 | NOT RUN |
| 不泄露未揭晓标准答案、Plan 保密、统一历史 | PASS | PASS | Thinking Prompt 不公开 | 后端已部署 | NOT RUN |
| medium/high/max 的服务端语义 | PASS | PASS | PASS | 配置已核验 | NOT RUN |
| 左右 Pane 强度独立与刷新持久化 | PASS | PASS（Playwright） | 不适用 | Schema 13 已部署 | NOT RUN |
| `registered_active` 自动学生资格 | PASS | PASS | 不适用 | 配置已核验 | BLOCKED |
| 既有资格来源、禁用身份、管理员边界 | PASS | PASS | 不适用 | 后端已部署 | NOT RUN |
| 全站浅色/深色与焦点可读性 | PASS | PASS（Playwright 截图） | 不适用 | 静态资产已部署 | NOT RUN |
| 公开健康、TLS、未认证 `/me` 边界 | 不适用 | 不适用 | 不适用 | PASS | 不适用 |
| 数据库 migration / backup / fallback | PASS | PASS | 不适用 | PASS | 不适用 |
| 新注册首次加入校园课程 | PASS | PASS | 不适用 | 后端已部署 | BLOCKED |
| 真实多用户消息、分享、私有文件隔离 | PASS | PASS | 不适用 | 未以真实用户写入测试 | NOT RUN |

## 本次基础回归证据

已存在的冻结版本记录包括：四项后端组合 97 passed、被替换旧断言 5 passed、Web 60 passed、Agent 66 passed、UI Refresh Playwright 19 passed、Codex Audit Playwright 14 passed、RAG 冻结回归 698 passed / 0 failed。它们在隔离 SQLite、test token 与 deterministic provider 环境运行，不读取生产密钥或产生模型费用。

另有随 `c484bb9` 预算修复代码运行的针对性 JUnit：28 passed、3 passed、1 passed、7 passed（仅第三方 deprecation warning）。`4ef5064` 与 `c484bb9` 的应用代码相同，差异仅为备份工具。

## 当前阻塞的准确原因

Clerk 注册页面在浏览器测试要求 Cloudflare 人机验证；自动化没有绕过它。受控合成身份工具以可用的现有 Clerk 后端凭证创建用户时返回 403，未获得用户 ID，也没有尝试替代凭证或变通路径。故真实注册、自动资格和已登录 UI 验收仍为 `BLOCKED / NOT RUN`，不是 `FAIL` 或 `PASS`。
