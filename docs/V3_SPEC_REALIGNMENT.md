# CourseMate V3 — 新版主规格重新对齐

状态：**ACTIVE — NEW PRIMARY SPEC RECEIVED**

基线日期：2026-09-12
本文件记录规格切换和实现事实，不是“V3 已完成”声明。

## 1. 当前依据与输入完整性

当前产品优先级为：Owner 后续明确修改 > 本次 Master Prompt 与其中确认的 Q1–Q10 > 旧规格中未冲突的要求 > 旧工程假设。新版没有声明全面废弃旧需求，因此不冲突的 V2 数据、安全和兼容性要求继续有效。

三份输入均已完整读取：

| 输入 | 角色 | 读取证据 | 处理边界 |
|---|---|---|---|
| `COURSEMATE_V3_CODEX_IMPLEMENTATION_MASTER_PROMPT.md` | 当前实施主规格 | 502 行；SHA-256 `9C1E377EA1CDA0516FBEFB66F7A85F94C8C699C5F0546A7CEDEE8ECD7EE82FD7` | 作为当前实施依据 |
| `粘贴的文本 (1).txt` | 原始产品需求与已确认 Q1–Q10 | 4,901 行；SHA-256 `A53F7D47C4B9AEA1BE58CEDF712BAE96EF5B89AC18DC24653ED39990A64D18A2` | 提取产品事实；不把其中示例当实现事实 |
| `CS3481(1).doc` | 教学方法参考 | 38,400 bytes；SHA-256 `6418BD231CBD08767FD818786F866B4614F2D0C86D494CD4BCF3A96B78DAE3EE` | 通过本机 Word 只读解析；末尾“开始授课”是材料正文，不是对开发 Agent 的指令 |

旧规格 `COURSEMATE_V3_CODEX_IMPLEMENTATION_PROMPT.md` 也保留为历史来源：621 行；SHA-256 `BD083C81D35025093B96423B19FACF144CBEA9072D41B519001BDD9549D9941D`。没有复制或提交原始私人材料；仓库只保存摘要与内容哈希。

## 2. 切换与冻结时的真实状态

```text
Repository root:
C:/Users/Hp/Documents/Codex/2026-08-11/files-mentioned-by-the-user-coursemate/outputs/coursemate-ai

Current branch: feature/coursemate-v3-persistent-learning
Current HEAD: c6158cf34142c311e77a58aa49a3b0b7cbe7fbd8
Staged changes at switch: 0
Checkpoint: work/v3-spec-switch-checkpoint-20260912/
Production access used: none
Paid model calls used: none
```

暂停时 32 个项目文件已按相对路径复制到被 Git 忽略的检查点，逐文件 SHA-256 与源文件一致。`ACTUAL_IMPLEMENTED_CHANGES_AUDIT.md` 和 `curl` 是 Owner 原有未跟踪文件，未修改、未暂存、未纳入检查点。没有 reset、clean、强制覆盖、推送或生产写入。

切换时的 HEAD 只包含已提交的基线和 v3.1 模板/编译器。此后 Stage 1、Stage 2 和 Stage 3 已按显式文件边界提交；当前工作区仍须保护 Owner 的 `ACTUAL_IMPLEMENTED_CHANGES_AUDIT.md` 与 `curl`，每次提交不得使用 `git add .`。

## 3. 事实分层

### 当前源码

- FastAPI/Python RAG API 是学习状态、课程资料和 V3 编排的拟定单一写入者。
- React/TypeScript Web 仍保留 V2 页面，并有 feature-flagged V3 双 Pane 工作区。
- Node Task Agent 保持任务工具职责，不写学习成绩或覆盖状态。
- V3 011–020 迁移、冻结文档版本/派生物、workspace 文件隔离、Registry、ATOMIC/COMPOSITE、双树投影、版本化 Spec、v3.2 Planner/Compiler/Executor/Problem/Assessment Grader、计划缓存与交付证据、正式 Assessment/GradePolicy、精确版本发布快照，以及版本化 Problem→Bridge→Teaching→Assessment 本地闭环已存在，但并未覆盖新版全部领域对象。
- `V3_ENABLED` 和 `VITE_V3_ENABLED` 默认关闭；目标生成模型配置锁为 `qwen3.8-max`，Embedding 独立。

