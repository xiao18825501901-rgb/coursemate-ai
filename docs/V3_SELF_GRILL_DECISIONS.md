# V3 Self-Grill 决策记录

不是逐条用户确认，不是无漏洞认证。采用规格 SG01–24；Q1–10 保持不变。

2026-09-12：本地未发现 grill-me/grilling；读取固定 commit `3cca18b368ae95cdbdebbff572ccafa662551015` 的 [grilling 入口](https://github.com/mattpocock/skills/blob/3cca18b368ae95cdbdebbff572ccafa662551015/skills/productivity/grilling/SKILL.md)。按用户要求用自审/反例测试替代重新访谈，不安装脚本。

| 问题 | 选择/依据 | 风险与验证 |
|---|---|---|
| 缺最终生产报告 | 保留 UNKNOWN；当前 Git 不能证明线上版本 | Stage 8 等待 Owner 控制台证据 |
| npm test 不能找到 vitest | node_modules 不完整；按 lockfile npm ci --ignore-scripts | 重新跑测试；audit high 未处理不得发布 |
| 原件 66/67 | 缺失明确 ORIGINAL_UNAVAILABLE | 只读审计，无伪下载 |
| V2 Admin 私有越权边界 | 新域 owner-only；旧审核改为快照独立授权 | A/B/Admin/匿名矩阵 |
| LEARNED 怎么防模型伪写 | coverage 提案引用保存完成正文与固定 Spec Item，后端求集合覆盖 | 标题/截断/假 ID/版本漂移必须拒绝；语义正确仍需模型/人工评测 |
| 模型超时是否重试 | 不自动重试；operation 保存不明状态；重连查原结果 | 防重复费用；可用性取舍显式展示 |
| A- 数值缺失 | 保存 draft null，未配置不产等级 | raw/rubric 继续工作 |

官方 [Responses 文档](https://help.aliyun.com/zh/model-studio/compatibility-with-openai-responses-api) 当日已将旧路径标为停止维护；V3 不自动猜 workspace 域名。配置显式端点，拒绝旧路径，账户实测单独记录。
