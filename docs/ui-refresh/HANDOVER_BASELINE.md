# HANDOVER BASELINE — Codex 交付包接入真实 CourseMate V3

**审计时间**：2026-09-14（Asia/Hong_Kong）
**接手前的真实基线 SHA**：`64e57501b380ffaefb55db92ef0fc328c39b0928`
（`docs: record source-region V3 production rollout`，与
`feature/coursemate-v3-persistent-learning`、`origin/feature/coursemate-v3-persistent-learning`
指向同一提交）
**接手分支**：`feature/dsh-ui-refresh-integration`（接手时已存在于该 SHA，工作树为空改动）
**本文档描述的是接手前的事实，不是本次修改后的结果。**

---

## 1. 真实工作区事实

| 项目 | 事实 |
|---|---|
| 仓库路径 | `C:\Users\Hp\Documents\Codex\2026-08-11\files-mentioned-by-the-user-coursemate\outputs\coursemate-ai` |
| remote | `https://github.com/xiao18825501901-rgb/coursemate-ai.git` |
| 当前分支 / HEAD | `feature/dsh-ui-refresh-integration` / `64e5750` |
| 未提交改动 | 只有两个未跟踪文件：`ACTUAL_IMPLEMENTED_CHANGES_AUDIT.md`、`curl`（0 字节）。**没有未提交的源码修改，dirty worktree 未被覆盖。** |
| 本地分支 | `feature/dsh-ui-refresh-integration`、`feature/coursemate-ui-refresh-qwen-teaching`、`feature/coursemate-v3-persistent-learning` 三者同指 `64e5750`；另有 `feature/coursemate-v2-ai-tutor`(`846138e`)、`main`(`e1ef57a`)、`feature/public-security-upgrade`(`360babf`) |
| 依赖 | `node_modules` 存在（201 项）；`services/rag-api/.venv` 存在（Python 3.12.14，pytest 9.1.1）；`apps/web/node_modules` 存在（typescript 等 4 项） |
| 本地数据 | `data/rag.sqlite3`（5.8 MB）+ `data/uploads`；**没有** `data/agent.sqlite3` |
| 本机工具 | node v24.19.0、npm 11.17.0（须用 `npm.cmd`，`npm.ps1` 被执行策略拦截）、npm registry 可达（`PONG 296ms`） |

接手时的 `git status` 只有两个未跟踪文件，说明**交付包从未被合入本仓库**，与
`docs/IMPLEMENTATION_STATUS.md` 自述一致。

## 2. 真实后端接口（接手前）

| 服务 | 形态 | 关键事实 |
|---|---|---|
| `services/rag-api` | FastAPI + SQLite，`app/main.py:create_app()` | Schema `LATEST_V3_SCHEMA_VERSION = 21`；迁移 `migrations/011`…`021` 仅在 `V3_ENABLED=true` 时用 `executescript` 应用；`is_ready()` 要求已应用版本集合等于 `1..21` 才返回健康 |
| `services/agent-api` | Express 5 + TypeScript | 5 条业务路由：`GET/POST /api/tasks`、`PATCH/DELETE /api/tasks/:taskId`、`POST /api/agent/chat`；`/health`；工具名固定五个（createTask/searchTask/updateTask/completeTask/deleteTask） |
| 认证 | Clerk | rag-api 用 `clerk_backend_api.authenticate_request`（`app/auth.py:19`）；agent-api 用 `@clerk/express`。测试可用 `AUTH_TEST_USER_ID`（只允许 test+deterministic） |
| 权限 | `app/course_access.py:require_course_access` | 允许条件：`owner_user_id` 匹配、或 `is_admin and course_type='official'`、或 `not write and visibility='public'`；否则一律 404（隐藏存在性）。写操作在 `publication_status ∈ {pending,published}` 时抛 409 |
| 知识/测评 | `app/learning/` | `LearningOrchestrator` + `KnowledgeService.snapshot()`；`has_learning_state` 返回 `{registry, official_tree, personalized_tree}`，节点状态含 `learning.status` 与 `assessment.grade_label`。**没有 `/journeys` 路由**，journey 在 `teach`/`solve` 内部隐式创建 |
| 检索 | `HybridRetriever` + `ChunkRepository` | FTS5 关键词 + 向量余弦，RRF 融合；必须传 `RetrievalAccess(owner_user_id, scope)`，`access=None` 只按 `course_id` 过滤，**不构成跨用户隔离** |
| 发布/审核 | `app/api/publication.py` | 20 条路由，`/api/courses/*/publication-requests`、`/api/admin/*`、`/api/shared-overlays/*` |
| 备份 | `ops/backup_v2.py` / `restore_v2.py` | 恢复单元 = `rag.sqlite3` + `agent.sqlite3` + `uploads.tar.gz`。**接手时不包含任何新增 UI 数据库或新增附件**（`ARTIFACTS` 常量硬编码） |

