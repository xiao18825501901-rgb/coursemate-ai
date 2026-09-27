# UI / 本地校园 / Course Hero 恢复任务最终状态 — 2026-09-27

## 总结

暂停前的三个任务已按原顺序恢复并收口：

| 顺序 | 工作 | 最终状态 |
|---:|---|---|
| 1 | UI 修改后立即发布 | `DEPLOYED` |
| 2 | 本地校园课程冻结、对账、增量处理 | `COMPLETE_WITH_RIGHTS_EXCEPTIONS` |
| 3 | 官方专业/课程目录与 Course Hero 补充 | `OFFICIAL_MATRIX_PARTIAL_COMPLETE / COURSEHERO_METADATA_ONLY` |

## 当前生产组合

- 当前源码 HEAD：`f77920f598e3195f4c70cef6390c1b0d4ba9f219`（报告提交前）。
- 自动知识图生产后端：`2d11587eb2f4037397ca654d2ee1b09558c94281`，schema 46。
- Netlify production deploy：`6ab88bbfa3cdab3c8481a88e`。
- 正式域名：<https://coursejesus.com>。
- Clerk、RAG/Agent origin、最高质量/无应用美元上限、Thinking、N>=5 测评、主题、校园权限和 Windows Bridge 均保持原配置。

## 数据与安全结果

- 两个本地源根保持只读；1,923 个源文件有冻结清单，新增 CS4394 资料只进入隔离私人复核库。
- 因没有面向 CourseJesus 全站用户的再发布权证明，校园 shared publication 为 0；这不是解析失败，也没有把候选移出分母。
- Course Hero 只完成公开元数据核对；没有附着登录会话、下载全文、上传、索引、购买或删除。
- 自动知识图任务此前完成的 production backfill、官方树、节点/Pair、学习进度、成绩和历史没有被本次恢复工作改写。

## 交付索引

- UI：`docs/coursejesus/UI_RELEASE_REPORT_20260927.md`
- 本地校园：`docs/coursejesus/LOCAL_CAMPUS_BATCH_REPORT_20260927.md`
- 官方覆盖：`docs/coursejesus/OFFICIAL_PROGRAMME_AND_COURSE_COVERAGE_20260927.md`
- Course Hero 权利：`docs/coursejesus/COURSEHERO_SOURCE_AND_LICENSE_REPORT_20260927.md`
- 自动知识图：`FINAL_COURSEJESUS_AUTO_KNOWLEDGE_MAP_REPORT.md`

## 明确例外

1. Owner Clerk 登录后的生产浏览器旅程仍未重跑；公开未登录页面与服务健康已验证。
2. 全部专业的 cohort 逐课程矩阵需要 CIR 或已认证 SIS；静态官方页面只能证明当前专业和 Gateway 子集。
3. Course Hero 登录会话当前没有安全的可附着工具；即使后续可接入，也仍需逐文件权利依据。
4. 本地候选资料的权利状态未解决前，不会自动变成校园共享课程。