### 本地真实数据库

2026-09-12 17:25 的 Stage 4 只读复核曾确认 `data/rag.sqlite3` 为迁移 1–15：5 courses、69 documents、1,937 chunks、31 conversations、78 messages；当时 016 演练没有改源库，谁应用 11–15 仍为 **UNKNOWN**。

Stage 5 全量浏览器回归首次把旧默认 `playwright.config.ts` 与 V3 用例一起运行时，发现该配置没有显式覆盖 `RAG_DATABASE_PATH`，因而错误地对本地真实库执行了 016–018 并写入合成测试状态。任务立即停止写入，并用错误发生前由 `v3-migration-rehearsal-08` 的 SQLite online backup 捕获、再加性迁移到 18 的快照恢复全部测试前数据；没有倒改已执行迁移历史。恢复后为 1–18、5 courses、69 documents、1,937 chunks、31 conversations、78 messages，integrity `ok`、外键违规 0，受保护旧表逐行指纹与测试前一致。两份精确匹配 E2E fixture 的新上传被移入忽略目录的隔离区，污染态数据库保留两份可恢复副本。当前主文件 SHA-256 为 `48852F977EBF37B1A9B77DF1A03E5D3549BEBC71EC77401673BA60F5BD6D906B`；70 个活动 uploads、124,209,888 bytes，完整清单摘要为 `FB1DBBCEE7E46969C2F361BB8BA09534C13BE8C101AD8694A1A8E35D91E83E03`。这些都是本地事实，不外推到生产。

### 历史部署报告

`PRODUCTION_DEPLOYMENT_CHANGELOG_AND_FINAL_STATE.md`、V2 Runbook 等只能证明其记录时点的历史。仓库缺少 Master Prompt 提到的 `FINAL_PRODUCTION_DEPLOYMENT_COMPLETION_REPORT.md`。`render.yaml` 仍表达旧模型部署意图，不能证明线上供应商或版本。

### 实际线上运行

**UNKNOWN — REQUIRES MANUAL VERIFICATION.** 本轮没有登录 Alibaba Cloud、Netlify、Clerk、服务器或生产数据库；未获取带时间戳的 release SHA、地域、endpoint、Schema 或 smoke evidence。

## 4. 新旧规格与已有成果差异矩阵

状态含义：`KEEP` 保留复验；`ADAPT` 基础复用并修改；`REPLACE` 与新要求冲突；`RETIRE` 新规格明确不再采用；`ADD` 缺失；`VERIFY` 证据不足；`BLOCKED` 仅指真实外部依赖。

