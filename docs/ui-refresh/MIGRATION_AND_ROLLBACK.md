# MIGRATION AND ROLLBACK — 新 UI 与新增数据

本文档描述本次接线的数据影响、迁移步骤、恢复单元和回滚边界。
**所有生产动作都必须先取得授权，本文档不构成执行许可。**

---

## 1. 数据影响总览

| 存储 | 变化 | 说明 |
|---|---|---|
| `data/rag.sqlite3`（RAG Schema 22） | **一个真实迁移** | `022_shell_delivery_evidence.sql`：证据表按 12 步模式重建，`validation_status` 增加 `REVIEWED`（经评审的新壳自由文本交付，plan 列 NULL + content_hash 64 位 hex）；作用域触发器同步重写；`teaching_units(journey_id, operation_id)` 唯一索引。列**未**增删改，`VALIDATED`/`LEGACY_PRESERVED` 契约不变 |
| `data/agent.sqlite3`（Agent Schema 1） | **Schema 不变** | 只加了启动守卫：`NODE_ENV=production` 时 `AUTH_TEST_USER_ID` 与 `AGENT_PROVIDER_MODE=deterministic` 直接退出 |
| `data/uploads/` | **不变** | 原上传目录与路径规则未改；**文件字节**的唯一存放处 |
| `<CMUI_DATA_DIR>/ui.sqlite3` | **新增**（Schema 5） | 承载新 UI 的 profile、收藏、评论/点赞/通知、私信、会话/消息/生成、布局、Bridge、限额、Agent receipt、`cmui_run_v3`、`cmui_delivery_submissions` 覆盖回执。`cmui_runs` 带租约列；`cmui_bridges` 带 V3 追溯列（`problem_revision_id`/`solution_id`/`step_ids_json`/`teach_run`/`journey_id`/`spec_version`/`delivery_unit_id`）。`cmui_courses`/`cmui_files`/`cmui_chunks`/`cmui_nodes`/`cmui_learning`/`cmui_tasks` 是 standalone 镜像表，integrated 模式不写入 |
| `<CMUI_DATA_DIR>/uploads/` | **新增** | 新 UI 会话中上传的**题目图片附件字节**（元数据仍在 RAG 库）；课程文件字节仍在 `data/uploads/` |

**没有任何原 V3 表被复制、改名或删除。** 新课程、新文件、新知识节点全部只映射不复制：
`course.list`/`course.get` 直接读 `courses`，文件直接读 `documents ⋈ document_versions`，
检索直接走 `chunks`/`chunks_fts`，知识树直接读 `knowledge_tree_versions` /
`knowledge_tree_memberships` / `knowledge_nodes`。

## 2. 数据归属表（P0-8，逐项核对后的权威事实）

“权威库”是 integrated 生产模式下该数据的唯一写入来源；`cmui_*` 镜像表只在
standalone 模式（开发/离线演示）被读写，integrated 模式一律走 V3 域适配器。
跨库引用都是**字符串 id + 失效处理（404/空列表）**，不存在跨库外键或跨库原子事务。

