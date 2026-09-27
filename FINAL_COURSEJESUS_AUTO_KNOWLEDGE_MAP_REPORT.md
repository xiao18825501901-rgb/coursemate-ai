# CourseJesus 全课程自动知识点与 Teaching Spec 最终报告

结论：`PRODUCTION DEPLOYED / LIVE MODEL VERIFIED / T0 ELIGIBLE BACKFILL COMPLETE / AUTHENTICATED BROWSER NOT VERIFIED`

## 发布版本

- application/source SHA：`2d11587eb2f4037397ca654d2ee1b09558c94281`
- branch：`feature/auto-knowledge-map-20260927`
- production RAG schema：`46`
- backend release：`/srv/coursemate/releases/2d11587`
- Netlify deploy：`6ab866aedac313b9a4edcdc1`；当前 `coursejesus.com` 200
- 生产开关：enabled=true、billable=true

## 达成的产品结果

所有网页批量上传、旧单文件、Canvas/Local Bridge、管理员导入、共享接收、资料变更与存量对账统一进入持久自动准备管线。它冻结授权资料版本，完整分段，生成/去重/组织节点，为每个可学习 ATOMIC 建立带真实 evidence 的 Teaching Spec，经权限、来源、结构、revision 和 lease 校验后原子激活。

私人图仅 owner 可用；校园机器图不冒充人工 OFFICIAL；分享只读接收时快照；已有官方树、node ID、Pair、覆盖、成绩、历史和进行中测评不重建、不清零。resolver 已接入学习、做一题和 N 题测评的节点/Spec 选择。

## 真实生产结果

- 存量 target：2 个已有有效图；4 个机器图完成（1 READY、3 READY_WITH_EXCEPTIONS）；28 个真实 WAITING_SOURCE。
- T0 没有 QUEUED、RUNNING 或 UNKNOWN；资料充分的当前目标没有偷偷移出分母。
- 机器图共有 1,413 个 ATOMIC，缺 Spec 0，REQUIRED 教学项 2,964。
- 来源 hash、私人 owner scope、terminal tree revision mismatch 均为 0。
- 2 个人工 official tree 行 hash 前后相同；学习 Pair、教学交付、成绩快照和测评 session 前后相同。
- 真实 provider 回填 usage：263 attempts、1,093,539 input tokens、488,160 output tokens；美元结算没有被应用保存，故保持 UNKNOWN。

## 新上传证明

使用生产主机、部署的同一 release、真实 production provider/embedding 配置以及隔离 DB/存储，执行了真实 API 双文件私人课程链。seal 前没有 job；seal 后只生成一个 job；结果 READY、2 个 ATOMIC、缺 Spec 0、两个 attempt 均 ACCEPTED、无 UNKNOWN，并可由 KnowledgeService 读取。该证据证明“多文件一个批次只合并一次”和“新上传可自动生效”，未写入真实用户数据。

生产只读抽样进一步证明 active machine map 被当前 resolver 消费：一个 PERSONALIZED snapshot 返回 404 个 ATOMIC，LearningOrchestrator 与 Assessment resolver 得到同一 Spec version。

## 质量、恢复和监控

- 本地最终回归：RAG 1897 passed/10 skipped/4 个已知既有失败；Web 133 passed/1 个旧 Bridge 命令期望失败；Agent 98 passed；构建和静态门通过。
- 发布前 schema 副本演练和发布后三库/文件恢复演练均通过，integrity ok、FK 0、schema 46。
- 最终恢复点：`/srv/coursemate/backups/post-auto-map-2d11587/coursemate-v2-20260927T025959.263575Z`。
- 监控已从旧备份根切到该验证根，没有放宽 93,600 秒阈值；RAG、Agent、backup、disk 四项实时结果均 ok，timer active。
- 发布暴露 Agent archive 未携带 ignored `dist`；源代码在相关 commits 间无变化，已显式复用已验证的同源只读构建产物并重启验证。后续 release 必须显式构建/打包所有服务 artifact。

## 准确的未验证项

当前没有 Owner Clerk 浏览器会话，因此没有冒称“真实生产账号在浏览器上传、点击节点、做题和提交 N>=5 测评”已通过。浏览器层标记 `NOT VERIFIED`；真实 API、真实模型、生产激活、生产 resolver、公开健康、备份恢复与监控分别有证据。

## 原任务恢复

五个恢复门均已满足并写入 `PAUSED_TASKS_AND_RESUME.json`。暂停前任务现已按原顺序全部恢复并收口：UI 已发布为 Netlify deploy `6ab88bbfa3cdab3c8481a88e`；本地校园根完成新冻结清单和 CS4394 私人隔离增量，但因共享再发布权不明而没有生产发布；官方目录完成当前 5 本科/10 硕士及静态 Gateway 覆盖表，Course Hero 因没有可安全附着的已登录会话且缺逐文件再利用权，只保留公共元数据，零下载/上传/删除。详见 `docs/coursejesus/FINAL_UI_CAMPUS_COURSEHERO_EXECUTION_STATE_20260927.md`。

当前前端源码 HEAD 为 `f77920f598e3195f4c70cef6390c1b0d4ba9f219`；自动知识图 production backend 仍是经过验收的 `2d11587eb2f4037397ca654d2ee1b09558c94281`，本次恢复未改变 schema 或后端运行时。

详细证据：

- `docs/auto-knowledge-map/IMPLEMENTATION_MAP.md`
- `docs/auto-knowledge-map/CONTRACTS_AND_MIGRATION.md`
- `docs/auto-knowledge-map/TEST_AND_PRODUCTION_EVIDENCE.md`
- `docs/auto-knowledge-map/BACKFILL_INVENTORY_AND_RESULTS.jsonl`
- `docs/auto-knowledge-map/PAUSED_TASKS_AND_RESUME.json`
- `docs/auto-knowledge-map/EXECUTION_CHECKPOINT_20260927.json`