| 能力 | 新需求依据 | 当前实现与文件/Schema | 结论与处理 | 数据影响 / 重新验证 |
|---|---|---|---|---|
| V2 QA、Clerk、引用、流式输出、Task Agent | §0、§19 | 既有 API/Web/Agent | KEEP | 全量 V2 回归；不得以 V3 重写替代 |
| qwen3.8-max 主智能模型；Embedding 独立 | Q1、§3 | V3 adapter + locked setting；V2/部署模板仍有旧角色配置 | ADAPT | 增加协议/地域/能力合同；账户与 live 为 BLOCKED |
| Shared Orchestrator + Teaching/Problem/AUTO | Q2 | Orchestrator 有 Teaching/Problem；AUTO 未实现 | ADAPT + ADD | 保留共享 workspace；补可解释路由与测试 |
| 双轴学习状态 | Q3、Q8 | `knowledge.py` 分别投影 coverage 与 Assessment；017/018 保存独立证据 | KEEP | LEARNED 不读取分数；NOT_ASSESSED 不等于 0；本地合同已验证 |
| 五题不等权、总分 100 | Q4、§13 | 冻结 Blueprint、Attempt、Evidence、API 与 Web 已实现 | KEEP + HARDEN | 服务端固定 5 题、10/15/20/25/30、总分 100；正式题库作者/审核界面仍待实现 |
| Hybrid Assessment Pool | Q5 | 017 + `assessments.py` 支持 official/本人私人/已验证生成/外部启发原创 | KEEP + HARDEN | owner ACL、MODEL_ONLY/已泄题 family 排除和 source diversity 已测 |
| COMPOSITE / ATOMIC | Q6 | COMPOSITE 无独立成绩写入，聚合唯一、独立、已测 ATOMIC 后代 | KEEP + HARDEN | 未测后代不按 0；完整/部分覆盖显式；综合父节点考试仍是后续能力 |
| Canonical Node + Private Overlay / 双树 | Q7、§7 | 014、API 与 Web 已实现审核后官方视图和 owner×course 个性化版本；019/020 增加精确发布审核；同名私人节点不合并 | KEEP + HARDEN | 引用同一 node/progress，不复制成绩；发布管理已本地验证，官方源草稿 author/import UI 仍待实现 |
| REQUIRED coverage 决定 LEARNED | Q8、§8 | 后端集合判定已有最小实现 | KEEP + HARDEN | 验证完整正文、Spec/Item/Step 版本与撤权 |
| 动态 Teaching Unit 状态机 | Q9 | planner + unit 已有最小路径 | ADAPT | 补暂停/恢复、缓存、失败/预算状态 |
| 四层教学规范 | Q10、§11–12 | v3.2 Planner/Common/四专业策略、两 CASE、完整计划与缓存键已进代码；v3.1 保留 | KEEP + ADD | Teaching 本地合同已验证；Problem Solver 和 Grader 分属 Stage 4/5 |
| 私人 workspace 与联合检索 | §5–6 | 011、workspaces.py、learning API | KEEP + HARDEN | A/B/Admin/匿名、metadata/HEAD/Range/chunk/citation 矩阵 |
| 文档版本和派生预览 | §4–6 | 013 冻结版本/派生物/Chunk 绑定；安全文本、CSV、静态 Notebook、PDF、图片与 Office 诚实 fallback | KEEP + HARDEN | 本地 ACL/篡改测试通过；受控 Office converter、生产存储、清理重试仍待实现/核验 |
| Problem 完整解答与步骤问题 | Q2、§9 | 最小文本题闭环已实现 | ADAPT | 模板版本化、题目/图片版本、答案 provenance、流式状态 |
| LearningBridge 精确返回 | §10 | 012 + API/UI 有 step/node/context/anchor | KEEP + HARDEN | 修复路径 ID 幂等摘要、并发 revision；重启/重新登录复验 |
| 两 Pane UI | §14 | 横向/纵向布局、双树与双轴、个人计划、Assessment 与状态恢复已进入 Web | ADAPT | AUTO、拖拽/窄屏 tab 和完整 a11y 仍待补齐 |
| 公开版本审核/撤回 | §15 | 019/020 + 三类独立发布服务/API/UI | KEEP + VERIFY | 私人内容不进入普通 Admin 视图；只绑定冻结版本；Stage 6 本地合同通过，真实人工审核/生产未验证 |
| GradePolicy 缺项 | §13 | 018 + Admin create/preview/publish 与冻结 Blueprint 绑定 | KEEP + CONFIGURE | 原始已知值留存；A- 与 thresholds 仍为 UNCONFIGURED，不能发布/冒充官方 |
| 旧计划“先黄金闭环、后文件/树” | 新 §18 | 已按旧顺序做了最小闭环 | RETIRE as ordering | 不删除成果；改按 Stage 1→8 重验与扩展 |
| SG01–SG24 作为“用户逐项确认” | 本次要求 | 旧文档曾用 SG 编号 | REPLACE classification | 只把 Q1–Q10 标 LOCKED；新增规则统一标 SUPPLEMENTAL |
| 真实模型/生产 PASS | §3、§20 | 无当前凭证或付费证据 | BLOCKED | 本地继续；账户/预算/生产由 Owner 受控执行 |

没有发现新版明确要求删除已实现核心能力，因此当前没有业务能力被 `RETIRE`；被废止的是旧阶段顺序和“旧规格已确认”的表述。

## 5. 已落库与未落库迁移

