# SOURCE_BASELINE_AND_GAPS

Round: Jev + DeepSeek implementation on the live CourseMate code base.
Audit date of the input package: 2026-09-21. Implementation baseline checked out and
verified in this session.

## 1. Identity of the four different source states

These are NOT the same thing and are never conflated in this round:

| Symbol | Value | Meaning / evidence |
|---|---|---|
| `ARCHIVE_SHA` | `c309219ef7fbaa28ce203ef21e3fe02d3eee716f` | Source commit declared by the delivery archive (`INPUT_ARCHIVE_FACTS.json`; `CourseMate_release_evidence_20260921_part01.zip`, sha256 `36f365f0…6de7`, 578 entries). Confirmed present in this repository and an ancestor of the work tree. |
| `WORKTREE_SHA` | `b05fd29417bf306e3615e2cb6e9117ab85e333cb` | Implementation baseline = `c309219` + the Stage-0/1 fixes committed on branch `fix/codex-dsh-audit-20260919` (learning-start fact, global retrieval fusion, assessment projection, formal probe regressions). |
| `APPLICATION_SHA` | `4ef50642c0b2336e64c384752ea262901a32d81d` | The application run recorded inside the package's production report ("Add guarded production backup window"). It is a *reported* runtime identity, not the current live one. |
| `PRODUCTION_SHA` | `5ba6a3a` (release dir `/home/admin/coursemate-v3-releases/5ba6a3a`) | Live production release recorded during the earlier archive/verification round of this session; report schema RAG 25 / UI 13 / Agent 1. Not re-verified this round (no production authorization). |

Work-tree schema constants after this round's migrations: **RAG 28**, **UI 13**,
**Agent 1** (`services/rag-api/app/db.py::LATEST_V3_SCHEMA_VERSION`,
`services/rag-api/app/cm_update/db.py::SCHEMA_VERSION`).

Source of the pack facts: `DSH_MASTER_IMPLEMENTATION_PROMPT.md`, `SOURCE_AUDIT_AND_FINAL_PLAN.md`,
`SOURCE_EVIDENCE.md` (S01–S21), `ISOLATED_SOURCE_PROBES.json`, `JEV_DECISION_CATALOG.json`,
`TEMPLATE_V2_MANIFEST.json`, `reproduce_source_findings.py`. The auditors ran **no** project tests,
no model calls and no production access (`tested_with_live_model=false`,
`full_project_tests_run=false`), so their findings are reproduced here as real regressions
before any code change is credited.

Cross-check performed this round: every quoted code window in `SOURCE_EVIDENCE.md`
(S01–S21) still matches the work tree at the same identifiers and line numbers — no stale
quotes. Per-file hashes differ from the archive only because `core.autocrlf=true`
(ZIP snapshot vs git checkout line endings); the code content is identical.

## 2. The nine gaps this round must close, and their real status

Status legend: ✅ fixed and covered by a test in this workspace · 🟡 implemented, live
verification NOT_RUN · ⬜ still open.

