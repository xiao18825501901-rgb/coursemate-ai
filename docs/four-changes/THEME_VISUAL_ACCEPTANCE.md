# 浅色/深色视觉验收

## 覆盖范围

主题开关位于控制面板标题行右侧，默认浅色。偏好保存到服务端，并以用户维度的
本地缓存改善首屏；服务端值为最终持久化状态。`data-theme` 设置在 document root，
因此课程、文件、评论、日历、收件箱、帮助、双导航、知识树、双 Pane、历史、
测评、详解浮窗、portal 和全屏模式共享同一主题。

图片、PDF 与原始资料不使用 invert/filter；只改变预览外壳。切换不重建 Pair，
不清空输入，不重启模型，也不重置会话状态。

## 本地浏览器证据

- `artifacts/four-changes/screenshots/dark-learning-workspace.png`
- `artifacts/four-changes/screenshots/light-independent-reasoning-strengths.png`

人工检查结果：深灰层次、浅色文字、导航、两 Pane、输入框与焦点边界清晰；浅色截图
同时显示左侧“最高”和右侧“高”的独立状态。以上为本地 deterministic provider
截图，不是生产截图。
