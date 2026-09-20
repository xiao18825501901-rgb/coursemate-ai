# 生产预算配置与真实 Qwen Canary

## 当前应用配置

| 推理强度 | 应用美元上限语义 | 生产值 |
|---|---|---:|
| 中（medium） | `B` | `$0.20` |
| 高（high） | `2B` | `$0.40` |
| 最高（max） | `null`（不设 CourseMate 应用美元上限） | `null` |

`max=null` 不等于无限 token、余额、供应商配额或绕开停止/取消逻辑。它只取消 CourseMate 的应用级美元拦截；上游模型服务仍可能拒绝、限流或余额不足。

生产价格配置：输入 `$2/M`、输出 `$6/M`，与 [qwen3.8-max 官方定价页](https://www.alibabacloud.com/help/en/model-studio/qwen3-8-max) 一致。

## Canary 证据

- 精确 release 源码：`4ef5064`
- provider：`qwen3.8-max`
- 数据边界：隔离合成 RAG/UI 数据库；没有生产用户资料、课程证据或写入。
- 预算授权：最多 USD 2.00、最多 5 次调用、无自动重试。
- 实际：4 次成功调用，按返回 token 和上述单价计算为 `$0.052956`。

| 用例 | 模式 | 强度 | 应用预算初值 | token（in/out） | 估算 |
|---|---|---|---:|---:|---:|
| normal-medium | normal | medium | 0.20 | 122 / 142 | 0.001096 |
| thinking-medium | thinking | medium | 0.20 | 4,495 / 5,563 | 0.042368 |
| problem-high | normal | high | 0.40 | 1,766 / 923 | 0.009070 |
| normal-max | normal | max | null | 121 / 30 | 0.000422 |

Canary 额外断言：Thinking Prompt 在数据库中保存了 3,803 字符、不出现在公开响应；没有新建 LearningBridge 行。该证据验证真实上游调用和服务端计费边界，但**不等于真实学生账号的浏览器体验验收**。

## 持续费用控制

- 每个 run 固化当时选择的强度、B、预测成本和上限；切换控件不会改变进行中的 run。
- 中/高由应用预检拦截；max 明确传递 null，不以 `0`、大数或默认 fallback 伪装。
- 模型供应商仍是最终技术和账户限额边界。应用没有把不存在的云账户“硬停”能力声明为已配置。
- 后续任何额外真实模型批量测试、重嵌入或生产资料调用都必须在可用余额和具体预算内执行、记录实际 token 结果。
