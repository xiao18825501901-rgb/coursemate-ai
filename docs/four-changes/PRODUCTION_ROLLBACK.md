# 四项改造生产回滚说明

## 保护点

- 发布前可验证备份：`/srv/coursemate/backups/20260921-four-changes-final-before-schema13/coursemate-v2-20260920T175807.651970Z`
- 当前后端 release：`/srv/coursemate/releases/4ef5064`
- Schema 13 兼容 fallback：`/srv/coursemate/releases/c484bb9-fallback`
- 前端上一部署：Netlify `6aaf951c45a27f7ea503df44`

## 何时停止发布并回退

立即停止新的上线动作，并保留日志与数据库现场，如果发生任一情况：RAG/Agent 服务无法启动、SQLite integrity/foreign-key 检查失败、认证边界意外变为公开、数据路径不符、模型费用超批准上限、或用户数据出现异常写入迹象。

## 回退决策

| 情况 | 受控动作 |
|---|---|
| 前端静态资源异常、后端健康正常 | 将 Netlify 回退到上一已知 deploy，再验证 `qqttai.com` 与 build-info |
| 应用异常，Schema 13 与数据正常 | 切换到 `c484bb9-fallback`；它支持 Schema 13，避免不兼容降级 |
| Schema 13 / 数据迁移异常 | 停止写入，使用发布前备份在隔离位置验证 manifest、hash、integrity 与外键，再按匹配 release 恢复数据库与上传/分享目录 |
| 不支持 Schema 13 的旧构建必须恢复 | 不能直接连当前数据库；仅在已核对的发布前数据库和资料目录恢复后，才可切回匹配的旧构建 |

## 不可接受的“回滚”

- 不删除用户、文件、课程、学习记录、资格、Bridge 或历史来使检查变绿。
- 不将旧 Singapore 主机重新投入流量。
- 不用不支持当前 schema 的构建直接访问已迁移数据库。
- 不跳过 manifest/hash/SQLite 校验，也不以恢复后的手工补跑替代首次恢复验证。

## 回退后验证

每次回退均需记录实际 SHA/deploy ID、服务状态、公开 health、未认证 `/me=401`、SQLite integrity/foreign-key、数据目录 manifest，以及触发回退的错误时间线。若涉及真实用户写入，先冻结新写入再作决定。
