# CourseJesus 自动知识图实现映射

状态：`PRODUCTION DEPLOYED / LIVE PROVIDER VERIFIED / ELIGIBLE BACKFILL TERMINAL`

## 冻结版本

- 分支：`feature/auto-knowledge-map-20260927`
- 源基线：`4492fc82253a55af4b6b9a45c9d1425d01349323`
- 应用候选与生产后端：`2d11587eb2f4037397ca654d2ee1b09558c94281`
- 生产前端：Netlify deploy `6ab866aedac313b9a4edcdc1`，标题 `Auto knowledge map candidate 2cebd0e`。`apps/web` 与 `netlify.toml` 从 `2cebd0e` 到 `2d11587` 无差异。
- RAG schema：`46`；生产 release：`/srv/coursemate/releases/2d11587`。
- 本轮没有扫描 `D:\Canvas`、`D:\Canvas-DG`，没有获取 Course Hero 新资料。

## 需求到真实实现

| 需求 | 实现与证据边界 |
|---|---|
| 持久触发 | schema 42 source events/targets/jobs/receipts；网页 batch、旧单文件、Canvas OAuth、Local Bridge、管理员导入、共享快照和文档变更均进入同一 reconcile 路径。 |
| 多文件只生成一次 | begin/item/seal 固定 manifest；seal 前不派发，全部终态后仅一个 corpus revision。生产外隔离的双文件 API canary 得到一个 READY job。 |
| 冻结资料 | job sources 保存 document version、SHA-256、scope、owner、chunk 与 corpus fingerprint；激活时再做 revision/permission fence。 |
| 全量处理 | 每个冻结 chunk 进入有界 map shard；每段记录 MAPPED、DUPLICATE、NON_TEACHING 或 REVIEW_REQUIRED，不用 top-k 代替整课扫描。 |
| 节点与 Spec | 确定性 reduce 建立 COMPOSITE/ATOMIC；所有可学习 ATOMIC 必须有有效 Teaching Spec 和 REQUIRED evidence。生产机器图 1,413 个 ATOMIC，缺 Spec 为 0。 |
| 有限修复 | 完整但不合约的结果最多按 shard 两次 linked repair；UNKNOWN 禁止自动重发。schema 45/46 仅为有精确历史证据的两类兼容恢复各授权一次，不形成循环。 |
| 计量 | 每次真实发送先写 reservation/attempt；完整 response/usage 先保存再解析；后台 scope 不消耗学生交互日配额，仍保留实际 usage。 |
| 原子激活 | 图闭包、无环、Spec/evidence、来源、权限、lease、source revision 全部通过才短事务切换；旧版在构建期继续服务。 |
| 私人权限 | PRIVATE 图只对 owner 激活；生产对账 owner-scope mismatch 为 0。 |
| 校园政策 | 人工 `OFFICIAL/PUBLISHED` 始终优先且未被改写；缺图才使用标记为机器整理的候选图。两个人工发布树前后行 hash 完全相同。 |
| 分享 | 只读接收时冻结的 document/map snapshot，不追随 sender 后续资料。 |
| 消费入口 | `KnowledgeService.snapshot`、`LearningOrchestrator.node`、Question Engine 与 Assessment 的 ATOMIC resolver 均接受 active machine map。生产只读抽样中 snapshot 返回 PERSONALIZED 及 404 个 ATOMIC，学习与测评解析到相同 Spec 版本。 |
| 历史保护 | 构图不写 LEARNED、教学覆盖或成绩。生产前后 Pair、教学交付、成绩快照、进行中测评表 hash/行数一致。 |
| 状态展示 | `knowledge-build-status` 是只读接口；页面显示真实等待、构建、部分可用、失败、未知和排除原因，不用 GET 发起计费任务。 |

## 生产结果

- T0 target：`EXISTING_ACTIVE=2`、`READY=1`、`READY_WITH_EXCEPTIONS=3`、`WAITING_SOURCE=28`。
- 资料充足 target 均已 terminal；没有 QUEUED、RUNNING 或 UNKNOWN。
- 28 个 WAITING_SOURCE 是真实无可读来源/来源不足，不生成“第一章”等假节点；未来资料事件会重新对账。
- 保留 1 个旧 V2 历史 FAILED receipt，不覆盖或伪造成 V4 成功；当前 V4 可处理目标已经完成。
- 真实模型回填记录：263 attempts，input 1,093,539 tokens，output 488,160 tokens；应用未保存美元结算值，因此实际供应商金额保持 `UNKNOWN`。

## 当前限制

- 已验证部署代码下的隔离真实模型双文件垂直链和生产 resolver，但没有可用 Owner Clerk 浏览器会话，所以“生产账号在浏览器亲手上传并点击学习/测评”的层级仍标 `NOT VERIFIED`。
- 这不改变后端自动触发、真实模型生成、生产存量激活和消费者可读的已验证事实；不得把它写成浏览器验收通过。
