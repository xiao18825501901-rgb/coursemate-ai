# MIGRATION AND ROLLBACK — 新 UI 与新增数据

本文档描述本次接线的数据影响、迁移步骤、恢复单元和回滚边界。
**所有生产动作都必须先取得授权，本文档不构成执行许可。**

---

## 1. 数据影响总览

| 存储 | 变化 | 说明 |
|---|---|---|
| `data/rag.sqlite3`（RAG Schema 21） | **Schema 不变** | 本次没有新增表、没有新增列、没有新增迁移文件。`migrations/` 目录与 `app/db.py` 的 `SCHEMA_SQL`、`V3_MIGRATIONS` 全部未改 |
| `data/agent.sqlite3`（Agent Schema 1） | **Schema 不变** | `services/agent-api` 未改一行 |
| `data/uploads/` | **不变** | 原上传目录与路径规则未改 |
| `<CMUI_DATA_DIR>/ui.sqlite3` | **新增**（Schema 2，21 张 `cmui_*` 表） | 只承载新 UI 的 profile、课程收藏、评论、通知、私信、任务镜像、会话/消息/生成、布局、Bridge、外键与 receipt |
| `<CMUI_DATA_DIR>/uploads/` | **新增** | 新 UI 上传的附件原件 |

**没有任何原 V3 表被复制、改名或删除。** 新课程、新文件、新知识节点全部只映射不复制：
`course.list`/`course.get` 直接读 `courses`，文件直接读 `documents ⋈ document_versions`，
检索直接走 `chunks`/`chunks_fts`，知识树直接读 `knowledge_tree_versions` /
`knowledge_tree_memberships` / `knowledge_nodes`。

## 2. 为什么 `ui.sqlite3` 可以安全新增

`app/cm_update/db.py:Database.initialize()`：

```python
tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
if tables.intersection({'courses','chunks','tasks','schema_migrations'}):
    raise ValueError('Refusing to initialize UI database over an existing CourseMate domain database')
if 'cmui_meta' in tables:
    current = c.execute("SELECT value FROM cmui_meta WHERE key='schema_version'").fetchone()
    if current and int(current[0]) > 2:
        raise ValueError('Newer UI database schema detected; do not downgrade')
```

因此：

* 把 `CMUI_DATA_DIR` 误指向 `data/`（含 `rag.sqlite3`）**不会**破坏原库——只会报错退出；
* 如果这个库将来被更高版本初始化过，旧版代码**拒绝降级**，不会静默写坏数据。

## 3. 部署前：备份（必须包含新库）

原 `ops/backup_v2.py` 的恢复单元只有 `rag.sqlite3` + `agent.sqlite3` + `uploads.tar.gz`，
**会漏掉新 UI 库**。本次已扩展：只要设置了 `CMUI_DATA_DIR`，`ui.sqlite3` 与
`ui-uploads.tar.gz` 就自动并入同一单元，并写入 `manifest.json` 与 `SHA256SUMS`。

```bash
export RAG_DATABASE_PATH=/srv/coursemate/data/rag.sqlite3
export AGENT_DATABASE_PATH=/srv/coursemate/data/agent.sqlite3
export RAG_UPLOAD_DIR=/srv/coursemate/data/uploads
export CMUI_DATA_DIR=/srv/coursemate/data/ui-extension   # 扩展已部署时才设置
export BACKUP_ROOT=/home/admin/coursemate-v3-preflight-backups
python3 ops/backup_v2.py
```

若 `CMUI_DATA_DIR` 已设置但其中没有 `ui.sqlite3`，备份**直接失败**，不会产出一个
看起来完整、实则缺库的备份。

### 跨库一致性限制（必须承认）

三个 SQLite `backup` 调用之间**没有分布式事务**。一个新 UI 部署下：

* 备份 `rag.sqlite3` 与 `agent.sqlite3` 之间若有写入，快照不是同一瞬间；
* 备份 `ui.sqlite3` 与 RAG 库之间同理。

因此生产备份必须在**维护窗口**内进行，或使用项目既有的协调方案。
`backup_v2.py` 的注释已把这一点写明；本次**没有**实现跨库原子快照。
New UI 与 RAG 之间没有跨库外键（新 UI 只存课程/文件/节点的**字符串 id**，不建 FK），
所以恢复后即使某个 id 已不存在，表现是 404/空列表，而不是数据损坏。

## 4. 部署前：副本恢复演练

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

## 5. 部署顺序

后端与前端 API 是**兼容新增**关系，因此顺序要求如下：

1. **先备份**（§3），并在副本上完成恢复演练（§4）。
2. **再迁数据**：新 UI 库不需要「迁移」——首次启动时 `Database.initialize()`
   以 `CREATE TABLE IF NOT EXISTS` 建表（幂等，可重复运行）。
   原 RAG 库不需要迁移（Schema 未变）。
3. **再发后端**：部署新 release 但保持 `UI_EXTENSION_ENABLED=false`。
   此时行为与原 V3 **逐字节相同**，可以先用 `https://rag.qqttai.com/health` 确认无回归。
