# 本地校园课程批次结果 — 2026-09-27

## 结论

`INVENTORY COMPLETE / PRIVATE REVIEW LEDGER UPDATED / SHARED PUBLICATION WITHHELD FOR RIGHTS`

本批次严格只读扫描 `D:\Canvas` 与 `D:\Canvas-DG`。两个源目录没有删除、移动或改名；没有把原件放入 Git、Netlify 或 CourseJesus production。没有建立持续扫描器。

## 冻结清单

批次目录：`work/local-campus-20260927T0325Z`

| 指标 | 结果 |
|---|---:|
| 清单行 | 1,925（含两份 source manifest） |
| 实际源文件 | 1,923 |
| 总字节 | 8,870,732,743 |
| Academic teaching | 1,718 |
| Information | 170 |
| Personal/restricted | 22 |
| Training | 13 |
| Unknown review | 2 |
| Parseable | 1,686 |
| Download-only | 65 |
| Unknown format | 174 |
| byte-identical duplicate groups | 76 |
| same-name groups | 15 |
| `publishable_now` | **0** |

逐文件脱敏清单在 `LOCAL_CAMPUS_INVENTORY.csv`，统一权利复核清单在 `CAMPUS_RIGHTS_REVIEW_LIST.csv`。含私人文件名的 full inventory 只留在忽略的批次目录，不进入 Git。

## 与上次冻结批次的差异

`D:\Canvas-DG` 没有变化。`D:\Canvas` 的 CS4394 新增四份真实文件：三份可解析教学资料和一份答案资料。答案资料按现有规则保持 restricted；没有因为它位于教学目录而自动公开。

规划结果：34 门课程、1,923 个源文件；1,482 `INGESTABLE`、186 `DOWNLOAD_ONLY`、255 `BLOCKED`，28 门课程至少有一份可解析候选。这里的 `INGESTABLE` 只表示 loader 能读取，不代表拥有面向全站用户再发布的权利。

## 隔离增量入库

在既有的本地私人复核库 `work/current-change/campus-library.sqlite3` 上，仅对 CS4394 执行增量：

- 第一次：新索引 3 份，新增 117 chunks；3 项 blocked；课程当前共 10 documents、377 chunks。
- 第二次：10 项 `SKIPPED_IDENTICAL`、3 项 `BLOCKED`、新增 0；证明重复执行不重复索引。
- 执行后本地库：schema 46、integrity ok、foreign keys 0；28 courses、834 documents、21,173 chunks、1,732 campus records。
- 私人复核库没有发布到生产，`published_at` 仍为空。

恢复点：

- 前：`work/local-campus-20260927T0325Z/pre-increment-campus-library.sqlite3`，SHA-256 `025F1441F36B990BB1F5C05EA9D8C9CE9051F229A48DB1F9039AA6D6FE442AD9`
- 后：`work/local-campus-20260927T0325Z/post-increment-campus-library.sqlite3`，SHA-256 `C2A70352BB9CF8AD7121CD386E87262ECEBB2725BA1487C1C721F4A859A9D90B`

## 源目录保护复核

执行后源目录仍为：

- `D:\Canvas`：206 项，775,294,768 bytes。
- `D:\Canvas-DG`：1,719 项，8,095,437,975 bytes。

本批没有删除候选；清理回执为 `NO_DELETE_CANDIDATES`。CS3481、GE2324 的既有 CourseJesus ID、树、Teaching Spec、历史、成绩和进度均未改写。

## 权利例外

已有文件只有 owner/platform import intent，没有证明可向 CourseJesus 全部注册用户再发布的许可。根据当前政策，本批准确结果是：

- 私人隔离复核：可做，已对新增 CS4394 内容完成。
- 校园共享 RAG/校园课程发布：0，保持待权利依据。
- 个人、出勤、名单、提交和答案文件：继续 blocked。
- 原文件存在、可下载或已解析不等于已获得公开/共享许可。
