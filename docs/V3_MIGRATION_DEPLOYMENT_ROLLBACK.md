# V3 Migration / Rollback boundaries

> 历史说明（2026-09-12）：新版主规格现已收到。本文件保留旧规格下的早期迁移边界；当前迁移与恢复契约见 [v3/MIGRATION_AND_ROLLBACK.md](v3/MIGRATION_AND_ROLLBACK.md)。本文件不再单独授权实施。

本轮只迁移隔离测试库/副本，不迁移当前真实资料库，不执行生产写入。V3 仅新增表，旧课程、文档、chunks、向量、会话与 Task DB 不重建、不重嵌入。

迁移门禁：SQLite online backup → 新隔离目录 → 使用新代码初始化两次 → 核对旧行/内容摘要、integrity/FKs、版本与新增约束 → 跑 A/B/Admin 隔离与闭环 → 保留可回滚快照。不得对未知服务器 git pull 当部署。

生产必须由 Owner 提供当前后端/Netlify SHA、Clerk/API origin、显式模型端点/地域、数据库/上传目录、备份证据。按现有 `ops/backup_v2.py` 与 `ops/restore_v2.py` 创建完整恢复单元（两库+uploads）；恢复到新目录，不覆盖原目录。历史路径不是生产事实。

初始回滚：关闭 `V3_ENABLED` 与 `VITE_V3_ENABLED`，旧 QA 与 Task Agent 保持可用。新表保留，不 drop。若需数据回滚，先停写，另存 V3 增量与审计，再恢复匹配版本的完整快照；恢复旧快照会丢失之后的新写入，必须由 Owner 明确批准。私人 workspace 若使用独立 corpus 复用 V2 ingestion，必须在 V2 列表/发布路由隐去并禁止其公开；旧版本回退期间禁用该 corpus 的发布与管理。

LIVE 模型/生产未验；无预算时不能执行 canary。不可把 health 通过当双 Pane/成绩/隔离通过。
