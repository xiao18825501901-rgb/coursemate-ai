# INTEGRATION MAP — 交付包与真实 CourseMate V3 的接线

本文档记录每一项接线的**真实落点**：文件、函数、调用的原服务，以及该操作
在交付包中的确切调用点。所有路径相对仓库根目录。

---

## 1. 挂载方式

```
app/main.py:create_app()
  └─ if resolved_settings.ui_extension_enabled:          # UI_EXTENSION_ENABLED=true 时才挂载
       app.ui_extension.mount.mount_ui_extension(application)
         └─ app.cm_update.integration.install_ui_extension(host, ui_settings, adapter, resolver)
              └─ host_app.mount('/ui-extension', ui_app)     # 保留宿主路由与 lifespan
```

* 新 UI 的 API 前缀：`/ui-extension/api/ui/v1`
* 挂载门（`app/cm_update/integration.py:27`）：必须 `integration_mode=='integrated'`
  **且** `auth_mode=='injected'`，否则 `install_ui_extension` 直接 `ValueError`。
  这阻止了生产环境误用 `standalone` 参考域。
* 默认关闭：`ui_extension_enabled: bool = False`（`app/config.py`），生产不开关就不会出现新入口。

## 2. 注入了什么（以及为什么改）

| 改动 | 文件 | 原因 |
|---|---|---|
| `encoding='utf-8'` 读 Word 模板 | `app/cm_update/provider.py:20` | Windows 中文区域 locale 是 GBK，`read_text()` 无参会在**真实付费调用**上抛 `UnicodeDecodeError`（Linux 上不可见） |
| `encoding='utf-8'` 读 build 标记 | `app/cm_update/config.py:48` | 同一类 locale 缺陷，出现在 production 启动门路径上 |
| `seed(cfg, documents=None)` | `app/cm_update/seed.py` | 原本从包根 `sample-documents/` 读示例 PDF。本仓库不发布示例课程资料，因此改为显式传入目录；`production` / `integrated` 仍然直接拒绝 |
| 历史弹窗新增"旧版问答记录"分组 + 新增 `Assessment` 组件 | `apps/web/src/ui/pages.jsx` | 让原 V3 问答历史在新壳内可读，并把节点测评从 `JSON.stringify` 原始 JSON 改成真实结果面板。**纯新增，未改动既有页面布局、样式类或交互** |
| 追加 `.legacy-*` / `.assessment-grid` 样式 | `apps/web/src/ui/styles-extra.css` | 只追加，未修改既有规则 |
| `provider_mode` / `allowed_origins` 等以宿主配置为准 | `app/ui_extension/mount.py:_ui_settings` | 复用已部署的**同一个**千问凭据（`V3_MODEL_API_KEY` / `V3_MODEL_BASE_URL`），不产生第二份密钥 |

交付包其余源码逐字节未改（下节校验）。

## 3. DomainPort 契约 → 真实 V3 实现

实现：`services/rag-api/app/ui_extension/domain.py:V3DomainAdapter`
（`integration/README.md` 的全部调用点，共 **28** 个 operation，程序枚举自
`if operation == "…"` 分支）：course.list/get/create/update/delete、
file.list/upload/content/text/delete、context.retrieve、attachments.prepare、
task.list/create/update/delete/plan、knowledge.tree/assessment/begin_learning/
submit_delivery/record_problem/assessment.start/assessment.view/assessment.submit/
assessment.abandon、legacy.conversations/legacy.conversation。

