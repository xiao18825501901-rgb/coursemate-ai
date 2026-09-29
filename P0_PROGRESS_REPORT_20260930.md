# CourseJesus P0 进度报告（截至 2026-09-30，目标第 11 轮停止）

本报告是**进度汇报**，不是验收通过声明。所有数字均来自本轮可复现的测量；
未能完成的部分与仍未建立的证据逐项列出，不做美化。

---

## 0. 一句话结论

混合严格审核链（`hybrid-strict-v1`）**已完整实现并通过测试**，OpenJev 的
0.50 已被定位为可修复的输入契约缺陷加评估设计假象，双 DeepSeek 审核**已真实
联通**；但**四项质量要求中的歧义一项无法由该审核配置判定**，因此
**没有任何新题被发布，目标第 4/5/6 项未达成**。同时如实记录一次**生产库被意外
执行迁移**的事故（纯加法，已完整核实无数据损失）。

---

## 1. 工作树与版本（保护现状）

```text
REPO     D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY
         \work\auto-knowledge-map-20260927\candidate
分支     feature/learning-loop-20260928
基线     51e2f3f87368e1b36db1b6329e7da4b0dc52fbe7  （= 交接包里的 DOC）
应用基线 916b76ce0534e4ce50a589521b0b618850df6956  （51e2f3f 的父提交）
本轮提交 20 个，自 8b84f94 至 2bd9e82
工作树   干净；仅剩本轮之前就存在的未跟踪目录（artifacts/、apps/web/public/downloads/）
```

未做任何 reset / stash / 强推 / 清理他人改动。

---

## 2. 生产实际状态（只读核实）

| 项 | 值 |
|---|---|
| 应用 release 符号链接 | `/srv/coursemate/releases/916b76c`（**未切换**） |
| 服务 | `coursemate-rag`、`coursemate-agent`、`coursejesus-openjev` 全部 active |
| Schema | **65**（原为 64，见 §9 事故） |
| `integrity_check` / 外键违规 | `ok` / **0** |
| JEV 回执 | 117 条（全部 `model_version=jev-latest`，退役 TypeSafe 通道，未改写） |
| 题目修订 / provenance | 58 / 58（49 READY、9 NEEDS_REVIEW，**未变**） |
| hybrid 回执 / 人工卡 | **0 / 0**（生产从未写入） |
| 测评配置 / 阻塞准备 | 11 / **7**（两个 SQL 私课配置仍 0/5） |
| 磁盘 `/` | 40 G，已用 34 G，**剩 3.8 GiB（90%）** |
| OpenJev | active，RSS ≈1.45 GB，回环 `127.0.0.1:28765`，`/ready` ready |

**结论：生产对外行为与接手时一致**，没有任何学生数据、成绩、曝光、答卷被改动。

---

## 3. 交付物清单

### 3.1 七份要求文档（仓库根目录）

| 文件 | 大小 |
|---|---|
| `HYBRID_REVIEW_ADR_AND_SCOPE.md` | 6.9 KB |
| `OPENJEV_50PCT_ROOT_CAUSE_AND_LOCAL_SCOPE.md` | 9.9 KB |
| `HYBRID_QUALIFICATION_AND_REGRESSION.md` | 43.6 KB（最完整，含 9 次验收全部数据） |
| `HYBRID_RECEIPT_AND_RECOVERY_CONTRACT.md` | 10.1 KB |
| `HYBRID_AUTHENTICATED_LIVE_ACCEPTANCE.md` | 6.5 KB |
| `HYBRID_PRODUCTION_RELEASE_AND_ROLLBACK.md` | 10.7 KB（含事故章节 §0） |
| `HYBRID_RECOVERY_STATE.md` | 11.0 KB（状态标签表） |

### 3.2 新增源码（`services/rag-api/app/learning/`）

