# M6D1A SOURCE ACCEPTANCE REPORT — 只读源码级验收

**Audit date**: 2026-09-16
**Candidate**: `53549663797a199b31c7156ef2daf30900269d3a`
**Baseline**: `cdf52b2cba1700805d9982950c202e9cb927825a`
**Branch**: `release/openapi-fix`
**Audit mode**: read-only（未修改代码、未 amend/rebase/push、未部署、未动生产 DB、未调用真实 Qwen、未动 credential；本报告文件本身为唯一新增文件，未提交）

---

## 1. Git identity / cleanliness

| 检查 | 结果 |
|---|---|
| `git rev-parse HEAD` | `53549663797a199b31c7156ef2daf30900269d3a` ✓ |
| `git branch --show-current` | `release/openapi-fix` ✓ |
| `git status --porcelain`（验收时刻） | 空（clean）✓（本报告创建后为唯一 untracked 文件） |
| `git log -8 --oneline` | 5354966 → 5cbfa18 → cdf52b2 → b69df54 → 6b13cdf → dac9807 → a54819a → 5848efa |
| `git merge-base --is-ancestor cdf52b2..5354966` | **exit 0**（baseline 是候选的祖先）✓ |

## 2. Exact diff inventory

`git diff --stat cdf52b2..5354966`：12 files changed, +1717/−2。
其中 `netlify.toml`（+1）属于 **BASELINE commit `5cbfa18`（netlify 修复），不是 M6D1**。

**M6D1 commit `5354966` 自身**（`git show --stat`）：11 files, +1716/−2

| 状态 | 文件 |
|---|---|
| A | `M6D1_OFFICIAL_KNOWLEDGE_DRAFT_BUILDER_REPORT.md` |
| M | `services/rag-api/app/api/publication.py`（+30） |
| M | `services/rag-api/app/db.py`（+21/−1） |
| M | `services/rag-api/app/learning/models.py`（+67） |
| M | `services/rag-api/app/learning/testing.py`（+33） |
| M | `services/rag-api/app/main.py`（+4） |
| M | `services/rag-api/app/models.py`（+45） |
| A | `services/rag-api/app/services/official_knowledge_draft_builder.py`（+710） |
| A | `services/rag-api/migrations/023_official_knowledge_draft_fingerprint.sql`（+13） |
| A | `services/rag-api/tests/test_official_knowledge_draft_builder.py`（+587） |
| M | `services/rag-api/tests/test_ui_extension_schema_compat.py`（+1/−1，断言改用 LATEST 常量） |

## 3. API authorization audit

- 文件 `app/api/publication.py`，路由 `POST /api/admin/courses/{course_id}/official-knowledge-drafts/generate`（行 181-198）。
- 行 189：`admin: Annotated[AuthenticatedUser, Depends(require_admin)]` — **require_admin 依赖**。
- 行 198：`return _draft_builder(request).generate(course_id, payload, admin_user_id=admin.user_id)` — 身份只来自认证依赖的 `admin.user_id`，请求体/查询参数无任何 user id 字段（`OfficialKnowledgeDraftGenerate` 只有 operationId/maxNodes/maxModelCalls/maxReservedOutputTokens/dryRun）。
- `app/auth.py` 行 59-64：`require_user` 未认证 → `ApiError(401, "UNAUTHENTICATED", ...)`；行 68-73：`require_admin` 非 admin → `ApiError(403, "ADMIN_REQUIRED", ...)`。
- 动态验证（本审计 scratch 运行，deterministic 模式）：未认证 → **401 UNAUTHENTICATED**；owner token → **403 ADMIN_REQUIRED**；admin → **200**。
- 测试覆盖：`test_non_admin_cannot_generate`（403）；401 由 `require_user` 依赖结构性保证（本审计已动态复核）；admin 成功路径由全部 M6D1 测试覆盖。如实说明：新测试文件未单独写 401 用例（结构保证 + 动态复核替代）。

**ADMIN_GATE=PASS**

## 4. dryRun hard audit（代码路径证明）