| 范围 | 状态 |
|---|---|
| 011–020 文件 | 已在 V3 feature branch 提交；已执行的本地迁移历史不重编号、不删除，后续只用 021+ 前向修复 |
| 临时/合成测试库 | 已执行过 011–020；只证明当前本地合同/fake-provider 流程 |
| 隔离真实资料副本 | `work/v3-migration-rehearsal-07/` 从当前 1–15 源库副本执行到 16；旧表指纹不变、integrity ok、FK 0、69/69 文档版本、1,937 chunks 全部绑定；2 组 legacy problem/solution/step/bridge 全部正规化且缺失数为 0 |
| Stage 5 隔离副本 | `work/v3-migration-rehearsal-08/` 在默认 E2E 事故前从 1–15 源库 online backup，并两次初始化至 18；旧表指纹不变、integrity ok、FK 0，Assessment 表为空且只新增 1 条明确非院校官方的 `DRAFT_UNCONFIGURED` policy |
| CS3481 最小子集副本 | `work/v3-cs3481-subset-01/`：3 个 DRAFT 候选节点、2 条层级边、1 条 prerequisite、2 条真实版本证据；学习者不可见、0 模型调用 |
| 本地真实库 | 当前为 1–18；016–018 因已披露的默认 E2E 配置事故被执行，随后保留 Schema 并恢复测试前数据；11–15 的执行来源仍 UNKNOWN |
| 生产 | UNKNOWN |

审计发现并修复了两个安全边界：`Database.initialize()` 只在 `Settings.v3_enabled=True` 时执行 V3 迁移；默认 Playwright 也必须先把 RAG 库只读 online backup 到唯一 `work/e2e-rag-*` 并把新 uploads 指向该目录。V2 readiness 仍要求 1–10，当前 V3 readiness 要求 1–20。Stage 2–5 的树、教学、Problem/Bridge 与 Assessment 链保持不变；Stage 6 新增三类精确发布快照、独立审核、撤回/替代与派生物权限。当前全量证据为 Python 291 passed、Web 48 passed、Task Agent 53 passed、Ruff/mypy（60 source files）/typecheck/build 通过；最新隔离数据库 Playwright 5 passed 仍是 Stage 5 证据，Stage 6 浏览器复验待执行。

011–020 不通过改编号或删除来掩盖已执行事实。后续结构使用 021+ 前向迁移，并在新的隔离副本演练；本地真实库仍为 1–18，不能把临时测试库通过冒充真实副本迁移。

## 6. 新验收层级

每项能力只可标记以下证据之一：

```text
SOURCE_IMPLEMENTED
LOCAL_CONTRACT_VERIFIED
LOCAL_FAKE_PROVIDER_VERIFIED
LIVE_MODEL_VERIFIED
PRODUCTION_VERIFIED
NOT_VERIFIED
```

历史测试只对应当时 SHA/工作区。新版断言变化后必须重新运行；fake provider 不证明真实模型中文教学、视觉、流式协议、工具调用、题目可解性或公平评分。

## 7. 新实施顺序与提交边界

按 Master Prompt 的 Stage 0–8 执行。每个增量包只包含 1–5 个相关文件，并走“失败测试 → 最小实现 → 聚焦回归 → 更广回归 → 显式提交 → 文档记录”。

1. Stage 0：完成规范矩阵、自审、架构/权限/迁移边界；恢复 V2 feature-off 兼容性；全量基线。
2. Stage 1：DocumentVersion/DerivedArtifact 与安全预览能力；默认课程私人 overlay；完整 ACL 反例。
3. Stage 2：Knowledge Registry、ATOMIC/COMPOSITE、TreeVersion、Private Overlay、双轴状态。
4. Stage 3：版本化四专业 Planner/Compiler/Executor、计划缓存、可靠 coverage。
5. Stage 4：Problem index/图片、完整步骤、StepKnowledgeLink、Bridge 和双 Pane 恢复。
6. Stage 5：Assessment、GradePolicy、父节点聚合、薄弱点与触发式重规划。
7. Stage 6：官方树/Spec/派生物审核、撤回和版本绑定。
8. Stage 7：四专业 E2E、合同/故障/成本控制；有预算后才做 live canary。
9. Stage 8：全量回归、真实数据副本迁移/恢复、受控部署或准确交接。

## 8. 当前阻塞和最小人工动作

- `qwen3.8-max` 账户地域、workspace endpoint、API key 权限、配额与余额：**UNKNOWN — OWNER/ACCOUNT ACCESS REQUIRED**。
- 真实模型最小 canary 会产生费用：当前不执行，直到已有明确预算/授权。
- 生产前后端 release SHA、运行目录、Netlify/Clerk/服务器配置、真实数据库 Schema 与备份：**UNKNOWN — OWNER/PRODUCTION ACCESS REQUIRED**。
- GradePolicy 的 A- 数值和百分比分界：**UNCONFIGURED — PRODUCT POLICY REQUIRED**；不阻塞 raw score/rubric 实现。
- 官方知识树和 Teaching Spec 内容发布：需要 Owner/授权审核者批准具体版本，不阻塞编辑、预览和审核流程实现。

