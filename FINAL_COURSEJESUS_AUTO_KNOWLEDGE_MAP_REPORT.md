# CourseJesus 全课程自动知识点与 Teaching Spec 最终报告

当前状态：`LOCAL RELEASE CANDIDATE — PRODUCTION ACCEPTANCE PENDING`

## 已完成

- 所有现有入库入口接入单一、持久、可恢复的自动准备服务。
- 全量可读内容分段 map/reduce，逐来源处置，ATOMIC 节点逐一生成 Teaching Spec。
- 私人、校园、共享快照与私人补充保持各自权限和发布语义。
- resolver、学习、做一题与测评可以消费 active machine map。
- 旧树在新版本准备期间可用；已有节点/历史不删除；人工官方树不被机器覆盖。
- schema 42、worker、receipts、backfill CLI、用户状态 API 与页面状态已实现。

## 当前证据

详见：

- `docs/auto-knowledge-map/IMPLEMENTATION_MAP.md`
- `docs/auto-knowledge-map/CONTRACTS_AND_MIGRATION.md`
- `docs/auto-knowledge-map/TEST_AND_PRODUCTION_EVIDENCE.md`
- `docs/auto-knowledge-map/BACKFILL_INVENTORY_AND_RESULTS.jsonl`
- `docs/auto-knowledge-map/PAUSED_TASKS_AND_RESUME.json`

## 生产完成门

以下全部满足后，本文状态才可改为 `PRODUCTION ACCEPTED`：

1. 最新生产现场、三库/文件/配置与 service units 重新核验并备份。
2. 生产数据副本 schema 41→42 隔离迁移与恢复验证通过。
3. 新不可变后端和同站前端部署，健康检查与 Clerk 登录正常。
4. 一个权限受控的私人课程完成真实模型代表链，reservation/usage/artifact/receipt 对账。
5. 新上传自动生成并可学习、做题、进入 N>=5 测评。
6. 全部 eligible 存量 target 到达 READY、READY_WITH_EXCEPTIONS、EXISTING_ACTIVE、WAITING_SOURCE、FAILED、BLOCKED 或 UNKNOWN 等真实 terminal/exception 分类；资料充分但 provider 失败仍保留在分母。
7. 发布后备份、监控与回滚点完成，历史/权限抽样不变。
8. `PAUSED_TASKS_AND_RESUME.json` 的五个 resume gate 全部为 true，随后按原顺序恢复暂停任务。

当前未执行生产写入、真实模型调用或任务恢复，不虚报上线。
