# R7 安全减枝审计

记录时间：2026-10-18T06:04:07.9785379Z

## 结论

本轮删除数为 **0**。没有候选同时满足“当前运行不可达、已有等价替代、删除后可独立恢复、且不属于学生数据/审计/并行成果”四项条件。按照 R7 合同，零删除是合格结果；不为制造减枝数量而扩大风险。

## 已审查候选

| 候选 | 引用与用途证据 | 决定 | 理由 |
| --- | --- | --- | --- |
| `social.ensure_registered_qualification` | 仓库内没有生产调用者；迁移文档明确保留该符号用于追溯旧自动授权缺陷及发现树外调用 | KEEP | 函数当前不可从产品入口到达，删除不能改变运行时；但现有迁移证据明确把符号保留作为审计与树外调用探针。缺少树外调用清单，不能证明删除后无恢复风险。 |
| `artifacts/four-changes/replaced-legacy-assertions-final.xml` 与 Legacy 报告 | 历史失败、兼容和回滚证据 | KEEP | 属于验收与恢复证据，不是活动运行路径；删除不改善学生请求，并违反保留历史失败/回滚材料的边界。 |
| `/srv/coursemate/releases/*` | 61 个发布目录，共约 7.9 GiB | KEEP | 含当前及多个可回滚版本；没有逐目录的发布所有权、最后引用和外部归档证明。 |
| `/srv/coursemate/backups/*` | 78 个备份对象，共约 59 GiB | KEEP | 包含 Five、Visual、Map50、P0 和当前回滚点；在没有保留策略与异地副本证明前不能删除。 |
| 旧 Schema、UNKNOWN、题目与答卷记录 | 当前 Schema 85 兼容读路径及审计账本 | KEEP | 合同要求不可删除、不可重算、不可重放。 |

## 当前生产安全状态

- 后端 `coursemate-rag` active，PID `314653`，本机 `:28000/health` PASS。
- 前端 `https://coursejesus.com/build-info.json` 返回 production 构建，代码 SHA `13ee6793be257d15c11df6f5f8c5481520f4867d`，Clerk 为 `pk_live`，无测试令牌。
- 数据库 Schema 85，`integrity_check=ok`，外键违规 0。
- 发布锁 `/run/lock/coursejesus-production-publish.lock` 空闲。
- 根卷约 99 GiB，已用 91 GiB，可用约 3.5 GiB（97%）。这是容量风险，但不是无证据删除的许可；需要单独的保留策略和可恢复归档后才能清理旧备份。

## R7 动作

- 没有修改运行时代码、Schema、生产文件或学生数据。
- 没有重新部署；当前已验收的不可变生产组合保持不变。
- 没有重放 UNKNOWN，没有产生新模型请求。
- 若后续专门处理磁盘，应先给每个备份/发布目录标注所有者、最后恢复用途、异地副本及最短保留期，再执行可回收清单；不得把该容量治理并入本轮零证据删除。