| 操作 | 权威数据库/文件目录 | 新增引用（谁引用谁） | 备份要求 | 回滚影响 |
|---|---|---|---|---|
| 课程（列表/详情/加入） | `rag.sqlite3.courses` | UI 库不复制课程，按 id 实时读取 | 随 RAG 库 | 课程数据不受新壳回滚影响 |
| 私人资料 | **元数据**：`rag.sqlite3.documents` / `document_versions` / `chunks`；**字节**：`data/uploads/` | UI 附件消息只存文件 id | RAG 库 + 上传包 | 上传原件与解析结果都在原库，新壳回滚不丢文件 |
| 任务（日历计划） | `agent.sqlite3`（经 Node Agent REST） | UI 库 `cmui_agent_receipts` 只存请求回执；`cmui_tasks` 是 standalone 镜像，integrated 不写 | Agent 库 | 关闭新壳不影响任务；恢复时三库同单元 |
| 评论/点赞/通知 | `ui.sqlite3.cmui_comments` / `cmui_likes` / `cmui_notifications` | 引用课程/文件字符串 id | UI 库 | **只回滚代码不回滚 UI 库**；回滚 UI 库即丢新评论 |
| 私信 | `ui.sqlite3.cmui_threads` / `cmui_direct_messages` | 用户 id | UI 库 | 同上，只存在于 UI 库 |
| 新壳对话/消息/生成 | `ui.sqlite3.cmui_conversations` / `cmui_messages` / `cmui_runs` / `cmui_run_events` | `cmui_run_v3(run → workspace/journey/node/spec)`；`cmui_delivery_submissions(run → unit)` | UI 库 | 同上；`cmui_runs.usage` 保留真实用量 |
| 旧版问答记录 | `rag.sqlite3.conversations` / `messages`（只读投影） | 无复制，`legacy.conversations` 直接读原表 | RAG 库 | 原样保留，新壳只读 |
| 新壳题目与解法（V3 账本映射） | `rag.sqlite3.learning_problems` / `problem_revisions`（不可变、VALIDATED+content_hash）/ `learning_solutions` / `learning_steps` | UI `cmui_bridges.problem_revision_id`/`solution_id`/`step_ids_json` 回指；稳定 id 由问题 run id 派生（`shell-<run>`），重放幂等 | RAG 库 | 与教学事实同库备份；UI 桥接表只是导航快照 |
| Bridge（返回原步骤 + 教学追溯） | UI `cmui_bridges` 承担导航；V3 承担教学事实（journey/unit/evidence 经 `teach_run`/`delivery_unit_id` 链接） | `problem_message`→`problem_revision_id`→`solution_id`→`step_ids`→`teach_run`→`journey`→`delivery_unit_id`→`REVIEWED` 证据 | UI 库 + RAG 库（同单元） | 关闭新壳即导航不可达；V3 侧记录原样保留 |
| 教学覆盖（REQUIRED item 覆盖、LEARNING/LEARNED） | `rag.sqlite3.teaching_delivery_evidence` + `learning_coverage` + `learning_journeys` | 新壳教学完成后经评审器提交 `REVIEWED` 证据（`SHELL_COVERAGE_REVIEW_V1`）；未确认不写证据 | RAG 库 | 覆盖事实与新旧壳无关；回滚 RAG 库才会丢真实覆盖 |
| 测评（场次/提交/评分） | `rag.sqlite3.assessment_sessions` / `grade_snapshots`（V3 AssessmentService 权威） | UI 不复制结果，实时委托 | RAG 库 | 测评结果独立于学习进度，同 RAG 库备份单元 |

恢复后的校验不能只看 SQLite 完整性：跨库引用无外键约束，必须抽查
**孤立引用与可读性**（课程/文件/节点 id 是否还能命中、旧对话可读、任务回执
对应的任务存在、桥接的 problem_revision/unit/证据还能解析），见 §5 末尾的校验清单。

## 3. 为什么 `ui.sqlite3` 可以安全新增

`app/cm_update/db.py:Database.initialize()`：

```python
tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
if tables.intersection({'courses','chunks','tasks','schema_migrations'}):
    raise ValueError('Refusing to initialize UI database over an existing CourseMate domain database')
if 'cmui_meta' in tables:
    current = c.execute("SELECT value FROM cmui_meta WHERE key='schema_version'").fetchone()
    if current and int(current[0]) > SCHEMA_VERSION:   # SCHEMA_VERSION = 5
        raise ValueError('Newer UI database schema detected; do not downgrade')
```

Schema 升级全部幂等（缺列才 `ALTER`：租约列、桥接追溯列；新表用
`CREATE TABLE IF NOT EXISTS`），旧库首次以新代码启动即自动升级，无需手工迁移。

因此：

* 把 `CMUI_DATA_DIR` 误指向 `data/`（含 `rag.sqlite3`）**不会**破坏原库——只会报错退出；
* 如果这个库将来被更高版本初始化过，旧版代码**拒绝降级**，不会静默写坏数据。

## 4. 首次启用 A/B/C 与备份（区分两个进程的 `CMUI_DATA_DIR`）

**关键顺序：先把备份做完，再让 UI 库存在。** `backup_v2.py` 在**备份进程**设置了
`CMUI_DATA_DIR` 时强制要求 `ui.sqlite3` 已存在（防止产出缺库的假备份）。
注意区分两个使用方：

