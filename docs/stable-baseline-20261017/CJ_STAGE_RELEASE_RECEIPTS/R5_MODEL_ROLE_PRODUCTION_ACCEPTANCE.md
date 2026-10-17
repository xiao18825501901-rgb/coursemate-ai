# R5 模型角色生产验收

状态：`PARTIAL_PASS_PRODUCTION_ACTIVE`

候选 `05946c2194f1ead7e5392b846a09abe94661a15b` 已部署到后端目录
`/srv/coursemate/releases/r5-05946c2`。数据库仍为 schema 84，前端仍为 Netlify
deploy `6ad362811442c797c05e1be2`，本次没有迁移或前端切换。

## 已确认

- 私有课程知识树继续使用 DeepSeek；通用教学、题目应对、Question Engine、测评和
  grounded QA 的服务端路由已切换到受资格约束的 Qwen 配置。
- 客户端不能以 role 标签选择模型；Question Engine 只接受受信服务端 Qwen 身份、旧
  DeepSeek 身份或显式测试 fixture，没有放宽题目内容、来源、答案或资格校验。
- 真实 Clerk 学生的题目应对 run
  `run_5f72e7ade7054874920da9ca8737a19e` 在约 6 秒内完成，回答正确引用了当前课程资料，
  学生界面没有显示底层模型名。
- 真实 Clerk「做一题」run
  `run_508ecdad5a894f1bab2d4dd1678cda61` 的作者和盲解调用均已完成。最终
  `specification_audit` 在 370022 ms 后没有收到响应，以 `UNKNOWN / TimeoutError` 写入
  `hybrid_provider_failures`，UI run 失败关闭为 `QUESTION_ENGINE_FAILED`。未审核题目没有发布，
  没有重发、取消或创建替代请求。这证明 Qwen 作者与盲解路由可用，但不构成冷题完整发布通过。

## 尚未关闭的门

1. 保留并只读对账该 `specification_audit` UNKNOWN；不得重放或换 operation id 绕过。
2. 本机离机备份已完成，大小 244991111 bytes，SHA-256 为
   `44f7effa20e20a76724803f648d57735e27fac45c95bc45285c31e544bb05e43`，与服务器源文件一致。
3. 服务器临时备份已按精确路径移除，共享生产锁已释放；后端仍运行 R5 目录且健康。R2
   已验收的 READY 复用路径继续可用；这次失败不能冒充冷题完整验收通过。

回滚仅移除 R5 的两个具名配置文件并重启后端，返回 R4 代码；不得替换生产数据库或
逆向迁移。
