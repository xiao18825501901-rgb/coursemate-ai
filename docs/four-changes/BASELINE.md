# CourseMate 四项改造基线

记录日期：2026-09-20

## 代码事实

- 仓库：`D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY`
- 分支：`fix/codex-dsh-audit-20260919`
- 开始实施时 HEAD：`89b04e8ff8a507a4fcdf5f81e8fe1bed889ba86e`
- 冻结应用 SHA：`e6c77dc9ebe779efea2882b92e1f1e99425d4cc8`
- 用户提供的已部署应用线索：`46415bde81df28f4dc18629219bc9ddc50e4c215`
- 数据库迁移目标：UI Schema 13
- 工作方式：保留现有仓库与数据模型，增量修改；未 reset、未清库、未修改旧 C 盘仓库。

## 事实边界

| 层次 | 状态 |
|---|---|
| 源码实现 | 已完成四项改造 |
| 本地合成/离线合同 | 已验证，698 项后端与两套浏览器回归均通过，详见 `RELEASE_EVIDENCE.md` |
| 真实模型 | 未验证；本轮未批准新的模型费用 |
| 生产部署 | 未执行；没有复用旧发布或旧 canary 授权 |
| 当前生产版本 | 未在本轮访问生产，保持未知 |

## 保留的既有能力

`exercise.v2`、答案揭晓边界、plan 隐藏、统一 Pair 历史、知识点绑定、
teaching-only Pair 重启安全、私人资源隔离、正式课程树、学习覆盖与测评状态
均保留并纳入回归。旧 LearningBridge 数据、外键和教学证据没有删除；仅退役新的
跨栏动作入口。
