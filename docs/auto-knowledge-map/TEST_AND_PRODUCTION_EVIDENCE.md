# 自动知识图测试与生产证据

## 已验证（当前工作树）

- 自动知识图专项：17 passed。
- 直接相关 API/集成/Question persistence：49 passed。
- 较宽组合回归：214 passed；另有 1 个既有 Canvas Bridge 断言失败，见下文。
- 全量 RAG 后端（明确排除真实 P5 live CLI，并从测试进程移除模型密钥、关闭本功能付费开关）：1888 passed、10 skipped、4 failed，耗时 1245.90 秒。4 个失败均列在下方，未发现本轮功能失败。
- migration rehearsal tests：6 passed。
- frontend targeted：2 files / 4 tests passed。
- Web TypeScript + Vite production build：137 modules built；PAT bundle scan passed。
- focused Ruff：passed。
- Python compile：passed。
- schema 41→42 fresh copied database rehearsal：versions 1..42，integrity OK，foreign-key violations 0，旧数据不变。

专项覆盖包括：

- 私人多文件 batch 在 seal 前不生成、seal 后只生成一次；
- Canvas local import 在 terminal 前不生成、完成后只生成一次；
- 官方人工发布树不被替换；
- 既有私人树首次登记不重建，增量更新期间继续 ACTIVE，并被新树继承；
- 240k 字符资料完整分段，每个 provider context <60k；
- fake HTTP 通过真实 OpenAI SDK、LearningProvider 与 LearningOrchestrator；max_retries=0；
- reservation、transport phases、artifact hashes 与 receipt 一致；
- 完整但不合法的输出只进行一次受控 repair；
- 冻结来源缺项会失败，不静默丢弃；
- restart 重用 durable artifacts，新增 provider dispatch 为 0；
- active machine campus tree 能被前端、learning resolver 与 assessment resolver 消费但仍保持 DRAFT/CANDIDATE 标签；
- 分享恢复固定快照回归 5 passed。

## 已知既有测试差异

`test_canvas_local_bridge.py::test_no_column_of_the_local_bridge_could_hold_a_credential`
要求任何列名都不能包含 `token`，而当前既有 Windows Bridge 实现保存
`bridge_token_hash`（一次性桥接凭据的不可逆哈希）。该列由现有 `db.py` 兼容逻辑添加，
不是 schema 42 或本功能引入。本轮未删除安全校验或修改测试来制造绿色结果。

前端全套测试另有一个既有期望仍检查旧 `--code` 命令，而当前已发布 Windows Bridge
使用 `--ticket`。本轮 targeted tests 与正式构建通过；该旧期望不属于自动知识图改动。

全量后端其余 3 个失败为：

- `test_jev_deepseek_template_v2.py` 两项：当前 15 份 V2 prompt/EXERCISE 文件 hash 与旧 manifest 期望不同；本轮未修改这些 prompt 或 manifest。
- `test_jev_gateway.py::test_live_sdk_transport_disables_hidden_retries_and_passes_timeout`：可选依赖 `typesafe_sdk` 未安装；同套件另一项已按此环境条件 skip，但该断言没有 skip guard。

## 尚未声称通过

- 真实 DeepSeek/Jev 代表链：PENDING。
- 生产 schema 41 副本迁移演练：PENDING。
- 生产部署与公开健康检查：PENDING。
- 新上传真实用户流程：PENDING。
- 所有 eligible 存量课程回填到 terminal：PENDING。
- 发布后备份、监控与暂停任务恢复：PENDING。

这些层级在取得对应证据前不得写成 Production PASS。