4. **再开开关**：设置 `UI_EXTENSION_ENABLED=true` 与 `CMUI_DATA_DIR`，重启 rag-api。
   `UI_TASK_AGENT_URL` 指向既有 agent 公网 origin（`https://agent.qqttai.com`）。
5. **最后发前端**：Netlify 用本仓库真实构建（`npm run build --workspace @coursemate/web`），
   确认 `/` 与 `/app` 都返回 200，且 `/app` 是 `ui.html`。

### 必需的环境变量（后端）

| 变量 | 值 | 说明 |
|---|---|---|
| `UI_EXTENSION_ENABLED` | `true` | 唯一的挂载开关，默认 `false` |
| `CMUI_DATA_DIR` | 例如 `/srv/coursemate/data/ui-extension` | 新库与附件根目录，**不能指向 `data/` 本身** |
| `CMUI_ENV` | `production` | `validate()` 用它启用生产门 |
| `CMUI_AUTH_MODE` | `injected` | 与宿主 Clerk 共用身份 |
| `CMUI_INTEGRATION_MODE` | `integrated` | 由挂载器强制 |
| `UI_TASK_AGENT_URL` | `https://agent.qqttai.com` | Node 任务 Agent 的 origin |
| `CMUI_PROVIDER_MODE` | `qwen` 或 `disabled` | 未获付费授权时保持 `disabled` |
| `CMUI_ALLOW_BILLABLE` | `false`（未授权时） | `true` 才会真正发出千问请求 |
| `VITE_UI_API_BASE` | `https://rag.qqttai.com/ui-extension/api/ui/v1`（Netlify 构建期） | 前端 API 前缀 |

千问凭据**不需要新增**：`mount.py` 直接复用 `V3_MODEL_API_KEY` / `V3_MODEL_BASE_URL`，
所以站点仍然只有一份模型密钥。

## 6. 回滚

### 前置

* 记录当前 release SHA 与上一个已知可用的 Netlify deploy id。
* 确认 `UI_EXTENSION_ENABLED=true` 之前的那次 release 仍在服务器上（本次不需要 DNS 变更）。

### 回滚步骤（按代价从低到高）

**A. 只关新入口（最小、最先试）**
```
UI_EXTENSION_ENABLED=false
systemctl restart coursemate-rag        # 实际 unit 名以生产控制台为准
```
新 UI 立即从路由中消失，原站点完全不受影响。`ui.sqlite3` 与 `ui-uploads/` 保持不动，
用户下次开启后数据照旧。

**B. 回滚后端 release**
按 V3 报告 `COURSEMATE_V3_FINAL_PRODUCTION_DEPLOYMENT_REPORT.md` 的回滚边界：
停服务 → 移除新 release 的 drop-in → 恢复受保护环境副本
（`/etc/coursemate/env-backups/…`）→ 用恢复单元还原数据库与上传 → `systemctl daemon-reload`
→ 启动上一版 unit → 重复本地与公网完整性与健康检查。

**C. 回滚前端**
重新发布上一个已知可用的 Netlify deploy（V3 报告中的
`6a83d079cd1da1000859b96c`）。后端 DNS 未变，前端回滚不依赖 DNS 传播。

### 回滚不会做什么

* 不会删除用户在新 UI 中创建的课程、评论、私信、任务或对话——它们都在
  `ui.sqlite3` 里，回滚后文件仍在原地，只是入口暂时不可达。
* 不会回滚 `rag.sqlite3`，因为**本次没有改动它的 Schema**；
  若 RAG 库因其它原因需要回滚，用 A 步之后的完整恢复单元。

### 不可逆点

* 一旦在新 UI 中产生了真实用户数据（评论、私信、任务、上传），
  **这些数据只存在于 `ui.sqlite3`**。回滚到「未部署扩展」的备份单元会丢失它们，
  除非单独保留 `ui.sqlite3` 与 `ui-uploads/`。
  因此回滚时**只回滚代码与配置，不要回滚新库**。
* 千问两阶段的真实调用一旦发出即已计费，无法回滚；`cmui_runs.usage` 会保留真实用量。

## 7. 生产开关与预算

* `CMUI_ALLOW_BILLABLE=false` 时 `QwenProvider.stream()` 在发出请求**之前**
  就抛 `BILLING_NOT_AUTHORIZED`，`self.calls` 保持为空，**零出网请求**。
* 生成 run 在 `provider_mode='qwen' and not allow_billable` 时返回 402。
* 模型调用受 `v3_daily_model_calls_per_user` / `_per_user_course` 与
  `cmui_limits` 每分钟桶双重约束；本次**没有**放宽任何限额。
* `app.py` 的生成 runner 是**单进程**内存任务表（`app.state.jobs`），
  启动时把残留的 `queued/planning/generating` 标记为 `failed/SERVER_RESTARTED`。
  多 worker 部署必须把生成搬到既有持久化 worker，这一步**尚未完成**。
