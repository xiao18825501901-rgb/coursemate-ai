# CourseJesus R3 动态 K 测评生产验收回执

结论：**通过（在生产发现并修复一个受限评分缺陷后）**。

## 实际学生路径

- 真实 Clerk 学生会话在 `coursejesus.com` 选择 Graph Theory 范围。
- 系统从版本化 Catalog 得到 `K=4`，默认配置 `N=4`，四题各 2500 basis points，总分 10000 basis points。
- 配置 `assessment-config-8cd6d2082407a50522285c59d96ad11d` 冻结，准备状态为 `READY`，`4/4` 题均为来源绑定、确定性发布的合法题。
- 学生开卷、提交、评分并在结果页看到每题得分、反馈、参考解与来源。

## 首次生产验收发现的真实缺陷

首次会话 `1968e230dd2244cea3cc459bfd715984` 使用语义正确的四份答案，结果为 **50/100**（逐题 `0, 0, 25, 25`）。

根因不是题目、来源或 Catalog 错误，而是两个可信确定性 `SHORT_TEXT` 题仍使用整段字符串精确匹配。发布器把完整参考解放入 `accepted`，评分器却把它当作唯一允许的答案文本，导致等价表述被误判。

## 修复边界

后端修复提交：`c9dbd1b49f2a5a8d8d116cc8c461f074cb051f8a`。

结构化验证仅在以下全部条件满足时启用：

- 发布方法为 `finite-loop-free-graph-degree-assessment.v1`；
- Rubric 仅含一个受支持 item；
- item 为 `vd_degree_definition_required` 或 `vd_handshake_identity_required`。

其他 `SHORT_TEXT` 题仍沿用原精确匹配合同。旧成绩不重算。

## 最终生产验收

修复后重新配置并开卷，新会话 `d325878bdb6c4329920efbfa2230f6dd` 使用与首次相同的答案，结果为 **100/100**（逐题 `25, 25, 25, 25`）。真实浏览器结果页显示：

- 两个简答题均显示 `Deterministic check matched the frozen answer.`；
- 两个分析题均得到 25/25；
- 四题均显示参考解、分步详解和来源；
- 首次 50/100 会话仍按原分数保留，证明没有重算历史成绩。

## 调用与安全

- 修复、部署和两个简答题评分没有新增模型调用。
- 两次完整提交各使用一次既有语义 grader 调用处理两个分析题，均 `COMPLETED`。
- 回执时没有本次流程的 `UNKNOWN` 或进行中调用；没有重放任何旧 `UNKNOWN`。
- 后端热修复不含前端发布或 Schema 迁移。
- 数据库 `integrity_check=ok`，外键违规为 0，迁移表版本为 84。
- 本地异机压缩备份 SHA-256 为 `c4199b89e3934a1b845ab384a7dc34710f5918e6927ed9142be131a4c81c010c`。
- 异机备份核验后，服务器临时原始备份已精确删除，磁盘占用由 96% 降至 95%；生产数据库未删除或替换。

## 发布身份与回滚

- R3 候选：`a8d08f1e7d2e397b02ec11f60669ef91ef7b8b76`
- 后端热修复：`c9dbd1b49f2a5a8d8d116cc8c461f074cb051f8a`
- 后端目录：`/srv/coursemate/releases/r3-hotfix-c9dbd1b`
- systemd 单元：`coursemate-rag`
- 前端仍为 Netlify deploy `6ad362811442c797c05e1be2`

回滚只需移除热修复 drop-in，重新加载 systemd 并重启 `coursemate-rag`，让后端返回 R3 `a8d08f1` 目录。回滚不覆盖数据库、不逆向迁移，也不删除验收期间新增的会话和成绩。

生产发布锁在核对 owner 与 candidate 后已释放；释放后服务保持 `active`，健康检查通过。