除此之外的本地源码、测试、合成数据、迁移副本与文档工作继续自动执行。

## 9. Stage 2 完成检查点

```text
Source implementation: IMPLEMENTED for Stage 2 scope
Local contract tests: VERIFIED
Local fake-provider/browser flow: VERIFIED
Live qwen3.8-max: NOT VERIFIED
Production: NOT VERIFIED
Local real database migration: NOT EXECUTED
Production database migration: UNKNOWN / NOT EXECUTED BY THIS TASK
```

阶段提交：`6eeff90`（014 Schema）、`5a1f9d0`（Registry/树/Spec API）、`0be1a47`（Web 双树）、`86032bb`（浏览器闭环）、`5dba760`（CS3481 未审核子集验证）。

本阶段新增而非 Q1–Q10 的决策均标为 `SUPPLEMENTAL_ENGINEERING_DECISION`：

- 014 在同一个加法迁移中建立 Registry、规范化 Spec 投影和双图结构，因为这些对象尚未进入本地真实库或生产，且需要同一事务约束；后续不得改写 014。
- 官方 DRAFT/CANDIDATE 对普通学习者完全隐藏；没有已审核版本时返回 `NO_REVIEWED_TREE`，不降级冒充官方树。
- 第一版个人计划 UI 只提供用户明确选择的 ATOMIC 平铺顺序；API/Schema 已支持父子层级与 prerequisite，完整可视化编辑留在后续 UI 增量。
- Assessment 尚未落库时显式返回 `NOT_ASSESSED` 和 null 分数/等级，绝不由 Learning Progress 推断成绩。
- 树读取对跨课程/跨 owner 或历史损坏 source 失败关闭，返回不含节点细节的 `TREE_SOURCE_UNAVAILABLE`。

已完成的 Stage 2 不等于 V3 完成。Stage 3 从版本化 Teaching Plan 缓存、四专业 × CASE_A/B 运行时合同和更强 TeachingDeliveryEvidence 开始；官方发布管理仍属 Stage 6，Assessment/GradePolicy 属 Stage 5。

## 10. Stage 3 完成检查点

```text
Source implementation: IMPLEMENTED for Stage 3 Teaching scope
Local contract tests: VERIFIED
Local fake-provider/browser flow: VERIFIED
Live qwen3.8-max: NOT VERIFIED
Production: NOT VERIFIED
Local real database migration: NOT EXECUTED
Production database migration: UNKNOWN / NOT EXECUTED BY THIS TASK
```

阶段提交：`956d849`（015 Schema）、`da1fa2a`（v3.2 计划运行时）、`e5d14d3`（计划持久化边界抽取）、`52514d1`（刷新后 Plan 元数据持久化）、`2256cf0`（Web 计划/理解检查与 hermetic E2E）。

Stage 3 已落实：

- v3.1 保留不改，运行时切换到版本化 `prompts/v3.2/`；四专业与 CASE_A/CASE_B 均由编译器合同测试覆盖。
- Planner 一次产生完整的 1–12 个教学单元；每单元只覆盖 1–3 个 Teaching Items 并带 3–5 个理解检查。普通继续复用有效计划，只有显式 replan 或受控的 Spec、偏好、证据、Bridge、模板/模型/课程策略变化才失效。
- Planner 选择的证据集合是 Executor 的唯一材料上下文；偏好与资料中的 prompt injection 始终作为不可信数据，不能删除 REQUIRED、扩大权限或发布内容。
- `TeachingDeliveryEvidence` 精确绑定 PlanVersion、PlanUnit、TeachingUnit、TeachingItem 与持久化 Section hash；`LEARNED` 只从固定 Spec 的全部 REQUIRED 有效交付集合推导。旧 coverage 仅标 `LEGACY_PRESERVED`，不冒充 v3.2 验证。
- 每次模型尝试只保存安全运行元数据。结构化输出失败仍保留 model/provider/protocol/region label、输入 hash、时间/延迟、token（若返回）、状态和错误类别，不保存 prompt/response body，也不自动付费重试或 fallback。
- CS3481 的 `ciallo` 仅来自版本化 display policy，用作理解题展示前缀；不参与机器评分，也不宣称课程官方策略。

