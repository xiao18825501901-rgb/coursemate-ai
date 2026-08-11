# Technical References

The implementation is based on primary papers and official project/provider documentation. Retrieval and agent concepts are translated into explicit local code rather than copied as opaque framework defaults.

## Research foundations

- Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks, Lewis et al. The paper establishes the generator-plus-retrieved-nonparametric-memory framing used by the QA flow: https://arxiv.org/abs/2005.11401
- Okapi at TREC-3, Robertson et al. Background for probabilistic term ranking; SQLite FTS5 exposes BM25 ordering used by keyword_search: https://trec.nist.gov/pubs/trec3/papers/city.ps.gz
- ReAct: Synergizing Reasoning and Acting in Language Models, Yao et al. Motivates interleaving model reasoning with environment actions: https://arxiv.org/abs/2210.03629
- Toolformer: Language Models Can Teach Themselves to Use Tools, Schick et al. Broader tool-use foundation: https://arxiv.org/abs/2302.04761

## OpenAI

- Responses migration guide; selected instead of Chat Completions for new work: https://developers.openai.com/api/docs/guides/migrate-to-responses
- Streaming Responses guide; source for response.output_text.delta handling: https://developers.openai.com/api/docs/guides/streaming-responses
- Function Calling guide; source for strict schemas, function_call, call_id, and function_call_output: https://developers.openai.com/api/docs/guides/function-calling
- Embeddings guide; source for embedding creation and semantic similarity: https://developers.openai.com/api/docs/guides/embeddings

## Data and web stack

- SQLite FTS5 official documentation, including BM25 and external synchronization patterns: https://www.sqlite.org/fts5.html
- SQLite foreign keys: https://www.sqlite.org/foreignkeys.html
- Node.js SQLite API; source for DatabaseSync, prepared statements, timeout, and change counts: https://nodejs.org/api/sqlite.html
- JSON Schema specification: https://json-schema.org/specification
- FastAPI file upload: https://fastapi.tiangolo.com/tutorial/request-files/
- FastAPI StreamingResponse: https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse
- React documentation: https://react.dev/reference/react
- Express 5 API: https://expressjs.com/en/5x/api.html
- Vite guide and runtime requirements: https://vite.dev/guide/
- Playwright test assertions: https://playwright.dev/docs/test-assertions

## Hosting

- Netlify Vite setup: https://docs.netlify.com/build/frameworks/framework-setup-guides/vite/
- Netlify environment variables: https://docs.netlify.com/build/environment-variables/overview/
- Netlify CLI deployments: https://docs.netlify.com/api-and-cli-guides/cli-guides/get-started-with-cli/
- Render Blueprint specification: https://render.com/docs/blueprint-spec
- Render infrastructure as code: https://render.com/docs/infrastructure-as-code
- Render persistent disks: https://render.com/docs/disks

## Mapping references to code

| Concept | Primary code location |
|---|---|
| located ingestion | services/rag-api/app/rag/loaders.py |
| chunking | services/rag-api/app/rag/chunking.py |
| BM25/FTS and vector queries | services/rag-api/app/repositories/chunks.py |
| reciprocal-rank fusion | services/rag-api/app/rag/retrieval.py |
| RAG context/prompt | services/rag-api/app/rag/prompt.py and answers.py |
| SSE persistence flow | services/rag-api/app/services/qa.py |
| strict function tools | services/agent-api/src/tools/schemas.ts |
| tool validation/execution | services/agent-api/src/tools/validator.ts and executor.ts |
| Responses tool loop | services/agent-api/src/services/agent.ts |
