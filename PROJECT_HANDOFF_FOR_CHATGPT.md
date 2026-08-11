# CourseMate AI — ChatGPT 教学与维护交接

## 1. 一句话总结

CourseMate AI 把两门课程的真实资料做成“按课程强隔离、可引用来源、流式回答”的 RAG 问答系统，并用 OpenAI Function Calling 把自然语言学习意图安全地落成持久化 Todo 操作。

## 2. 系统架构 ASCII 图

    [Student / Chrome]
           |
           v
    [React + TypeScript + Vite]
      |                     |
      | HTTP + SSE          | JSON HTTP
      v                     v
    [FastAPI RAG]         [Express Agent]
      |                     |
      |-- upload/load       |-- AgentService loop
      |-- chunk/embed       |-- strict JSON Schemas
      |-- FTS5 search       |-- Ajv validation
      |-- cosine search     |-- allow-listed executor
      |-- RRF fusion        |-- TaskRepository
      |-- grounded prompt   |
      |-- Responses stream  |-- Responses tool calls
      v                     v
    [rag.sqlite3]         [agent.sqlite3]
      |                     |
      v                     v
    [courses/docs/        [tasks]
     chunks/messages]

    Cross-module bridge:
    cited QA answer --POST /api/tasks--> persistent study task

## 3. 项目目录与关键文件

    coursemate-ai/
    |-- .env.example                    # 所有环境变量模板，无真实密钥
    |-- netlify.toml                    # Vite 构建与 SPA rewrite
    |-- render.yaml                     # 两个带持久盘的后端服务
    |-- package.json / package-lock.json# npm workspaces 与锁文件
    |-- playwright.config.ts            # 真 Chrome、三服务 E2E
    |-- README.md                       # 最快启动入口
    |-- PROJECT_HANDOFF_FOR_CHATGPT.md  # 本文
    |-- apps/web/
    |   |-- src/App.tsx                 # 路由
    |   |-- src/components/Layout.tsx   # 全局导航/布局
    |   |-- src/components/CitationList.tsx
    |   |-- src/components/TaskBoard.tsx
    |   |-- src/pages/HomePage.tsx
    |   |-- src/pages/QaPage.tsx        # 课程选择、SSE、上传、加入计划
    |   |-- src/pages/TasksPage.tsx     # CRUD、筛选、Agent 对话
    |   |-- src/pages/DocumentsPage.tsx
    |   |-- src/pages/AboutPage.tsx
    |   |-- src/services/ragApi.ts      # RAG HTTP/SSE 客户端
    |   |-- src/services/agentApi.ts    # Agent HTTP 客户端
    |   |-- src/services/http.ts        # 统一错误处理
    |   |-- src/types/api.ts            # 前端合同
    |   \-- src/styles.css              # 响应式设计系统
    |-- services/rag-api/
    |   |-- app/main.py                 # 依赖装配、中间件、异常处理
    |   |-- app/config.py               # Pydantic Settings
    |   |-- app/db.py                   # RAG DDL、连接与 FTS 触发器
    |   |-- app/models.py               # API Pydantic 模型
    |   |-- app/api/ingestion.py        # 课程、资料、任务状态路由
    |   |-- app/api/qa.py               # SSE 问答路由
    |   |-- app/services/ingestion.py   # 验证、状态机、持久化
    |   |-- app/services/qa.py          # 检索、SSE、对话持久化
    |   |-- app/rag/loaders.py          # PDF/MD/TXT/DOCX/PPTX
    |   |-- app/rag/chunking.py         # 段落感知切块
    |   |-- app/rag/embeddings.py       # OpenAI/确定性向量
    |   |-- app/rag/retrieval.py        # RRF 混合检索
    |   |-- app/rag/prompt.py           # 上下文构建
    |   |-- app/rag/answers.py          # Responses 流式回答
    |   |-- app/repositories/chunks.py  # FTS5 与向量查询
    |   |-- app/corpus_import.py        # 清单驱动批量导入
    |   \-- tests/                      # 42 个 Python 测试
    |-- services/agent-api/
    |   |-- src/server.ts               # 进程装配和优雅关闭
    |   |-- src/app.ts                  # Express 路由/安全中间件
    |   |-- src/config.ts               # 环境变量验证
    |   |-- src/db.ts                   # tasks DDL
    |   |-- src/types.ts                # Task/Tool 类型
    |   |-- src/repositories/tasks.ts   # 参数化 CRUD
    |   |-- src/services/agent.ts       # Function Calling 循环
    |   |-- src/openai/client.ts        # Responses SDK 适配
    |   |-- src/openai/deterministic-client.ts
    |   |-- src/tools/schemas.ts        # 五个 strict schemas
    |   |-- src/tools/validator.ts      # Ajv 校验
    |   |-- src/tools/executor.ts       # allow-list 执行
    |   \-- test/                       # 32 个 Agent 测试
    |-- data/
    |   |-- inventory/course-files.json # 86 文件清单
    |   |-- inventory/import-report.json# 66 成功导入报告
    |   |-- transcriptions/<sha>.md     # 扫描 PDF 的校验和绑定文本
    |   |-- uploads/<course>/           # 生成名的本地资料副本
    |   \-- rag.sqlite3                 # 已导入本地库
    |-- scripts/
    |   |-- inventory.ps1 / test_inventory.ps1
    |   |-- import_corpus.py
    |   \-- start_local.ps1
    |-- tests/e2e/coursemate.spec.ts    # 三条完整浏览器验收
    \-- docs/                           # 架构、API、数据库、部署、排错等