* **应用进程（rag-api）**：由 systemd 环境注入 `CMUI_DATA_DIR`，A 阶段必须
  **不设置**（扩展未启用时它也不读这个变量）；
* **备份进程（`ops/backup_v2.py`）**：独立 shell 里的 `export`，只影响那一次
  备份命令，与 systemd 无关。

因此 A 阶段在**备份 shell**里 `unset CMUI_DATA_DIR` 即可；B 阶段应用进程首次
启动自动建库；C 阶段备份 shell 再 `export` 它——空目录、建库、纳入备份分别
发生在哪一步是明确的，没有循环依赖。

**A. UI 库尚不存在时，对现有两库一上传做一致备份**
备份进程里**不要**设置 `CMUI_DATA_DIR`：

```bash
export RAG_DATABASE_PATH=/srv/coursemate/data/rag.sqlite3
export AGENT_DATABASE_PATH=/srv/coursemate/data/agent.sqlite3
export RAG_UPLOAD_DIR=/srv/coursemate/data/uploads
unset CMUI_DATA_DIR                  # A 步骤必须未定义，缺库检查不会触发
export BACKUP_ROOT=/home/admin/coursemate-v3-preflight-backups
python3 ops/backup_v2.py             # 两库 + uploads.tar.gz，通过
```

**B. 在独立路径初始化 UI 库，不调用任何集成/生产禁止的 seed**
后端 release 已部署但 `UI_EXTENSION_ENABLED=false` 时，挂载不执行、库不会被触碰。
开启开关（应用进程）后，首次请求挂载时 `Database.initialize()` 以
`CREATE TABLE IF NOT EXISTS` 幂等建表（Schema 5）。**不要**运行
`scripts/seed_*.py` 或任何集成/生产禁止的 seed——`scripts/seed_*` 是
test-only 夹具，且会拒绝 `work/` 以外的目标。

```bash
mkdir -p /srv/coursemate/data/ui-extension      # 空目录先建好（应用进程的变量指向它）
# 应用进程首次启动后确认：
ls /srv/coursemate/data/ui-extension/ui.sqlite3     # 建表完成
```

**C. 启用后，三个库和两组上传纳入新的恢复单元**
现在备份进程才 `export CMUI_DATA_DIR`，之后的每次备份自动包含 `ui.sqlite3`
与 `ui-uploads.tar.gz`，并写入 `manifest.json` 与 `SHA256SUMS`：

```bash
export CMUI_DATA_DIR=/srv/coursemate/data/ui-extension   # 现在合法：ui.sqlite3 已存在
python3 ops/backup_v2.py                                  # 三库 + 两组上传，通过
```

若 `CMUI_DATA_DIR` 已设置但其中没有 `ui.sqlite3`，备份**直接失败**，不会产出一个
看起来完整、实则缺库的备份——这是 C 及之后的保护，不是 A 的障碍。

### 跨库一致性限制（必须承认）

三个 SQLite `backup` 调用之间**没有分布式事务**。一个新 UI 部署下：

* 备份 `rag.sqlite3` 与 `agent.sqlite3` 之间若有写入，快照不是同一瞬间；
* 备份 `ui.sqlite3` 与 RAG 库之间同理。

因此生产备份必须在**维护窗口**内进行，或使用项目既有的协调方案。
`backup_v2.py` 的注释已把这一点写明；本次**没有**实现跨库原子快照。
New UI 与 RAG 之间没有跨库外键（新 UI 只存课程/文件/节点的**字符串 id**，不建 FK），
所以恢复后即使某个 id 已不存在，表现是 404/空列表，而不是数据损坏。

## 5. 部署前：副本恢复演练

```bash
export RESTORE_SOURCE=/home/admin/coursemate-v3-preflight-backups/coursemate-v2-<stamp>
export RESTORE_TARGET=/home/admin/coursemate-v3-restores/preflight-<stamp>
python3 ops/restore_v2.py
```

`restore_v2.py` 在**发布目标目录之前**依次校验：

