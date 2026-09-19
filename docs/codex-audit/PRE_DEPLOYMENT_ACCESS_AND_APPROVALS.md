# CourseMate 分阶段上线访问与授权操作卡

2026-09-20 · **仅准备；以下外部动作均未获本轮授权、均未执行。**

源码目录：`D:/CourseMate_COMPLETE_ARCHIVE_20260918/01_SOURCE_REPOSITORY`。候选 `73b7049ee3204d5c213ad70c67db9b892aa306bf`，分支 `fix/codex-dsh-audit-20260919`。测试结果和文档版本见 [LONG_COURSE_NAME_FIX.md](LONG_COURSE_NAME_FIX.md)。不要从旧 C 盘目录构建或发布。

本轮只完成本地长课程名修复、隔离测试、构建和本地提交。平台工具具备访问能力≠Owner 已授权；批准只读≠批准写入，批准费用≠已提供账户访问。既往 CNY 5 canary 预算**不沿用**。凭据仅由本人在可信控制台、受保护终端、既有凭据管理器配置，**不贴聊天、不写报告、不进 Git**。优先复用权限合适的既有凭据，不一次新建所有密钥。

## 1. 历史定位线索，不是当前生产事实

| 资源 | 项目内历史记录 | 必须现场重核 |
|---|---|---|
| 公网 | `https://qqttai.com/`；`https://rag.qqttai.com/health`；`https://agent.qqttai.com/health`；扩展 `https://rag.qqttai.com/ui-extension/health` | DNS/TLS/HTTP、当前应用版本；200 不证明用户业务通过 |
| ECS | `47.237.179.69`，实例 `iZt4n0k005125h6vlxoiloZ`，历史地域 `ap-southeast-1`，用户 `admin` | 控制台实例、公网 IP、主机公钥指纹、实际运行服务/目录/地域 |
| 历史后端 | `cd8c1218b56f04c3947abda33cf1b2638bafbf16`；`/home/admin/coursemate-v3-releases/cd8c121`；`coursemate-rag`/`coursemate-agent`，loopback8000/8001、Caddy80/443 | 不能把此旧路径直接当部署目标；后续版本/数据路径可能改变 |
| 非权威旧候选 | 杭州 `47.114.34.175`；历史只作恢复副本 | 不能因名字叫 new 就部署到此，不修改 DNS |
| GitHub | `https://github.com/xiao18825501901-rgb/coursemate-ai.git` | 实际远端、权限、分支、保护和 push 自动发布触发器 |
| Netlify | 站点 `coursemate-ai-qqtt`，site ID `166afb5a-4103-4236-9f13-4be34dc68cd2`；历史 production deploy `6aa70f2b5a330d5a8ae4be56` | Owner/团队、当前 deploy、构建配置、发布分支及自动发布。历史 deploy 的 commit_ref=null，标题不能证明源码 SHA |
| Clerk | 当前源码使用 Clerk；API 客户端基址 `https://api.clerk.com/v1/` | 实际生产应用/instance/允许域名/登录态；项目内未确证当前实例 ID |
| 模型 | 意图 `qwen3.8-max`，独立 embedding；历史 Singapore workspace、`text-embedding-v4` | 真实账户/地域/workspace、协议/endpoint/模型可见性/能力/价格；不能套用旧文档中的北京示例 endpoint |
| 数据版本 | 当前源码 RAG025 / UI11，Agent历史1 | 实际生产 schema、三库和原件/UI uploads/shares 位置及最后备份 |

出处：`docs/COURSEMATE_V3_FINAL_PRODUCTION_DEPLOYMENT_REPORT.md`（09-14）；`docs/ui-refresh/LAST_MILE_STATUS.md` 与 `release-manifest.json`（09-15）；`netlify.toml`；`app/main.py`、`app/db.py`、`cm_update/db.py`、`cm_update/directory.py`。09-15 文档曾记录公网200、扩展404；**本轮未再访问，不把它当今天结果**。旧报告中的预算、凭据状态、部署批准均不继承。

## 2. 第一张卡 A：固定公网 HTTPS 只读

- **目标/权限**：仅上表四个 HTTPS URL，各一次无身份 GET，TLS 校验开启、不跟随跨域跳转、不携带 Cookie/Token、不触发生成或登录。
- **本人做**：确认这仍是你的域名；单独批准 A。无需提供密码或密钥。
- **Codex 做**：获批后使用只读请求记录 UTC 时间、URL、HTTP 状态、Content-Type、受限非敏感摘要和错误阶段。不扫描路径、不发送写请求。
- **成功标志/保存**：站点200、RAG/Agent健康200；扩展的200/404按实际记录。404可能表示未启用或路由不同，不能单凭它确定配置；200也不等于新版本已部署。保留脱敏检查单，可发 ChatGPT。
- **费用/写入/回滚**：无模型费、无应用写入（正常服务器访问日志可能增加），无部署回滚动作。
- **可复制批准语**：`批准 A：仅对这四个既有 HTTPS 地址各做一次无身份只读检查；不批准 SSH、登录、付费或发布。`