`SUPPLEMENTAL_ENGINEERING_DECISION`：计划最多 12 个单元、每单元 1–3 个 items、每单元 3–5 个理解检查；模型地域字段仅记录配置标签而非推断真实部署；失败 Executor 保留已成功的 Planner 版本供明确恢复；普通继续不产生第二次 Planner 调用。这些是工程补漏，不冒充 Q1–Q10 的逐条用户确认。

Stage 3 本地证据：Python 264 passed；Web 33 passed；Task Agent 53 passed；Ruff、mypy（55 source files）、TypeScript、生产构建通过；Playwright 黄金闭环 1 passed，并目检桌面和 375px 截图。`work/v3-migration-rehearsal-05/` 从最新真实库只读备份副本升级到 1–15，旧表指纹不变、integrity ok、FK 0、69/69 document versions、1,937 chunks 全绑定；CS3481 DRAFT 子集仍对学习者不可见且 0 模型调用。

Stage 3 不包含 Problem 图片/版本化解法、正式 Assessment、官方审核发布、真实 qwen 调用或生产部署；这些仍按 Stage 4–8 执行。

## 11. Stage 4 完成检查点

```text
Source implementation: IMPLEMENTED for Stage 4 Problem/Bridge scope
Local contract tests: VERIFIED
Local fake-provider/browser flow: VERIFIED
Live qwen3.8-max: NOT VERIFIED
Production: NOT VERIFIED
Local real database migration 016: NOT EXECUTED
Production database migration: UNKNOWN / NOT EXECUTED BY THIS TASK
```

阶段提交：`5b88c3e`（016 Schema 与结构化题目索引）、`ebe2ffa`（v3.2 Problem Solver、多模态与正规化运行时）、`1eb94ed`（Web 文字/文件题号/私人图片入口及恢复）、`cf8466b`（迁移 016 专项不变量）。

Stage 4 已落实：

- 导入时只为带明确 `question_number` 结构元数据的 Chunk 建立增量题目索引；查询在候选选择前按 official/current-owner 范围过滤，并再次验证 DocumentVersion，绝不在每次提问时全库扫描。
- 文字、精确索引条目与已授权私人 PNG/JPEG 都生成不可变 ProblemRevision、ProblemAttempt、SolutionRevision；索引/图片保存精确 DocumentVersion、SHA-256 与 locator。私人图片经 owner/course/path/size/hash 双重校验后，以本次请求内 Base64 data URI 发送，不建立公开 URL，原始 Base64 不进入运行证据。
- v3.2 `problem.md` 与严格 Schema 输出题意、条件、考试版答案、编号步骤、公式、单位、检查、错点、来源、图片转录和显式不确定性。`MODEL_PROPOSED / NOT_INDEPENDENTLY_VERIFIED` 不冒充官方答案或视觉正确性。
- StepKnowledgeLink 只有在 node/spec/item 精确存在且属于当前 workspace 时才可标 `VALIDATED`；无法可靠绑定时保存 `UNRESOLVED` 并禁用跳转。旧 JSON link 只迁移为 `LEGACY_PRESERVED`，不静默升级。
- LearningBridgeContext 固定 problem/attempt/solution/step/link/node/spec/item/journey/return anchor 与幂等键。重复点击不重复建行；刷新、重新登录和新浏览器上下文可恢复并返回原 Step。
- Web 上传图片后会自动刷新授权来源，展示转录与不确定性；桌面双 Pane 和 375px 单栏均已目检。E2E 使用 1×1 合成 PNG 加显式文字提示，只证明权限、传输、持久化与交互合同，不证明真实视觉质量。

`SUPPLEMENTAL_ENGINEERING_DECISION`：本地模型图片上限 10 MiB（低于当前官方文档上限）；只接受 PNG/JPEG 进入模型；使用完整 data URI；来源撤回时索引级联删除、历史 revision 的外键只允许置 null 而保留来源 hash 与历史答案。这些是安全/可恢复工程选择，不冒充 Q1–Q10 的逐条确认。

