# REQUIREMENTS_TRACEABILITY

Requirement → implementation → test mapping for the current change round.
Status legend: ✅ implemented & locally tested · 🟡 implemented, real-model verification NOT_RUN · ⬜ not implemented (declared).

| # | Requirement (user prompt) | Backend | Frontend | Test |
|---|---|---|---|---|
| A1 | 课程名只显示用户输入的 x；内部 ID 继续用时间戳后缀 | V3 course create keeps `name` as typed (`ui_extension/domain.py _create_course`); DTO `name` unchanged; frontend cards show `name` not `code` | `ui/App.jsx` course cards | `test_current_change_features.py` (DTO) + legacy name repair in migration 025 |
| A2 | 合法数字名保留（CS3481 等） | no global regex stripping; suffix only in id | — | migration 025 only strips proven `<base> <id>` names |
| A3 | 删除顶部“CS3481 模板 → …”固定说明 | — | `ui/pages.jsx` status fallback removed | frontend build |
| A4 | 运行状态动态（正在思考中/正在输出中），空闲隐藏，左右独立 | SSE `status` labels (`provider.py`, `app.py` queued label) | `Learn.watch`/`renderPane` per-lane state | `test_normal_mode_is_single_stage_and_thinking_runs_plan` (labels) |
| A5 | 删除“Shift + Enter 换行” | — | composer footer | frontend build |
| A6 | 左 Pane 红色 Thinking + 圆形开关（默认关，aria-pressed） | `teaching_mode` field on runs (`models.py RunCreate`, `cmui_runs.teaching_mode`) | Thinking toggle (teach pane only) | `test_normal_mode_…` |
| A7 | 右 Pane 加粗“做一题”真动作 | `POST /courses/{cid}/exercises` | 做一题 button → exercise flow | `test_exercise_hides_answer_until_reveal` |
| B1 | normal：直接回答，不调 plan、不加载专业模板 | `provider.generate(teaching_mode='normal')` single-stage | toggle off default | `test_normal_mode_…` (no prompt_ready) |
| B2 | thinking：模板→plan→work，plan 保存并关联 | `generate(teaching_mode='thinking')` plan→work; run stores template_id context | toggle on | `test_normal_mode_…` (prompt_ready present) |
| B3 | plan 失败/截断不伪称完成；恢复不重跑 | existing run error/terminal semantics unchanged | — | existing suites |
| B4 | 开关只影响后续请求 | mode captured at run creation | — | ✅ by design |
| B5 | 原生推理参数与 teaching_mode 分开 | `enable_thinking=False` kept; documented separation | — | 🟡 NOT_RUN (no real-model call) |
| C1 | 14 模板全文注册 + OTHER | `cm_update/prompts/*` (extracted bodies) + `templates.py` registry | — | `test_template_registry_has_15_distinct_full_bodies` |
| C2 | 分类状态机 + 千问分类 + 校验 + OTHER 回退 | `classify_course_task`, `validate_classification`, `cmui_classifications` | classification correction UI | `test_classification_manual_and_auto` (auto=TestProvider 🟡 real qwen NOT_RUN) |
| C3 | 手动纠正不被自动覆盖 | `source='manual'` guard | — | `test_classification_manual_and_auto` |
| D1 | plan 永不进用户响应（含旧记录） | `GET /runs/{id}` whitelist; SSE prompt_ready only length; no other plan endpoints | `查看本次教学 Prompt` removed | `test_run_response_never_exposes_plan_text` |
| D2 | 猜 ID/跨用户/对抗样例 | ownership checks existing; whitelist is per-row | — | 🟡 adversarial prompts NOT_RUN (model-level) |
| E1 | 统一双栏历史（一个历史项恢复两 Pane） | `cmui_pairs` + `/pairs` endpoints | History modal lists pairs; restore both panes | `test_pair_lifecycle_restores_both_lanes` |
| E2 | 单侧为空显示空态 | pair lane NULL renders empty | — | ✅ by design |
| E3 | 新对话建新双栏会话 | `POST /pairs` | 新对话 → pair | `test_pair_lifecycle_…` |
| E4 | 节点唯一绑定（user+course+node） | partial unique index `cmui_pairs_node_binding` + transactional bind | ⋯ menu | `test_pair_node_binding_unique_and_switchable` |
| E5 | 首次点节点自动 Thinking 一次 | run endpoint atomic claim + forced thinking on first bind | — | ✅ by design (logic in `run`) |
| E6 | 再点节点恢复原 Pair 不再扣费 | existing pair restore path (unchanged, layout→pair) | — | ✅ by design |
| E7 | 旧历史迁移不猜配对 | `_migrate_pairs` (layout evidence only; leftovers single-lane) | — | schema test (migration idempotence via app boot) |
| F1 | 做一题选题优先级 | `pick_exercise_node` (bound → earliest NOT_STARTED/LEARNING atomic → review first) | — | ✅ code path (deterministic) |
| F2 | 首轮无答案；显示答案同版本、幂等 | exercise stream cuts at 【标准答案】; answer stored server-side; reveal idempotent | 显示答案 → steps | `test_exercise_hides_answer_until_reveal` |
| F3 | 用户上传题目直接分点作答 | problem lane normal mode uses 题目 prompt (`provider.direct_messages`) | — | `test_normal_mode_…` (problem TestProvider) 🟡 real 题目prompt NOT_RUN |
| F4 | 每步“详解”浮动窗（多窗、拖拽、缩放、关闭、缓存、追问） | `cmui_step_explanations` + endpoints; hidden conversations | floating window implementation | `test_explanation_flow_and_reuse` |
| G1 | 校园课程/共享课程显示类型与访问要求分开 | V3 `display_type` + `requires_student_verification` (migration 025); gate helper | badges + gated actions | `test_code_redemption_and_campus_gate`, `test_share_snapshot_and_join` |
| G2 | 学生认证 7 位码、HMAC 存储、唯一兑换、幂等、限速、审计、管理员发行 | `social.py` + endpoints | account panel | `test_code_redemption_…`, `test_grandfather_boundary_is_one_time` |
| G3 | 既有用户 grandfathered 一次性 | `grandfather_existing_users` (meta-boundary; integrated candidates via domain) | — | `test_grandfather_boundary_…` |
| H1 | 全站用户目录 | existing `/people` (fields only) | — | existing suite |
| H2 | 私信无商业次数上限（保留防护） | existing `/messages` unchanged | — | existing suite |
| H3 | 共享课程：快照冻结、三档历史、文件必含、幂等、加入、provenance | `social.py` share/join + endpoints + domain `course.create_shared` | inbox 共享课程 UI | `test_share_snapshot_and_join` |
| H4 | 校园快照要求认证 | `requires_student_verification` carried into snapshot & join gate | — | `test_share_snapshot_and_join` (403 → verified → join) |
| I1 | 学习状态/测评不破坏 | no change to V3 state semantics | — | full regression suite |

## Implementation decisions (engineering supplements, NOT user words)

1. Exercise delivery format line appended to the 做一题 prompt ("先输出题目正文；然后另起一行输出【标准答案】…") to make the hide/reveal split mechanically reliable.
2. `display_type` is a presentation column; access rules stay in `course_type`/ownership + `requires_student_verification`.
3. Manual classification correction is allowed for the course owner or an admin (official courses have no student owner).
4. Explanation follow-ups reuse the explanation prompt with the accumulated explanation as context (the Word prompt does not define a follow-up format).
5. Sharing a campus course snapshot keeps its verification requirement on the recipient side (independent of the "共享课程" label).