`official_knowledge_draft_builder.py::generate` 顺序：
- 行 564-571：硬上限校验（无写、无调用）。
- 行 572-579：`_course` → 读 corpus → 算 fingerprint → 查 existing（只读）。
- 行 581-601：预算计划与 corpus 统计（纯计算）。
- **行 602-625：`if payload.dry_run:` 直接 return** —— 位于 `join_course`（行 656）、`_official_evidence`（行 660）、`_generate_drafts`（行 667）**之前**。
- 全文件唯一的模型入口是行 295 `self.learning.generate(...)`（在 `_generate_drafts` 内部）；builder 无其他 provider 调用、无 reservation 写入代码。
- 因此 dryRun=true 时：provider.generate=0、LearningOrchestrator.generate=0、learning_operations/reservations/run_evidence/knowledge_nodes/teaching_specs/knowledge_tree_versions/material_evidence 全部 0 写入。
- 测试：`test_dry_run_writes_nothing_and_makes_no_provider_calls`（逐表计数前后相等，含 reservations/runs）。

**DRY_RUN_ZERO_SPEND=PASS**

## 5. Idempotency BEFORE spend（最高优先级）

精确调用顺序（`generate`，行 573-667）：

```
1. _official_versions + _chunk_count            （只读，573-577）
2. _fingerprint(course, versions, config)       （纯计算，578）
3. _existing_draft(connection, course, fp)      （只读，579）
4. 预算计划/统计                                （纯计算，581-601）
5. dry_run → return（若有）                     （602-625）
6. planned_calls==0 → 429                       （627-632，无调用）
7. existing is not None → return existing draft （633-654）★★★
8. join_course / evidence / _generate_drafts    （656-673，此时才可能花钱）
```

第 7 步（existing-draft return）严格先于第 8 步；任何 `LearningOrchestrator.generate` / `provider.generate` / reservation 都在第 8 步之后。事务内二次防御：`_canonicalize` 行 406-423 在 `BEGIN IMMEDIATE` 后重读 fingerprint 并重查 existing，漂移 → 409。
测试：`test_same_corpus_rerun_reuses_the_existing_draft`（第二次运行 reservations 仍为 2 —— 零新增调用）。

**IDEMPOTENCY_BEFORE_SPEND=PASS**

## 6. Budget hard limits（服务端 enforce，非仅 schema）

- 服务端硬上限（行 564-571）：`maxNodes>10 → 422`；`maxModelCalls>20 → 422`；`maxReservedOutputTokens>20000 → 422`（`OFFICIAL_DRAFT_LIMIT`）。
- 更小请求值即为真正上限：`_guard_call`（行 230-245）在**每次**调用 `learning.generate` 之前执行：
  - `calls_made + 1 > payload.max_model_calls → 429 OFFICIAL_DRAFT_BUDGET_EXCEEDED`
  - `(calls_made + 1) * settings.v3_max_output_tokens > payload.max_reserved_output_tokens → 429`
  - guard 抛出后控制流不进入 provider（`run_operation` 行 295 在 guard 之后才被调用）。
- 整批 fail-fast：行 627-632，`planned_calls==0 → 429`（首次调用前）。
- 429 真实路径：`ApiError(429, ...)` → `app/main.py` 行 174-185 异常处理器 → HTTP 429；无 reservation/run 写入。
- 测试：`test_hard_ceilings_are_rejected`（10/20/20000 超限 422）、`test_reserved_token_ceiling_blocks_before_any_call`（3999 上限 → 429，reservations=0）、`test_partial_ceiling_degrades_to_the_single_call_bundle`（7999 → 单次 bundle，booked 4000）、`test_single_call_budget_uses_the_bundle_schema`。

**BUDGET_HARD_CAP=PASS**

## 7. Provider path audit

对 builder 全文检索 `OpenAI(` / `requests.post` / `httpx.` / `aiohttp` / `urllib` / `DashScope` / `chat/completions`：**0 命中**。
调用链（唯一）：
`OfficialKnowledgeDraftBuilder.generate → _generate_drafts → run_operation → LearningOrchestrator.generate（orchestrator.py:793）→ reserve_model_call（:687，写 learning_model_call_reservations）→ LearningProvider.generate（provider.py:78）→ 成功/失败 record_run（orchestrator.py:733，写 learning_model_run_evidence）`。
builder 未新建任何 HTTP client；凭据/endpoint 全在既有 Settings/LearningProvider。

## 8. Official evidence boundary（服务端校验）

