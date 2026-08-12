# CourseMate AI — DEPLOYMENT HANDOFF FOR CHATGPT

> 核对日期：2026-08-12
> 核对基线：Git `main` / `2d14630dd0d3b50aad0c91c1e657a89e0efc5aa1`
> 用途：交给没有当前 Codex 工作区访问权的 ChatGPT，逐步指导项目所有者完成 GitHub → Render → Netlify 公网部署。
> 安全规则：本文不包含任何 API key、password、token 或其他 secret。未来 ChatGPT 不得要求用户在聊天中粘贴 secret。

## Operator stop gate

当前项目已完成本地验证，但**还不能安全地匿名开放到公网**：两个 backend 没有终端用户认证、授权或用户级数据隔离。所有访问者会共享同一课程库和 Todo 数据，并且任何能访问 API 的人都能上传课程文件、创建/修改/删除任务和消耗模型调用。

在公开站点前，项目所有者必须二选一并亲自确认：

1. 先实现应用级 authentication/authorization 与用户数据隔离；或
2. 使用可靠的平台级访问控制，把 Netlify 和两个 Render endpoints 限制给明确授权用户。

仅配置 CORS、隐藏 URL 或使用 Render/Netlify HTTPS 都不等于认证。若尚未完成访问控制，只能做受控 staging 验证，不应宣布为公共产品上线。

---

# 1. CURRENT DEPLOYMENT STATUS

```text
Repository name: coursemate-ai
Repository root: C:\Users\Hp\Documents\Codex\2026-08-11\files-mentioned-by-the-user-coursemate\outputs\coursemate-ai
Git remote: NONE CONFIGURED
Git branch: main
Latest audited product commit: 2d14630dd0d3b50aad0c91c1e657a89e0efc5aa1
Latest commit to deploy: the GitHub main HEAD that contains this handoff file; verify it in GitHub before deployment
GitHub pushed: NO

Netlify deployed: NO
Render deployed: NO
Production fully verified: NO
```

当前没有 GitHub repository URL。未来操作者需新建或选择一个 GitHub repository，将这个 repository root 的 `main` branch 推送上去。只有实际 push 后才能填写 GitHub owner/repository URL；不得猜测名称或 owner。`2d14630...` 是生成本交接文件时核对的产品基线；交接文件自身提交后 HEAD 必然更晚，因此部署时以“包含本文件且通过审核的 GitHub `main` HEAD”为准。

本地验证状态：RAG pytest 42、Agent Vitest 32、Web Vitest 8、Playwright 3 均通过；Ruff、mypy、TypeScript typecheck 与 production build 通过。OpenAI live 网络调用和任何云部署尚未验证。

---

# 2. ACTUAL PRODUCTION ARCHITECTURE

```text
                           OpenAI API
                         ↗            ↖
User Browser ─ HTTPS ─ Netlify         │
                    React/Vite SPA     │
                       │        │      │
        public HTTPS   │        │ public HTTPS
                       ▼        ▼
              Render Web Service A    Render Web Service B
              coursemate-rag-api      coursemate-agent-api
              FastAPI / Python        Express / Node 24.14
                 │          │                    │
                 │          └─ /var/data/uploads│
                 ▼                               ▼
        /var/data/rag.sqlite3          /var/data/agent.sqlite3
        dedicated persistent disk      separate persistent disk
```

- Netlify 只部署 `apps/web` 产生的静态 Vite bundle。
- Render 创建 **2 个独立 Web Service**，不是一个合并服务。
- RAG service 独占课程 SQLite 和上传文件；Agent service 独占 Todo SQLite。
- 两个 backend 不直接互调。浏览器分别调用两者。
- 两个 backend 都在 live mode 下调用 OpenAI；浏览器绝不能持有 OpenAI key。
- 每个 SQLite service 必须保持单实例。Render persistent disk 只能挂载给一个 service instance，不能横向扩容。

---

# 3. REPOSITORY STRUCTURE FOR DEPLOYMENT

```text
coursemate-ai/
├─ apps/
│  └─ web/
│     ├─ src/
│     ├─ package.json
│     └─ dist/                 # build output；不应依赖本地已生成版本
├─ services/
│  ├─ rag-api/
│  │  ├─ app/
│  │  ├─ requirements.txt
│  │  └─ pyproject.toml
│  └─ agent-api/
│     ├─ src/
│     ├─ package.json
│     └─ dist/                 # Render build 时重新生成
├─ data/
│  ├─ inventory/              # inventory/report 已追踪
│  ├─ transcriptions/         # 一份 checksum-bound transcription 已追踪
│  ├─ rag.sqlite3             # 本地 runtime；Git 忽略
│  └─ uploads/                # 私有课程文件；Git 忽略
├─ docs/DEPLOYMENT.md
├─ docs/VERIFICATION_REPORT.md
├─ .env.example
├─ .gitignore
├─ package.json
├─ package-lock.json
├─ netlify.toml
└─ render.yaml
```