1. `SHA256SUMS` 覆盖 `manifest.json` 声明的全部 artifact（多一项、少一项都拒绝）；
2. `manifest.json` 只允许声明已知 artifact 名（伪造/未知名字直接拒绝）；
3. 每个数据 artifact 的 sha256 与校验和一致；
4. `ui.sqlite3`（若声明）`PRAGMA integrity_check == 'ok'` 且 `foreign_key_check` 为空；
5. `uploads.tar.gz` / `ui-uploads.tar.gz` 的成员数与总字节数与 manifest 完全一致，
   且拒绝 `\\`、绝对路径、`..`、重复路径、非常规成员。

任一步失败只留下一个隐藏的 `.partial` 目录，不会出现「看起来完整」的半成品。

恢复后的目录布局：

```
<target>/rag.sqlite3
<target>/agent.sqlite3
<target>/ui.sqlite3           # 仅当备份声明了扩展
<target>/uploads/…
<target>/ui-uploads/…         # 仅当备份声明了扩展
```

**恢复后还必须做跨库引用抽查**（跨库无外键 ≠ 数据关联正确）：

1. 恢复目录重新映射：`RAG_DATABASE_PATH`/`AGENT_DATABASE_PATH`/`RAG_UPLOAD_DIR`/
   `CMUI_DATA_DIR` 全部指向恢复目录后，`/health` 与 `/ui-extension/health` 均 200；
2. 课程/文件/节点引用：新壳课程页、文件列表、知识树可打开，无整页 500；
3. 旧对话可读性：`/ui-extension/api/ui/v1/courses/<id>/legacy-conversations` 返回且
   正文可读；
4. 任务回执：日历任务列表可加载（Agent 库与 UI 回执同单元恢复）；
5. 孤引用表现：任何失效 id 表现为 404/空列表，不崩溃。

## 6. 部署顺序（后端兼容新增，前端独立发布）

1. **先备份**（§4-A 顺序），并在副本上完成恢复演练（§5）。
2. **再发后端**：部署新 release 但保持 `UI_EXTENSION_ENABLED=false`。
   此时**不会挂载扩展，但 RAG 022 迁移仍会执行**（开关只控制扩展挂载，不控制
   `Database.initialize` 的 V3 迁移；副本测试已证明）——数据库不是零影响，
   行为也**不等同旧版**。先用 `https://rag.qqttai.com/health` 确认无回归。
3. **再开开关**：设置 `UI_EXTENSION_ENABLED=true` 与 `CMUI_DATA_DIR`（§4-B），
   重启 rag-api；首次挂载自动幂等建库（不运行任何 seed）。
   `UI_TASK_AGENT_URL` 指向既有 agent 公网 origin（`https://agent.qqttai.com`）。
4. **最后发前端**：Netlify 用本仓库真实构建（`npm run build --workspace @coursemate/web`），
   确认 `/` 与 `/app` 都返回 200 且都是新壳文档（`/app` 兼容别名保留），
   旧深链（`/qa` `/learn` `/courses` 等）仍返回旧文档。
   发布前记录**现场**的上一个可用 deploy id（见 §7-C；早期报告里的 id 只是历史快照）。

### 必需的环境变量（后端）

| 变量 | 值 | 说明 |
|---|---|---|
| `UI_EXTENSION_ENABLED` | `true` | 唯一的挂载开关，默认 `false` |
| `CMUI_DATA_DIR` | 例如 `/srv/coursemate/data/ui-extension` | 新库与附件根目录，**不能指向 `data/` 本身** |
| `CMUI_ENV` | `production` | `validate()` 用它启用生产门 |
| `CMUI_AUTH_MODE` | `injected` | 与宿主 Clerk 共用身份 |
| `CMUI_INTEGRATION_MODE` | `integrated` | 由挂载器强制 |
| `UI_TASK_AGENT_URL` | `https://agent.qqttai.com` | Node 任务 Agent 的 origin |
| `CMUI_PROVIDER_MODE` | `qwen` 或 `disabled`（`test` 仅限本地/浏览器验收，生产被 `validate()` 拒绝） | 未获付费授权时保持 `disabled` |
| `CMUI_ALLOW_BILLABLE` | `false`（未授权时） | `true` 才会真正发出千问请求 |
| `VITE_UI_API_BASE` | `https://rag.qqttai.com/ui-extension/api/ui/v1`（Netlify 构建期） | 前端 API 前缀 |
| `VITE_CLERK_PUBLISHABLE_KEY` | 真实 publishable key（**Netlify 构建期必填**） | 构建期变量：不给 key 时壳的 Clerk 分支被 tree-shake，产物只渲染"认证未配置"（fail-closed，不破坏数据但不可登录）。假 key 只用于本地产物扫描验证 |

