# 合法长课程名修复与候选冻结

## 本轮基线与执行计划（2026-09-20）

- 规格：`D:/UserData/Downloads/CODEX_FIX_LONG_COURSE_NAME_AND_PREPARE_RELEASE.md`，已完整读取。
- 工作区：`D:/CourseMate_COMPLETE_ARCHIVE_20260918/01_SOURCE_REPOSITORY`。
- 分支：`fix/codex-dsh-audit-20260919`；起点 `20b45fb02609114d04e479f7056216a1f41fe457`，开始时无未提交修改。
- 旧实现 `dcfd3221ce12170521807e4b1c52fcc2003cbd0b` 的 657/13 等证据保留，不作为新版本验收。
- 步骤：真实 integrated / 浏览器 RED → 内部 ID 最小修复 → 边界、碰撞、隔离、分享测试 → 本地提交冻结 → 同版本回归与构建 → 文档及独立授权卡 → 等待，不部署。
- 本轮不改 Schema，不改已有 ID，不重做恢复/PREPARING/侧栏，不访问生产或计费模型。

## 已核验根因与契约

UI 表单和 UI CourseCreate 接受 1–100 字符名称（去首尾空白）；领域显示名上限 120。内部 ID 必须匹配 `[a-z0-9][a-z0-9-]{1,49}`。旧 `_new_course_id` 的 40 字符名称前缀加 `-` 和 12 位时间戳可达 53；Unicode `isalnum()` 也不能保证 ASCII ID，时间精度为秒还可能造成同名碰撞。领域模型校验发生在课程 INSERT 前。

共享创建不复用该 ID 算法：`share-` 加分享 ID × 接收者 SHA256 的前 20 位，保持原有幂等映射；仅复用领域 CourseCreate 校验。UI 收藏在远端创建成功后写入。

浏览器 RED：直接输入 100 字符合法名称，实际 POST name 完整，期望 201、实际 500。原始证据保留于 `work/codex-audit/browser-1789836358998-5912/playwright-report.json`。

## 验收与发布候选

```text
APPLICATION_RELEASE_SHA: 73b7049ee3204d5c213ad70c67db9b892aa306bf
TESTED_CODE_SHA: 73b7049ee3204d5c213ad70c67db9b892aa306bf
DOCUMENTATION_HEAD: 本报告所在最终文档提交；用下方 git log 命令解析，不用文件内自引用SHA制造无限提交
WORKTREE_STATE: 应用已冻结；本轮文档独立提交，交付前以 git status --porcelain 核验干净
PRODUCTION / LIVE_MODEL / LIVE_ACCOUNT: NOT_RUN, NOT_AUTHORIZED
```

解析文档提交：在指定仓库执行 `git log -1 --format=%H -- docs/codex-audit/LONG_COURSE_NAME_FIX.md`。最终聊天交付列出实际文档HEAD；后续纯文档提交不改变TESTED_CODE_SHA，也不重新跑不变的全套。

### 最小修复

`services/rag-api/app/ui_extension/domain.py` 的 `_create_course` / `_new_course_id`：使用项目已有的标准库 UUID4 模式（`cm_update/db.py:uid` 同样使用 uuid4().hex），但不新增跨层DB依赖；`course-` +32位hex，共39字符ASCII。名称不参与ID生成。数据库事务唯一约束裁决冲突，最多3次，仅重试 `COURSE_EXISTS`，额度等其他错误立即传播。没有读取后再写入的竞争检查，也没有修改全局验证规则。

新增 `services/rag-api/tests/test_codex_long_course_names.py`，实测挂载后的 `POST /ui-extension/api/ui/v1/courses`，独立SQLite/上传目录、合成Clerk身份与fake embedding。覆盖完整合法中/英/混合Unicode（99/100字符）、x/数字名称、超限/空白/非字符串422、同名并发/同前缀/两用户404、列表/详情/收藏、强制碰撞后成功及3次耗尽409无新增课程/收藏、429不重试，以及长名冻结分享加入/幂等重放/文件ID映射/原件和副本预览下载字节。API的100字符按Python Unicode code point计，浏览器maxLength按原生UTF-16规则；未擅自改变任何一端既有合法上限。全ASCII100字符真实浏览器输入命中两端共同边界。

浏览器 `tests/e2e/codex-audit.spec.ts` 新增真实表单100字符创建测试，校验POST201、完整name、ID约束、files页面、列表pin、另一用户404和刷新；原13项原样保留。无短创建后改名绕过。

### 真实执行证据

以下路径均相对仓库 `work/codex-audit/`，RED文件不删除或覆盖：

