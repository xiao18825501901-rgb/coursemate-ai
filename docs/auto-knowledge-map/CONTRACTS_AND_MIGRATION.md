# 自动知识图合同、迁移与回滚

## Schema 42–46

迁移均为追加式，已在生产副本和生产数据库执行到 46：

- `042_auto_knowledge_map.sql`：source events、targets、jobs、frozen sources、artifacts、terminal receipts、machine activation、upload batch/items 与入口 triggers。
- `043_auto_knowledge_model_attempts.sql`：真实模型 attempt、operation、phase、hash、usage 和恢复边界。
- `044_auto_knowledge_background_budget_scope.sql`：自动构图使用独立 background scope，不占学生交互日调用数，但不跳过计量。
- `045_auto_knowledge_local_recovery_reasons.sql`：对一种有精确 durable evidence 的旧本地 artifact mismatch 提供一次性恢复原因。
- `046_auto_knowledge_legacy_feedback_recovery.sql`：仅对“已有首次 repair receipt、完整 CONTRACT_REJECTED 输出、空 feedback、已接受 repaired artifact、无 UNKNOWN send”的旧 job 提供第二个不同的一次性恢复原因。

没有改写或删除课程、文档、chunk、KnowledgeNode、TeachingSpec、tree、Pair、会话、覆盖、成绩和测评表。schema 46 初始化重复执行仍保持 versions `1..46` 连续、integrity `ok`、foreign-key violations `0`。

## 幂等与费用合同

- Job：`target_key + corpus_fingerprint + builder_version` 唯一。
- Artifact：`job_id + stage + shard_key` 唯一，保存输入/输出 hash 与 operation ID。
- Upload batch：sealed manifest SHA-256 不可变；重复 seal 必须完全相同。
- Model send：发送前有 durable intent/reservation；完整 response 与 usage 先保存；UNKNOWN 不自动重发。
- Repair：每 job/stage/shard 最多两次；不同历史兼容问题必须有不同、schema 约束的一次性 reason。
- Node：target + normalized semantic key 生成稳定 ID；同内容 Spec 复用，要求变化才递增版本。
- Tree：candidate 完整校验后原子 ACTIVE；过期 source revision 不得覆盖新版本。

## 权限合同

- `AUTO_COURSE` 只读课程允许的官方资料；机器图不等于人工 OFFICIAL 审核。
- `PRIVATE` 必须匹配 owner course/workspace scope。
- `SUPPLEMENT` 只允许当前 owner 私人证据叠加当前合法课程基线。
- 分享只消费接收时冻结副本；撤权立即影响 resolver，历史审计不等于继续公开原文。
- 自动生成不写学生成绩、LEARNED 或教学交付证据。

## 生产迁移与恢复证据

- 发布前 schema 45→46 隔离演练：`/srv/coursemate/restore-rehearsals/pre-2d11587-schema46`；初始化两次、integrity `ok`、FK `0`。
- 发布前即时备份：`/srv/coursemate/backups/jit-pre-2d11587-20260927T021201Z`。
- 发布后完整、干净、验证通过的备份：`/srv/coursemate/backups/post-auto-map-2d11587/coursemate-v2-20260927T025959.263575Z`。
- 隔离恢复：`/srv/coursemate/restore-rehearsals/post-auto-map-2d11587`；RAG/Agent/UI 三库 integrity `ok`、FK `0`，RAG schema 46，目标计数保持。
- 首次发布后备份 `...T025744.296460Z` 数据完整但在重启 Agent 时暴露 release 缺少 ignored `dist`；保留为故障证据，不作为最终恢复点。

## 运行开关

- 生产：`AUTO_KNOWLEDGE_MAP_ENABLED=true`。
- 生产：`AUTO_KNOWLEDGE_MAP_ALLOW_BILLABLE=true`。
- 全站仅一个 build worker；provider 调用有界，SDK 隐式 retry 为 0。
- 监控仍使用原 `MAX_BACKUP_AGE_SECONDS=93600`，未放宽阈值。

## 回滚

1. 关闭两个自动知识图开关并重启 RAG，停止新 claim；不要强杀已发送请求。
2. 等 RUNNING 到 terminal；不明 transport 保留 UNKNOWN。
3. 将 `/srv/coursemate/current` 切回前一个不可变 release 并重启/验证所有 service；不能只切 symlink 后沿用旧进程。
4. 保留 schema 42–46 表、artifacts 与 receipts；不做 destructive down migration。
5. 回退 active machine manifest 时保留人工 official tree、旧私人树、新聊天和学生记录。
6. 需要数据恢复时只从已验证备份恢复到新隔离目标，核验 manifest/hash/integrity/FK 后再切换；不要用旧整库覆盖新生产写入。

Agent 在 2d11587 无源码差异，但 release archive 没有 ignored `dist`。生产已用只读 symlink 指向 0bd1362 的同源构建产物并完成重启健康检查；后续发布必须显式构建或携带每个服务 runtime artifact。
