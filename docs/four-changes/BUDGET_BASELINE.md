# 推理强度预算基线

状态：**SOURCE IMPLEMENTED / LOCAL CONTRACT VERIFIED**。本文件记录 2026-09-21
生产候选的明确配置，尚不表示配置已经写入生产环境或发生过真实模型费用。

## Owner 已批准的产品政策

| UI 档位 | API 值 | 应用美元上限 |
|---|---|---|
| 中 | `medium` | `$0.20` |
| 高 | `high` | `$0.40`（`2B`）|
| 最高 | `max` | `null`（明确的无限应用美元上限）|

`max` 不使用 `0`、大数字、`Infinity` 或默认值冒充无限。它仍受取消/停止、速率限制、
模型账户与上游技术限制约束；不会启用供应商原生 Thinking。产品的 Thinking 仍只控制
normal work 与 plan→work 两阶段教学。

## 生产配置（待受保护环境写入）

```text
CMUI_OPERATION_USD_BASELINE=0.20
CMUI_OPERATION_INPUT_USD_PER_MILLION=2
CMUI_OPERATION_OUTPUT_USD_PER_MILLION=6
CMUI_IMAGE_MAX_PIXELS=2621440
CMUI_CAMPUS_QUALIFICATION_POLICY=registered_active
```

该服务实际配置的 Qwen endpoint 必须先核实为 Alibaba Cloud Model Studio Singapore
International 的 `qwen3.8-max`。截至本文复核时间，官方模型页列出的新加坡按量价格为
输入 `$2` / 百万 token、输出 `$6` / 百万 token；本次不假定免费额度、缓存折扣或优惠
命中。[Model Studio qwen3.8-max pricing](https://www.alibabacloud.com/help/en/model-studio/qwen3-8-max)

`CMUI_OPERATION_ESTIMATED_USD` 是历史统一估算变量，已不参与任何生产预算判定。它可
保留在旧环境文件中以兼容人工诊断，但不能用它解锁调用或把它称为逐请求价格。

## 实际请求估算与快照

在 Qwen 模式，浏览器只提交强度，不提交费用。服务端使用已构造的请求消息、检索资料、
历史、附件数、模型输出上限和调用阶段数，按下式作向上取整的保守预估：

```text
estimated_usd = ceil_1e-6(
  input_tokens_upper_bound * input_usd_per_million / 1_000_000
  + output_tokens_upper_bound * output_usd_per_million / 1_000_000
)
```

- normal teaching / problem：一个 answer 阶段；
- Thinking：planner + teacher 两阶段，teacher 输入额外预留 planner 的完整最大输出；
- 做一题、独立详解、自动专业分类：各自独立的有界 Qwen 阶段；
- 已保存的答案、显式揭晓、缓存详解、历史读取不新增 Provider 调用；
- 图片以 `max_pixels=2,621,440` 发送和估算。Qwen3.8 视觉输入按 32×32 像素一 token
  加两个分隔 token 计，故每张图保守预留 2,562 个输入 token；Base64 transport bytes
  不会被当作免费文本。[Official visual-token formula](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/vision)

每个已启动 run 保存 strength、B、estimated cost、application cap 和结构化估算审计。
自动分类使用冻结 materials revision，并写入无资料正文的调用审计；若分类 worker 在
外呼后失去 claim，结果不会覆盖较新修订，但失败/未知用量仍保留审计。

首次绑定知识节点的教学运行会在事务中提升为 Thinking。预检发现尚无 node start 时会先
按两阶段估算；若并发 worker 抢先完成首开，本请求实际退回单阶段，估算仍是保守的。

## 启动与失败关闭

生产 Qwen runtime 缺少或非法的 B、输入单价或输出单价会拒绝启动；不会以健康 200
掩盖默认中档后续必然 409。已运行请求保存的快照不会受之后切换强度或更改 B 影响。
max 仍会要求可用的服务端估算和价格记录，但不会因为应用美元 cap 被拒绝。

## 本地合同证据（当前源码候选前）

- `tests/test_reasoning_strength_budget.py`
- `tests/ui_extension/test_operation_estimation.py`
- `tests/ui_extension/test_production_budget_config.py`
- `tests/test_server_operation_budget.py`
- `tests/test_codex_classification.py`

2026-09-21 运行结果：`32 passed`（两条 FastAPI/Starlette 第三方弃用 warning）。
其中证明 medium 拒绝、高通过、高拒绝、max `null`，图片上界、首次节点双阶段预检、
自动分类的 preflight 与不含正文的 usage audit。真实模型 usage、供应商账单与本轮
`$2.00` canary 总额仍为 **NOT VERIFIED**，在发布完成前不得写成通过。