- `_official_evidence`（行 162-193）：对检索到的每个 chunk，按 `document_versions` 复核 `course_id == 目标课程 AND source_scope=='OFFICIAL'`，否则丢弃；locator/id 为空丢弃。PRIVATE / OWNER_COURSE / 他课 OFFICIAL 证据全部进不了 verified 集合。
- `_validate_outputs`（行 195-226）：模型返回的每个 `evidence_ids` 必须 ∈ verified 集合，否则 422 `OFFICIAL_DRAFT_EVIDENCE_REQUIRED`；每个 REQUIRED item 空证据 → 同样 422；spec item 集合 ≠ node item 集合 → 422 `OFFICIAL_DRAFT_INVALID`。
- 不存在的 evidence id：不在 verified 集合 → 422（同上路径）。
- 失败时不 canonicalize：校验发生在 `_canonicalize` 之前（行 674-684 顺序），zero official 写入。
- 测试：`test_private_evidence_is_rejected`（伪造 OWNER_COURSE 证据 → 422、零写入）、`test_required_item_without_evidence_is_rejected`（422、零写入）。

**OFFICIAL_EVIDENCE_ONLY=PASS**

## 9. Canonicalization atomicity

- 单事务：`_canonicalize` 行 404-405 `with self.database.connect(): connection.execute("BEGIN IMMEDIATE")`，事务内含：in-tx fingerprint 复核（406-412）→ in-tx existing 重查（413-423）→ **canonical node**（425-456，`owner_user_id=NULL, status='CANDIDATE'`，保留 title/description/major/kind）→ **teaching_specs**（457-472，content_json/content_hash 精确复制）→ **teaching_spec_metadata**（473-475，触发器自动 DRAFT + created_by_user_id=admin）→ **material_evidence**（478-497，OFFICIAL/owner NULL/真实 version+chunk+locator，INSERT OR IGNORE）→ 图校验（499-508，复用 `KnowledgeService._validate_graph`：cycle/orphan/atomic-parent/前置完整）→ **knowledge_tree_versions**（510-547，OFFICIAL/DRAFT/workspace NULL/owner NULL/version=MAX+1/content_hash/corpus_fingerprint）→ **knowledge_tree_memberships**（548-552，teaching_spec_version=1 精确）。
- 任意一步抛错 → `with` 上下文回滚整个官方包；模型账本（operations/reservations/run evidence）在事务外，允许保留（审计证据）。
- COMPOSITE：v1 生成 schema `kind: Literal["ATOMIC"]` 不产出 COMPOSITE；若未来引入，membership 的 DB 触发器（014 行 254-309）强制 COMPOSITE 绑定 `teaching_spec_version IS NULL`，且 `_validate_graph` 强制 COMPOSITE 必须有子节点。
- 测试：`test_generation_failure_leaves_no_half_tree`（第二次调用模拟失败 → nodes/specs/trees/memberships/evidence 全 0，保留 1 条 reservation）。

**CANONICAL_ATOMICITY=PASS**

## 10. Fingerprint correctness + migration 023

- 结构（行 123-148）：`sha256(canonical_json({builder_version, course_id, config{maxNodes,maxModelCalls,maxReservedOutputTokens}, documents[{version_id, version, sha256, status}...]}))` —— 覆盖 course id、当前 OFFICIAL document version 身份与 sha256、生成配置、builder 版本；**无随机 UUID、无时间戳**。
- 迁移 023（`migrations/023_...sql` + `app/db.py` 行 459-482）：nullable 加法列 + 部分索引；`initialize()` 用 `PRAGMA table_info` guard + `CREATE INDEX IF NOT EXISTS` 保证可重复执行；ledger `INSERT OR IGNORE ... VALUES(23, ...)`；`LATEST_V3_SCHEMA_VERSION=23`。
- 隔离演练（本审计 scratch，**测试生成的 Schema-22 fixture，如实注明非 production copy**）：
  - before：ledger max=22、无列 → after：ledger max=23、列存在、既有行 `corpus_fingerprint=NULL`
  - `integrity_check=ok`、`foreign_key_check=0`
  - documents/chunks/document_versions/chunk_source_versions/workspaces/knowledge_nodes/teaching_specs/teaching_spec_metadata/knowledge_tree_versions/memberships/material_evidence 行数全部不变
  - 再次 initialize 幂等成功。