## 3. 卡 B：SSH 只读现场盘点

- **目标/权限**：Owner 确认的权威 ECS；只读主机身份、进程状态、release、文件系统、数据路径/版本/备份元数据。默认普通账户，不新增 sudo/admin 授权。
- **本人做**：在 Alibaba Cloud ECS 控制台核对实例 ID/IP/地域；通过可信控制台确认主机公钥指纹；在本机受保护 SSH agent/config 中解锁既有专用密钥。只回报“访问已就绪”和非敏感目标，不发私钥/口令。
- **Codex 做**：先检查既有别名最终目标，再严格 host-key 校验连接；读取 `hostname`、`id`、`systemctl is-active coursemate-rag coursemate-agent caddy`、针对服务的 `systemctl show` 非敏感属性（MainPID、WorkingDirectory、FragmentPath）、已确认数据路径的 `findmnt -T` 与 `df -h`、release Git SHA/manifest。不整份打印 env、unit、进程参数或日志，因为可能含凭据/用户资料。
- **数据库只读边界**：先定位实际三库/上传/UI shares；只用 SQLite readonly 方式取 schema/version/count，不启动应用、不调用 initialize。若 readonly 打开需要 WAL 恢复或缺权限，停止该检查，不改权限、不开写模式；一致快照改走 H。
- **成功标志/保存**：目标指纹与 Owner 一致；release SHA、服务 PID、各真实数据路径、FS 类型、schema、备份路径/时间/完整性状态形成脱敏清单。读不到标 UNKNOWN。
- **费用/写入**：不调用模型、不改应用/DB、不重启；SSH 本身产生常规认证日志。密钥替换/新增信任记录如有必要另说明。
- **批准语**：`批准 B：对已确认的[实例/IP/账户]做上述只读盘点；不批准备份写入、迁移、sudo诊断、重启或模型调用。`

## 4. 卡 C：GitHub 只读与 push 分开

- **目标/权限**：上表仓库。C1只读 repository/branch/protection/webhook及关联自动构建信息（权限不足如实记录）；C2才允许指定 SHA 到指定分支的 push。
- **本人做**：浏览器登录 GitHub 并完成本人 MFA，选对账号/仓库；使用系统凭据管理器，Token不贴聊天。
- **Codex 做**：C1核对远端、共同祖先、分支与保护、Netlify Git关联、是否任何push触发部署。不能仅因本地无 `.github` 就断言不会自动发布。C2前列出精确remote/ref/SHA及会触发什么；不force-push、不直接推main、不暗中解除保护。
- **成功标志/保存**：C1配置脱敏记录；C2远端ref指向批准SHA且CI/自动发布行为符合批准。远端若已前进先停，不覆盖。
- **费用/写入/回滚**：C1无写；C2写远端，可能触发构建/发布费用，不能当“只是同步”。撤回用审查后的新提交，不强推回退；已部署时另走 I 回滚。
- **批准分句**：`批准 C1 只读，不批准 push。` 后续 `批准 C2：仅将[SHA]推到[remote/ref]，已确认自动发布[关闭/明确批准]。`

## 5. 卡 D：Netlify 只读与发布分开

- **目标/权限**：历史站点ID先重核；D1只读站点/域名/部署/构建与变量**名称及是否配置**，不导出密钥；D2指定已验证artifact或SHA发布权限。
- **本人做**：Netlify 控制台登录/MFA、确认team/site。完成生产 Clerk publishable 配置及 API origin 选择；秘密只在受保护位置配置。
- **Codex 做**：D1核对 publish分支/自动发布/hooks、当前及可回滚deploy、`netlify.toml`一致性。D2必须在H/I门槛通过并单独批准后构建发布。
- **成功标志/保存**：D1当前 deploy ID/status/source证据；D2记录新deploy ID、精确应用SHA、artifact hash、原deploy回滚ID、公网检查。标题不是SHA证明。
- **构建门槛**：正式发布运行 `netlify.toml` 已接入的 preflight → Vite build → artifact verify；实际 `pk_live_`、HTTPS origins、无test token、V3启用、`build-info.json`需核对。此次本地 `npm run build`成功不等于生产配置门槛已通过；本地合成浏览器bundle绝不能发布。
- **费用/写入/回滚**：D1无发布；D2改公开前端/可能构建费。回滚到现场确认的旧deploy，不抄历史ID自动执行。
- **批准分句**：`批准 D1 仅只读。` / `批准 D2 发布[SHA/artifact hash]到[site ID]，回滚到[现场已核实deploy ID]。`

