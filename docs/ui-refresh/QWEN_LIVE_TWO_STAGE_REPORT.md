# QWEN LIVE TWO-STAGE REPORT — 千问两阶段教学

**结论：NOT RUN。没有任何真实千问调用在本会话发生，零模型费用。**

本文件说明链路现状、为什么没有跑、以及跑之前必须先完成什么。**不把 MockTransport 的
两次请求契约测试当作千问实测。**

---

## 1. 要求的链路（用户明确指定的教学方法）

```
学生当前问题/知识点 + 学习要求 + 课程材料 + 历史/题目步骤
    ↓
qwen3.8-max 第一次调用：读取完整 CS3481 Word 模板，输出完整 Prompt 正文
    ↓
保存生成的 Prompt、版本/来源及模型信息
    ↓
qwen3.8-max 第二次调用：以生成 Prompt 为主要教学指令，生成可见教学内容
    ↓
流式输出 + 真实引用 + 数据库历史保存
```

## 2. 真实代码落点（已接入原仓库，不是环境变量开关）

| 环节 | 真实实现 |
|---|---|
| 第一阶段（千问自己写教学 Prompt） | `app/cm_update/provider.py:QwenProvider.planner_messages()` → `stream(messages, cfg.prompt_tokens)`。system 消息里内嵌 **`app/cm_update/prompts/cs3481_original.txt` 全文**（7422 字节），指令明确"直接输出 Prompt 正文，不要输出 JSON，不要回答学生问题" |
| 第一阶段产物保存 | `app.py:627` 发 `prompt_ready` 事件；`cmui_runs.generated_prompt` 落库；前端"查看生成的 Prompt"直接读它 |
| 第二阶段（千问执行该 Prompt） | `provider.py:generate()` 把第一阶段文本放进**第二阶段 system 消息**："你是 CourseMate 教师。执行下面由千问生成的教学 Prompt…" |
| 流式输出 | `provider.py:stream()` 用 httpx 流式解析 SSE；`app.py:632` 逐段写 `delta` 事件并累积 `partial_text` |
| 引用 | `app.py:639` 只在正文里出现 `[S1]` 且该来源存在时才生成引用卡片；来源 id 由适配器统一编号 |
| 预算门 | `provider.py:48`：`if not cfg.allow_billable: raise ProviderError('BILLING_NOT_AUTHORIZED')`，**在发出请求之前**抛出，`self.calls` 保持为空 |
| 凭据 | 只有一份：`mount.py` 把 `V3_MODEL_API_KEY` / `V3_MODEL_BASE_URL` 转给 `QwenProvider`，与 V3 学习链路共用，不新增第二份密钥 |
| 协议 | 默认 `chat_completions`（`enable_thinking=False`），可选 `responses`；两种都由测试覆盖 |
| 失败语义 | 第一阶段截断/失败 → `INCOMPLETE_PROVIDER_RESPONSE` / `DISCONNECTED_PROVIDER_STREAM`，**不启动第二阶段**；第二阶段失败 → 保存 `partial_text` + `status='failed'`，不写 assistant 消息，不宣称学完 |

## 3. 当前部署开关状态（**尚未开启真实调用**）

| 变量 | 需要设为 | 说明 |
|---|---|---|
| `CMUI_PROVIDER_MODE` | `qwen` | `validate()` 要求 `qwen_base_url` 是 HTTPS、无凭据/query/fragment，且 `qwen_key` 非空 |
| `CMUI_ALLOW_BILLABLE` | `true` | `false` 时零出网请求 |
| `CMUI_QWEN_BASE_URL` | 留空即可 | `mount.py` 回落到 `V3_MODEL_BASE_URL`；也可显式覆盖 |
| `CMUI_QWEN_API_KEY` | 留空即可 | 回落到 `V3_MODEL_API_KEY` |
| `CMUI_QWEN_MODEL` | `qwen3.8-max` | 默认值即为它，且与 `Settings.v3_model` 一致 |
| `CMUI_PROMPT_TOKENS` | 2500 | 第一阶段输出上限（256–12000） |
| `CMUI_ANSWER_TOKENS` | 6500 | 第二阶段输出上限（256–16000） |
| `CMUI_MODEL_TIMEOUT` | 180 | 秒（10–300） |

