# CourseJesus UI 独立发布报告 — 2026-09-27

## 结论

`DEPLOYED / PUBLIC SIGNED-OUT VISUAL VERIFIED / AUTHENTICATED FLOW NOT RE-RUN`

本次只恢复暂停清单中的第一项 UI 工作；没有改动 Clerk 实例、API origin、课程数据、Windows Canvas Bridge 或自动知识图后端。

## 版本和发布

- 当前源码提交：`f77920f598e3195f4c70cef6390c1b0d4ba9f219`
- 自动知识图后端基线：`2d11587eb2f4037397ca654d2ee1b09558c94281`
- Netlify site id：`166afb5a-4103-4236-9f13-4be34dc68cd2`
- production deploy id：`6ab88bbfa3cdab3c8481a88e`
- 发布时间：`2026-09-27T03:21:46.939Z`
- 正式入口：<https://coursejesus.com>
- 不可变 deploy：<https://6ab88bbfa3cdab3c8481a88e--coursemate-ai-qqtt.netlify.app>

## 实际变化

1. 未登录正常页只保留 Logo、`CourseJesus`、`From Confusion to Revelation` 和真实登录/注册按钮；正常 sentinel `请登录` 不再显示，真实错误仍按条件显示。
2. “所有课程”顶部的“从 Canvas 导入”改为与“创建课程”一致的主按钮，原 handler 不变。
3. 控制面板新增独立虚线 Canvas 导入卡，排序为 Canvas 导入、创建课程、已固定课程；操作卡不计课程数。

## 验证证据

- focused Vitest：3 个文件、6 个测试通过。
- targeted Playwright：`default entry` 与 `both dashboard actions`，2 个测试通过。
- production Netlify build：137 modules；构建后的 production preflight 证明 `pk_live`、正式 RAG/Agent origin 正确且测试 token 不存在。
- `build-info.json`：release SHA 为 `f77920f`，`not_for_production=false`。
- 构建中实际 API origins：`https://rag.47-237-179-69.sslip.io`、`https://agent.47-237-179-69.sslip.io`；没有从品牌常量猜测 DNS。
- 公网未登录页面截图：`work/ui-release-f77920f/signed-out-production.png`；旧欢迎语、旧副标题和正常“请登录”计数均为 0。
- `2026-09-27T03:40Z` 按 build-info 中实际 origins 复核：公网根页、RAG health、UI extension health、Agent health 均返回 200；只执行未认证 GET，无 token、写入或付费调用。
- Windows Bridge ZIP 仍包含在构建中，SHA-256 前缀为 `cbbcc51f`；未替换原产物。

## 准确边界

- 未使用 Owner Clerk 会话重跑登录后控制面板，因此登录后浏览器验收保持 `NOT RE-RUN`。
- 未修改或重启后端；此次 deploy 不能替代自动知识图后端的独立生产证据。