## 6. 卡 E：Clerk 目录读取与本地投影同步

- **目标/权限**：Owner确认的 Clerk生产实例；E1只读完整注册目录；E2将完整目录投影到指定 CourseMate UI DB（这是目标DB写入，仍不是资格写入）。
- **本人做**：登录 Clerk Dashboard，确认production而非development、获授权的目录范围；将后端凭据放入既有受保护运行环境。真实登录/MFA只能本人完成。
- **Codex 做**：E1批准后使用 `ClerkDirectoryClient.fetch_users` 有界分页读取并保护快照，只报告聚合数/完整性/排除原因；不公开注册名单。E2先在副本核验 `sync_directory`，再申请明确目标DB写入。
- **现有 CLI 注意**：`python -m app.cm_update.directory --database <已确认UI库> --approved-clerk-sync` **会写投影**，不是E1只读命令；它没有纯读取/preview CLI，不能虚构 `--dry-run`。E1/F预览需用现有只读客户端/纯函数的受控调用，不调用同步/资格apply函数。
- **成功标志/保存**：所有页成功，snapshot timestamp/hash、总量/排除统计完整，失败不接受部分目录；E2回执与副本前后对照证明用户隐私设置/已有资格不变。
- **费用/写入/回滚**：无模型费；Clerk API配额遵账户，E2写指定DB。恢复须保留后续写入，不能盲目全库回滚。
- **批准分句**：`批准 E1 仅读取[Clerk实例]目录作受保护完整快照。` / `批准 E2 将已验收快照同步到[UI DB]，不授予资格、不改Clerk账号。`

## 7. 卡 F：历史用户资格预览与写入

- **目标/权限**：F1基于E1完整可信快照、Owner固定截止时间的纯计算预览；F2才修改指定UI DB资格及回执。必须单独批准。
- **本人做**：给出业务截止时间/时区并确认换算Unix毫秒；审阅候选人数、未知注册时间、禁用/删除/锁定排除数及受保护候选清单，确认业务资格政策。不要用本地首次登录时间代替注册时间。
- **Codex 做**：F1先只读核对目标库已固定cutoff与COMPLETED回执，再调用纯函数 `grandfather_candidates(..., cutoff_ms=..., complete=True)`，不写库。F2前备份/副本演练并重新核对完整快照及候选差异。**现有正式CLI会先写FETCHING/cutoff、重新fetch后立即apply，没有expected-hash守卫或暂停比对点；不得直接用它执行“只批准指定快照集合”的F2。** 后续受控调用必须读取已批准冻结快照，用纯函数重算并核对hash+候选集合，再仅将同一份records传入 `apply_grandfather_snapshot`（或另行批准实现compare-before-apply工具）。有旧COMPLETED回执不能当作本次新集合已执行；cutoff冲突或快照差异先停并重新确认，不覆盖旧回执。
- **成功标志/保存**：固定cutoff、snapshot SHA、候选/排除计数；apply回执COMPLETED、只影响批准集合、重复操作幂等；缺时间戳不自动合格，不全局自动认证。
- **费用/写入/回滚**：F1无资格写入；F2是真实资格写入且影响访问权限。资格撤销/回滚需保留原状态和审计记录，不能用删库替代。
- **批准分句**：`批准 F1 仅资格预览，截止[含时区时间]。` / `批准 F2 对[快照hash/确认候选集合/目标UI DB]写资格，已完成备份，其他用户不变。`

## 8. 卡 G：一次有限真实 Qwen canary

