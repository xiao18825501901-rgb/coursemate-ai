# 推理强度预算基线

## 当前已实现公式

| UI 档位 | API 值 | 应用美元上限 |
|---|---|---|
| 中 | `medium` | `B` |
| 高 | `high` | `2B` |
| 最高 | `max` | `null`，表示无应用层美元上限 |

`max` 不使用 0、大数字、Infinity 或默认值冒充无限。它仍受取消/停止、供应商
技术限制、速率限制、账户余额及上游失败约束。“最高”不会自动开启供应商原生
Thinking；Thinking 仍只控制 normal work 与 plan→work。

## B 的事实状态

真实生产 `B` 在本轮为 **UNKNOWN — REQUIRES PRODUCTION CONFIG VERIFICATION**。
旧 USD 1.50 是一次历史验收批次预算，未被当作单消息 B。

生产需要显式设置并核验：

- `CMUI_OPERATION_USD_BASELINE`：B，正十进制美元值；
- `CMUI_OPERATION_ESTIMATED_USD`：本次调用的预计美元成本，正十进制值。

真实 Qwen 模式缺少任一值时返回可诊断的 409，不采用不安全的猜测。
本地 deterministic/test provider 不伪造真实价格。

## 离线合同证明

以 B=0.10、预计成本=0.15 为例：中拒绝，高通过；预计成本=0.21 时高拒绝；
最高返回 `application_usd_cap=null`，不会因应用美元额度拒绝。