千问凭据**不需要新增**：`mount.py` 直接复用 `V3_MODEL_API_KEY` / `V3_MODEL_BASE_URL`，
所以站点仍然只有一份模型密钥。

## 7. 回滚（两类流程严格分开）

普通撤回与数据灾难恢复是**两种不同流程**：A 只撤回代码/路由/配置并保留全部数据；
B 是确需覆盖数据时的灾难恢复，需要独立审批与损失窗口说明。

### 前置

* 发布前记录：当前后端 release SHA、**现场读取的**上一个可用 Netlify deploy id。
  早期报告里的 deploy id（如 `6a83d079cd1da1000859b96c`）只是历史快照，
  发布前的生产现场可能已变化，**不能盲用**——必须从 Netlify 控制台取发布前记录。
* 确认 `UI_EXTENSION_ENABLED=true` 之前的那次 release 仍在服务器上（本次不需要 DNS 变更）。
* **核查目标旧代码对当前 Schema 的兼容性**（A 流程必做）：本次 RAG 库升到 Schema 22
  （022 迁移：证据表重建 + `REVIEWED` 状态 + `teaching_units(journey_id,operation_id)`
  唯一索引），UI 库升到 Schema 5（回执表 + 桥接追溯列）。旧代码打不开更高版本库
  （RAG/UI 两侧都有 downgrade 守卫），因此回退到旧 release 时：旧 UI 扩展代码会
  拒绝打开 Schema 5 的 UI 库（报"Newer UI database schema detected"而不是写坏），
  旧 V3 代码读 Schema 22 的 RAG 库不受影响（022 是加性重建，列未变）。
  需要在旧代码上继续用 UI 库时，**保留当前 UI 库不动**，等到重新启用新 release
  再使用，或按 B 流程单独决策。

### A. 代码 / 路由 / 配置撤回（默认路径，保留全部新增数据）

1. **关后端新入口**：`UI_EXTENSION_ENABLED=false` + 重启 rag-api。新 UI API 立即
   404，`ui.sqlite3` 与 `ui-uploads/` 保持不动，数据照旧。
2. **回滚后端 release**：停服务 → 移除新 release 的 drop-in → 恢复受保护环境副本
   （`/etc/coursemate/env-backups/…`，只恢复**配置**，不恢复数据库）→
   `systemctl daemon-reload` → 启动上一版 unit → 健康检查。
3. **回滚前端**（必须单独做，第 1 步不会自动带上它）：重新发布**发布前现场记录**
   的上一个可用 Netlify deploy；验证 `/` 与 `/qa/...` 都回到旧站文档。
4. **核查**：目标旧代码对当前库的兼容性见前置；数据一律保留，不还原任何库。

**A 不做什么**：不删除新 UI 的评论、私信、通知、对话、回执、覆盖记录；
不还原 `rag.sqlite3` / `agent.sqlite3` / `ui.sqlite3` / 两组上传。

### B. 数据灾难恢复（独立审批，只确需时执行）

触发条件：数据损坏/误删/审计要求回退数据，**不是**普通功能撤回。执行前：

1. **独立审批**：说明要恢复的数据范围、目标时间点与预期损失窗口；
2. **先快照当前库**：对**当前**（可能含最新写入的）三库与两组上传做一次完整备份，
   恢复后任何"切换后新增数据"都不被静默丢弃；
3. **明确损失窗口**：恢复到时间点 T 后，T 之后的评论/私信/任务/教学覆盖/测评
   （RAG 库与 UI 库）与上传字节都会回到 T 状态——**"Schema 没变"不等于恢复旧数据
   没有损失**；
4. **成套恢复 + 跨库抽查**：用 §5 的恢复单元整套还原（三库 + 两组上传必须来自
   **同一次**备份），恢复后执行 §5 的跨库引用抽查（课程/文件/节点引用、旧对话
   可读性、任务回执、孤引用表现为 404/空列表）；
5. 恢复后再按需走 A 流程撤回代码。

### 不可逆点

