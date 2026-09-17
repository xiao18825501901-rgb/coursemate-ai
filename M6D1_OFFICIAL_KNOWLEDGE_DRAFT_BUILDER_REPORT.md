# M6D1 OFFICIAL KNOWLEDGE DRAFT BUILDER REPORT

**Date**: 2026-09-16 (local)
**Branch**: `release/openapi-fix`
**Base release**: `cdf52b2cba1700805d9982950c202e9cb927825a` (production release, Schema 22 → local code now 23)
**Stage**: M6D1 — 真实官方课程资料 → 可审核 OFFICIAL DRAFT 的生产级管理员路径

```text
M6D1_CODE_GATE=PASS
LIVE_MODEL_CALLS=0
PRODUCTION_WRITES=0
DEPLOYED=NO
```

## 1. 目标与边界

把 `官方 corpus → generation workspace → private generated draft → validation →
canonicalization → OFFICIAL DRAFT` 安全连接起来，为后续的"内容审核 → 独立管理员
approve → 课程开放"做准备。本阶段只产生 **OFFICIAL + DRAFT**，绝不提交/审批发布。

本阶段未做：部署、真实付费模型调用、生产数据库写入、自动 publication、自动
approve、seed fixture 当正式内容。全部测试使用 deterministic/fake provider。

## 2. 数据流

```
POST /api/admin/courses/{course_id}/official-knowledge-drafts/generate
  (admin-only; operationId, maxNodes, maxModelCalls, maxReservedOutputTokens, dryRun)
    │
    ├─ read corpus: 当前 OFFICIAL document_versions (id/version/sha256/status)
    │     + chunk count  →  corpus fingerprint (course + versions + config + BUILDER_VERSION)
    │
    ├─ dryRun=true → 只返回 course/document/chunk 计数、fingerprint、计划调用数、
    │     计划 reserved 上限、是否已存在同 fingerprint 的 draft；零写入零调用
    │
    ├─ 已存在同 fingerprint 的 OFFICIAL DRAFT → existingDraft=true 直接返回（幂等）
    │
    ├─ join_course(admin, course) → 受控 learning workspace
    ├─ learning.evidence(workspace, query, scope="official")
    │     → 逐条复核 document_version: course_id == 本课 AND source_scope='OFFICIAL'
    │       私有/OWNER_COURSE/他课证据一律丢弃；无官方证据 → 422，不 canonicalize
    │
    ├─ 模型调用（全部走 LearningOrchestrator.generate）：
    │     learning_operations (RUNNING→COMPLETED/FAILED) 先建行（reservation FK 要求）
    │     → learning_model_call_reservations（role='teacher'，真实账本）
    │     → learning_model_run_evidence
    │     maxModelCalls=1 → OfficialKnowledgeDraftBundleOutput（单次 bundle）
    │     maxModelCalls≥2 → OfficialNodeDraftOutput + OfficialTeachingSpecDraftOutput（两次）
    │     每次调用前 guard：calls_made < maxModelCalls 且
    │       (calls_made+1) × v3_max_output_tokens ≤ maxReservedOutputTokens，
    │       超限立即 429，绝不调用 provider；整批计划超限在首调前 429（fail fast）
    │
    ├─ 输出校验：spec item 集合 == node item 集合；每个 REQUIRED item 至少一条
    │     evidence 且全部 evidence ∈ 已验证官方证据 → 否则 422，保持 draft 不落库
    │
    └─ canonicalization（单个短事务 BEGIN IMMEDIATE）：
          事务内重读 corpus fingerprint（漂移 → 409 OFFICIAL_CORPUS_CHANGED，回滚）
          幂等重查 existing draft（并发防御）
          canonical node id = "official-node-" + sha256(course,title,major,kind,items)[:24]
            （已存在则校验逐字段一致，冲突 → 409 CANONICAL_NODE_CONFLICT）
          INSERT knowledge_nodes(owner_user_id=NULL, status='CANDIDATE')
          INSERT teaching_specs(version=1, content_json, content_hash 精确复制)
          teaching_spec_metadata: status='DRAFT'（014 触发器自动）+ created_by_user_id=admin
          INSERT OR IGNORE material_evidence(source_scope='OFFICIAL', owner NULL,
            真实 document_version_id/chunk_id/locator)
          复用 KnowledgeService._validate_graph（cycle/orphan/atomic-parent/前置完整）
          INSERT knowledge_tree_versions(OFFICIAL, DRAFT, workspace NULL, owner NULL,
            version=MAX+1, title, change_reason, content_hash=确定性 payload,
            corpus_fingerprint)
          INSERT knowledge_tree_memberships(teaching_spec_version=1 精确)
          —— 不写任何 publication_* 表，不改变任何 PUBLISHED 状态
```