**开发执行模型与网站教学模型没有混淆**：DSH 本会话运行在
`deepseek-v4-pro`（`C:\Users\Hp\.dsh\settings.yaml`，用户已切换），它只用于读写代码与
运行测试，从未作为网站教学内容来源；网站教学链路的模型常量是 `qwen3.8-max`。

## 4. 为什么本会话没有跑真实调用

1. **需要付费授权**。交付的总控要求在任何真实模型付费调用前弹出原生授权提示框，
   说明动作、资源、版本、备份、回滚与费用上限。
2. **本会话的批准提示被禁用**（会话策略 `approval_policy: never`），所有需要批准的
   动作都会被自动拒绝。因此本会话**无法取得**该授权。
3. 没有授权就调用会产生未经批准的费用，并与明确指令冲突。因此**不跑**，并如实标注
   `NOT RUN`，而不是用 Mock、DeepSeek 回答或确定性模板冒充实测。

## 5. 已有证据的边界（不能当作千问实测）

`tests/ui_extension/test_provider.py` 用 `httpx.MockTransport` 验证的是**传输契约**：

* 恰好 2 次 HTTP 调用；`enable_thinking is False`；
* 第一阶段 system 消息里含完整 Word 模板；含"不要输出 JSON"；
* 第二阶段 system 消息里含第一阶段生成的 Prompt；
* 第一阶段 `finish_reason='length'`（截断）时**只有 1 次调用**；
* 401/402/403/429/500 各自只尝试一次且错误里不含上游正文；
* `allow_billable=False` 时**零出网请求**；
* `responses` 协议的 body 形态。

**这些证明"程序发出了正确的请求"，不证明"千问教得好"，也不证明模型真的可用。**
两者必须分开报告。

## 6. 授权后要跑的 canary（有预算、有上限，不自动重试）

需要在授权框里明确的预算上限建议：**CNY 5.00**（远高于 V3 报告里
CNY 0.686 的历史可见用量估计，留出截断重试余量），ISO 币种 CNY，超限即停。

1. **1 次完整 Prompt → Teaching**
   * 打开 `/app#/course/cs3481/learn`，在左侧知识 Pane 提一个中文知识问题；
   * 记录：第一阶段 `prompt_ready` 的字符数、落库的 `generated_prompt`、
     第二阶段可见输出、`usage` 的 input/output token、端到端延迟、实际费用；
   * 判定：第一阶段必须输出**自由文本 Prompt**（不是 JSON），第二阶段必须基于它教学。
2. **1 次 Problem → Step → Teaching → Return**
   * 右侧题目 Pane 提一道真实题目；
   * 确认服务端从**已完成解法**里抽取步骤（不是文本标题），点击某步的知识问题能携带
     原题/步骤/版本到左侧并成功返回；
   * 记录 bridge 的 `step`、`status`、返回后的原题锚点。
3. **1 次取消**：生成中调用 `POST /runs/{id}/cancel`，确认 `status='cancelled'`、
   `error='CANCELLED'`、**不产生第三次调用**、不写 assistant 消息。
4. **1 次超时/失败观察**：用受限超时触发，确认保存 partial 且不宣称学完。
5. **可选：1 次图像题 canary**：上传题目图片，确认两次调用都带图片部件
   （`input_image` 或 `image_url`），并**人工判断模型是否真的读对了题**。

每次都必须区分并分别记录：第一阶段 Prompt、第二阶段可见输出、思考/输出 token、
取消、超时、实际费用。**不得自动无限重试。**

## 7. 需要一并确认的既有问题（来自 V3 生产报告）

V3 最终生产报告记录：此前的 Teacher 生成要么在旧的 90 秒上限下超时，要么把
4000 token 的"推理+回答"合并预算用尽。当前 `mount.py` 的默认配置是
`CMUI_ANSWER_TOKENS=6500`、`CMUI_MODEL_TIMEOUT=180`（秒），且 `enable_thinking=False`。
**这意味着旧的失败模式在配置层面已被规避，但尚未用真实调用证明**。
canary 必须同时验证：输出是否被截断（`finish_reason='length'` /
`status != 'completed'` 都会直接失败，不会伪装成完成）。

## 8. 明确未完成标签

```text
真实千问两阶段教学：NOT RUN
真实图像题视觉正确率：NOT VERIFIED
真实 Node 工具调用（模型侧选择）：NOT VERIFIED
真实流式首 token 延迟：NOT VERIFIED
实际费用：CNY 0.00（零真实调用）
```
