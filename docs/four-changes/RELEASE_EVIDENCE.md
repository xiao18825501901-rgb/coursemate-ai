# 四项改造发布证据

记录日期：2026-09-20

## 已完成验证

| 验证 | 结果 |
|---|---|
| 四项后端针对性组合 | 97 passed |
| 被新版政策替代的旧断言 | 5 passed |
| Web 单元测试 | 60 passed |
| Agent 单元测试 | 66 passed |
| Web + Agent 类型检查 | PASS |
| UI Refresh Playwright | 19 passed |
| Codex Audit Playwright | 14 passed |
| Web 生产构建 | PASS |
| RAG 完整冻结回归 | 698 passed，0 failed，2 条第三方弃用 warning |
| 合成 token 发布产物扫描 | 0 命中 |

冻结应用 SHA：`e6c77dc9ebe779efea2882b92e1f1e99425d4cc8`。

最终 JUnit 为 `artifacts/four-changes/final-full-rag-frozen.xml`，针对性 JUnit 位于
同目录。浏览器套件使用隔离 SQLite、test token 和
deterministic provider；未读取生产密钥，未产生模型费用。

## 验证层级

- SOURCE IMPLEMENTED：是。
- LOCAL / FAKE-PROVIDER VERIFIED：是。
- LIVE MODEL VERIFIED：否。
- PRODUCTION VERIFIED：否。
- PRODUCTION DEPLOYED：否。

## 发布停止条件

生产前仍需新的、明确的发布授权及以下值：生产 B、预计费用计算来源、维护窗口、
备份位置、冻结应用 SHA、实际目标主机与回滚构建。不得复用旧 canary 或历史部署授权。