| 文件 | 作用 |
|---|---|
| `hybrid_review.py` (24.9 KB) | 政策常量、case 映射、判定契约、引用核验、合并规则、方法标识 |
| `hybrid_quality.py` (31.3 KB) | 编排、回执落库、资格复核、人工卡合并 |
| `deepseek_reviewer.py` | 三个角色（A/B/规格）的隔离调用与运行记录 |
| `hybrid_qualification.py` (19.2 KB) | 留出集指标、release 级误放行/误拒、精确二项上界、门槛 |
| `hybrid_evaluation_set.py` (15.7 KB) | 正例控制组 + 记录式缺陷注入 |
| `sql_oracle.py` (15.3 KB) | 隔离有界 SQL oracle |
| `human_review_card.py` (11.0 KB) | 只覆盖歧义 case 的人工审核卡 |
| `candidate_recovery.py` (14.7 KB) | 已出题候选的"只补审核"重建与哈希核验 |
| `openjev_observer.py` (8.5 KB) | 仅建议性本地观察 |
| `migrations/065_hybrid_quality_review.sql` | 5 张加法表 + append-only 触发器 |

### 3.3 新增测试（`services/rag-api/tests/`）

`test_hybrid_review_policy.py`、`test_hybrid_publication.py`、
`test_hybrid_qualification.py`、`test_sql_oracle.py`、
`test_human_review_card.py`、`test_candidate_recovery.py`
—— 共 6 个模块，本轮最新一次定向回归 **142 项全绿**。

### 3.4 新增运维脚本（`services/rag-api/scripts/`）

`run_hybrid_qualification.py`、`rehearse_hybrid_migration.py`、
`re_evaluate_qualification.py`、`review_existing_candidates.py`。
另在 `work/hybrid-p0-20260929/` 保存全部生产只读探针与诊断脚本。

---

## 4. 目标第 1 项：OpenJev 0.50 诊断 —— **达成**

### 4.1 数据重算（240 条，只读、无模型调用）

| 事实 | 值 |
|---|---|
| gold 来源 | `DETERMINISTIC_ORACLE` × 240，`human_gold=false` × 240 |
| 截断 / HTTP 错误 | 无（全 200，`truncated=false`） |
| input hash 唯一性 | 240 个互不相同（无缓存串味） |
| 平均 top-1 概率 | **0.3727**（中位 0.3326） |
| 预测分布 | ambiguity 56/60 `UNDER_SPECIFIED`；agreement **60/60 `AGREE`**；mcq **60/60 `WEAK`**；rule **60/60 `UNSUPPORTED`** |

**结论：这是常量预测器 + 每格恰好 5/5 平衡的 oracle gold，0.50 是按构造必然
出现的结果，不是"对了一半"。** 更准确的读法是"没有信号"，比 50% 更差。

### 4.2 真实输入契约缺陷（本轮新发现）

四个硬门 callsite 传 `candidate_labels=None`，产生
`descriptions: {"CLEAR": "", ...}`。对运行中的服务实弹探测：

| 请求形态 | 结果 |
|---|---|
| 描述为空串（原生产形态） | **HTTP 422 `INVALID_QUESTION`** |
| 完全不传 descriptions | HTTP 200（库退化为裸枚举词） |
| 传 catalog 的真实描述 | HTTP 200 |

即**生产形态根本无法成功**；catalog 本来就声明了完整自然语言描述。已修复：
`definition_labels()` 在 callsite 未提供标签且 catalog 选项 ID 完全匹配时采用
catalog 描述，`bounded_choice_input_hash` 同步，保证决策与持久化输入标识一致。

同时确认**不是**模型替换、tokenizer 不匹配、标签映射反转、缓存过弱或截断丢条件
——这几项逐条探测后排除。

### 4.3 OpenJev 的现定位

降级为**仅建议性局部观察**：正向不能放行、负向不能否决、宕机不阻塞、不删证据、
不截断、不触发重生成；中文/混合/过长/图片按原因跳过（不翻译不压缩）。记录模型
revision、dtype、tokenizer hash、变换版本、编码 token 数、概率分布、耗时。

---

## 5. 目标第 2 项：确定性校验 + 双向隔离强审核 + 真实混合回执 —— **达成**

### 5.1 确定性侧

* **原六门硬门完全保留**（`INPUT_IDENTITY`、`MARKS_MATCH`、`SOURCE_SCOPE`、
  `CONDITIONS_PRESENT`、`QUESTION_SHAPE`、`BLIND_SOLVE_CURRENT`）。
