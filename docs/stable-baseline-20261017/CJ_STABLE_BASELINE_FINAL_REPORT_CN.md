# CourseJesus 稳定基础功能最终报告

记录时间：2026-10-18T06:15:30.2621466Z

## 最终生产身份

- 生产代码 SHA：`13ee6793be257d15c11df6f5f8c5481520f4867d`
- 后端：`/srv/coursemate/releases/r8-history-fix-13ee679/services/rag-api`
- 前端：现有 Netlify 站点 `166afb5a-4103-4236-9f13-4be34dc68cd2`，deploy `6ad4593cb08dc21cb3548538`
- 数据库：Schema 85，`integrity_check=ok`，外键违规 0
- 最终备份：`/srv/coursemate/backups/r8-predeploy-20261018T042006Z.sqlite3.gz`
- 备份 SHA-256：`b28401f91a53a31e6d93d851b93bd05e846ad37f65e46af33a81b19bac4f71af`

## S0、R1—R7 结果

| 阶段 | 代码/结果 | 真实结果 |
| --- | --- | --- |
| S0 | 现场拓扑、Schema、Provider、依赖和数据兼容审计 | PASS；生产身份、旧 UNKNOWN、磁盘和回滚边界已冻结 |
| R1 | `a4e4c152731b18c7b2d9d27b12d5196c3c5a5df2` | 知识学习首段 5.788s、完成 15.648s；题目应对首段 5.367s、完成 6.957s；正文、引用与历史可见，内部锚点/模型名不泄露 |
| R2 | 原 R2 后由 `9e02ce0`、`827fb94`、`13ee679` 收口 | 做一题真实 Clerk：题目、作答、确定性判分、答案、三步详解、Pair/历史全部 PASS；确定性判分 0 模型调用 |
| R3 | `a8d08f1` + `c9dbd1b`，后由 `13ee679` 收口历史 | 动态 K 的 K=4 图论试卷 100/100；当前 K=1 和冷课程 0 READY 路径均完成配置、生成、开卷、评分与历史 |
| R4 | `accff2ebaa4ec06cc2673a2bcd7b61855e48f700` | 上传/索引与检索移出在线事件循环；真实 Clerk 课程、12 节点知识树、Pair 和历史读取 PASS |
| R5 | `05946c2194f1ead7e5392b846a09abe94661a15b`，问题入口缺口由 R8 修复 | 通用 LLM 服务端路由保持 Qwen，私人课程建树保持 DeepSeek；真实题目应对 Qwen 调用 PASS，旧 UNKNOWN 原样保留未重放 |
| R6 | `46d1bb328ce63d3002df2c583c23f1a089ed2621` | 现有 15 份 V2 教学模板 registry 原样保留；zh-CN/en 1010/1010 key parity、系统型号隐藏、语言/主题状态保持、390×844 验收、2439 项后端回归 PASS |
| R7 | 生产代码不变；最终审计回执 `R7_FINAL_RELEASE_FREEZE.json` | PASS，零删除；没有候选同时满足无引用、已有替代、可独立恢复和不越过并行成果边界 |

## 七项学生功能最终验收

1. **知识学习：PASS。** 真实生产流式正文、4 个引用、历史恢复通过；点击到首段 5.788s。
2. **DeepSeek 课程知识树：PASS（复用现有合法证据）。** 真实 Clerk 读取 12 个节点，低于 50；私人树路由仍为服务端 DeepSeek 例外；当前 Teaching Spec v1 已被来源绑定测评使用。本活动未为证明相同事实而重新计费生成第二棵树。
3. **做一题：PASS。** 当前节点可复用 READY 题；学生完整完成作答、正确判分、答案、详解和历史。此前错误节点 Qwen 请求保持 UNKNOWN，0/0，未重发。
4. **题目应对：PASS。** 真实生产结果正确，点击到首段 5.367s、完成 6.957s；R5 通用角色迁移后 Qwen 实际调用也已通过。
5. **开始测评：PASS。** K 来自独立来源目标而非 READY 数；CS3481 K=1 得分 100/100，GE2324 冷启动从 0 READY 自动生成并得分 90/100，参考解、Rubric、来源和历史均可读。
6. **RAG：PASS。** 生产教学显示来源引用，课程文件/节点读取正常；上传索引和检索不再阻塞在线事件循环，权限与课程隔离未放宽。
7. **OpenJEV：PASS（既有非阻塞边界）。** 保留现有 advisory/fallback 合同，没有把不可用或不确定语义判断变成基础功能的全局同步门禁；本最终验收没有为重复证明而新增 OpenJEV 模型请求。

## Dashboard 三入口

生产中顺序为“从 Canvas 导入｜创建自己的课程｜进入所有课程”。真实登录的 390×844 Chrome 生产页面测得三卡同一行、每卡 90px 等宽、无横向溢出，文字正常换行；截图与布局指标位于 `CJ_STAGE_RELEASE_RECEIPTS/evidence/`。

## 调用与费用边界

- R1 教学与题目应对合计估算：USD 0.0027375（按当次部署费率）。
- CS3481 K=1 作者：输入 6278、输出 9662 tokens。
- GE2324 冷启动作者：输入 6266、输出 12120 tokens，单次请求完成；SSE 断线没有触发重发。
- 做一题最终确定性判分：0/0 tokens。
- 所有历史 UNKNOWN 均保留，未通过新 operation ID 重放。

## 回滚与剩余运营风险

- 后端代码回滚：切回 `/srv/coursemate/releases/r8-mcq-hotfix-827fb94/services/rag-api`，不覆盖数据库。
- 前端回滚：恢复 Netlify deploy `6ad450265760f7f94d548e50`。
- 当前发布锁空闲。
- 根卷已达约 97%，可用约 3.5 GiB；备份约 59 GiB、发布目录约 7.9 GiB。R7 没有足够所有权与异地恢复证据来安全删除，因此容量治理是后续独立运维任务，不影响本次功能验收结论。

`COURSEJESUS_STABLE_BASELINE = COMPLETE`

