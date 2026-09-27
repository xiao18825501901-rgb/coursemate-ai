# 自动知识图测试与生产证据

证据版本：应用 `2d11587eb2f4037397ca654d2ee1b09558c94281`，schema `46`。

## 本地自动验证

- 最终专项 schema/自动图：`55 passed`。
- 自动图 + DB 组合：`44 passed`。
- 全量 RAG（移除真实 key、关闭 billable、排除 live CLI）：`1897 passed, 10 skipped, 4 failed`，1301.04 秒。
- Web 全套：`133 passed, 1 failed`；生产构建 137 modules，PAT bundle scan passed。
- Agent：13 files / `98 passed`。
- Ruff、Python compile、TypeScript/build 和 git diff safety gates：passed。

4 个 RAG 失败是未被本轮改动掩盖的既有环境/manifest 差异：Canvas Bridge 安全测试拒绝列名 `bridge_token_hash`；两项旧 V2 prompt/EXERCISE manifest hash 过期；可选 `typesafe_sdk` 未安装。Web 的 1 项失败仍期望旧 `--code`，当前已发布便携 Bridge 使用 `--ticket`。没有删除这些测试或放宽断言。

## 真实模型与新上传垂直链

在生产主机、部署的 2d11587 release、真实 production provider/embedding 配置下，使用完全隔离数据库和上传目录执行：

1. API 创建私人课程；
2. 打开 expected=2 的 batch；
3. 上传两个 markdown；
4. seal 前 reconcile 为 BATCH_OPEN 且 job=0；
5. seal 后仅一个 job；
6. 真实模型生成、校验、激活；
7. `KnowledgeService` 返回可见图。

结果：`READY`、2 ATOMIC、missing Spec=0、attempts `ACCEPTED=2`、无 SEND_INTENT/UNKNOWN。隔离 DB SHA-256 `35944e79...`，log SHA-256 `054d8840...`，证据位于 `/srv/coursemate/validation/auto-map-upload-2d11587`。最初两个启动失败发生在任何 provider dispatch 前，分别是外部脚本缺 `PYTHONPATH` 和隔离目录不可写；修复运行环境后使用新 unit 成功，没有把失败启动计为模型调用。

## 生产部署与回填

- 后端 `/srv/coursemate/current -> /srv/coursemate/releases/2d11587`。
- `coursemate-rag`、`coursemate-agent`、Caddy、SSH 均 active；RAG/Agent 公网 health 200。
- Netlify production deploy `6ab866aedac313b9a4edcdc1` ready；`coursejesus.com` 200。该 deploy 的 web tree 与 2d11587 完全相同。
- production DB schema 46、integrity `ok`、FK violations 0。
- 回填 unit `coursemate-auto-map-backfill-2d11587` 已结束，无 QUEUED/RUNNING/UNKNOWN。
- targets：EXISTING_ACTIVE 2、READY 1、READY_WITH_EXCEPTIONS 3、WAITING_SOURCE 28。
- machine ATOMIC 1,413、missing Spec 0、REQUIRED items 2,964。
- frozen source hash mismatch、private owner mismatch、terminal tree revision mismatch 均为 0。
- 人工 official trees 2 个，发布前后 hash 相同。
- Pair、教学交付、成绩、进行中测评表前后相同。
- 生产只读 resolver 抽样：PERSONALIZED 404 ATOMIC；learning 与 assessment resolver 指向同一 Spec version。

## 费用与失败语义

- 回填：263 attempts，1,093,539 input tokens，488,160 output tokens。
- 应用 ledger 没有供应商最终美元结算字段，因此实际美元金额为 `UNKNOWN`，不根据 token 自行编造。
- attempts 最终只有 ACCEPTED、BUSINESS_REJECTED、CONTRACT_REJECTED；没有未决 SEND_INTENT/RESPONSE_UNKNOWN。
- 28 个 WAITING_SOURCE 保留在例外分母；没有资料时不生成假节点。

## 备份、恢复与监控

- 最终验证备份：`/srv/coursemate/backups/post-auto-map-2d11587/coursemate-v2-20260927T025959.263575Z`。
- 三库/文件隔离恢复通过，schema 46 二次初始化通过。
- `coursemate-monitor.timer` active；2026-09-27T03:05:23Z 手动触发真实 monitor 得到 status=ok：RAG healthy、Agent healthy、backup age 325s、free 20,770,656,256 bytes。

## 未验证层级

- `AUTHENTICATED PRODUCTION BROWSER VERIFIED`：**NOT VERIFIED**。当前没有可用的 Owner Clerk 浏览器会话，未冒充用户完成生产账号上传/点击/测评。
- 其下的真实 API、真实模型、生产激活、生产 resolver、公开站点和恢复监控均有上述独立证据。