* 一旦在新 UI 中产生了真实用户数据（评论、私信、任务回执、上传、对话、覆盖回执），
  **这些数据只存在于 `ui.sqlite3`**。A 流程绝不触碰它们；B 流程恢复旧副本会
  丢掉 T 之后的新增数据（必须先快照并在审批里写明损失窗口）。
* **同理，不能因为 RAG Schema 22 是加性重建（列未变）就随意恢复旧 RAG 库**：V3 侧的新课程、新上传、
  真实教学覆盖（含 REVIEWED 证据）与测评成绩同样存在于当前 RAG 库。
* 千问两阶段的真实调用一旦发出即已计费，无法回滚；`cmui_runs.usage` 会保留真实用量。

## 8. 生产开关、预算与单 worker 约束

### 预算开关

* `CMUI_ALLOW_BILLABLE=false` 时 `QwenProvider.stream()` 在发出请求**之前**
  就抛 `BILLING_NOT_AUTHORIZED`，`self.calls` 保持为空，**零出网请求**。
* 生成 run 在 `provider_mode='qwen' and not allow_billable` 时返回 402。
* 模型调用受 `v3_daily_model_calls_per_user` / `_per_user_course` 与
  `cmui_limits` 每分钟桶双重约束；本次**没有**放宽任何限额。
* `provider_mode='test'`（本地/浏览器验收用的确定性 TestProvider）在
  `environment='production'` 下被 `validate()` 直接拒绝，生产只能
  `qwen` 或 `disabled`。

### 单 worker 约束：已实现的实际防护（P1-7，不是文档提醒）

交付包的生成 runner 是**单进程**内存任务表（`app.state.jobs`），且 V3 侧不存在
durable worker / 队列。首发维持**单实例/单 worker** 是明确约束，而不是已支持
多 worker。本轮已把「单 worker」从口头约定变成可执行的防护（`dd710b3`，
UI Schema 2 → 3）：

| 防护 | 实现 | 验证 |
|---|---|---|
| 每次启动的唯一 worker 身份 | `worker_id=uid('worker-')` 写入每个 run 的 `lease_worker` | `tests/test_ui_extension_single_worker.py` |
| 启动清理只回收**有充分证据失去拥有者**的 run | `reclaim_orphaned_runs()`：仅 `lease_heartbeat` 缺失或超过 `CMUI_RUN_LEASE_GRACE`（默认 120s）的 `queued/planning/generating` 才标 `failed/SERVER_RESTARTED`；**第二个进程启动不再无差别杀掉第一个进程的进行中 run** | 同套件：双进程场景断言另一进程在跑的 run 不受启动影响 |
| 生成期间心跳 | 生成循环每 5s `heartbeat(run_id)`（条件更新，仅非终态） | 同套件 |
| 跨进程取消 | 取消写库优先；生成循环**每个事件前复读数据库状态**，终态即停止，不继续流式输出 | 同套件：取消后不再产出消息 |
| 完成/取消竞争由数据库裁决 | 最终写入是条件更新 `WHERE status IN ('queued','planning','generating')`；抢不到就按取消处理，**不会在取消后补写"成功"消息** | 同套件 |
| 失败不自动重试 | 任何 ProviderError 落 `failed`，无重试循环，不重复计费 | 既有 provider 测试 |
| 幂等 Schema 升级 | `lease_worker`/`lease_heartbeat` 缺列时 `ALTER TABLE` 自动补列；新版库被旧代码打开时 `SCHEMA_VERSION` 守卫拒绝降级 | `tests/test_ui_extension_single_worker.py` 与 db 守卫测试 |

**仍然成立的限制（必须写明）：** 以上防护保证「意外出现第二个进程」不会互相
破坏，但**不等于多 worker 可用**——内存任务表意味着第二个进程接不到第一个进程
的任务，SSE 事件虽走库表、任务执行却仍在创建它的进程里。生产部署检查应为：
rag-api 只运行**一个** uvicorn 进程（无 `--workers`、无重复 systemd 实例、无
托管平台多副本），同一 `CMUI_DATA_DIR` 只能被一个实例挂载。要真正扩容，必须把
生成搬到持久化 worker（V3 侧尚不存在），在此之前不得以「租约存在」为由宣称
多 worker 已支持。