## 3. 交付包自述边界（接手时未闭环项）

`docs/IMPLEMENTATION_STATUS.md`、`docs/TEST_REPORT.md`、`integration/README.md` 一致声明：

1. 包是**独立环境已验证的增量包**，不是原 V3 补丁；造包时 GitHub 返回 404，未访问生产。
2. `web/dist` 使用离线 React16 验证运行时，`build-info.json` 带 `not_for_production:true`，
   **明令禁止生产发布**；`app/config.py:48` 的 production 校验会拒绝它。
3. `integration.DomainPort` 只有 Protocol 定义和文档契约，**没有任何真实实现**；
   包内唯一触及 `DomainPort` 的测试 `test_upgrade.py::test_host_mount_preserves_host_lifespan_and_endpoints`
   只处理 `course.list`，其余操作直接 `raise AssertionError`。
4. 包内 `cmui_*` 表是新增业务库，`seed()` 会写入两个示例课程（`cs3481`/`ge2324`）、
   4 个示例 PDF 和 10 个示例知识节点——**不得进入生产**。
5. 真实 Clerk / 真实千问 / 原生浏览器 / 生产部署均为 `NOT VERIFIED`。

## 4. 复用结论表

| 包内容 | 处置 | 理由 |
|---|---|---|
| `web/src/*.jsx`、`*.css`、`api.js`、`utils.js`、`icons.jsx`、`richtext.jsx` | **原样复用** | 用户已认可的视觉与交互基准。仅迁入原仓库 Vite 构建体系，未重画 |
| `web/src/vendor/katex.mjs`（265 KB） | **替换** | 改用 npm `katex@0.16.22` 正式依赖，避免把验证运行时副本带进生产 |
| `web/dist`、`web/offline-runtime` | **禁止使用** | 离线 React16 验证产物，生产门会拒绝 |
| `backend/cm_update/`（app/auth/config/db/models/provider/retrieval/sse/steps/filesystem） | **复用**，3 处可移植性修正 | 见 `INTEGRATION_MAP.md` §2 |
| `backend/cm_update/prompts/cs3481_original.txt` | **原样复用** | 千问两阶段第一阶段的完整 Word 模板 |
| `backend/cm_update/integration.py` | **原样复用** | `install_ui_extension()` 保持宿主路由与 lifespan |
| `backend/tests/*` | **复用**，改为 `app.cm_update` 命名空间 + pytest-asyncio | 见 `INTEGRATION_MAP.md` §5 |
| `backend/cm_update/seed.py` | **复用（仅本地）** | `environment=='production'` 或 `integration_mode=='integrated'` 时直接 `RuntimeError` |
| `agent/src/*` | **未采用** | 正式部署复用原 V3 `services/agent-api`，不开第二套工具系统 |
| `artifacts/*`、`sample-documents/*`、`reference/*` | **不发布** | 证据与示例资料，不属于源码交付 |

## 5. 接手前实测基线（本次运行，非引用包内日志）

| 项 | 命令 | 结果 |
|---|---|---|
| rag-api 全量回归 | `.venv\Scripts\python.exe -m pytest -q`（`services/rag-api`） | **329 passed**，527.52s |
| web 单测 | `vitest run`（`apps/web`） | **49 passed** |
| 交付包 Python 测试 | 包内 `backend/tests` 迁移后 | **71 passed** |
| 真实千问 | — | **未运行**（无预算授权） |
| 生产 | — | **未触碰** |

## 6. 尚存环境缺口（接手前已存在，不由本次引入）

1. `pytest-asyncio` 不在 `requirements-dev.txt` 中；`apps/web` 的 `typescript` 只装在
   `apps/web/node_modules`，不在根 `.bin`。
2. `tzdata` 未安装，Windows 上 `ZoneInfo('Asia/Hong_Kong')` 直接抛
   `ZoneInfoNotFoundError`。
3. `apps/web` 的 `esbuild@0.28.1` postinstall 被 npm `allow-scripts` 策略拦下（`npm warn`），
   但构建仍正常完成。