GitHub 必须连接 repository root，而不是只上传 `apps/web` 或某个 backend 子目录。两个平台都从根配置文件读取部署信息。

---

# 4. NETLIFY EXACT CONFIGURATION

```text
Frontend framework: React 19 + TypeScript + Vite 8
Frontend directory: apps/web
Base directory: repository root (leave blank in Netlify UI)
Package directory: NOT CONFIGURED; leave blank
Build command: npm run build --workspace @coursemate/web
Publish directory: apps/web/dist
Node version: 24.14.0
Config file: netlify.toml at repository root
```

`netlify.toml` 的实际部署设置：

```toml
[build]
  command = "npm run build --workspace @coursemate/web"
  publish = "apps/web/dist"

[build.environment]
  NODE_VERSION = "24.14.0"

[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200
```

SPA rewrite 是必需的：React Router routes（如 `/qa/cs3481`、`/tasks`）直接刷新时由 Netlify 返回 `index.html`。如果 Netlify UI 中另设 Base Directory 或 Package Directory，可能导致根 workspace、lockfile 或 publish 路径解析错误；当前已验证配置是两者留空，让根 `netlify.toml` 成为唯一配置真相源。

---

# 5. NETLIFY ENVIRONMENT VARIABLES

## `VITE_RAG_API_URL`

```text
Purpose: 浏览器访问 FastAPI RAG service 的公开 base URL
Example format: https://coursemate-rag-api-<unique>.onrender.com
Where value comes from: Render RAG service 部署完成后的 public URL
Required / Optional: REQUIRED for production
```

## `VITE_AGENT_API_URL`

```text
Purpose: 浏览器访问 Express Agent service 的公开 base URL
Example format: https://coursemate-agent-api-<unique>.onrender.com
Where value comes from: Render Agent service 部署完成后的 public URL
Required / Optional: REQUIRED for production
```

注意：

- 两个值都不要以 `/` 结尾，避免形成 `//api/...`。
- 它们由 Vite 在 **build time** 写入浏览器 bundle；修改后必须触发 Netlify rebuild/redeploy。
- 本项目没有单一 `API_BASE_URL` 或 production build-mode 自定义变量。
- `VITE_*` 是公开值。只能放公开 backend URL，不得放 key/token/password。
- **禁止在 Netlify 设置 `OPENAI_API_KEY`。** React 无需且不应看到它。

---

# 6. RENDER SERVICE INVENTORY

## Service A — RAG API

```text
Service name: coursemate-rag-api
Service type: Web Service
Runtime: Python
Plan: Starter (paid; required for persistent disk)
Root directory: services/rag-api
Build command: pip install -r requirements.txt
Start command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Health endpoint: /health
Expected port handling: Render PORT; start command binds 0.0.0.0:$PORT
Database path: /var/data/rag.sqlite3
Upload path: /var/data/uploads
Persistent storage: disk rag-data, mount /var/data, 1 GB
```

该 service 在 Blueprint 中显式设置 `rootDir: services/rag-api`，因此 Python import `app.main:app` 和 `requirements.txt` 都相对该目录解析。

## Service B — Agent API

```text
Service name: coursemate-agent-api
Service type: Web Service
Runtime: Node
Plan: Starter (paid; required for persistent disk)
Root directory: repository root (render.yaml does not set rootDir)
Build command: npm ci && npm run build --workspace @coursemate/agent-api
Start command: node services/agent-api/dist/src/server.js
Health endpoint: /health
Expected port handling: SEE PORT WARNING BELOW
Database path: /var/data/agent.sqlite3
Persistent storage: disk agent-data, mount /var/data, 1 GB
```

### Agent port warning

最终源码 `services/agent-api/src/config.ts` 只读取 `AGENT_PORT`，默认 `8001`；它没有读取 Render 的 `PORT`。`render.yaml` 当前也没有设置 `AGENT_PORT`。Render 可能自动侦测 8001，但其官方推荐服务绑定 `PORT`，生产部署不应依赖隐式侦测。

本次交接禁止继续改项目，因此部署 session 的安全配置办法是：

1. 在 `coursemate-agent-api` 的 Render environment 中增加 `AGENT_PORT`；
2. 值填 Render 为该 service 提供的 `PORT` 值，通常默认是 `10000`；
3. 不要把 shell 字面量 `$PORT` 填进 `AGENT_PORT`，除非 Render UI 明确支持变量引用；应填实际端口数字；
4. 检查日志中 `CourseMate Agent API listening on http://localhost:<port>`；
5. 以 `/health` 200 为最终判断。

长期代码修复应让 `loadConfig()` 使用 `AGENT_PORT ?? PORT ?? 8001` 并新增测试，但这不属于当前文档生成任务。

---

# 7. RENDER ENVIRONMENT VARIABLES

## Service A — `coursemate-rag-api`