* **新增隔离可执行 SQL oracle**（`sql_oracle.py`）：
  * 隔离：私有内存库 + authorizer 只放行 `SELECT/READ/FUNCTION`；`ATTACH`、
    `PRAGMA` 写、`load_extension`、临时表、所有写动词与多语句全部拒绝。
  * 有界：语句长度、行数、列数、结果单元格、墙钟进度处理器全部封顶；
    超界是 `NOT_SUPPORTED`，**永不是通过**；结果截断即拒绝比较。
  * 作用域写进类型：`PASS` 只表示"在给定 schema 与数据上一致"，**不是等价性证明**，
    并用"同一实例一致、另一实例分叉"的测试钉住这个边界。
  * 比较语义逐项测试：`DISTINCT` 在集合比较下 `PASS`、在包比较下 `FAIL`；
    `LEFT JOIN` 谓词放 `ON` vs 放 `WHERE` 判 `FAIL`；行序仅 `ORDERED` 下有意义；
    缺 join 条件导致行数翻倍被包比较抓住；`NULL` 与 `NULL` 相等但 `NULL` ≠ `0`。
  * **不可被模型投票推翻**：任何 oracle `FAIL` 直接将报告置为 `REJECTED`
    ——与硬门失败同一终态——即便两位审核员全 PASS 且资格覆盖。

### 5.2 强审核侧

* 三个隔离调用：`evidence_audit`(A)、`adversarial_audit`(B)、
  `specification_audit`（专职规格通道，**输出里没有判决字段**）。
* 隔离是**结构性**的：`ReviewerInputs` 没有任何字段可以承载同伴结论或本地标签；
  A/B 的匿名解法顺序由修订哈希冻结并互换，不先看答案再挑顺序；三次调用全部
  完成后才读取任一结果。
* **同模型不同请求只作流程隔离，不称统计独立，不乘概率，不用多票多数决。**
* 服务端引用核验：来源 span id 必须由服务端提供、引文必须逐字命中（仅空白归一）、
  解法步 id 必须存在；任一不可追溯即整条审核不可用。
* 实质性规则：无据 `FAIL` 降为 `UNCERTAIN`；`ambiguity` 的自相矛盾 `PASS`
  降为 `UNCERTAIN`；**永不产生 PASS**。

### 5.3 回执与恢复

新表 `hybrid_review_calls`、`hybrid_local_observations`、`hybrid_quality_receipts`、
`hybrid_qualifications`、`hybrid_human_reviews`；回执与审核调用 **append-only**
（触发器拒绝 UPDATE/DELETE）。发布事务内复核：修订/workspace/course/node/spec/
owner scope、投影判决、两次角色调用、资格有效性与时效。旧 117 条 JEV 回执**身份
与解码完全未改**，未被改标为 hybrid。

---

## 6. 目标第 3 项：四项原义保留、确定性失败不可被投票推翻 —— **达成**

* 四项语义与词表**一字未改**；适用集合由服务端题型合同决定，模型不能省略。
* 报告为 `REJECTED`（确定性硬门失败）时，服务**在启动任何审核员之前返回**，
  一张人工卡也不会被读取——两票肯定无法复活确定性失败。
* 人工卡不能推翻确定性与 oracle 失败（有端到端测试）。

---

## 7. 九次真实验收：完整测量与前沿

### 7.1 逐次结果（全部为真实 DeepSeek 计费调用）

| | run1 | run2 | run3 | run4 | run5 | run6 | run7 | run8 | run9 |
|---|---|---|---|---|---|---|---|---|---|
| prompt 版本 | v1 | v2 | v2 | v2 | v2 | v2 | v3 | v4 | v4+专职 |
| 行数 | 43 | 43 | 27 | 30 | 67 | 64 | 69 | 67 | 66 |
| 负例数 | 29 | 30 | 16 | 18 | 40 | 33 | 41 | 41 | 39 |
| **误放行** | 9 | 3 | 1 | **0** | 3 | 4 | **0** | 4 | 2 |
| 精度 | 0.50 | 0.667 | 0.875 | **1.00** | 0.85 | 0.80 | **1.00** | 0.75 | 0.714 |
| 召回 | 0.818 | 0.50 | 0.70 | 0.70 | 0.708 | 0.727 | 0.375 | **0.632** | 0.238 |
| 缺条件检出 | 8/10 | 8/11 | 无行 | 1/1 | 2/3 | **0/3** | **5/5** | 2/5 | 4/5 |
| 判定 | DRAFT | DRAFT | DRAFT | 记录通过 | DRAFT | DRAFT | DRAFT | DRAFT | DRAFT |