| operation | 真实调用 | 交付包读取的字段 |
|---|---|---|
| `course.list` | `SELECT * FROM courses WHERE visibility='public' OR owner_user_id=?`（排除 workspace 私有语料课程） | `x['id']`（算 pinned） |
| `course.get` | `require_course_access(database, id, owner_user_id=subject, is_admin=…)` | `name`、`code`、`requirements`（**两阶段千问硬索引这三个键**） |
| `course.create` | `IngestionService.create_course(CourseCreate(id=slug, …), is_admin=False)` → 得到 `course_type='user'`、`visibility='private'` 的真实课程 | `row['id']` |
| `course.update` | `IngestionService.update_course(...)`；`requirements` 写入该用户最新 `course_teaching_profiles.custom_requirements` | 整行 |
| `course.delete` | 先比对 `confirm == row['name']`，再 `IngestionService.delete_course(...)` | 整行 |
| `file.list` | 直接查询 `documents ⋈ document_versions`，union「课程公开资料」与「本人 workspace 私有语料」；**不返回 `stored_path`** | 返回原样 |
| `file.upload` | `IngestionService.queue_document(course_id=workspace.private_course_id, owner_user_id=subject, is_admin=False)` + 同步 `process_document` | 整行；`status` 取**重新读取**后的真实状态 |
| `file.content` | `current_document_version` + `original_path`（重算 sha256 校验）→ `FileResponse` | 原样；Range/HEAD 交给 Starlette |
| `file.text` | `document_for` + `SELECT locator_type,locator_value,content FROM chunks` | 原样 |
| `file.delete` | 拒绝删除共享课程资料（403 `SHARED_DOCUMENT`），否则 `IngestionService.delete_document` | — |
| `context.retrieve` | `HybridRetriever.retrieve(..., access=RetrievalAccess(subject,'official'))` + `scope='mine'` 第二次检索；去重后编号 `S1..Sn` | `id` 必须是 `S<n>` 形 |
| `attachments.prepare` | `ProblemRepository.image_input(workspace, subject, version_id, max_bytes=…)` 授权取字节 | `images[].data_url`、`metadata[].id` |
| `task.list/create/update/delete` | HTTP 转发到 V3 `services/agent-api`（`/api/tasks…`），转发调用方原始 `Authorization` | `title/dueDate/courseId/status/updatedAt` |
| `task.plan` | HTTP 转发到 `POST /api/agent/chat` —— **原 Node Function Calling Agent**，不做正则、不做假成功 | `message`、`toolResults` |
| `knowledge.tree` | `LearningOrchestrator.knowledge_state(workspace_id, subject)` → 取 `personalized_tree`（存在时）否则 `official_tree` 的 `members`，与 `registry` 合并 | `id/parent/title/position/progress/grade` |
| `knowledge.assessment` | 同一份 snapshot 的 `state.assessment`；缺失时 404，**不伪造 GPA** | 原样 |
| `knowledge.begin_learning` | `orchestrator.node()` 校验节点与 Spec 版本后，用 `LearningOrchestrator.journey()` 创建/复用 V3 `learning_journeys` 行（幂等）；run 侧把 run→journey 交叉引用写入 `cmui_run_v3` | `journey_id/node_id/spec_version/workspace_id/status` |
| `knowledge.assessment.start` | `orchestrator.start_assessment(workspace, subject, AssessmentStartInput(...))` | V3 会话 dict |
| `knowledge.assessment.view` | `orchestrator.assessment(workspace, subject, session_id)`（提交前答案键不可见，由 V3 view 契约保证） | 会话 + 5 题 |
| `knowledge.assessment.submit` | `orchestrator.submit_assessment(...)`，workspace revision 现读现用，`REVISION_CONFLICT` 重试一次 | 评分结果 |
| `knowledge.assessment.abandon` | `orchestrator.abandon_assessment(...)` | 会话 dict |
| `legacy.conversations` | 直接读原 `conversations` 表，按 `owner_user_id` + `course_id` 过滤 | 宿主新增路由使用 |
| `legacy.conversation` | 直接读原 `conversations` / `messages`，返回真实正文与引用 | 宿主新增路由使用 |

**覆盖记录的权威归属（本轮闭环接线后，有代码与测试证据）**：
`app/learning/knowledge.py:_atomic_learning` 用 `teaching_delivery_evidence` 计算
`covered_required` 与 `NOT_STARTED/LEARNING/LEARNED`，计数的
`validation_status` 集合为 `('VALIDATED','LEGACY_PRESERVED','REVIEWED')`
（`VALIDATED`=计划式 `teach()`；`LEGACY_PRESERVED`=迁移 015 保留的旧行；
`REVIEWED`=迁移 022 新增的**经评审的新壳自由文本交付**）。

新壳两阶段教学现在走完整闭环（不重复生成答案、不伪造 LEARNED）：