node_modules、.venv、dist、缓存和 work/ 均属于生成物，不是源代码交接面。

## 4. RAG 请求全链路（对应函数）

### 4.1 入库

浏览器 QaPage.upload 调用 services/ragApi.uploadDocument，向 POST /api/courses/:courseId/documents 发 multipart 请求。api/ingestion.py 的 upload_document 只读取受限字节数，再调用 IngestionService.queue_document。queue_document 做课程检查、扩展名/签名/大小/哈希验证，写 documents 与 ingestion_jobs，并生成安全存储名。FastAPI BackgroundTasks 随后调用 process_document。

process_document 调用 rag/loaders.py::load_document。PDF 按页、PPTX 按 slide、DOCX 按标题/段落、Markdown 按 heading、TXT 按行组返回 SourceSection。rag/chunking.py::chunk_sections 将 section 切为 TextChunk，并保留 locator。EmbeddingProvider.embed_texts 生成向量；同一事务删除旧 chunks、写入新 chunks。db.py 的 SQLite triggers 同步 chunks_fts。最后文档和作业状态变为 ready/completed。

批量路径 scripts/import_corpus.py -> corpus_import.import_corpus 使用 inventory JSON；它先确保 cs3481/ge2324 存在，再逐个复用 IngestionService，因此批量导入没有绕过上传安全和数据库逻辑。

### 4.2 问答

QaPage.ask 调用 ragApi.streamQa，POST /api/qa/chat。api/qa.py::chat 先 require_course，再返回 StreamingResponse(QaService.stream)。QaService._start_conversation 先落用户消息。

HybridRetriever.retrieve 只计算一次 query embedding，然后并行逻辑上取得两组候选：ChunkRepository.keyword_search 用 FTS5/BM25；vector_search 对该课程的 stored vectors 计算 cosine_similarity。reciprocal_rank_fusion 通过 chunk ID 去重并累计倒数排名分。build_context_with_hits 依 TOP_K 与 MAX_CONTEXT_CHARS 构造带 source label 的上下文。