| 阶段 | 结果 | 证据 |
|---|---|---|
| 后端RED，修复前20b45fb + 新测试 | 10 passed / 8 failed，18.51s，真实500及碰撞失败 | `long-name-red.xml`，含完整traceback |
| 浏览器RED，修复前20b45fb + 新测试 | 1 failed，100字符提交实际500而非201 | `browser-1789836358998-5912/playwright-report.json` |
| 初次修复+共享/恢复联测 | 35 passed，60.25s | `long-name-green.xml` |
| 最终针对性（增补下载字节、非冲突不重试） | 19 passed，24.49s，2依赖弃用警告 | `long-name-final-targeted.xml` |
| 浏览器新例GREEN | 1 passed，11.0s | `browser-1789836700254-30704/playwright-report.json` |
| 冻结SHA完整浏览器 | 14 passed，48.2s，0失败/跳过/flaky，retries=0 | `browser-1789836865875-21196/playwright-report.json`；长名与768px侧栏截图 |
| 冻结SHA Web / Agent | 60 / 66 passed | `long-name-release-npm-test.log` |
| 冻结SHA typecheck / build | 两workspace全部PASS，退出0 | `long-name-release-typecheck.log` / `long-name-release-build.log` |
| 冻结SHA完整后端 | **676 passed，0失败/错误/跳过，755.03s，2既有依赖弃用警告，退出0** | `long-name-release-regression.xml` / `.log` |

针对性命令（在 `services/rag-api`）：

```powershell
$env:CMUI_ALLOW_BILLABLE='false'
$env:CMUI_ENV='test'
$env:CMUI_DATA_DIR=''
& ../../work/codex-audit/venv/Scripts/python.exe -m pytest tests/test_codex_long_course_names.py -q --tb=short --basetemp=../../work/codex-audit/long-name-final-targeted --junitxml=../../work/codex-audit/long-name-final-targeted.xml
```

RED用同一新测试路径、不同新目录 `long-name-red`；35项联测附加 `tests/test_codex_sharing.py tests/test_codex_share_recovery.py`，输出到 `long-name-green`。不要重新运行覆盖这些证据；将来重跑选新目录。

冻结后完整回归同样环境，命令 `../../work/codex-audit/venv/Scripts/python.exe -m pytest -q --tb=short --basetemp=../../work/codex-audit/long-name-release-regression --junitxml=../../work/codex-audit/long-name-release-regression.xml`。stdout/stderr均保存在同名log。仓库根目录执行 `npm test`、`npm run typecheck`、`npm run build`；`npm exec -- playwright test --config playwright.codex-audit.config.ts`。浏览器harness使用环境白名单、零账号凭据、独立synthetic DB与独立web-dist。

`npm run build` 是本地优化构建成功，**不是使用真实生产账号配置的发布artifact验收**。Netlify正式preflight/artifact验证和真实登录仍待D/I；本地测试bundle不可发布。依赖审计的外部registry请求、真实模型、真实账号及生产测试均未执行。

最终XML实际统计tests676/failures0/errors0/skipped0，XML suite时间754.825s，pytest摘要755.03s（统计边界不同）。两条警告为Starlette/httpx与AnyIO BlockingPortal弃用提示；不为消除警告扩大依赖升级范围。结构门槛（规定报告/操作卡/版本字段）与行为门槛（实际HTTP、文件字节、浏览器和全回归）分别核验通过。

### 审查、迁移与回滚

独立只读审查未发现此修复阻塞项；审查建议的原件/副本下载字节断言已补入并通过。代码范围只有一个应用文件和两个测试文件；不增加依赖、Schema、数据重建或付费路径。

无需新增迁移。没有操作唯一真实DB，已有课程、文件、会话、知识节点、收藏、分享ID不重写。共享课程的 `share-<digest>` ID算法完全未改。回退本轮代码不能回改或删掉已创建ID；新ID仍符合原模型，旧版能读取。回退旧版会重新暴露创建缺陷。整个待发布审计版本相对历史生产仍有RAG/UI迁移，需要完整备份/副本演练，不能把“这次没有新增迁移”说成“上线没有迁移风险”。

Windows有界恢复、显式resume、PREPARING新冻结协议与侧栏原实现不变。Linux ext4的7项真实证据来自旧实现且相关代码字节未变，**不是本轮重新在Linux执行**；DrvFS仍不支持。Windows原始具体归因、历史embedding来源继续UNKNOWN。

### 交付界限

本轮明确的长名500已修，无本轮新确认而未处理的应用缺陷；不声称重新审计全站或证明没有其他缺陷。原始645/2及所有RED证据保留。真实模型/Clerk同步/真实资格/消息分享/生产访问和部署均未执行。逐项外部授权见 [PRE_DEPLOYMENT_ACCESS_AND_APPROVALS.md](PRE_DEPLOYMENT_ACCESS_AND_APPROVALS.md)；先请求A，不沿用历史预算，不自动push或发布。