| # | Gap (user requirement) | Where it lived | Status in this round |
|---|---|---|---|
| 1 | 学习开始事实与覆盖投影分离 | `learning/knowledge.py::_atomic_learning` (`covered==0 → NOT_STARTED`, no start fact) | ✅ migration 026 `learning_start_events` + projection fix + `_begin_learning` start receipt; regression `tests/test_jev_deepseek_gap_regressions.py::test_probe_started_learning_without_coverage_is_learning` (was failing, now green) and negative control `…not_started_node_stays_not_started` |
| 2 | 集成检索先合并官方/私人候选再统一排名 | `ui_extension/domain.py::_retrieve` (official-first append + `top_k` truncation) | ✅ `learning/retrieval_orchestrator.py` (RRF across scopes, exact-target protection, boundary-aware budget) wired into `_retrieve`; regressions `test_probe_retrieval_merges_private_candidates_before_top_k`, `test_probe_exact_target_is_not_replaced_by_rank` (both were failing, now green) |
| 3 | 有原始分但无等级时不得显示“未测评” | `_knowledge_tree` exposed only `grade_label`; UI rendered `n.grade \|\| '未测评'` | 🟡 backend ✅ (`raw_score`/`assessment_status`/`assessment_display`/`latest_result`/`latest_independent_result`/`active_session`; `_atomic_assessment` no longer prefers independent over recency); fullscreen UI replacement in progress (assessment workstream) |
| 4 | 复用 AssessmentService / 五题蓝图 / grade_snapshots | `learning/assessments.py` already owned them | 🟡 extended by the assessment workstream (no parallel grade system, proven by tests) |
| 5 | 题池不足时真实准备 + 正确验证等级（不 seed、不改标签） | pool filter `VALIDATED AND verification_method!='MODEL_ONLY'`, hard `ASSESSMENT_POOL_INSUFFICIENT` 409 | 🟡 `assessment_preparation_jobs` + `AI_REVIEWED` diagnostic channel (migration 027) by the assessment workstream |
| 6 | 新生成角色统一迁移到核验后的 DeepSeek，无 Qwen 回落 | `cm_update/provider.py`, `learning/provider.py`, `learning/coverage_review.py`, `rag/answers.py`, `agent-api` | 🟡 DeepSeek workstream (adapter + capability matrix + host-spy test); **live canary RUN 2026-09-24（round 96 更正）**：10/10 角色在 `deepseek-flash` 上完成，USD 0.0079908；仍未覆盖 streaming、tool replay 与人工质量复核，见 `DEEPSEEK_LIVE_ACCEPTANCE.md` §2（原先此格为 "NOT_RUN (no credentials/budget)"） |
| 7 | 接入官方 Jev 判断服务（真实调用链 + 分层评估） | no Jev code existed | 🟡 `app/jev/` gateway + 12 catalog definitions + shadow/on + receipts/cache (migration 028); **live verification PARTIAL**：Choice 与 Noul 已在真实网关验证，`Score` 因返回连续值被类型校验按设计拒绝；校准/消融为 `INTERPRETABLE` 且不利，组件消融仍 NOT_RUN（预算待批） |
| 8 | 导入 16 份 V2 模板，保留题目/详解与 exercise.v2 | `cm_update/templates.py` registered V1 | ✅ 16/16 V2 files imported with manifest sha256 verified, versioned registry (V2 default, V1 retained), 题目/详解 and `EXERCISE_RUNTIME_CONTRACT_V2.txt` untouched; `tests/test_jev_deepseek_template_v2.py` 21 passed |
| 9 | 全屏五题、底部统一答案上传、评分、逐步详解与节点成绩更新 | modal `Assessment` with five separate textareas, `JSON.stringify` reference answer | 🟡 assessment workstream (fullscreen workspace + unified composer + draft + per-step 详解) |

## 3. Reproducing the two pack probes as real regressions

The pack proved both findings by extracting the exact methods (`reproduce_source_findings.py`).
In this round they are permanent tests against the **real** services and the real V3 schema:

* `services/rag-api/tests/test_jev_deepseek_gap_regressions.py`
  * `test_probe_started_learning_without_coverage_is_learning` — an accepted teaching run whose
    saved content supports none of the REQUIRED items leaves `covered_required = 0` and the node
    must read `LEARNING` (was `NOT_STARTED`), with `learning.started = true` and a real
    `started_at`; a second/third run with real coverage still walks LEARNING → LEARNED.
  * `test_probe_not_started_node_stays_not_started` — a node the learner never started stays
    `NOT_STARTED` (the fix must not turn every node into "learning").
  * `test_probe_retrieval_merges_private_candidates_before_top_k` — with `top_k = 2` and two
    candidates per authorized scope, the private candidate must reach the output through the
    merged ranking (was: two official hits filled `top_k`).
  * `test_probe_exact_target_is_not_replaced_by_rank` — `official-2.md` / `… page 2` keeps its
    slot in the merged ranking.

Verified sequence: these four tests were written first and **failed** on the pre-fix tree
(2 failed / 2 passed — the two negative controls passed), then passed after the fixes.
While fixing, the tests also exposed a defect in the new fusion itself (the candidate cap was
applied in append order, so the first scope consumed the whole budget); that is fixed and
covered by the same test.

## 4. Deliberate boundaries (what this round does not fake)

* No production write, no deployment, no DNS/Clerk/Netlify change (no authorization in session).
* No real DeepSeek or TypeSafe call: keys/budget are not available; every contract is verified
  with injected fake transports and the live path raises a typed error instead of silently
  falling back.
* No Qwen fallback for new generation; embeddings stay on their independent contract
  (`text-embedding-v4`) and are disclosed as such rather than rebuilt.
* Old chat, grades, bridges, template versions and learning evidence are never deleted; V1
  template versions stay on disk for existing conversations.