| Variable | Purpose | Secret? | Where obtained | Required? |
|---|---|---:|---|---|
| `PYTHON_VERSION` | 固定 runtime | NO | Blueprint 固定 `3.12.13` | REQUIRED |
| `RAG_DATABASE_PATH` | RAG SQLite 路径 | NO | 固定 `/var/data/rag.sqlite3` | REQUIRED |
| `RAG_UPLOAD_DIR` | 上传文件目录 | NO | 固定 `/var/data/uploads` | REQUIRED |
| `RAG_PROVIDER_MODE` | 使用 live OpenAI provider | NO | 固定 `openai` | REQUIRED |
| `OPENAI_API_KEY` | Responses + Embeddings 认证 | **YES** | 用户自己的 OpenAI dashboard/secret | REQUIRED for live mode |
| `OPENAI_CHAT_MODEL` | RAG 回答模型 | NO | Blueprint 当前模型名 | REQUIRED |
| `OPENAI_EMBEDDING_MODEL` | ingestion/query embedding 模型 | NO | Blueprint 当前 `text-embedding-3-small` | REQUIRED |
| `WEB_ORIGIN` | 唯一允许的浏览器 origin | NO | 最终 Netlify production origin | REQUIRED |
| `CHUNK_SIZE` | chunk 字符目标，默认 1200 | NO | 源码默认；仅调参时设置 | OPTIONAL |
| `CHUNK_OVERLAP` | overlap，默认 200 | NO | 源码默认 | OPTIONAL |
| `TOP_K` | retrieval hits，默认 6 | NO | 源码默认 | OPTIONAL |
| `MAX_UPLOAD_BYTES` | 上传上限，默认 20 MiB | NO | 源码默认 | OPTIONAL |
| `MAX_CONTEXT_CHARS` | context 字符上限，默认 18,000 | NO | 源码默认 | OPTIONAL |
| `PORT` | Render 注入监听端口 | NO | Render platform | PLATFORM-MANAGED |

## Service B — `coursemate-agent-api`

| Variable | Purpose | Secret? | Where obtained | Required? |
|---|---|---:|---|---|
| `NODE_VERSION` | 固定 `node:sqlite` runtime | NO | Blueprint 固定 `24.14.0` | REQUIRED |
| `AGENT_DATABASE_PATH` | Todo SQLite 路径 | NO | 固定 `/var/data/agent.sqlite3` | REQUIRED |
| `AGENT_PROVIDER_MODE` | 使用 live OpenAI Agent | NO | 固定 `openai` | REQUIRED |
| `OPENAI_API_KEY` | Responses Function Calling 认证 | **YES** | 用户自己的 OpenAI dashboard/secret | REQUIRED for live mode |
| `OPENAI_CHAT_MODEL` | Agent 模型 | NO | Blueprint 当前模型名 | REQUIRED |
| `WEB_ORIGIN` | 唯一允许的浏览器 origin | NO | 最终 Netlify production origin | REQUIRED |
| `AGENT_MAX_TOOL_ROUNDS` | 工具循环上限，默认 4 | NO | 源码默认 | OPTIONAL |
| `AGENT_PORT` | 源码实际读取的端口 | NO | 映射到 Render service 的端口数字 | **REQUIRED UNTIL CODE IS FIXED** |
| `PORT` | Render 平台端口 | NO | Render platform | PLATFORM-MANAGED，但源码当前不读 |

Blueprint 中 `sync: false` 表示用户必须在 Render dashboard 手工填值；不代表可以省略。

---

# 8. OPENAI API CONFIGURATION

`OPENAI_API_KEY` 必须分别配置到两个 Render Web Service：

- `coursemate-rag-api`：用于 OpenAI Embeddings 和流式 Responses answer。
- `coursemate-agent-api`：用于 OpenAI Responses Function Calling loop。

可以使用同一个用户拥有的 key，也可以为服务创建不同 key 以便成本/撤销隔离；无论哪种方式，都要在 Render secret UI 中分别设置。

绝对禁止配置在：

- Netlify environment；
- 任何 `VITE_*` 变量；
- `.env.example` 的非空值；
- GitHub repository、issue、commit、Actions log；
- ChatGPT 对话、截图或公开部署文档。

若 key 曾进入 Git，即使随后删除也应立即撤销并重新生成。当前本地审计未发现 credential-shaped `sk-...` 值或被追踪的真实 `.env`。

---

# 9. CORS CONFIGURATION

## RAG

```text
Actual file: services/rag-api/app/main.py
Middleware: fastapi.middleware.cors.CORSMiddleware
Actual variable: WEB_ORIGIN
Current local default: http://localhost:5173
Allowed methods: GET, POST, OPTIONS
Allowed headers: Content-Type
Credentials: false
```

## Agent

```text
Actual file: services/agent-api/src/app.ts
Middleware: cors
Actual variable: WEB_ORIGIN, passed from services/agent-api/src/config.ts
Current local default: http://localhost:5173
Allowed methods: GET, POST, PATCH, DELETE, OPTIONS
Allowed headers: Content-Type
Credentials: false
```