## 3. 新 API contract

`POST /api/admin/courses/{course_id}/official-knowledge-drafts/generate`（admin-only，403 ADMIN_REQUIRED）

请求 `OfficialKnowledgeDraftGenerate`：

| 字段 | 约束 |
|---|---|
| operationId | `^[a-zA-Z0-9_-]{1,100}$` |
| maxNodes | 1..10（builder 硬上限 10） |
| maxModelCalls | 1..20（builder 硬上限 20） |
| maxReservedOutputTokens | 1..20000（builder 硬上限 20000） |
| dryRun | bool，默认 false |

响应 `OfficialKnowledgeDraftGeneration`：courseId、operationId、dryRun、existingDraft、
treeVersionId、treeVersion、nodeIds、corpusFingerprint、corpus{documentCount,chunkCount,
versionCount}、budget{maxNodes,maxModelCalls,maxReservedOutputTokens,plannedModelCalls,
plannedReservedOutputTokens,modelCallsMade,reservedOutputTokensBooked}、
evidenceChunkCount、evidenceRows。

错误码：404 COURSE_NOT_FOUND；409 OFFICIAL_COURSE_REQUIRED / OFFICIAL_CORPUS_EMPTY /
OFFICIAL_CORPUS_CHANGED / CANONICAL_NODE_CONFLICT；422 OFFICIAL_DRAFT_LIMIT /
OFFICIAL_DRAFT_EVIDENCE_UNAVAILABLE / OFFICIAL_DRAFT_EVIDENCE_REQUIRED /
OFFICIAL_DRAFT_INVALID；429 OFFICIAL_DRAFT_BUDGET_EXCEEDED。

## 4. Canonicalization 规则

- 只允许 ATOMIC（v1 bounded，maxNodes=1）；COMPOSITE 本版本不出（schema kind 固定 ATOMIC）。
- node: owner_user_id=NULL, status='CANDIDATE'，保留 title/description/major/kind。
- spec: teaching_specs version=1 精确复制 content_json/content_hash；metadata status=DRAFT，
  created_by_user_id=实际操作管理员。
- canonical node id 稳定可审计：内容哈希派生，同内容幂等复用、冲突 409、绝不重复堆积。
- tree: workspace_id/owner_user_id NULL，tree_kind=OFFICIAL，status=DRAFT，
  version=课程内 OFFICIAL MAX+1，content_hash=确定性 payload，corpus_fingerprint 落列。

## 5. Evidence 规则

- 只用 `source_scope='OFFICIAL'` 且 `course_id==目标课程` 的真实 document_version/chunk。
- 私有（WORKSPACE_PRIVATE/OWNER_COURSE/他课）证据在进入 provider 前过滤。
- 每个 REQUIRED item 必须 ≥1 条证据；引用不存在的 chunk → 422，不 canonicalize。
- material_evidence 行 source_scope='OFFICIAL'、owner NULL、真实 version/chunk/locator，
  进入 publication snapshot review package（MATERIAL_EVIDENCE 资源）。

## 6. Budget enforcement

- 一切模型调用走 LearningOrchestrator.generate → learning_model_call_reservations
  （owner/course/role/reserved_output_tokens/status/input/output tokens 全账本）+ run evidence。
- 每次调用前 guard：调用数 ≤ maxModelCalls；累计 reserved ≤ maxReservedOutputTokens；
  任意下一次会超 → 429 立即 BLOCKED，不再调用 provider。
- 整批计划超限 → 首调前 429（fail fast）；部分超限自动降级为单次 bundle（1 次调用）。
- dryRun 零调用零预留。

## 7. Idempotency key

corpus fingerprint = sha256(canonical json)：
`{builder_version, course_id, config{maxNodes,maxModelCalls,maxReservedOutputTokens},
documents[{version_id, version, sha256, status} × 全部当前 OFFICIAL 版本]}`

落库列 `knowledge_tree_versions.corpus_fingerprint`（迁移 023，加法）。同 fingerprint 重跑 →
existingDraft=true 复用同一 tree，不重复生成节点/树/调用；corpus 或 config 变化 →
fingerprint 变化 → 安全创建明确新版本。

## 8. Transaction boundary

