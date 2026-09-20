# 四项需求到代码与测试的映射

| 需求 | 主要实现 | 验收证据 |
|---|---|---|
| 删除粉色跨栏提问 | `richtext.jsx` 不再生成 Step 问题控件；`pages.jsx` 删除 Bridge 横幅、左栏注入和返回模式；旧动作 API 返回 410，历史 GET 保留 | `test_ui_extension_bridge_trace.py`、`test_ui_extension_tree_and_dual_mode.py`、`ui-refresh.spec.ts`、`codex-audit.spec.ts` |
| 详解独立浮窗 | 题目 Step 只保留“详解”，浮窗可拖动、缩放、关闭，不写入左栏 | 两套 Playwright 均验证浮窗、左栏无副作用和移动端边界 |
| 三级推理强度 | `budget.py`、`models.py`、`app.py`、`db.py`、`pages.jsx`；左右独立，下一次 run 冻结快照 | `test_reasoning_strength_budget.py`、`test_four_change_api_contracts.py`、`ui-refresh.spec.ts` |
| 注册自动学生资格 | `auth.py`、`social.py`、`mount.py`；活动注册身份自动持久化 `registered`，禁用身份不复活 | `test_codex_campus_access.py`、`test_current_change_features.py`、`codex-audit.spec.ts` |
| 全站浅/深色 | `App.jsx`、`theme.css`、用户偏好 API/表；根节点主题覆盖 portal 与全屏 | `ui-refresh.spec.ts` 及深色工作台截图 |
| 数据迁移 | Schema 13 添加左右强度、run 预算快照、用户主题偏好 | `test_four_change_migration.py`、完整后端回归 |

## 被新版要求替代的旧断言

- “新注册用户未认证”改为活动注册身份自动获得学生资格。
- “校园分享加入必须先兑换七位码”改为活动注册身份首次加入即可成功。
- 只允许旧 config 字段的精确集合改为允许 `reasoning_strengths` 枚举。
- 只识别 Schema 11 的只读预览改为引用当前 `SCHEMA_VERSION`。
- 旧测试中要求粉色跨栏按钮存在的断言改为要求它不存在，同时保留详解。

这些变化只更新已被本次产品规则明确替代的期望；答案防泄露、权限隔离、
禁用身份、旧资格来源和审计记录的断言没有放宽。
