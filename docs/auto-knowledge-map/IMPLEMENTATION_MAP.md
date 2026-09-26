# CourseJesus 自动知识图实现映射

状态：`SOURCE IMPLEMENTED / LOCAL VERIFIED / PRODUCTION PENDING`

## 基线与范围

- 工作分支：`feature/auto-knowledge-map-20260927`
- 源基线：`4492fc82253a55af4b6b9a45c9d1425d01349323`
- 生产核验基线：后端 release `c32f1c2`、RAG schema 41；最终发布前必须重新核验。
- 本轮不扫描 `D:\Canvas`、`D:\Canvas-DG`，不下载 Course Hero 内容，不改变域名、Clerk、Thinking、测评 N>=5、主题或 Windows Canvas Bridge。
- 暂停任务与恢复顺序见 `PAUSED_TASKS_AND_RESUME.json`。

## 单一垂直流程

| 要求 | 真实实现 |
|---|---|
| 上传/导入完成后自动启动 | schema 42 的文档、显式上传批次、Canvas OAuth、Canvas Local Bridge 终态事件统一进入 `auto_knowledge_source_events` |
| 多文件只生成一次 | `auto_knowledge_upload_batches` + item receipts + seal hash；前端仍复用单文件 API、并发数 2，所有项目终态后 seal |
| 冻结资料版本 | job 保存 document version、SHA-256、scope、owner、chunk count 与 corpus fingerprint |
| 全部可读内容分析 | 每个冻结 chunk 全量分段；每个模型输入小于 60k 字符；不以 top-k 代替整课扫描 |
| 去重、分组与知识点 | bounded map shards + 本地确定性 reduce；稳定 key/ID；每段必须 MAPPED、DUPLICATE、NON_TEACHING 或 REVIEW_REQUIRED |
| 每个 ATOMIC 生成 Teaching Spec | 最多 6 节点一批；每节点必须有 REQUIRED item 且只能引用该节点授权 evidence |
| 有限修复 | 仅完整返回但结构/业务校验失败时最多 2 次新 operation；UNKNOWN transport 不自动重试 |
| 持久恢复 | 每个 shard 的 input/output hash、operation ID 与结构化结果先落 `auto_knowledge_job_artifacts`；重启复用，不重复付费 |
| 原子激活 | source revision、权限、lease、图闭包、无环、Spec 与 evidence 全部通过后在同一事务切换 |
| 用户可见 | `knowledge-build-status` 只读接口；页面显示真实 QUEUED/BUILDING/WAITING/FAILED/UNKNOWN，不制造百分比或假节点 |
| 学习/做题/测评可消费 | resolver、begin learning、Question Engine 与 Assessment 的可访问节点规则都接受当前 active machine map |

## 课程与权限策略

- 私人自建/Canvas 私人课程：生成 owner-only `PERSONALIZED` 树与 `PRIVATE_ACTIVE` Teaching Specs。
- 校园课程缺人工发布图：生成 `OFFICIAL/DRAFT` 候选树，通过 `auto_course_tree_activations` 标记为“AI整理 · 未经人工审核”，不冒充人工发布。
- 已有人工发布 `OFFICIAL/PUBLISHED`：始终权威，自动服务只登记并保留，不替换。
- 校园私人补充：合并当前人工官方树或 active machine course map 与本人私人节点，不泄露给其他用户。
- 共享课程：仅导入分享时冻结的文件快照；批次 seal 后生成，不读取 sender 后续资料。
- 已有私人树：首次启用只登记为增量基线；后续资料变化时旧树保持 ACTIVE，验证完成后新树继承旧 memberships 并原子切换。
- 自动生成不写 `LEARNED`、教学覆盖、正式成绩或测评结果；旧节点、Pair、历史、成绩记录不删除。

## 入口接线

1. 新多文件创建课程与追加文件：显式 begin/item/seal。
2. 旧单文件与管理员导入：文档 ready 事件 + 60 秒 quiet window。
3. Canvas OAuth worker：import job 终态释放。
4. Windows Canvas Bridge：local session 终态释放。
5. 共享接收：固定快照使用一个显式 batch，全部导入后 seal。
6. 后续资料版本变化与删除：document event 触发新的 corpus fingerprint。
7. 存量课程：`scripts/auto_knowledge_map_backfill.py` 只读取现有 application DB/index，不扫描外部目录。

## 可靠性与停止条件

- 数据库全局 fence 同一时刻仅允许一个 RUNNING 自动建图 job。
- job lease 过期转 `UNKNOWN` 并保留现场，绝不盲目重发可能收费的请求。
- 每个模型请求使用既有 metering/reservation/transport ledger；SDK 自动重试为 0。
- 资料在生成中变化则旧 job `SUPERSEDED` 或失败 revision fence；不会覆盖新版本。
- 不可读资料进入 `READY_WITH_EXCEPTIONS` 或 `WAITING_SOURCE`，不会生成“第一章”等占位节点。