read corpus →（fingerprint）→ reserve → model generation（每次调用自身有短保留事务，
模型 HTTP 调用绝不包在长 SQLite 写事务内）→ validate → **单个短事务**写
nodes/spec/metadata/evidence/tree/memberships。生成失败：无半棵树；写库失败：整体回滚。
PRIVATE generation 记录（learning_operations/reservations/run evidence）保留为审计证据。

## 9. 安全规则不变

- 不调用 POST /api/admin/knowledge-publication-requests，更不 review approve。
- INDEPENDENT_REVIEW_REQUIRED（自审 409）原样保留并已回归。
- 第二管理员配置未触碰（本阶段只产 DRAFT）。

## 10. 修改文件

- `services/rag-api/migrations/023_official_knowledge_draft_fingerprint.sql`（新，ledger）
- `services/rag-api/app/db.py`（V3_MIGRATIONS + LATEST=23 + 幂等 ALTER/index guard）
- `services/rag-api/app/learning/models.py`（OfficialNodeDraftItem/NodeDraftOutput/
  TeachingSpecDraftOutput/BundleOutput 生成契约）
- `services/rag-api/app/models.py`（OfficialKnowledgeDraftGenerate/Generation/Corpus/Budget）
- `services/rag-api/app/services/official_knowledge_draft_builder.py`（新，builder）
- `services/rag-api/app/api/publication.py`（新 admin 端点）
- `services/rag-api/app/main.py`（builder 注册）
- `services/rag-api/app/learning/testing.py`（3 个 deterministic fixture 分支）
- `services/rag-api/tests/test_official_knowledge_draft_builder.py`（新，15 项）
- `services/rag-api/tests/test_ui_extension_schema_compat.py`（断言改用 LATEST 常量）

## 11. 新增 tests（15，全部 deterministic/fake provider，零真实 Qwen）

1. dryRun 零 DB write、零 provider call
2. 有界生成：canonical node（owner NULL/CANDIDATE）+ 精确 spec + metadata DRAFT +
   OFFICIAL DRAFT tree + membership 精确 + 保留账本（2 行 reservation/run evidence）
3. maxModelCalls 硬限制（单次 bundle schema）
4. reserved 上限 fail-fast（429，零调用）
5. 部分上限降级为单次 bundle（1 调用，4000 booked）
6. 私有证据被拒绝（OWNER_COURSE 伪造证据 → 422，零写入）
7. REQUIRED item 无证据 → 422 不落库
8. 快照 pipeline：submit → snapshot 资源含 TREE_VERSION/KNOWLEDGE_NODE/TEACHING_SPEC/
   MATERIAL_EVIDENCE 且 sourceScope=OFFICIAL
9. 自审仍 409 INDEPENDENT_REVIEW_REQUIRED
10. builder 不创建 publication request / 不 publish（request 0、release 0、状态 DRAFT/CANDIDATE）
11. 同 corpus 幂等（existingDraft=true，无重复节点/树/调用）
12. 中途失败不留半棵树（保留 1 条 reservation 审计，canonical 全空）
13. 非 admin 403
14. 非 official course 409
15. 空 corpus 409 + 三个硬上限 422

## 12. 全量验证结果（本阶段实跑）

| 命令 | 结果 |
|---|---|
| `pytest tests/test_official_knowledge_draft_builder.py` | **15 passed** |
| 迁移相关组合（rehearsal + M6D1 + schema_compat + backup_restore） | **31 passed** |
| RAG 全量 `pytest -q --ignore=work`（凭据临时暂存，无真实调用） | **见最终一轮输出** |
| Agent `vitest run` + `tsc -p tsconfig.json` | **66 passed** / build exit 0 |
| Web `vitest run` + `tsc -b` + `vite build`（Clerk 形态） | **55 passed** / exit 0 |
| `ruff check`（变更文件） | 0 新增违规（main.py 1 条既有 E501 未动） |
| `git diff --check` | clean |

## 13. 与生产事实的关系（未触碰）

生产 release cdf52b2、RAG Schema 22、66 documents / 1936 chunks / 69 jobs、
knowledge_nodes=0 / knowledge_tree_versions=0 —— 本阶段只提交代码，未运行迁移、未写入、
未部署。迁移 023 为加法（一列 + 一索引），将在后续受控部署阶段由既有 initialize
路径应用；对现有行只加 NULL 列，不重写任何数据。

## 14. 未来课程兼容

builder 只依赖 course_id → official corpus 的通用合同（course_type='official' +
document source_scope='OFFICIAL'），不写死 cs3481/ge2324。学生访问路径不触发生成
（只有显式 admin 调用才会）。