Netlify 获得最终 production URL（例如 `https://<site>.netlify.app`）后：

1. 在两个 Render services 都把 `WEB_ORIGIN` 设置为该**精确 origin**；
2. 只包含 scheme + host，不含 path，不加尾部 `/`；
3. 保存并重启/redeploy 两个 services；
4. 重新打开 Netlify 网站，使用浏览器 Network/Console 验证 preflight 与实际请求。

实现每个 backend 只允许一个 origin 字符串，不支持逗号列表。Netlify draft/preview URLs 与 production URL 不同；当前代码不能同时允许全部 preview origin。生产验收应从最终 production URL 发起。

---

# 10. SQLITE / STORAGE PRODUCTION AUDIT

## RAG

- 本地 SQLite：`data/rag.sqlite3`，核对时约 4.40 MB，含 2 courses、66 documents、1,936 chunks。
- 生产 SQLite：`/var/data/rag.sqlite3`。
- 生产上传文件：`/var/data/uploads`。
- 课程索引、documents、chunks、FTS、conversation/messages 都在该 SQLite。
- 新上传原文件进入 uploads；数据库引用这些文件。
- DB 与 uploads 必须一起保留、备份和恢复。

## Agent

- 本地 `data/agent.sqlite3` 在服务启动时自动创建。
- 生产 Todo：`/var/data/agent.sqlite3`。
- 用户创建、修改、完成、删除的 tasks 都保存在这个独立 DB。
- 刷新浏览器后的持久性取决于该磁盘，而不是 React state。

## Production persistence strategy

```text
RAG: Render Starter Web Service + 1 GB persistent disk mounted /var/data
Agent: separate Render Starter Web Service + separate 1 GB persistent disk mounted /var/data
Scale: one instance per SQLite service
Backup unit: rag.sqlite3 + RAG uploads together; agent.sqlite3 separately
```