### 7.2 三处**测量缺陷**（不是审核员缺陷，已修）

1. **run1→2**：`DISAGREEING_SOLUTION` 只改一句总结、步骤仍写原答案 →
   审核员判 AGREE **是对的**。改为推导出具体相反结果并重写末步后 5/12 → **11/11**。
   旧数字**已撤回**。
2. **指标归属**：负例行被计入它报告的每一个 case → per-case 误放行被抬高。
   现只按 `target_case` 归属。
3. **run2→3**：`MISSING_CONDITION` 靠删尾句，而删铺垫句不构成"缺条件"。
   现只在真正移除答案依赖项时才生效，否则**不生成该行**。

### 7.3 两个关键的**诚实发现**

* **run4 vs run5（小样本假象）**：同一流程同一 prompt，18 个负例时记录通过，
  40 个负例时测出 3 个误放行。**干净的 18 个负例不是干净流程的证据。**
  据此把门槛提高到 8 负例/case + **16 个独立负例族**全局，并加测试固定。
* **歧义门的精度/召回前沿**：
  ```
  strict   (未给出即阻断)              检出 5/5   召回 0.375
  moderate (改变答案才阻断, A/B)        检出 2/5   召回 0.632
  dedicated(改变答案才阻断, 专职通道)    检出 4/5   召回 0.238
  ```
  **前沿上不存在合格点。** 五次规则迭代、三种设计都没能落进中间。原因是审核员
  在合格题上**系统性高报"缺失会导致不同答案"**——这是模型在该任务上的校准属性，
  不是 prompt 缺陷。

---

## 8. 目标第 4 项：业务恢复 —— **未达成**（但障碍已收敛到一步）

### 8.1 只补审核的恢复路径

`candidate_recovery.py` 从存储 provenance 重建已出题候选，**逐项校验哈希**：
blueprint 对 `blueprint_hash`、重建证据包对 `evidence_pack_hash`、候选修订对
`question_revision_hash`、盲解回执对 `blind_input_hash`。**不符即拒绝，不做修复。**

**九个真实 `NEEDS_REVIEW` 候选：全部重建成功，六门硬门全 PASS，9 张审核卡
在零 provider 调用下生成完毕。**

### 8.2 一处被查清的"疑似损坏"

首轮有 1 条被拒（`CANDIDATE_HASH_MISMATCH`）。彻查全部 58 条 provenance 后：

* **19 条无法复现 blueprint 哈希，全部是 2026-09-25 写入的**；09-27 之后的 39 条全部可以。
* 这 19 条**每一个字段的值都相等**；差异只有一处：`marks` 旧行是**整数** `100`，
  新行是**浮点** `100.0`；标识对规范 JSON 取哈希，故 `100` 与 `100.0` 哈希不同。
* 逐字段类型扫描全部 58 行，只报出**一处**漂移：`marks: int → float`。

**这不是数据损坏，没有任何值丢失。** 处理方式不是降低校验，而是增加一条被**命名**
的渲染：只把整数值浮点写成整数，且必须精确复现记录哈希才接受；记录会写明用了
`CANONICAL` 还是 `INTEGRAL_FLOAT_AS_INT`，真正的不匹配两种都过不了。

修这个又暴露**我自己的一个 bug**：重建把**重算**的 blueprint 哈希传给 candidate，
而修订标识当初是对**存储**哈希算的；改用存储值后，**九条全部可恢复**。

### 8.3 九个真实候选的自动审核结果（首次在真实存量题上测量）

| case | 出回执的 7 条中的结果 |
|---|---|
| `question.ambiguity.v1` | **FAIL 7 / 7** |
| `question.answer_agreement.v1` | PASS 4、**FAIL 3** |
| `question.mcq_distractor_quality.v1` | PASS 1、**FAIL 1** |

| 结果 | 数量 |
|---|---|
| 已审核、未接受 | 7 |
| provider 失败（记录、不重试） | 1 |
| **不合格**（重建后确定性硬门失败，审核员不会启动） | 1 |

**三条必须分开的发现：**