1. run 创建时先 `knowledge.begin_learning` 绑定用户/课程/workspace/journey/
   node/spec 版本，并把该 Spec 的 REQUIRED items 作为 `spec_requirements` 交给
   第一阶段规划（仍是自由文本 Prompt，不改为 JSON，不授予模型任何数据库权限）；
2. 第二阶段正文只有在 run 的**条件式最终写入**（`status='completed'` 且 assistant
   消息落库）之后才提交覆盖：`knowledge.submit_delivery` →
   `app/learning/shell_delivery.submit_shell_delivery`，在**单个 RAG 事务**内写入
   `teaching_units`（正文可恢复的 section）+ 每条确认 item 一条
   `validation_status='REVIEWED'` 的 `teaching_delivery_evidence`
   （`validation_reason='SHELL_COVERAGE_REVIEW_V1'`，content_hash 为 section 哈希）
   + `learning_coverage`，并按同一规则把 journey 置为 LEARNING/LEARNED；
3. **覆盖认定不由模型决定**：可注入的 `CoverageReviewer` 接口
   （`app/learning/coverage_review.py`）返回确认的 item 列表——
   `NullCoverageReviewer`（默认：不确认任何覆盖）、`DeterministicCoverageReviewer`
   （本地/测试用规则：acceptance 全句必须出现在正文，生产被拒）、
   模型评审器（文档化的收费第三次调用，**未实现且未授权运行**，见
   `QWEN_LIVE_TWO_STAGE_REPORT.md` 费用说明）。未获评审确认时只保存教学单元，
   不写任何证据，节点如实保持未覆盖；
4. **失败/取消/截断/重复/闲聊不可能记账**：只有 claim 成功的 run 才提交；取消与
   完成由数据库终态裁决；`teaching_units(journey_id, operation_id)` 唯一索引 +
   UI 库 `cmui_delivery_submissions` 回执（Schema 4）保证跨库中断后重启恢复只重放
   幂等记账、不重调 Provider；run 的 `coverage` 字段暴露回执。
5. 新旧入口读取一致：`teach()` 的已覆盖集合同样计入 REVIEWED，已覆盖的 item
   不再被旧入口重复教学。

正反验收（从零覆盖、无预种证据）见
`tests/test_ui_extension_coverage_submission.py`（7 项）：0/2→LEARNING、2/2→LEARNED、
测评低分不影响 LEARNED、仅提关键词/失败/截断/取消不计、重放不重复、
跨库中断恢复零 Provider 调用、错课程/旧 Spec/跨用户隔离、旧入口读到 REVIEWED。

### 管理员用真实资料生成、检查、发布官方知识树的最小路径（closure §五）

生产树尚未发布时新壳如实显示空态（已测：`knowledge.tree` 返回 `[]`，前端显示
"还没有课程知识树"）。**不得**用 `scripts/seed_tree_fixture.py` 之类的测试夹具冒充
发布（该脚本只写 `work/e2e-*` 副本且拒绝生产路径）。真实发布走 V3 既有的管理面
（`app/api/publication.py` + `app/services/knowledge_publication.py`）：

1. **生成**：在 V3 学习工作台用真实课程资料生成知识节点草案与教学规格
   （`LearningOrchestrator.create_node` / `create_spec`；模型生成步骤需要相应预算）；
2. **组装官方树草稿**：`knowledge_tree_versions`（`tree_kind='OFFICIAL'`，`DRAFT`）+
   memberships 指向原子节点与 spec 版本；
3. **提交发布申请**：`POST /api/admin/knowledge-publication-requests`
   （`OfficialKnowledgePublicationSubmit`，管理员）；
4. **检查快照**：`GET /api/admin/knowledge-publication-requests/{id}/snapshot`
   逐节点/逐 spec 核对内容，`GET /api/admin/knowledge-publication-drafts` 列草稿；
5. **审核**：`POST /api/admin/knowledge-publication-requests/{id}/review`
   （`PublicationReview`）。approve 会：旧 PUBLISHED 官方树转 `RETIRED`、
   快照内节点转 `PUBLISHED`、`teaching_spec_metadata` 转 `PUBLISHED`、
   树版本 DRAFT→PUBLISHED 并写 `reviewed_by_user_id`/`reviewed_at`（公开审核留痕）；