- **目标/权限**：确认账户/地域/workspace/endpoint与模型能力后，另批一次性总金额、最大请求数、输入输出token、截止时间、测试课程/账户/数据范围。旧C1–C5或模型列表可见不证明当前新调用链通过。
- **本人做**：本人登录 Alibaba Model Studio，确认可用模型/地区/协议/价格/余额；凭据仅放受保护环境。批准具体总额（目前 **未批准，不能填旧5元**）、超时失败如何计账与是否启用付费覆盖评审。
- **Codex 做**：仅隔离测试资料与指定账号，验证当前14模板分类（最小代表样本，不冒称14类都实测）、normal work、Thinking plan→work实际采用已保存Prompt、普通追问复用、做一题/答案隐藏跨SSE片段/显式揭晓/上传题详解/Step解释、覆盖评审。答案揭晓是**非模型操作而非只读**：复用已保存答案并写揭晓状态/操作回执，不强行制造模型调用。每个会生成的操作分别记请求/usage；跨境资料发送须在批准的数据范围内。
- **预算控制**：按实际账户价格编制输入/输出上限和最坏请求数后再执行；总额不足/未知用量/超时立即暂停，不自动重试、换模型或加钱。SDK重试与后台自动任务必须纳入限额。分类/覆盖可能额外调用，不能只数点击次数。
- **成功标志/保存**：真实 provider request ID、模型/协议/地域、usage与实际费用或标记待账单、Prompt版本hash进入后续请求的证据、答案不提前泄漏、coverage回执和持久化；只输出脱敏摘要，不打印原始用户内容或key。
- **费用/写入/回滚**：真实模型费用不可撤回；默认仅隔离DB写入，若拟用生产指定账号须额外批准J；评审常开费用走K。
- **批准语模板**：`批准 G：账户/地域/模型[...]; 数据范围[...]; 总额≤[币种金额]、请求≤[数]、token上限[...]、截止[...]；仅上述canary，失败不自动重试，不批准重嵌入或持续费用。`

## 9. 历史 Embedding 必须由 Owner 选择

来源仍 **UNKNOWN**：现有本地历史检查1937条chunk未记录来源；当前模型标签不证明向量由它生成。没有已实现的 lexical-only fallback、UNKNOWN隔离或UI警告可依赖。

- **A 暂用评估**：保留人工风险告知，另批限定真实检索验收（查询embedding也可能计费），核对维度、相关性、引用/原件及用户隔离；通过后再由Owner决定是否暂用。失败不放行。手册警告不是已上线UI提示。
- **B 重建**：单独批准课程/文件/token/金额范围及数据流出；建立有provider/model/dimension/preprocess/source回执的独立新索引，保留旧索引与映射，回归后单独批准切换/回滚。不在分享时隐式付费重嵌入。

这两个选项均不是本轮自动执行项，不能从G一次生成canary推定已批准。

## 10. 卡 H：一致备份、隔离恢复与副本迁移

- **目标/权限**：B核实后的真实RAG/Agent/UI三库、原始上传、UI uploads、UI shares、保护配置/验证HMAC secret、旧runtime；H1备份写入及必要暂停writer，H2新隔离目录恢复/副本迁移，列明路径、磁盘和窗口。
- **本人做**：确认允许短时暂停哪些服务/worker、备份存储位置和敏感数据保留策略；快照/新云盘等新增计费另批。
- **Codex 做**：使用 `ops/backup_v2.py` 与 `ops/restore_v2.py` 真实参数，按现场路径编制命令后再执行。单个SQLite backup不等于三库/文件一致快照；先排空所有writer并保护冻结分享。`BACKUP_ROOT`须在上传树之外，`RESTORE_SOURCE`为完整校验备份，`RESTORE_TARGET`必须是新的隔离目录。恢复不指向线上，不启动真实模型/Clerk/通知。
- **成功标志/保存**：manifest/hash、数据库integrity/FK、表/文件计数和字节hash、所有权映射、迁移前后对照、首次顶层恢复成功；保留旧版runtime/config及回滚单位。真实ECS文件系统须验证，WSL ext4通过不能代替；DrvFS不支持。
- **失败行为**：不得覆盖目标；失败staging原样留存，仅条件恢复后使用准确 `RESTORE_RESUME_PARTIAL` 校验resume。原WinError原因仍未知，不改ACL、不关防护。
- **费用/写入/回滚**：写备份/隔离副本，暂停writer本身影响服务，必须在批准窗口；可能存储费用但无模型费。未完成备份不可进入I。
- **批准语**：`批准 H：[确切源路径]一致备份到[路径]，在[窗口]暂停[明确writer集合]；恢复到[新的隔离路径]并迁移副本，不修改线上Schema、不发布。`

## 11. 卡 I：迁移、后端和前端切换