Render 默认 filesystem 是 ephemeral；只有 mount path 下的数据跨 restart/redeploy 保留。[Render 官方说明 persistent disk 只适用于付费服务，Free Web Service 不支持 persistent disk](https://render.com/docs/disks)。

```text
WARNING: 如果改用 Render Free tier、删除 disk，或把路径改到 /var/data 之外，课程索引、上传文件和 Todo 会在 restart/redeploy 后丢失。
```

Persistent disk 不能在 build command 中访问，也不能由另一个 service 共享；因此两个 backend 必须有两块独立磁盘。

---

# 11. COURSE DATA IN PRODUCTION

## 当前本地数据

```text
Inventory: 86 files (CS3481 50, GE2324 36)
Imported documents: 66 (CS3481 38, GE2324 28)
Indexed chunks: 1,936
Inventory-only: 20
Local rag.sqlite3: ~4.40 MB
Local upload files: 67 files, ~124.21 MB
```

## GitHub/Render 现实

- `data/rag.sqlite3` 与 `data/uploads/` 被 `.gitignore` 忽略，不随 GitHub deploy。
- Git 只追踪 inventory CSV/JSON、import report 与一份 checksum-bound transcription；这些不是完整课程数据库。
- Render Blueprint 创建空 disk。RAG 首次启动只创建空 schema，不会自动导入 CS3481/GE2324。
- `scripts/import_corpus.py` 读取 inventory 中的本机原始 `fullPath`（当前是本机 D 盘来源）；这些路径在 Render 不存在，因此不能把“在 Render shell 运行 importer”作为 production 初始化步骤。
- 本地课程材料可能受版权/授权限制，不能未经许可推送 GitHub 或公开上传。

## Production initialization steps

在课程材料所有者书面授权后：

1. 先确认 RAG health 为 200，disk 路径已正确挂载。
2. 创建 courses：

```http
POST https://<rag-host>/api/courses
Content-Type: application/json

{"id":"cs3481","name":"CS3481","description":"Authorized CS3481 course materials."}
```

```http
POST https://<rag-host>/api/courses
Content-Type: application/json

{"id":"ge2324","name":"GE2324","description":"Authorized GE2324 course materials."}
```

3. 通过受保护的产品 Documents/QA upload UI，或 `POST /api/courses/{course_id}/documents` multipart API，逐个上传已授权的 `.md/.txt/.pdf/.docx/.pptx`。
4. 对每个 202 response 记录 job ID，并轮询 `GET /api/ingestion-jobs/{job_id}` 直到 succeeded；失败时不要继续假定课程已完成。
5. 扫描版 `assignment_2.pdf` 的本地 sidecar 不会自动随 upload API 应用。应先执行授权 OCR/转录工作流并验证内容，或通过受控停止服务的磁盘迁移复制已验证 DB+uploads。
6. 运行第 15 章的两门课 smoke tests，检查 citation 只来自所选 course。
7. 备份 RAG DB 与 uploads。

推荐 API reingestion，因为可审计且不依赖本机路径。受控迁移本地 DB 是可选高级路径：必须停止 RAG service，成对复制 `rag.sqlite3` 与 `uploads` 到同一磁盘并校验路径/哈希，然后再启动；不要只复制 DB 或只复制 files。

---

# 12. GITHUB REQUIREMENTS

```text
Repository: 尚未创建/连接；必须由用户选择 GitHub owner 和 repository
Branch: main
Latest commit required: 2d14630dd0d3b50aad0c91c1e657a89e0efc5aa1 或包含本 handoff 的更晚提交
Required deployment files already committed: package.json, package-lock.json, netlify.toml, render.yaml, .env.example, .gitignore, backend package/requirements/entry points
```

部署前：

1. 创建 **private repository** 为默认安全选择；不要把私有课程资料放入 public repo。
2. 从当前 repository root 添加 GitHub remote，并 push `main`。
3. 在 GitHub UI 检查最新 commit 与本地一致。
4. 确认 `.env`、`data/rag.sqlite3`、`data/uploads/`、`*.pem`、`*.key` 不在 tracked files。
5. 不要用 `git add -f` 绕过 ignore。
6. 如后续使用 GitHub Actions，只在 GitHub Secrets 中设置 secret，并避免在 logs 输出。

## Secret / gitignore audit result

```text
Tracked files scanned: 121 at audit time
Tracked real .env files: 0
Credential-shaped sk-... values in current tracked content: 0
Credential-shaped historical file hits: 0
.env ignored: YES
data/*.sqlite3 ignored: YES
data/uploads ignored: YES
*.pem / *.key ignored: YES
```

`.env.example` 被有意追踪，其中 `OPENAI_API_KEY=` 为空；扫描器应把空占位符与实际 secret 区分。

---

# 13. EXACT DEPLOYMENT ORDER

## Step 0 — Security, rights, billing, GitHub readiness

- 决定并完成访问控制；若未完成，只做受控 staging。
- 取得课程资料上线授权。
- 准备 Render 两个 Starter services + 两块 1 GB disks 的付费批准。
- 创建 private GitHub repository，push `main`，核对 latest commit。
- 准备 OpenAI key，但不把它发给 ChatGPT。

## Step 1 — Create Render Blueprint

- 在 Render 连接 GitHub repository。
- 从根 `render.yaml` 创建 Blueprint。
- 确认正好出现两个 Web Service 和两块独立 persistent disk。
- 在两个 services 分别填 `OPENAI_API_KEY` 与临时 `WEB_ORIGIN`。
- 为 Agent 显式配置 `AGENT_PORT` 到 Render service port 数字，直到代码修复。

## Step 2 — Deploy and test RAG backend

- 等待 build/start 完成。
- 调 `GET https://<rag-host>/health`。
- 确认日志路径是 `/var/data/rag.sqlite3` 与 `/var/data/uploads`。
- 记录 RAG public base URL。

## Step 3 — Deploy and test Agent backend

- 检查 Node 24.14 与 build output。
- 检查监听端口日志；必要时修正 `AGENT_PORT`。
- 调 `GET https://<agent-host>/health`。
- 记录 Agent public base URL。

## Step 4 — Initialize authorized course data

- 创建 `cs3481` 与 `ge2324`。
- 通过 API/UI 上传已授权资料并等待 ingestion jobs 完成。
- 在此阶段不要依赖前端 production URL，可用受保护的直接 API 工具。

## Step 5 — Configure Netlify production API URLs

- 连接同一 GitHub repository / `main`。
- Base Directory 保持 repository root/blank。
- 设置 `VITE_RAG_API_URL=https://<rag-host>`。
- 设置 `VITE_AGENT_API_URL=https://<agent-host>`。

## Step 6 — Deploy Netlify production site

- 让 Netlify 读取根 `netlify.toml`。
- 检查 build command 和 publish directory。
- 完成 production deploy，记录最终 `https://<site>.netlify.app` URL。

## Step 7 — Close the CORS loop

- 把两个 Render services 的 `WEB_ORIGIN` 更新为 Netlify 精确 origin，不加尾部 `/`。
- 重启/redeploy两个 backend。
- 从 Netlify production site 实测，不从 localhost/draft URL 测。

## Step 8 — Full production smoke and persistence test

- 执行第 15 章全部测试。
- 分别 redeploy backend，但不删除 disk；确认 courses/tasks 仍存在。
- 查看 logs、browser console、Network 与 OpenAI usage。

## Step 9 — Release decision

- 只有访问控制、资料授权、health、CORS、两门课引用、Agent tool calling、持久化、secret audit 全部通过，才标记 production verified。
- 任一数据完整性、安全或模型费用异常时，按第 19 章 rollback 条件停止开放。

---

# 14. EXACT HEALTH CHECKS

## RAG

```http
GET https://<rag-host>/health
Expected status: 200
Expected JSON: {"status":"ok","service":"rag-api"}
```

## Agent

```http
GET https://<agent-host>/health
Expected status: 200
Expected JSON: {"status":"ok","service":"agent-api"}
```

Health endpoint 只证明进程可响应，不证明 OpenAI key、课程数据、CORS、tool calling 或 persistence 可用。必须继续执行 smoke tests。

---

# 15. PRODUCTION SMOKE TEST

## Test 1 — Homepage and SPA

1. 打开 Netlify production URL。
2. 依次打开 `/qa/cs3481`、`/tasks`、`/documents`、`/about`。
3. 在每个 route 直接刷新。

通过：HTTPS 正常、无 404、无 blank page、Console 无错误。

## Test 2 — CS3481 Course QA

问题：

```text
How does DBSCAN identify a core point?
```

通过：POST 请求成功；回答以 SSE 增量出现；文本包含 DBSCAN 相关解释；citation 可展开；citation course 为 CS3481，并指向真实文件/locator。

## Test 3 — GE2324 Course QA

问题：

```text
What does Assignment 2 ask students to do with K-means and colors?
```

通过：回答成功；首要 source 应包含 `assignment_2.pdf`（前提是已按授权 OCR/迁移正确初始化）；不出现 CS3481 source。

## Test 4 — Study Agent Function Calling

为避免语言能力变量干扰首次基础设施验收，先使用已在 deterministic E2E 验证过的英文格式：

```text
Add a high priority Review CS3481 K-means task due 2026-08-20
```

通过：Agent response 表示 action completed；TaskBoard 出现正确 title、high priority 和日期。随后可再测试中文：

```text
明天下午复习 CS3481 K-means
```

中文结果属于 live model 行为，当前本地 deterministic tests 没有证明其稳定性；若失败，先检查模型/提示和日志，不要误判为数据库故障。

## Test 5 — Task persistence

1. 创建唯一标题任务。
2. 刷新 Netlify 页面，确认任务仍在。
3. 在 Render redeploy Agent service，**不删除 disk**。
4. 再刷新并确认任务仍在。

失败优先检查 `AGENT_DATABASE_PATH=/var/data/agent.sqlite3` 与 agent-data disk。

## Test 6 — Update and complete task

- 把 due date 改为新日期；priority 改为 medium；标记 completed。
- 刷新页面，确认新值和 completed 分组保持。

## Test 7 — Upload persistence

- 上传一个小型、已授权 `.txt` 文件，等待 job succeeded。
- 用相关问题取得 citation。
- redeploy RAG service（不删 disk），确认 document/citation 仍存在。

## Test 8 — Security/visibility

- 在浏览器 build assets、Network、Console 与 error responses 中搜索 key 前缀；应为 0。
- 未完成 authentication/access control 时，不允许匿名第三方参与 smoke test。

---

# 16. COMMON DEPLOYMENT FAILURE MAP

## Netlify build failed

```text
Symptom: 找不到 workspace/package-lock，或 npm build command 失败
Likely cause: Base Directory 错设为 apps/web；Node 版本不是 24.14；GitHub 未包含 lockfile
Where to check: Netlify build settings, netlify.toml, root package.json/package-lock.json, build log
```

## Wrong publish directory

```text
Symptom: deploy 成功但网站 404/空目录
Likely cause: Publish 不是 apps/web/dist，或 Base Directory 改变导致相对路径重复
Where to check: netlify.toml and Netlify Deploy file browser
```

## Missing frontend env variable

```text
Symptom: 网站请求 localhost:8000/8001
Likely cause: VITE_RAG_API_URL 或 VITE_AGENT_API_URL 未在 build scope 设置，或设置后未 rebuild
Where to check: Netlify environment, latest deploy timestamp, browser Network request URL
```

## SPA refresh 404

```text
Symptom: 首页可开，直接刷新 /tasks 或 /qa/cs3481 404
Likely cause: 根 netlify.toml 未被读取，SPA rewrite 缺失
Where to check: repository root selection and netlify.toml redirect
```

## Render RAG build failure

```text
Symptom: requirements.txt 找不到或 app.main import 失败
Likely cause: RAG Root Directory 不是 services/rag-api，或 Blueprint 未从根加载
Where to check: render.yaml, service Root Directory, build/start logs
```

## Render Agent build/start failure

```text
Symptom: workspace 找不到、dist/src/server.js 不存在、Node SQLite 不可用
Likely cause: Agent 错设 rootDir，Node 不是 24.14，或 build command 未成功
Where to check: render.yaml, root package files, Agent build log, NODE_VERSION
```

## Wrong Agent port

```text
Symptom: process log 显示监听 8001，但 Render health check 失败/无法路由
Likely cause: source reads AGENT_PORT, not PORT
Where to check: services/agent-api/src/config.ts, Render PORT, AGENT_PORT, startup log
Fix for current commit: set AGENT_PORT to the Render service port number; then redeploy and test /health
```

## CORS blocked

```text
Symptom: curl health 成功，但浏览器报 CORS/preflight；Network 无可读 response
Likely cause: WEB_ORIGIN 不等于最终 Netlify origin，带尾斜杠，或仍是 localhost/draft URL
Where to check: both Render WEB_ORIGIN values, exact browser location.origin, backend CORS files
```

## OpenAI key missing or unusable

```text
Symptom: health 200，但 QA/Agent 返回 OPENAI_NOT_CONFIGURED、MODEL_ERROR 或 502
Likely cause: key 未分别设置、模型无权限、账单/限额/网络问题
Where to check: each Render secret presence (never print value), safe logs, OpenAI usage/billing dashboard
```

## Backend URL incorrect

```text
Symptom: DNS/network error、404、Mixed Content 或请求错误 service
Likely cause: VITE URL 拼错、含 path/trailing slash、用了 internal URL 或 http
Where to check: Netlify VITE_* and browser Network
```

## SQLite path/persistence failure

```text
Symptom: redeploy 后 courses/tasks 消失，或 SQLite readonly/unable to open
Likely cause: 没有 paid disk、路径不在 /var/data、disk 没挂载、权限/容量问题
Where to check: render.yaml disk section, Render Disks page, *_DATABASE_PATH, logs, disk usage
```

## Missing course data

```text
Symptom: /api/courses 为空、QA 无命中
Likely cause: Blueprint 只创建空 schema；Git 不含本地 DB/uploads；尚未执行 production ingestion
Where to check: Section 11 initialization, RAG course/document APIs, ingestion jobs
```

## Ingestion remains pending/failed

```text
Symptom: upload 202，但 document 不 ready
Likely cause: OpenAI embedding key/model/network、unsupported/scanned file、process restart during FastAPI BackgroundTask
Where to check: ingestion job endpoint and RAG logs
```

## Data visible to the wrong user

```text
Symptom: 不同访问者看到同一 tasks/courses 或可互相修改
Likely cause: 当前系统没有 identity/user ownership，这是已知设计边界
Where to check: Operator stop gate and API source
Fix: do not publicly expose until access control is implemented/configured
```

---

# 17. FILES THE FUTURE CHATGPT MAY NEED

只有本 handoff 无法定位具体部署错误时，才向用户索取最小文件包；不要要求整个 repository。

| 问题 | 最小文件 |
|---|---|
| Netlify build/publish/SPA | `netlify.toml`, root `package.json`, `apps/web/package.json` |
| Frontend 请求错误 host | `apps/web/src/services/ragApi.ts`, `apps/web/src/services/agentApi.ts`, Netlify env **变量名与遮蔽值截图** |
| Render Blueprint | `render.yaml` |
| RAG build/start | `services/rag-api/requirements.txt`, `services/rag-api/app/main.py`, `services/rag-api/app/config.py` |
| Agent build/start/port | `services/agent-api/package.json`, `services/agent-api/src/server.ts`, `services/agent-api/src/config.ts` |
| CORS | `services/rag-api/app/main.py`, `services/agent-api/src/app.ts`, 两服务 `WEB_ORIGIN` 的非敏感值 |
| Storage | `render.yaml`, 两个 DB config 文件、Render disk settings screenshot |
| Course initialization | `scripts/import_corpus.py`, `services/rag-api/app/corpus_import.py`, `docs/DEPLOYMENT.md` |
| 已知验证事实 | `docs/VERIFICATION_REPORT.md`, `PROJECT_ATLAS_FOR_CHATGPT.md` |

日志也应最小化提供：只贴相关错误附近 20～50 行，先遮蔽 authorization headers、cookies、key、token、email 和私有文件内容。

---

# 18. MANUAL ACTIONS

以下动作必须由项目所有者本人完成，ChatGPT 只能指导：

- 登录 GitHub，创建/选择 private repository，授权 Netlify/Render 访问。
- 决定 repository owner/name，并 push `main`。
- 登录 Render，确认两个 Starter services 与两块 persistent disks 的费用。
- 登录 Netlify，创建 site 并确认 production domain。
- 在两个 Render services 的 secret UI 分别输入 OpenAI key。
- 不把 key 发给 ChatGPT；ChatGPT 只可询问“是否已设置”，不可索取值。
- 决定、配置并验证终端用户 authentication/access control。
- 确认课程资料的版权/所有者授权和公开范围。
- 初始化 production courses/documents。
- 将最终 Netlify origin 填入两个 `WEB_ORIGIN`。
- 对 Agent 显式设置/验证端口映射。
- 执行真实 production smoke、检查 logs/usage、确认 rollback readiness。
- 为两块磁盘建立备份/恢复操作记录。

---

# 19. FINAL DEPLOYMENT CHECKLIST

## Git and secrets

- [ ] Private GitHub repository 已创建并连接
- [ ] `main` 包含本 handoff 所述 latest commit 或更晚已审核 commit
- [ ] `.env`、SQLite、uploads、key/token 未被追踪
- [ ] Netlify/Render build 都来自预期 Git commit

## Security and authorization

- [ ] 课程资料公开/上传授权已确认
- [ ] 终端用户 authentication/access control 已配置并测试
- [ ] 未授权用户不能访问 upload、task mutation 或 model-backed endpoints
- [ ] OpenAI key 只存在于两个 Render secret stores

## Render

- [ ] 正好两个 Web Service online
- [ ] RAG `/health` 200 且 response 正确
- [ ] Agent `/health` 200 且 response 正确
- [ ] Agent `AGENT_PORT`/Render port 已显式验证
- [ ] 两服务环境变量完整
- [ ] 两个 Starter persistent disks 已挂载到各自 `/var/data`
- [ ] RAG 和 Agent 均为单实例

## Course data

- [ ] `cs3481` 与 `ge2324` 已创建
- [ ] 授权文件 ingestion jobs 全部 succeeded
- [ ] scanned assignment 采用已授权且已验证的 OCR/迁移方案
- [ ] RAG DB 与 uploads 已一起备份

## Netlify and CORS

- [ ] Netlify build passed
- [ ] Publish directory 是 `apps/web/dist`
- [ ] `VITE_RAG_API_URL`、`VITE_AGENT_API_URL` 是正确 HTTPS public origins
- [ ] Netlify production site opens
- [ ] SPA routes direct refresh 不 404
- [ ] 两个 Render `WEB_ORIGIN` 精确等于 Netlify production origin
- [ ] Browser 无 CORS/console errors

## Product acceptance

- [ ] CS3481 QA works
- [ ] GE2324 QA works
- [ ] Streaming works
- [ ] Citations 正确且 course-isolated
- [ ] Agent `createTask` works
- [ ] Agent `updateTask` works
- [ ] Complete/reopen works
- [ ] 浏览器刷新后 Task persistence works
- [ ] Backend redeploy 后 course/task persistence works
- [ ] Authorized upload + ingestion works
- [ ] No secrets exposed in bundle/log/error/repository

## Rollback readiness

- [ ] 已记录前一 Netlify deploy
- [ ] 已记录前一 backend Git commit/deploy
- [ ] 两个 SQLite 与 RAG uploads 有可用备份/快照
- [ ] 操作者知道不要在 rollback 时删除 disks

只有全部必要 checkbox 通过，才能把 `Production fully verified` 改成 `YES`。

---

# 20. FINAL CONSISTENCY CHECK

## Sources checked

- `README.md`
- `docs/DEPLOYMENT.md`
- `docs/VERIFICATION_REPORT.md`
- `PROJECT_ATLAS_FOR_CHATGPT.md`
- `netlify.toml`
- `render.yaml`
- root/Web/Agent `package.json` 与 lockfile
- RAG requirements/pyproject、entry point、settings、routes
- Agent server/config/app、database runtime
- Web API clients
- `.env.example`、`.gitignore`、Git tracked files/history
- Local RAG database counts、uploads size、inventory/import report
- Playwright production-journey tests
- Render/Netlify 官方部署合同（用于易变的平台事实）

## DOCUMENTATION DISCREPANCIES

1. **README 的 “committed database” 不准确**：本地 `data/rag.sqlite3` 存在但被 `.gitignore` 忽略，不随 GitHub clone/deploy。生产 disk 初始为空。
2. **README import command 无效**：README 对 `scripts/import_corpus.py` 使用 `--reset`，最终 CLI 没有该参数；只有 `--mode`、`--inventory`、`--report`。
3. **Importer 不能直接在 Render 重建本地 corpus**：inventory `fullPath` 指向本机原始磁盘，Render 无这些 source files。生产应使用授权 API reingestion 或受控 DB+uploads 迁移。
4. **Agent port 合同不完整**：Render 推荐绑定 `PORT`，但最终 Agent 只读取 `AGENT_PORT`，Blueprint 未桥接。部署时必须显式设置/验证。
5. **“Blueprint ready” 不等于安全 production ready**：当前无 identity/user ownership；公网匿名暴露会共享并开放课程、tasks、uploads 和模型费用。
6. **本地 deterministic verification 不等于 live OpenAI verified**：当前网络探针在 HTTP 前失败；部署后必须实际 smoke。
7. **本地 assignment transcription 不会自动作用于普通 API upload**：扫描 PDF 的 production OCR/迁移需单独处理并授权。
8. **Render Free 不满足当前 persistence 方案**：Blueprint 使用 Starter + disks；改用 Free 会失去 persistent disk 能力。

## Final fact summary

```text
GitHub source: NOT YET CREATED/PUSHED
Deploy branch: main
Frontend: one Netlify Vite static site
Backends: two independent Render Web Services
Persistent stores: two independent /var/data disks
Production course data: NOT seeded by Git/Blueprint
Production authentication: NOT IMPLEMENTED in app
Production OpenAI: NOT VERIFIED
Production deployment: NOT STARTED
```

未来 ChatGPT 应按第 13 章逐步指导，并在每个 paid/security/data-rights/secret 动作前让用户本人操作确认。不得自行声称部署完成，也不得要求用户发送 OpenAI key。