**MIGRATION_22_TO_23=PASS**（fixture rehearsal；本机无 production Schema-22 脱敏副本）

## 11. No publication bypass

builder/API 检索：`knowledge-publication-requests` / `.review(` / `approve` / `publication_releases` / `activate_release` —— **0 命中**（唯一 "PUBLISHED" 命中是注释与既有节点状态校验 `{"CANDIDATE","PUBLISHED"}`，非发布动作）。
builder 只产生：CANDIDATE node、DRAFT spec metadata、OFFICIAL+DRAFT tree、ACTIVE official evidence。
动态验证：生成后 `official_knowledge_publication_requests=0`、`publication_releases=0`、tree status=`DRAFT`。
`INDEPENDENT_REVIEW_REQUIRED`：`test_draft_feeds_snapshot_and_self_review_stays_forbidden`（自审 409）+ 全量 `test_publication_v3.py` 通过。

**NO_PUBLICATION_BYPASS=PASS**

## 12. Snapshot compatibility

本审计 scratch（deterministic provider + 隔离 test DB）：builder 生成 1 个 ATOMIC node 后直接调用 `official_knowledge_snapshot_payload(connection, tree_id)` —— 成功；资源 kinds = `['KNOWLEDGE_NODE','MATERIAL_EVIDENCE','TEACHING_SPEC','TREE_VERSION']`（满足 TREE_VERSION/KNOWLEDGE_NODE/TEACHING_SPEC 最低要求，且 MATERIAL_EVIDENCE 以 `source_scope='OFFICIAL'` 正确进入 review package）；memberCount=1。未调用 approve。

**SNAPSHOT_COMPATIBILITY=PASS**

## 13. Exact tests（本轮实跑，全部 deterministic，零真实 provider）

| 套件 | 结果 |
|---|---|
| `tests/test_official_knowledge_draft_builder.py` | **15 passed** |
| `tests/test_publication_v3.py` | **passed**（含于下） |
| `tests/test_knowledge_registry.py` | **passed**（含于下） |
| `tests/test_ui_extension_schema_compat.py` | **5 passed** |
| 四套合计 | **38 passed**（60.92s） |

（全量 RAG 套件 521 passed 为同一 commit 下此前实跑结果；本轮按要求重跑上述四套。运行期间本地 `.env` 凭据临时改名暂存，避免任何真实调用，跑后原样恢复。）

## 14. Secret / production path audit

- M6D1 commit 文件列表：无 `.env`、无数据库文件、无 credential 文件。
- 全文检索 `sk-*` / `pk_live` / `pk_test_` / `secret_key=` / `api_key=` / 长 Bearer token / `.env` / `/srv/coursemate` / 硬编码 `rag.sqlite3`：唯一命中为测试文件中的 `database_path=tmp_path / "rag.sqlite3"`（pytest 临时目录 fixture，非生产路径）。
- builder 构造只注入既有 `Database/Settings/LearningOrchestrator`（行 61-69；main.py 行 225-231 传入 app 级实例），无任何硬编码生产路径或凭据。

**SECRET_SCAN=PASS**

---

# 结论

```text
ADMIN_GATE=PASS
DRY_RUN_ZERO_SPEND=PASS
IDEMPOTENCY_BEFORE_SPEND=PASS
BUDGET_HARD_CAP=PASS
OFFICIAL_EVIDENCE_ONLY=PASS
CANONICAL_ATOMICITY=PASS
MIGRATION_22_TO_23=PASS
NO_PUBLICATION_BYPASS=PASS
SNAPSHOT_COMPATIBILITY=PASS
INDEPENDENT_REVIEW_UNCHANGED=PASS
SECRET_SCAN=PASS
TEST_GATE=PASS

M6D1A_SOURCE_GATE=PASS
LIVE_MODEL_CALLS=0
PRODUCTION_WRITES=0
DEPLOYED=NO
```

如实备注：
1. Schema 22→23 演练使用测试生成的 Schema-22 fixture（本机没有 production 脱敏副本），非 production-copy rehearsal。
2. 新测试文件覆盖 403 与 admin 成功；401 由 `require_user` 依赖结构性保证并经本审计动态复核（401 UNAUTHENTICATED 实跑）。
3. 本审计期间除本报告文件外未产生任何仓库改动；报告未提交（保持 read-only）。