- **前置**：A/B/C1/D1核实；G与真实登录必要验收完成；Embedding已决策；F候选政策已确认；H恢复/迁移演练通过；明确应用SHA、artifact hash、schema差异、目标路径、窗口、负责人、现场旧版本/回滚单位。
- **源码事实**：`app/main.py:create_app` 在检查UI开关之前调用 `database.initialize()`；RAG是否迁到025还受V3配置影响。**UI_EXTENSION_ENABLED=false不是无写入模式**。UI挂载初始化可能把UI库升到11。不能启动新代码对唯一真实库“先试一下”。
- **本人做**：签收精确迁移清单和维护/回滚风险，独立批准I（可分I1迁移、I2后端、I3前端），不能用B只读批准代替。
- **Codex 做**：按核验后生成的操作表排空writer、再做最终一致备份、迁移并验证、切换到冻结runtime/config、启用批准的UI、执行D2正式frontend构建发布。现无现场信息，**这里不编造最终deploy命令/回滚ID**。
- **成功标志/保存**：生产release SHA与artifact吻合、Schema/数据hash与演练符合、服务健康/TLS/CORS/未登录401/测试身份不在artifact、新旧历史链接正常；实际业务另走J，不以health200宣称全部通过。
- **PREPARING兼容**：新恢复工具只支持冻结意图协议；所有发送worker必须锁感知，不与旧binary混跑。旧缺意图快照不伪造ready；切换须排空/控制这些任务。
- **回滚**：本轮ID修复无Schema迁移，39字符ID兼容旧约束，**不改回已有ID**。整站从旧生产升级仍可能迁库；旧UI拒绝新schema，不能只退代码/改版本号。恢复整个已验证旧单位到新目录并匹配旧runtime；有新写入必须先对账，禁止覆盖丢失新资料/通知/课程。
- **费用/写入**：真实生产迁库/重启/前端发布，可能流量/构建费；模型持续预算需K。越权/完整性破坏/恢复不可用立即停止放量，按照已批准回滚方案处理。
- **批准语**：`批准 I[1/2/3]：目标[...]; SHA[...]; 备份/恢复证据[...]; 维护窗口[...]; 回滚单位[...]; 授权动作仅[列明]。`

## 12. 卡 J：指定真实账号、多用户消息和分享验收

- **目标/权限**：Owner指定的两个学生测试账户及一个管理员测试账户、指定测试课程/资料/接收者；禁止对真实陌生用户发私信或共享。
- **本人做**：分别登录并本人完成验证码/MFA，确认可产生哪些通知/消息/资格记录；不把session/token给聊天。
- **Codex 做**：只在批准账号与课程验证目录分页、资格前后门禁、私信未读/重登、冻结分享/加入重放/引用原件隔离、长名直接创建、双Pane历史/Pair恢复、plan保密和当前Pair出题。真实生成依赖G或K预算，未批则只测试非模型路径。
- **成功标志/保存**：脱敏账号代号A/B/Admin、逐项状态、网络结果、本人遮挡后的截图、刷新/重登证据、跨用户404/403；数据真实私有，测试完成是否保留由Owner决定。
- **费用/写入/回滚**：确实写消息/分享/课程/可能通知；不自动永久清理，不把可撤销UI操作等同已撤销通知。资格写入仍需F授权。
- **批准语**：`批准 J：仅[指定账号代号/测试课程]进行[列明操作]，接收者[...]; 不接触其他用户、不自动删除，不额外增加模型预算。`

## 13. 卡 K：上线后的持续模型费用

- **目标/权限**：真实provider生产账号的持续分类/normal/Thinking/题目/覆盖以及查询embedding费用，独立于一次Gcanary。
- **本人做**：确定每日/月总额、每人上限、并发/最大token、失败重试政策、覆盖评审是否常开、报警接收人及停用阈值；在模型控制台设置实际可用的账户预算/告警。
- **Codex 做**：先核验现有应用限制和供应商能力是否能兑现该政策；缺硬限额就明确列缺口，不声称已有自动硬停，也不在这轮擅自新增计费平台。未落实约束不得开放未授权持续调用。
- **成功标志/保存**：批准政策版本、实际可验证的账户限制/应用参数、消费账单核对、告警和停用演练。模型/地域/计价改变重新批准。
- **费用/写入/回滚**：持续真实费用；停用影响教学可用性但不能回收已产生账单。
- **批准语**：`批准 K：账户[...]，日期范围[...]，每日/月/用户限额[...]，允许调用[...]，重试[...]，告警/停用责任人[...]；不含重新嵌入历史索引。`

## 14. 执行顺序与停点

本地缺陷关闭 → **A只读公网** → B/C1/D1及本人账户准备 → E1/F1预览 → G有限模型与真实登录验收 → Embedding选择 → H一致备份/副本恢复与迁移 → 必要E2/F2独立批准 → 精确I/D2/C2发布批准 → J多用户验收 → K费用政策落实与观察。

存在依赖的生产写入必须先H；上行顺序中的预览不代表已写入。若canary需要私有候选服务，单独明确隔离部署权限，不能借G之名启动线上迁库。本手册不提供一键“批准全部”。

**现在停在本地交付。用户下一项只需确认四个域名并决定是否批准A。不要发送任何密码、验证码、私钥、API Key或Token。**