OpenAIAnswerProvider.stream_answer 调用 client.responses.create(stream=True)，只转发 response.output_text.delta。QaService 收集完整文本，服务端从 included_hits 生成 citation（不是让模型编文件名），依次 SSE 发送 meta、delta、citation、done，并由 _record_answer 把完整答案和 citations_json 写入 messages。前端 SSE parser 将 delta 追加到同一条 assistant message，CitationList 渲染出处。

### 4.3 无证据路径

如果 included_hits 为空，QaService 直接返回固定证据不足提示、无 citation，并照常保存对话。模型不被调用。若模型中途失败，流发送 MODEL_ERROR；不向用户暴露 key、stack 或课程全文。

## 5. Function Calling 全链路（对应文件）

TasksPage.talkToAgent -> agentApi.chatWithAgent -> POST /api/agent/chat。app.ts::validateChat 校验消息，AgentService.chat 组装 AGENT_INSTRUCTIONS、user input 和 TOOL_DEFINITIONS。OpenAIResponsesClient.create 调 Responses API。

模型返回 function_call 后，AgentService 解析 arguments JSON；ToolExecutor.execute 先经 validateToolArguments。schemas.ts 的 additionalProperties=false 与 required/nullable 设计限制模型输出；validator.ts 用 strict Ajv 编译同一套 schema。executor.ts 的 switch 只允许 create_task、search_tasks、update_task、complete_task、delete_task，然后调用 TaskRepository 的参数化 SQL。

执行结果序列化为 function_call_output，并用原 call_id 回传下一轮 Responses。模型读到真实结果后给用户自然语言总结。最多 AGENT_MAX_TOOL_ROUNDS 轮。前端随后 refresh 任务板，所以数据库状态而非聊天文字才是真相源。

直接卡片编辑走 PATCH/DELETE，快速添加走 POST；它们与 Agent 工具共享同一个 TaskRepository，因此不是两套假数据。

## 6. 数据库结构

RAG 库包含 courses、documents、ingestion_jobs、chunks、chunks_fts、conversations、messages。关键关系为 course 1:N document，document 1:N chunk/job，course 1:N conversation，conversation 1:N message；删除父记录均有明确 cascade。documents 对 (course_id, sha256) 唯一，chunks 对 (document_id, ordinal) 唯一。FTS 表由 triggers 与 chunks 同步。

Agent 库只有 tasks：title、notes、course_id、status、priority、due_date、source_citation JSON、created/updated/completed timestamps。status/priority/date/length均由应用 schema 和 SQLite CHECK 双重约束。详见 docs/DATABASE_SCHEMA.md。

## 7. 主要 API 端点

| Method | Path | 作用 |
|---|---|---|
| GET | RAG /health | 存活检查 |
| POST | RAG /api/courses | 新建课程 |
| GET | RAG /api/courses | 分页课程 |
| GET | RAG /api/courses/:courseId/documents | 课程资料状态 |
| POST | RAG /api/courses/:courseId/documents | 上传并排队入库 |
| GET | RAG /api/ingestion-jobs/:jobId | 查询入库作业 |
| POST | RAG /api/qa/chat | SSE 课程问答 |
| GET | Agent /health | 存活检查 |
| GET | Agent /api/tasks | 分页/筛选/搜索 |
| POST | Agent /api/tasks | 直接建任务 |
| PATCH | Agent /api/tasks/:taskId | 直接改任务 |
| DELETE | Agent /api/tasks/:taskId | 直接删任务 |
| POST | Agent /api/agent/chat | 自然语言工具循环 |

完整请求、响应、错误和 SSE 示例见 docs/API_REFERENCE.md。

## 8. 50 个核心术语