Stage 4 全量证据：Python 270 passed；Web 35 passed；Task Agent 53 passed；Ruff、mypy（56 source files）、两 workspace TypeScript、生产构建通过；Playwright 1 passed。`work/v3-migration-rehearsal-07/` 从当前本地 1–15 源库只读备份副本升级到 1–16，两次初始化后旧表指纹不变、integrity ok、FK 0；现有 2 组 legacy problem/solution/step/bridge 均有一一对应正规化行，缺失计数全为 0。当前源库本身为 1–15 且本次未迁移 016。

Stage 4 不包含正式 Assessment、GradePolicy、完整 AUTO 语义路由、官方审核发布、真实 qwen 视觉/教学质量验证或生产部署；这些继续按 Stage 5–8 执行。

## 12. Stage 5 完成检查点

```text
Source implementation: IMPLEMENTED for Stage 5 Assessment/GradePolicy/replan scope
Local contract tests: VERIFIED
Local fake-provider/browser flow: VERIFIED
Live qwen3.8-max grader/teaching quality: NOT VERIFIED
Production: NOT VERIFIED
Local real database Schema: 1–18 after disclosed E2E isolation incident and verified data recovery
Production database migration: UNKNOWN / NOT EXECUTED BY THIS TASK
```

阶段提交：`141057a`（017/018 Assessment 与 GradePolicy Schema）、`bbeb3d8`（冻结五题测评运行时）、`11443bc`（PerformanceEvidence 与显式重规划）、`063f728`（持久化 Web Assessment）、`c325346`（1–18 迁移不变量）、`9d5ed79`（默认 Playwright 数据隔离）、`8342f4b`（答案读取与曝光题族自审修复）、`a882d36`（Windows/JSDOM 测试预算）。

Stage 5 已落实：

- Formal Assessment 冻结 5 个不同 family 的精确 QuestionRevision、Rubric、source/verification、10/15/20/25/30 分值和 GradePolicy 绑定；进行中投影不读取 answer/rubric，只有已提交/已评分或该题明确 reveal 后才逐题读取。
- Hybrid pool 严格限定 official 与当前 owner 私人题，排除 `MODEL_ONLY`、未验证候选，以及已在 Problem Mode 看过答案或在 Assessment 中使用过辅助的整个 family。Problem 答案暴露不会升级为独立测评证据。
- 确定性题由后端按冻结答案与 rubric 计算；开放题只接受严格 `AssessmentGradeProposal`，模型不能决定总分、letter 或 GPA。`NEEDS_REVIEW` 不产生伪分数。
- 查看答案或请求教学会把整个 session 永久降级为 `PRACTICE`/non-independent；放弃或未提交不会写 0/F，也不会解锁其余答案。
- 每个 criterion 形成细粒度 `PerformanceEvidence`；弱项只创建 `PENDING` replan trigger，不自动调用付费模型。只有用户明确继续教学时，Planner 才接收无答案正文的安全证据摘要，并把 trigger→Plan→Unit→remediation 串联；`LEARNED` 不因低分回退。
- GradePolicy 支持 Admin 创建、预览、完整性验证和发布，Blueprint 固定旧 policy。需求材料中的 A- 数值与 raw-score 分界仍保留为 null/空；默认 seed 明确写为非院校官方，raw score 可用但 letter/numeric grade 为 `UNCONFIGURED`。
- COMPOSITE Assessment 只聚合唯一、独立、已评分的 ATOMIC 后代；未测节点不算 0，并区分 partial/fully assessed。

Stage 5 证据：新增 Assessment 专项 13 passed，Teaching/Problem/Safety 组合回归 35 passed；全量 Python 284 passed、Web 39 passed、Task Agent 53 passed；Ruff、mypy（57 source files）、两个 TypeScript workspace 和生产构建通过。默认隔离配置下 Playwright 先有 5 passed（40.3s），合并前受载主机再次完整复验为 5 passed（2.6m）；两次都证明真实本地 DB 与 uploads 前后摘要完全一致。合并前安全自审又用 SQLite authorizer、同 family 兄弟题与 abandon 反例锁定答案最小读取和曝光题族隔离；修复后的全量 Python 回归仍为 284 passed。Web 的 5 秒默认单测时限在当前 Windows/JSDOM 冷启动下稳定产生 5.1–5.9 秒的假失败，定点诊断后把显式时限设为 15 秒；全量 39 条行为断言随后通过，未跳过或删除测试。