6. **生效**：新壳 `knowledge.tree` 立即读到新 PUBLISHED 官方树，无需任何 UI 库迁移；
7. 撤回/下线：`DELETE /api/admin/knowledge-publication-requests/{id}`（申请撤回）与
   新 approve 的自动 supersede。

该路径的每步都是 V3 现有真实接口（管理员角色 + 审核留痕），本接线**没有**为此新增
任何发布旁路；fixture 走的是同一套表与触发器，只用于隔离测试。

### 关键约束（来自逐行读包，非猜测）

1. **异常类型**：`cm_update` 对 DomainPort 抛出的异常**不做 try/except**，
   唯一例外是 `/notifications` 里 `except HTTPException`。而且 FastAPI 不会把子应用的异常
   交给宿主 handler。因此适配器在 `call()` 里把 `ApiError` 统一翻译成
   `fastapi.HTTPException(status_code, detail)`（`domain.py:call`）。
2. **`file.list` 每一项必须有 `id`**：`app.py:535` 与 `:539` 硬索引 `x['id']`，
   缺失就是 500。适配器保证每项都带 `id`。
3. **来源编号**：standalone 分支会在 `app.py:700` 重编号为 `S1..Sn`；
   domain 分支**不重编号**，所以适配器自己保证 `S<n>` 形且跨 `context.retrieve` 与
   `attachments.prepare` 唯一。
4. **上传去重**：V3 的 `documents` 有 `UNIQUE(course_id, sha256)`，重复上传抛
   409 `DUPLICATE_DOCUMENT`；交付包的 standalone 分支返回 `duplicate:true`。
   真实接线走 V3 语义（409），未伪造 `duplicate` 字段。
5. **已发布课程内容锁定**：`publication_status ∈ {pending,published}` 的课程，
   V3 用触发器禁止插入/更新 `documents`、`chunks`、`course_teaching_profiles`、`derived_artifacts`。
   因此**用户上传一律进入本人 workspace 的私有语料课程**（`learning_workspaces.private_course_id`），
   而不是往已发布的公开课程里塞文件——这正是 V3 自己的模型。

## 4. 认证桥

```
浏览器（/app，Clerk session）
  → window.CourseMateAuth.getToken()            # apps/web/src/CourseMateUi.tsx（Clerk useAuth）
  → Authorization: Bearer <Clerk session token>
  → /ui-extension/api/ui/v1/...                  # cm_update 的 current_user
  → app.state.subject_resolver(request)          # app/ui_extension/identity.py
  → host_app.state.auth_verifier.authenticate()  # app/auth.py 的 ClerkAuthVerifier（原逻辑）
  → subject = JWT.sub
```

* `subject_resolver` **绑定宿主 app**（`clerk_subject_resolver(host_app)`），
  因为被挂载的子应用里 `request.app` 指向子应用自身，取不到 `auth_verifier`。
* 身份只来自 `Authorization` 头，**从不**取自 body、query 或自定义头
  （`integration.py:8` 的硬规定）。
* `cmui_users.id` 就等于 Clerk `sub`（`auth.py:ensure_user`），所以评论、私信、
  通知天然按真实账号隔离，不需要第二套账号体系。
* 未登录：resolver 抛 `HTTPException(401, '请登录')` → 前端渲染登录卡片并调用
  `window.CourseMateAuth.signIn()` → Clerk 弹窗。

## 5. 前端接线