1. 每条真实题都没过歧义门——这既与已测出的过度触发一致，也与"题目本身确实依赖
   未写明的约定"一致；**读题之前无法区分**，这正是审核卡的用途，故不作为任何
   一方的证据。
2. **7 条里有 3 条存在实质作者/盲解分歧**——**卡片修不了**（卡片只覆盖歧义），
   这些需要**新修订版本**。
3. 有一条**完全不合格**（`qe_22cfcc08…`，课程 `cs3481`）：重建后确定性硬门失败。
   **此项尚未诊断完成**（我写了诊断脚本但按你要求已停止工作，未运行），
   **原因未知，不做推测。**

### 8.4 仍未恢复的业务

* SQL 私课两个 0/5 配置：**仍 0/5**，7 个 BLOCKED 准备任务未变。
* 校园与私人"做一题"：**无新题可发**。
* 另一课程 N=8：**未达成**。
* 原因：**生产没有任何资格行**，即使七个 case 全绿也不会被接受
  （7 条回执上都带 `HYBRID_QUALIFICATION_MISSING`，这是正确行为）。

---

## 9. 事故：生产库被意外执行迁移（必须单列）

**经过**：`work/hybrid-p0-20260929/remote_recover.sh` source 了生产环境文件
（其中 `RAG_DATABASE_PATH` 指向真实库），随后调用 `Database(...).initialize()`
本意只迁移还原副本——但我只为审核脚本设了副本路径，**没有为迁移调用导出**，
于是迁移 065 跑到了生产库。

**只读复核结果**：

| 检查 | 结果 |
|---|---|
| `integrity_check` / 外键违规 | `ok` / **0** |
| 新增表 | 5 张，**全部为空** |
| 其它新增对象 | 1 索引 + 4 个 append-only 触发器 |
| 既有表行数 | 题目 58、provenance 58、JEV 117、课程 87、文档 850、chunk 22 909、配置 11、准备 11、绑定题 27、会话 7 —— **全部未变** |
| 既有表 DDL | **无任何既有表被加列** |
| provenance 状态 | 49 READY / 9 NEEDS_REVIEW —— **未变** |
| 批改回执 / 提交 | 4 / 4 —— **未变** |
| RAG 服务 | active、**重启 0 次**、回环 `/health` 200 |

**为什么线上不受影响**：065 只含 `CREATE ... IF NOT EXISTS` 与一行
`INSERT OR IGNORE`；部署中的 `916b76c` 就绪判定只筛 `version <= 64`（仍恰好
1..64），且从不读取新表。代码回退仍有效，五张新表为空无需保留。

**我欠的**：发布计划要求 schema 变更前有已验证的一致备份 + 隔离恢复 + 分阶段切换，
**这次都没有**。"纯加法"让它可控而非有害，但**过程违规是真的**，已写入
`HYBRID_PRODUCTION_RELEASE_AND_ROLLBACK.md` §0。

**已加防呆**：CLI 拒绝"`RAG_DATABASE_PATH` 与 `--database` 指向不同文件"。
（第一版守卫定义错了——它分不清"环境指向真实库"与"我自己把环境指向了副本"，
第一次运行即误报；已改为按真正的失败模式判断。）

---

## 10. 目标第 5/6 项：浏览器验收与发布 —— **未达成 / 未切换**

* **真实浏览器验收未执行**。原因不是 Clerk 403、不是浏览器工具、不是缺凭据，
  而是**没有任何可发布的新题**。Clerk 管理 API 403 本轮**刻意未再探测**。
  未伪造 JWT、未用 `AUTH_TEST_USER_ID`、未冒用真实学生。
* **未做正式切换**：`/srv/coursemate/current` 仍为 `916b76c`。原计划在资格建立后
  按"备份 → 排练 → 阶段发布 → 后端先于前端"执行；迁移 065 已在真实库副本上完成
  正式演练（146→150 表、integrity ok、0 外键违规、历史行摘要未变、重放幂等、
  旧版就绪判定复现为真）。
* 唯一已在生产发生的 schema 变化就是 §9 那次事故。

---

## 11. 目标第 7 项：诚实报告 —— **达成**

