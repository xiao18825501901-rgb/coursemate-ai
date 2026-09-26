# 自动知识图合同、迁移与回滚

## Schema 42

迁移 `services/rag-api/migrations/042_auto_knowledge_map.sql` 只做增量创建：

- source events、targets、jobs、frozen job sources；
- durable shard artifacts 与 terminal receipts；
- machine course-map activation；
- browser multi-file batch/item receipts；
- document、batch、Canvas import/session terminal triggers；
- 允许 active machine candidates 进入受控 personalized resolver 的窄范围 membership guard。

迁移不删除或重写课程、文档、chunk、KnowledgeNode、TeachingSpec、tree、Pair、会话、覆盖、成绩或测评表。已验证 fresh schema 41 副本迁移到 42 后：schema versions 1..42、foreign key violations 0、旧行计数与内容不变。

## 幂等键与不可变事实

- Job：`target_key + corpus_fingerprint + builder_version` 唯一。
- Artifact：`job_id + stage + shard_key` 唯一，同时保存 input/output hash 与 model operation ID。
- Receipt：每 job 一份 terminal receipt；UNKNOWN 不覆盖、不自动重试。
- Upload batch：ID 参数不可变；sealed manifest 以 SHA-256 固定，重复 seal 只能完全相同。
- Node ID：`target_key + normalized semantic key` 的稳定 hash；同节点 Spec 内容相同复用版本，不同内容递增版本。
- Tree：fingerprint + builder version 的稳定 ID；激活前 DRAFT，完整事务通过后才 ACTIVE。

## 权限与来源合同

- `AUTO_COURSE` 只读 `OFFICIAL` source scope。
- `PRIVATE` 只读 owner course 与 workspace private scope，且 owner 必须匹配。
- `SUPPLEMENT` 只读当前 workspace owner 的 private scope，并引用可用的官方/机器课程基线。
- Material evidence 与 visible tree 在同一事务写入；撤销 evidence 不会被 `INSERT OR IGNORE` 静默复活。
- 用户状态接口不返回资料正文或文件标题，也不触发 job 或模型调用。

## 发布开关

- `AUTO_KNOWLEDGE_MAP_ENABLED=false`：不启动后台 worker。
- `AUTO_KNOWLEDGE_MAP_ALLOW_BILLABLE=false`：即使功能开关打开也不启动付费 worker。
- 生产只有在备份、隔离迁移、代表性真实链通过后才同时设置为 true。
- `AUTO_KNOWLEDGE_MAP_POLL_SECONDS` 默认 5；reconciliation 默认 300 秒；旧单文件 quiet window 60 秒。

## 回滚

1. 立即关闭两个自动建图开关并重启 RAG 服务，停止新 claim；不得强杀正在发送的 provider request。
2. 等待当前 RUNNING job terminal；若 lease/transport 不明，保留为 UNKNOWN。
3. 前端可回滚到前一不可变 deploy；后端可切回前一 release symlink。
4. schema 42 表和 receipts 保留，不执行 destructive down migration；旧应用会忽略新表。
5. 自动 course activation 可标 RETIRED；人工发布 official tree 与旧 personalized tree仍在原表中，可恢复选择。
6. 使用发布前数据库/文件备份在隔离目录验证恢复；生产恢复必须另建目标并核验 manifest/hash 后切换。
