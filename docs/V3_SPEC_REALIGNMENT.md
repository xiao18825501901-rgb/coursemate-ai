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

当前 HEAD 只包含已提交的基线和 v3.1 模板/编译器；大量 V3 闭环代码仍在工作区，不能用 HEAD 单独代表当前实现。每次提交必须显式选择项目文件，不得 `git add .`。

## 3. 事实分层

### 当前源码

- FastAPI/Python RAG API 是学习状态、课程资料和 V3 编排的拟定单一写入者。
- React/TypeScript Web 仍保留 V2 页面，并有 feature-flagged V3 双 Pane 工作区。
- Node Task Agent 保持任务工具职责，不写学习成绩或覆盖状态。
- V3 011–013 迁移、冻结文档版本/派生物、workspace 文件隔离、ATOMIC 节点、v3.1 Planner/Executor 契约、Problem→Bridge→Teaching→Return 本地闭环已存在，但并未覆盖新版全部领域对象。
- `V3_ENABLED` 和 `VITE_V3_ENABLED` 默认关闭；目标生成模型配置锁为 `qwen3.8-max`，Embedding 独立。

### 本地真实数据库

只读核验 `data/rag.sqlite3`：迁移 1–10，`integrity_check=ok`；3 courses、67 documents、1,937 chunks、31 conversations、78 messages。没有把这些数量外推到生产。当前真实库没有执行 011–013。

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
| 双轴学习状态 | Q3、Q8 | coverage 推导 Learning Progress；Assessment 缺失 | ADAPT + ADD | 不从旧聊天推导 LEARNED；测评独立迁移 |
| 五题不等权、总分 100 | Q4、§13 | 无 Assessment Schema/API/UI | ADD | 新增版本化 Blueprint/Attempt/Evidence；不写旧成绩 |
| Hybrid Assessment Pool | Q5 | 无正式题池 | ADD | source/scope/version/泄题边界必测 |
| COMPOSITE / ATOMIC | Q6 | 模型允许两类，当前只创建私人 ATOMIC | ADAPT | 新增 registry、关系、聚合；禁止矛盾父状态 |
| Canonical Node + Private Overlay / 双树 | Q7、§7 | 私人节点 + workspace；没有稳定发布树版本 | ADAPT + ADD | 引用同一 node/progress，不复制成绩 |
| REQUIRED coverage 决定 LEARNED | Q8、§8 | 后端集合判定已有最小实现 | KEEP + HARDEN | 验证完整正文、Spec/Item/Step 版本与撤权 |
| 动态 Teaching Unit 状态机 | Q9 | planner + unit 已有最小路径 | ADAPT | 补暂停/恢复、缓存、失败/预算状态 |
| 四层教学规范 | Q10、§11–12 | v3.1 Planner/Common/四专业策略已进代码 | ADAPT | 新建兼容版本；补 Problem Solver、Grader、缓存键 |
| 私人 workspace 与联合检索 | §5–6 | 011、workspaces.py、learning API | KEEP + HARDEN | A/B/Admin/匿名、metadata/HEAD/Range/chunk/citation 矩阵 |
| 文档版本和派生预览 | §4–6 | 013 冻结版本/派生物/Chunk 绑定；安全文本、CSV、静态 Notebook、PDF、图片与 Office 诚实 fallback | KEEP + HARDEN | 本地 ACL/篡改测试通过；受控 Office converter、生产存储、清理重试仍待实现/核验 |
| Problem 完整解答与步骤问题 | Q2、§9 | 最小文本题闭环已实现 | ADAPT | 模板版本化、题目/图片版本、答案 provenance、流式状态 |
| LearningBridge 精确返回 | §10 | 012 + API/UI 有 step/node/context/anchor | KEEP + HARDEN | 修复路径 ID 幂等摘要、并发 revision；重启/重新登录复验 |
| 两 Pane UI | §14 | 当前横向/纵向布局和状态恢复 | ADAPT | 补树、Assessment、AUTO、拖拽/窄屏 tab、a11y |
| 公开版本审核/撤回 | §15 | V2 course publication；无树/Spec/派生物版本绑定 | ADD | 私人内容不进入普通 Admin 视图；发布只绑定冻结版本 |
| GradePolicy 缺项 | §13 | 无 V3 policy | ADD | 原始已知值留存；A- 与 thresholds 为 UNCONFIGURED |
| 旧计划“先黄金闭环、后文件/树” | 新 §18 | 已按旧顺序做了最小闭环 | RETIRE as ordering | 不删除成果；改按 Stage 1→8 重验与扩展 |
| SG01–SG24 作为“用户逐项确认” | 本次要求 | 旧文档曾用 SG 编号 | REPLACE classification | 只把 Q1–Q10 标 LOCKED；新增规则统一标 SUPPLEMENTAL |
| 真实模型/生产 PASS | §3、§20 | 无当前凭证或付费证据 | BLOCKED | 本地继续；账户/预算/生产由 Owner 受控执行 |

没有发现新版明确要求删除已实现核心能力，因此当前没有业务能力被 `RETIRE`；被废止的是旧阶段顺序和“旧规格已确认”的表述。

## 5. 已落库与未落库迁移

| 范围 | 状态 |
|---|---|
| 011/012/013 文件 | 工作区已编写，尚未提交；013 已视为迁移历史冻结 |
| 临时/合成测试库 | 已执行过 011–013；只证明当前本地契约 |
| 隔离真实资料副本 | `work/v3-migration-rehearsal-03/` 执行到 13；旧表摘要不变、integrity ok、FK 0、67/67 文档版本、1,937 chunks 全部绑定 |
| 本地真实库 | 仍为 1–10；未执行 V3 |
| 生产 | UNKNOWN |

审计发现并修复了一个安全边界：此前 `Database.initialize()` 无条件执行 011/012。现在只有 `Settings.v3_enabled=True` 才执行 V3 迁移，V2 readiness 要求 1–10，V3 readiness 要求 1–13；V2 课程/发布查询也不会在 flag 关闭时引用 V3 表。失败测试先复现，当前全量证据为 Python 241 passed、Web 30 passed、Task Agent 53 passed、Ruff/mypy/typecheck/build 通过，以及隔离合成数据库 Playwright 1 passed。

011–013 不再通过改编号或删除来掩盖曾在合成/副本数据库执行的事实。后续结构使用 014+ 前向迁移，并在新的隔离副本演练。

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