| 项 | 值 |
|---|---|
| 新壳入口 | `apps/web/ui.html` → `src/main.ui.tsx` → `src/CourseMateUi.tsx` |
| 交付 UI 源码 | `apps/web/src/ui/*.jsx`、`*.js`、`*.css`（`pages.jsx` 与 `styles-extra.css` 有**纯新增**的测评流程/旧记录分组，其余原样） |
| API base | `window.COURSEMATE_CONFIG.apiBase`；构建期由 `VITE_UI_API_BASE` 决定，默认 `/ui-extension/api/ui/v1` |
| 数学渲染 | `window.CourseMateMath = katex`（npm `katex@0.16.22`），只生成 MathML |
| 路由（**本轮改为新壳默认**） | `netlify.toml` 与 `scripts/serve_web_dist.mjs` 及 Vite dev 插件共用同一决策表：`/` 与未知路径 → `ui.html`（打开站点/登录完成即进入新控制面板）；`/app`、`/app/*` → `ui.html`（兼容别名）；`/qa`、`/learn`、`/courses`、`/tasks`、`/documents`、`/admin`、`/about` 及其子路径 → `index.html`（旧深链、历史阅读与管理入口继续可达）；已部署的 `/assets/*` 等真实文件永远优先于重写 |
| 双文档理由 | 新壳自带 53 KB 全局 CSS（`*`、`html/body/#root` 重置），若与现有站点同文档会互相污染；双文档保留 |

交付 UI 的 `App.jsx`、`pages.jsx`、`richtext.jsx` 未做任何视觉或交互改动。

## 6. 会话历史

* 新 UI 的历史是 `cmui_conversations` / `cmui_messages` / `cmui_runs`，由 `cm_update` 自己持久化，
  刷新、换设备、退出重登后可恢复（`GET /conversations/{id}`）。
* **旧的 V3 会话历史仍在原表**：`conversations` / `messages` / `qa.py` 路由与
  `services/rag-api/app/api/qa.py` 的 `/api/conversations*` **完全没有改动**，
  旧入口继续可用（`apps/web` 原有 `QaPage` 仍在 `index.html` 文档中）。
* 本次**没有**写入任何把旧 `conversations` 复制进 `cmui_conversations` 的迁移。
  理由：复制会制造两份会各自漂移的副本，且 `cmui_*` 的 lane（`teach`/`problem`）
  与 V3 会话（问答流）语义并不一一对应。旧记录通过旧入口访问，新记录通过新入口访问，
  两者都保留、都不丢。
* 新壳内提供**只读**的旧记录入口（`app/ui_extension/mount.py:_prepend_legacy_history`）：

  | 路由 | 行为 |
  |---|---|
  | `GET /ui-extension/api/ui/v1/courses/{cid}/legacy-conversations` | 列出该课程下**本人**的 V3 会话，含真实 `title` / `message_count` / `updated_at` |
  | `GET /ui-extension/api/ui/v1/courses/{cid}/legacy-conversations/{id}` | 返回该会话的真实消息与引用 |

  这两条路由由宿主新增（交付包本身没有旧历史路由），但**所有授权仍走原有代码**：
  身份来自宿主 `auth_verifier`，课程访问走 `require_course_access`，
  会话按 `owner_user_id` 过滤。它们被插入在子应用既有路由**之前**，
  否则 `cm_update` 的静态兜底挂载会吞掉它们。
  学习页的历史弹窗底部新增"旧版问答记录"分组，打开后是只读阅读器
  （无重命名、无删除、无输入框）。

## 7. 新增数据与备份

* 新表全部在独立文件 `CMUI_DATA_DIR/ui.sqlite3`（**Schema 3**，26 张 `cmui_*` 表，
  其中 `cmui_run_v3` 是 Schema 2→3 新增的 run→V3 journey 交叉引用，
  `cmui_runs` 的 `lease_worker`/`lease_heartbeat` 是 Schema 3 租约列），
  与 `rag.sqlite3`、`agent.sqlite3` 物理分离；`Database.initialize()` 检测到
  `courses`/`chunks`/`tasks`/`schema_migrations` 会拒绝初始化，**不可能覆盖原库**。
* 附件在 `CMUI_DATA_DIR/uploads/`。
* `ops/backup_v2.py` 在 `CMUI_DATA_DIR` 存在时把 `ui.sqlite3` 与 `ui-uploads.tar.gz`
  并入同一恢复单元，并写进 `manifest.json`；`ops/restore_v2.py` 在发布目标目录前
  逐项校验校验和、完整性、外键与上传清单。
* 两个独立 SQLite `backup` 调用之间**不是原子的**：跨库一致性仍需维护窗口，
  已写入 `MIGRATION_AND_ROLLBACK.md`。
