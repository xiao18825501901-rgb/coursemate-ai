# 四项改造生产执行记录

## 范围与版本

- 应用候选：`4ef50642c0b2336e64c384752ea262901a32d81d`
- 后端当前 release：`/srv/coursemate/releases/4ef5064`
- 前端 Netlify production deploy：`6ab02278b7fae664934df25d`
- 旧 Singapore 主机未被重新启用或写入。

## 已执行的受控步骤

1. 对现有生产数据路径做只读盘点，确认没有活动 writer、PREPARING share 或 active import。
2. 创建发布前的完整 SQLite、上传资料、分享资料、manifest 与 checksum 备份，并验证 RAG、Agent、UI 数据库完整性与外键。
3. 在隔离副本上演练 Schema 13，确认工厂启动、10 条路由、UI Schema 13、完整性和外键检查通过。
4. 由 guarded switch 更新五个非机密策略值，迁移 UI Schema 13，并切换后端 release；guard 在迁移前失败时恢复原配置/runtime，在迁移后失败时切换到 Schema 13 兼容 fallback。
5. 仅从已预构建 `dist` 发布 Netlify 生产前端；未将密钥写入仓库或命令输出。
6. 执行公网无身份、无 token、无付费的单次 GET 健康检查；RAG、集成 UI、Agent 与站点均为 200。

## 迁移后实测

```text
RAG_DB integrity=ok foreign=0
AGENT_DB integrity=ok foreign=0
UI_DB integrity=ok foreign=0 schema=13
CMUI_OPERATION_USD_BASELINE=0.20
CMUI_OPERATION_INPUT_USD_PER_MILLION=2
CMUI_OPERATION_OUTPUT_USD_PER_MILLION=6
CMUI_CAMPUS_QUALIFICATION_POLICY=registered_active
```

## 未执行的危险动作

- 未删除生产课程、用户、文件、会话、资格、Bridge 或学习记录。
- 未执行 DNS 变更、旧 Singapore 重启或数据库重建。
- 未以伪造 Clerk 身份、全局自动认证或模拟模型输出来制造验收。

## 公开 smoke 证据

2026-09-20 18:50 +08:00 的无认证检查：

```text
https://rag.qqttai.com/health                 200 rag-api
https://rag.qqttai.com/ui-extension/health    200 integrated / qwen
https://agent.qqttai.com/health               200 agent-api
https://qqttai.com/                           200 CourseMate 学习空间
```

已认证用户路径、真实注册和多用户互动不在无身份 smoke 的证明范围内，见 [验收矩阵](PRODUCTION_ACCEPTANCE_MATRIX.md)。