| # | 术语 | 是什么 | 在本项目做什么 | 为什么需要 | 代码位置 |
|---:|---|---|---|---|---|
| 1 | RAG | 检索增强生成 | 先找课程证据再回答 | 降低无依据回答 | rag/ + services/qa.py |
| 2 | Corpus | 可检索语料集合 | 66 份支持文档 | 决定知识边界 | data/inventory |
| 3 | Ingestion | 资料入库过程 | 验证、抽取、切块、向量化 | 把文件变成可查数据 | services/ingestion.py |
| 4 | Loader | 格式解析器 | 解析 PDF/DOCX/PPTX/MD/TXT | 保留格式差异与位置 | rag/loaders.py |
| 5 | SourceSection | 带位置的文本段 | loader 标准输出 | 让后续格式无关 | rag/types.py |
| 6 | Chunk | 检索最小文本单元 | 保存文本/位置/向量 | 平衡召回与上下文 | rag/chunking.py |
| 7 | Chunk overlap | 相邻块重叠 | 带入前块末尾 | 避免边界语义断裂 | rag/chunking.py |
| 8 | Locator | 页/页码/slide/section | 出现在 chunk/citation | 便于核查原文 | rag/types.py |
| 9 | Embedding | 文本数值向量 | 表示问题和 chunk | 支持语义相似 | rag/embeddings.py |
| 10 | Cosine similarity | 向量夹角相似度 | 排序语义候选 | 与长度相对无关 | cosine_similarity |
| 11 | Keyword retrieval | 词项匹配检索 | 找专有词与精确短语 | 向量会漏精确术语 | keyword_search |
| 12 | FTS5 | SQLite 全文索引 | 索引 chunks.content | 本地快速可解释搜索 | db.py/chunks.py |
| 13 | BM25 | 概率相关性排序 | FTS 候选顺序 | 平衡词频/文档频率 | keyword_search |
| 14 | Vector retrieval | 向量相似检索 | 找同义语义 | 补足关键词表达差异 | vector_search |
| 15 | Hybrid retrieval | 词法+语义检索 | 组合两路候选 | 提升总体召回稳健性 | HybridRetriever |
| 16 | RRF | 倒数排名融合 | 按名次累加分数 | 不混合异质原始分值 | reciprocal_rank_fusion |
| 17 | Top K | 最终命中数量 | 默认取 6 块 | 控制噪声与 token | Settings.top_k |
| 18 | Context budget | 模型证据字符上限 | 截断为 18,000 字符 | 控成本与上下文溢出 | build_context_with_hits |
| 19 | Grounding | 回答绑定证据 | prompt 只允许给定材料 | 减少幻觉 | rag/prompt.py |
| 20 | Citation | 可核查来源对象 | 文件名、locator、excerpt | 建立可验证性 | services/qa.py::_citation |
| 21 | SSE | 单向服务器事件流 | 增量传 answer/citation | 改善等待体验 | encode_sse/streamQa |
| 22 | Conversation | 一次 QA 会话记录 | 关联课程和消息 | 持久化学习历史基础 | conversations table |
| 23 | SHA-256 | 内容哈希 | 去重、绑定 transcription | 不依赖文件名判断身份 | queue_document |
| 24 | OCR sidecar | 扫描件外置转录 | 修复 assignment_2.pdf | 可审阅且不改原 PDF | data/transcriptions |
| 25 | Course isolation | 课程级强过滤 | 两路检索都带 course_id | 防资料串课 | repositories/chunks.py |
| 26 | Responses API | OpenAI 新统一生成 API | 回答流和工具循环 | 同一模型交互范式 | answers.py/client.ts |
| 27 | Function Calling | 模型选择结构化工具 | 把自然语言转 CRUD | 分离意图与执行 | services/agent.ts |
| 28 | Tool schema | 工具参数 JSON Schema | 定义五个动作 | 约束模型输出合同 | tools/schemas.ts |
| 29 | strict mode | 严格结构化输出 | 禁额外字段/完整属性 | 降低形状漂移 | TOOL_DEFINITIONS |
| 30 | Ajv | JS JSON Schema 验证器 | 二次验证每次 tool call | 模型输出仍不可信 | tools/validator.ts |
| 31 | Allow-list executor | 显式可执行函数集合 | switch 五个工具 | 防任意代码/SQL | tools/executor.ts |
| 32 | Tool round | 模型调用到工具回传一轮 | 允许多步操作 | 完成搜索后更新等流程 | AgentService.chat |
| 33 | call_id | 工具调用关联 ID | 对应 function output | 让模型匹配结果 | services/agent.ts |
| 34 | function_call_output | 工具执行结果项 | 把真实 DB 结果回模型 | 最终答复基于事实 | services/agent.ts |
| 35 | Repository pattern | 持久化抽象 | 封装 task/chunk SQL | 便于测试和边界清晰 | repositories/ |
| 36 | Parameterized SQL | 值与 SQL 分离 | 所有用户值作参数 | 防 SQL 注入 | repositories/*.ts/py |
| 37 | SQLite WAL | 预写日志模式 | 改善读写并发 | 本地多请求更稳 | db.py/db.ts |
| 38 | Foreign key | 关系完整性约束 | course/doc/chunk cascade | 防孤儿记录 | RAG SCHEMA_SQL |
| 39 | CHECK constraint | 数据库值域约束 | 状态、长度、日期 | 最后一层不变量 | both db schemas |
| 40 | Provider mode | 外部/离线实现选择 | openai 或 deterministic | 测试不依赖网络/key | config.py/config.ts |
| 41 | Deterministic double | 稳定本地实现 | 固定向量/回答/工具意图 | 可重复验收 | deterministic providers |
| 42 | CORS | 浏览器跨源规则 | 只允许 WEB_ORIGIN | 缩小 API 调用面 | main.py/app.ts |
| 43 | Helmet | Express 安全头集合 | 设置常见响应头 | 减少 Web 攻击面 | agent app.ts |
| 44 | Rate limit | 请求频率限制 | Agent 每分钟 120 | 防滥用/成本失控 | agent app.ts |
| 45 | Pydantic | Python 数据验证 | 配置与 API 合同 | 早失败、清晰错误 | config.py/models.py |
| 46 | TypeScript strict | 静态严格类型 | Web/Agent 全部类型检查 | 降低接口漂移 | tsconfig.json |
| 47 | TDD | 先测试再实现/修复 | 单元/集成覆盖核心行为 | 证明逻辑而非猜测 | tests/ and test/ |
| 48 | E2E | 真实浏览器端到端测试 | 三进程、全库、真 Chrome | 验证用户闭环 | tests/e2e |
| 49 | Persistent disk | 跨部署保留的云磁盘 | Render /var/data | SQLite 不能放临时 FS | render.yaml |
| 50 | SPA rewrite | 任意前端路由回 index | Netlify /* -> /index.html | 刷新 /qa 不 404 | netlify.toml |

## 9. 实战经验与踩坑总结

1. 先做不可变 inventory，再导入。否则“漏文件”和“改了原资料”都无法证明。
2. 旧 .ppt 与新 .pptx 不是改扩展名能解决；不支持就明确登记，避免抽出垃圾文本。
3. 扫描 PDF 必须有显式 OCR 分支。空文本不是“没有相关内容”，而是入库失败。
4. OCR/transcription 要绑定内容哈希，否则文件更新后会误用旧文本。
5. 混合检索不要直接相加 BM25 与 cosine 原始分数；RRF 更透明。
6. course_id 必须进入两条检索 SQL/候选路径，而不是生成前才过滤。
7. citation 应由服务器检索命中生成，不让模型自由输出文件名。
8. Function Calling 的 JSON Schema 只是第一道门；服务器仍需 Ajv、业务校验和 allow-list。
9. SQLite 在云上必须有持久盘；普通容器文件系统会在部署后清空。
10. Playwright webServer 退出不总等于 Windows 子进程彻底退出；按端口+完整命令行确认，不能按 python/node 名称批量杀。
11. PowerShell 5.1 的默认文本编码会把 UTF-8 无 BOM 显示成乱码；读取时显式 -Encoding utf8，不要据乱码误改源文件。
12. 浏览器 console 里的 favicon 404 也是验收失败；静态资源和功能同样需要真实浏览器检查。
13. OpenAI TLS/网络超时发生在 HTTP 响应前时，不能声称 key 或 model 已验证。

## 10. 可练习的扩展题

1. 为 conversations/messages 增加只读历史 API 和前端会话列表。
2. 增加文档删除/重试端点，并用事务证明 FTS 触发器同步。
3. 用真实评测集比较 keyword、vector、hybrid 的 Recall@K 与 MRR。
4. 为不同课程引入可配置 chunk 策略，并记录实验结果。
5. 加一个 VectorRepository 接口和 pgvector 实现，但保留 SQLite 适配器。
6. 将 BackgroundTasks 替换为持久队列，证明进程重启后作业可恢复。
7. 为 Agent 增加批量 reschedule 工具，保持 strict schema 和幂等语义。
8. 增加任务版本号实现 optimistic concurrency。
9. 为上传资料增加授权/用户隔离，不让不同用户看到同一课程。
10. 为每个 tool call 写 audit 表，但避免记录课程全文或密钥。

## 11. 常见 bug 与修复方向

| 症状 | 可能原因 | 修复方向 |
|---|---|---|
| QA 引用了另一门课 | repository 查询漏 course_id | 给 keyword/vector 都加过滤与回归测试 |
| 回答空白但有 done | provider 没有输出 text delta | 维持空答案错误并检查 SDK event 类型 |
| citation locator 错位 | chunk 丢失 SourceSection 元数据 | 让 locator 随 chunk 复制，增加 loader fixture |
| 上传一直 processing | 进程在 BackgroundTask 中断 | 标记/恢复孤儿 job；生产迁持久队列 |
| FTS 查不到专有名词 | query token 清理过度或索引不同步 | 检查 FTS rows、trigger、MATCH expression |
| 任务改完又变回去 | 前端旧请求竞态 | 为 patch 加 loading/序列或版本控制 |
| Agent 重复创建 | 模型重试/工具调用不幂等 | 添加 idempotency key/调用审计 |
| tool call 永远循环 | 模型未理解 error | 保持轮次上限，改善错误提示/系统指令 |
| Render 重部署丢数据 | DB 不在 /var/data | 修正 env 与 disk mount，恢复备份 |
| Netlify 能开首页但 /qa 刷新 404 | 缺 SPA rewrite | 部署 netlify.toml redirects |
| 浏览器 CORS 拒绝 | WEB_ORIGIN 与最终 URL 不完全一致 | 改两个后端并重启 |
| live 模式失败而测试全绿 | 测试用 deterministic provider | 单独做有凭据/网络的 live smoke，不混淆结论 |

## 12. 面试问题与答案要点

1. 为什么是 RRF 而不是 BM25 + cosine 加权？——分值空间不同；RRF 只依赖名次、易解释，权重融合需校准集。
2. 如何保证不串课？——course_id 在 keyword SQL 和 vector candidate load 两处强过滤，再在 citation 保留 courseId，测试跨课问题。
3. 为什么不直接让模型输出 citation？——模型会编造；服务器从真实 hit 生成 citation。
4. 为什么两个 SQLite？——服务自治、迁移/锁/备份边界清晰；跨模块通过 HTTP。
5. Function Calling 安全边界是什么？——模型只提议；strict schema + Ajv + allow-list + 参数化 repository 才执行。
6. deterministic provider 是不是假功能？——它只是可替换模型实现；真实 loaders、检索、SSE、DB、HTTP、工具执行均运行。
7. BackgroundTasks 的生产限制？——进程内、无持久队列、重启可能丢正在执行的 job。
8. SQLite 云部署最大限制？——单机磁盘、不适合横向扩展；需持久盘/备份或数据库适配器。
9. 如何测 RAG 质量？——人工标注 query/evidence，Recall@K、MRR、citation precision、faithfulness、no-answer accuracy、跨课泄漏率。
10. chunk_size 如何选择？——以资料结构、检索评测、模型上下文/成本共同决定，不凭感觉。
11. 为什么 source SHA 重要？——去重、可追溯、OCR sidecar 绑定、导入复现。
12. SSE 与 WebSocket 的取舍？——这里只有服务器单向增量输出，SSE 更简单、HTTP 兼容好。
13. 如何防 prompt injection？——把课程文本视为不可信数据、明确分隔、仅证据回答；不让材料获得工具权限。
14. Tool output 为什么还回模型？——模型需基于真实执行结果总结或继续多步动作。
15. 如何做零停机迁移？——先加兼容 schema/双读写或 adapter、备份、分阶段验证；SQLite destructive change 前快照。

## 13. 技术选型决策

- React/Vite：组件化和快速静态部署；代价是 API URL 为构建期配置。
- FastAPI/Pydantic：Python 文档解析与 OpenAI 生态强、合同清晰；代价是第二运行时。
- Express/TypeScript/Ajv：Function Calling schema 与服务类型一致；代价是跨语言共享类型需人工同步。
- SQLite/FTS5：真正持久、零外部服务、可查看 SQL/BM25；代价是单实例与向量扫描。
- JSON vectors：学习和小语料透明；代价是 O(N) 解析/相似度，规模变大应换索引。
- Responses API：统一流式文本和 tool items；代价是需要理解 output item/event 协议。
- 独立 RAG/Agent 服务：职责与故障域清楚；代价是两个部署和 CORS 配置。
- Netlify + Render：静态站点与带盘长进程各用适合的平台；代价是 Render 持久盘付费且不能横向扩展。

## 14. 从零复现项目

1. 建独立目录，初始化 Git main，先写 PROJECT_SPEC、API/数据合同和 ADR。
2. 用只读脚本递归扫描两门课程目录，输出 path、extension、size、SHA-256、course mapping；永不改原文件。
3. 建 npm workspace 与 Python venv，锁版本，提交空骨架。
4. 先为 RAG schema、chunking、loaders、retrieval 写失败测试，再依次实现。
5. 创建 RAG tables/FTS triggers；实现五类 loader 和定位元数据。
6. 实现 paragraph-aware chunk、OpenAI/deterministic embeddings、keyword/vector、RRF。
7. 实现上传状态机和事务；处理 duplicate、unsupported、scanned PDF。
8. 实现 grounded prompt、Responses SSE、server citations 和 conversation persistence。
9. 先写五个 tool schema/validator tests，再实现 TaskRepository 和 ToolExecutor。
10. 实现 Responses function_call/function_call_output 循环与轮次上限。
11. 实现 Express CRUD/Agent routes、安全头、CORS、rate limit、统一错误。
12. 实现 React 五页、typed clients、SSE parser、citation 和 answer-to-plan。
13. 用 inventory 驱动导入；核对总数、支持数、失败数、chunks 和 source checksum。
14. 运行 CS/GE acceptance queries，证明 citation 与 course isolation。
15. 跑 Python pytest/Ruff/mypy、Node/React tests/typecheck/build、真 Chrome E2E。
16. 做代码审查、secret scan、依赖审计、响应式/无障碍/console 检查。
17. 写 README、architecture、pipelines、schema、API、deployment、references、troubleshooting 和本交接。
18. 部署 Render paid disks 后端与 Netlify 前端；只在获得授权后上传私有课程资料。
19. 在公网重复 10 步用户验收并测试 redeploy 后持久性。

接手时先读 README、docs/ARCHITECTURE.md、docs/RAG_PIPELINE.md、docs/AGENT_PIPELINE.md，然后从失败测试或可复现的用户路径开始改动；不要直接改数据库、降低 schema 严格度或绕过课程过滤。