* `QUALITY_NONINFERIORITY_EVIDENCE = UNKNOWN`：没有同样本配对 gold；
  旧 117 条回执是已退役 TypeSafe 通道的 `choice` 字符串，无分布、无留出标签。
  **不声称"标准未降低"等于"已证明错误率未提高"。**
* **13 棵 Map50 保持暂停**，未启动任何 Map50 单元。
* 学生收益：**未测量**，不声称。

---

## 12. 成本计量（真实计费，不宣称任何环节免费）

| 项 | 数量 |
|---|---|
| 资格验收 9 次 | 约 132 次出题 + 132 次盲解 + 约 680 次审核调用 |
| 真实候选审核 | 9 × 3 = 27 次审核调用（7 条成回执、1 条 provider 失败、1 条未进入审核） |
| 语料诊断 | 23 次出题 |
| 双角色实弹验证 | 2 次（5 171 输入 / 736 输出 token） |

单行审核约 5 200 输入 / 740 输出 token。**上限不是应用美元上限**，
OpenJev 本地推理无逐次供应商费用，但双审核**有真实费用**。

---

## 13. 仍未完成 / 未建立（逐项）

1. **歧义门的资格**——前沿无合格点，自动通道做不到安全且可用。
2. **人工卡本身的质量未测**——管线侧已验证（无卡拒绝、有卡接受、卡不能扩权），
   但**还没有人在生产里审过一张真卡**。
3. **`qe_22cfcc08…` 的确定性硬门失败未诊断**（脚本已备，未运行）。
4. **provider 失败率未定位**——run6 9/64、run8 7/67、run9 6/66、
   真实候选 1/9；按契约记录不重试，只损覆盖，但需区分 schema 拒收 /
   输出上限 / 上游瞬时错误。
5. **严格逐字引文检查造成真实误拒**（每次运行 3–10 行）。行为正确但代价存在。
6. **SQL 五题、N8、校园/私人做一题、真实浏览器验收、正式发布全部未完成。**
7. **run5 原始 artifact 因我清理脚本命名冲突被覆盖**（测量值保留在文档中，
   原始文件已不在；脚本已改为按 run 编号命名）。

---

## 14. 需要你决定的三件事

1. **审卡**：9 张卡在服务器 root-only 目录
   `/srv/coursemate/validation/hybrid-strict-v1/cards/`（`0700`/`0600`）。
   其中 **4 条只卡歧义门**（可能一卡可发），**3 条另有真实分歧**（须重出题）。
   我可先给你 9 张的摘要（不含题干原文），你指定后我再贴全文供审。
2. **事故处置**：目前纯加法、服务正常，我倾向**保留 schema 65 继续**；
   若要求回到事故前状态，需走备份恢复流程而非代码回退——请明示。
3. **是否接受已测风险**：例如接受 run8 的 4/41（约 9.8%）误放行率并在政策中写明。
   这是**产品决策**，我不擅自做，本轮也没有做。

---

## 15. 状态标签表（与 `HYBRID_RECOVERY_STATE.md` 一致）

| 标签 | 状态 |
|---|---|
| `LOCAL_RUNTIME_REUSED` | 达成 |
| `OPENJEV_DIAGNOSTICS_COMPLETE` | 达成 |
| `OPENJEV_ADVISORY_SCOPE` | 达成 |
| `DETERMINISTIC_CHECKS` | 达成（六门硬门 + 不与模型投票挂钩的执行门） |
| `DEEPSEEK_REVIEW_A_B` | 达成（实弹验证） |
| `HYBRID_SCOPED_QUALIFICATION` | **未建立** |
| `CAMPUS_EXERCISE_RESTORED` | **未达成** |
| `PRIVATE_EXERCISE_RESTORED` | **未达成** |
| `SQL_COLD_POOL_GRADED` | **未达成** |
| `N8_ASSESSMENT_GRADED` | **未达成** |
| `NORMAL_TEACHING_PRESERVED` | 保持（源码未动，回归全绿） |
| `AUTHENTICATED_BROWSER_ACCEPTANCE` | **未达成** |
| `PRODUCTION_DEPLOYED` | 未切换（`916b76c` 仍在服务） |
| `QUALITY_NONINFERIORITY_EVIDENCE` | **UNKNOWN** |
| `MAP50_13_PAUSED` | 暂停未变 |