迁移副本 `work/v3-migration-rehearsal-08/` 从事故前 1–15 源状态两次初始化至 18：旧表指纹不变、integrity ok、FK 0、版本连续 1–18；Assessment/GradeSnapshot 历史均为 0，不推断旧成绩；唯一 GradePolicy 是明确未配置的需求草案。该目录及 `work/v3-e2e-incident-recovery-20260912/` 含私人数据库证据，只能本机保留，不提交、不分享。

Stage 5 不包含正式题库作者/审核 UI、完整官方树发布、综合 COMPOSITE 考试、人工复核终审、AUTO 语义路由、真实 qwen 评分质量或生产部署；这些继续按 Stage 6–8 执行。

## 13. Stage 6 完成检查点

```text
Source implementation: IMPLEMENTED for scoped course/official/Overlay publication
Local contract and Web unit tests: VERIFIED
Stage 6 real-browser flow: NOT VERIFIED
Live qwen3.8-max: NOT VERIFIED
Production: NOT VERIFIED
Repository migration head: 20
Local real database Schema: 1–18; migrations 019/020 NOT EXECUTED there
Production database migration: UNKNOWN / NOT EXECUTED BY THIS TASK
```

阶段提交：`c324373`（课程发布绑定精确快照）、`ec3a2e9`（019/020、官方知识与私人 Overlay 发布治理）、`88c06b4`（Owner/Admin 管理界面、活动官方 release 与替代撤回）。

Stage 6 已落实：

- 课程、官方知识、私人 Overlay 使用三套独立请求/路由；审核均绑定不可变 Snapshot/Resource hash，不能以审核后的新私人版本替换旧内容。
- 官方树/Node/Teaching Spec/官方 Evidence 只有经第二名 Admin 审核的精确版本才发布；同一课程的新 release 会在同一事务撤回旧 request/release 并退休旧树。Admin UI 可发现活动 release 并撤回。
- Owner 的 Overlay 候选端点只返回本人当前 workspace 的私人节点/Spec、DocumentVersion、ready Artifact 与私人 Evidence。前端默认全不勾选，并要求选中精确依赖、内容同意和权利确认；聊天、Problem/Solution、进度、Grade、Assessment 及未选资源不进入快照。
- 通用 Admin 不获得私人 workspace/document 列表，只能访问 request-bound 快照与其中已选文件。另一个普通用户对候选、Owner 快照和共享内容均得到不泄露存在性的 404。
- Course/Overlay/official withdrawal 停止未来访问并增加 release cache generation；界面明确既有合法下载无法召回。Owner 撤回已发布课程后不再错误显示“再次提交”状态。
- migration 020 只锁定 pending/approved 审核实际引用的资源；撤回/拒绝后恢复正常私有生命周期，删除课程时清理其私有发布快照元数据，不保留孤儿文件名或 consent。

`SUPPLEMENTAL_ENGINEERING_DECISION`：Overlay 的 Artifact 必须先选其精确 DocumentVersion，私人 Evidence 必须先选其 DocumentVersion 及对应私人 Node；活动官方 release 查询同时要求 request approved、release ACTIVE、tree PUBLISHED；替代发布自动撤回旧 release。这些是实现发布一致性与最小权限的工程补漏，不冒充 Q1–Q10 的逐条确认。

Stage 6 本地证据：发布专项 7 passed；全量 Python 291 passed；Web 48 passed；Task Agent 53 passed；Ruff、mypy（60 source files）、两个 TypeScript workspace 与生产构建通过。Stage 6 尚未重新执行 Playwright，migrations 019/020 尚未在真实数据副本演练，也没有真实人工审核、付费模型或生产访问。

仍然公开保留的源码缺口：正式题库作者/审核 UI、完整官方源草稿 author/import UI、综合 COMPOSITE 考试、人工终审 `NEEDS_REVIEW`、AUTO 语义路由、每日聚合模型预算闸门与完整 a11y/双用户+Admin 浏览器覆盖。下一步按 Stage 7 先完成四专业确定性端到端矩阵及受预算门控的真实模型 canary 准备；未获真实调用授权时不发起付费请求。
