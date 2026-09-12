# CourseMate AI Model Benchmark — V2 Baseline and V3 Stage 7

## V3 Stage 7 status (2026-09-12)

**qwen3.8-max live verification: NOT RUN. Human quality review: NOT RUN.** No paid request, account login or production access occurred. Source/local work at commits `1750cfb` and `5201e76` provides two complementary harnesses:

- `scripts/run_v3_model_canary.py` executes the real v3.2 Planner → major-specific Compiler → Teacher contracts for a fixed synthetic four-major × CASE_A/B matrix, then one synthetic image Problem contract. The full run is exactly 17 calls; one selected teaching case plus image is exactly 3.
- `scripts/run_model_benchmark.py --case-id zh-01` tests the Responses event stream, while `--case-id tool-03` tests search→complete tool calls, strict arguments, `call_id` replay and a final response using content-free simulated tool output.

Both runners have zero SDK retry, conservative whole-run cost ceilings, non-overwriting outputs and per-result checkpoints. Both support a non-billable `--preflight-only` path that returns before reading the API key or constructing a client. For `qwen3.8-max`, both require the exact HTTPS Model Studio compatible-mode path on the Alibaba/DashScope host allowlist. The V3 runner additionally requires `--max-provider-calls`, a bounded local PNG/JPEG and live-only `--confirm-synthetic-image`.

The fixed V3 dataset is `benchmarks/v3-teaching-canary-cases.json`. Artifacts record its hash, the endpoint category rather than secret URL details, the image hash/size rather than bytes/path, Owner-supplied prices/currency, approved maximum, conservative ceiling, actual usage/cost estimate and structured synthetic output. An automated Schema pass is intentionally labeled `PENDING_HUMAN_QUALITY_REVIEW`; it cannot establish domain quality or production acceptance.

Exact preflight/live command templates and the required human rubric are in `docs/v3/DEPLOYMENT_RUNBOOK.md`. Current price, account region, workspace endpoint, entitlement, quota and actual model capabilities remain **UNKNOWN — OWNER VERIFICATION REQUIRED**. Do not substitute another model or endpoint and call it a qwen3.8-max result.

Official documentation rechecked on 2026-09-12:

- Model Studio’s [Base URL reference](https://help.aliyun.com/en/model-studio/base-url) lists the shared and workspace-dedicated regional compatible-mode endpoints, says API keys are region-specific, and recommends workspace-dedicated domains for production. The backend allowlist follows those documented regions and rejects trial/Token Plan endpoints for application backend use.
- The [qwen3.8-max model page](https://help.aliyun.com/en/model-studio/qwen3-8-max) lists regional deployment scopes, context/capability tables and original per-token prices, while explicitly directing users to the console for promotions. Therefore prices are Owner inputs at run time, never constants in source.
- The official [Responses API reference](https://help.aliyun.com/en/model-studio/qwen-api-via-openai-responses) lists qwen3.8-max and structured message/tool input, and the [vision reference](https://help.aliyun.com/zh/model-studio/vision-model) lists image input, Function Calling and structured output. These are documentation-qualified capabilities only; the exact account/endpoint still needs the gated canaries.

## V2 historical decision status

**Live quality benchmark: NOT RUN. Final model selection: NOT APPROVED.**

This is deliberate. Every candidate endpoint is billable, and the V2 authorization explicitly
forbids paid actions without separate approval. The repository now contains a reproducible 50-case
benchmark and a fail-closed runner, but no model was contacted and no quality, latency, or real cost
result is claimed.

The current deploy template still expresses the previous migration intent—Qwen for tutor and Agent,
and Alibaba `text-embedding-v4` for embeddings—but it is not evidence of the actual `qqttai.com`
runtime. No SSH access or production environment files were available in this workspace.

## Evidence levels

- **Official-doc qualified:** capability exists according to current first-party documentation.
- **Local contract verified:** CourseMate's SDK/configuration behavior is covered by automated tests.
- **Live verified:** the exact account, region, model, endpoint, and workload were exercised.
- **Production verified:** the deployed service was observed and smoke-tested.

Only the first two levels are complete. Anything stronger is recorded as unknown.

## Benchmark assets

- Dataset: `benchmarks/tutor-model-cases.json` — exactly 50 cases across Chinese and English
  tutoring, grounded QA, exact locators, multi-turn teaching, general chat, course isolation,
  private-course authorization, prompt customization, and Agent tools.
- Candidate template: `benchmarks/model-candidates.example.json`.
- Runner: `scripts/run_model_benchmark.py`.
- Embedding judgments: `benchmarks/embedding-retrieval-cases.json` (eight resolvable judgments on
  the local official/public CS3481 and GE2324 corpus).
- Embedding runner: `scripts/run_embedding_benchmark.py`.
- Scoring library: `services/rag-api/app/evaluation/model_benchmark.py`.
- Tests: `services/rag-api/tests/test_model_benchmark.py`.

The runner exits before creating a client unless either non-billable `--preflight-only` or live
`--allow-billable` is explicitly supplied. A live run also requires explicit input/output prices,
currency and `--max-cost`. Before constructing the
SDK client it computes a deliberately conservative whole-run ceiling (one UTF-8 byte per possible
input token, tool-schema/protocol allowance, and the full output-token cap) and refuses a run above
the approved maximum. It never writes API keys to results. Automatic checks are intentionally narrow; a human must still score
retrieval relevance, source and citation correctness, teaching depth, step-by-step quality, Chinese
quality, follow-up coherence, hallucination, and instruction adherence.

Example preflight (replace `--preflight-only` with `--allow-billable` only after billing is approved):

```powershell
services\rag-api\.venv\Scripts\python.exe scripts\run_model_benchmark.py `
  --provider "candidate" `
  --model "candidate-model" `
  --base-url "https://provider.example/v1" `
  --api-key-env "CANDIDATE_API_KEY" `
  --output "work\benchmarks\candidate.json" `
  --input-price-per-million <verified-current-price> `
  --output-price-per-million <verified-current-price> `
  --max-cost <approved-maximum> `
  --currency <ISO-4217-code> `
  --preflight-only
```

Run a small compatibility canary first (`--limit 2`), then all 50 cases. Non-tool cases use the
Responses stream and record time-to-first-token, total latency, P50/P95, and streaming support.
The five Agent cases use the same strict task schemas and instructions as the production Agent,
declare an exact expected tool sequence, simulate content-free tool results, replay every original
`call_id`, and require a final natural-language response. They validate JSON argument shape,
tool name/order, and multi-round Responses compatibility without mutating any real task database.
The preflight cost ceiling reserves all three possible Agent response rounds. The client
uses a 60-second timeout and zero SDK retries so the benchmark never hides a second billable attempt.
Repeat each candidate at least three times before treating the latency percentiles as stable.
Output paths are non-overwriting. Each completed case is atomically checkpointed; a provider
failure preserves already-paid evidence without an automatic resume or retry that could double
charge. A successful final artifact records its currency, approved maximum, preflight ceiling and
actual token-based cost estimate. Use a new output path for every repetition.

Custom provider base URLs must use HTTPS and cannot contain credentials, query strings, fragments
or control characters. Plain HTTP is available only for an explicitly enabled loopback development
server (`--allow-insecure-loopback`); it is never allowed for an external host. This validation runs
before either benchmark constructs a client, so an API key cannot be sent to an unsafe destination.

## Current first-party capability matrix

| Candidate | Current official model evidence | Responses API | Tool calls / schema | Context | CourseMate status |
|---|---|---:|---:|---:|---|
| Alibaba / Qwen | Qwen 3.7 Plus and newer variants are listed by region | Documented | Must be canary-tested on the exact endpoint | up to 1M by pricing tier | Eligible; previous config intent only |
| DeepSeek | `deepseek-v4-flash`, `deepseek-v4-pro` | Documented | JSON and tool calls documented | 1M | Eligible; no live account test |
| Moonshot / Kimi | Kimi K3, K2.7 Code, K2.6 | Chat Completions documented | strict tools documented | K3: 1M | Adapter required for current Responses-only code |
| Zhipu / GLM | GLM-5.2 | Not established from reviewed page | function calling and JSON documented | 1M | Adapter/canary required |
| Volcengine / Doubao | Doubao Seed 2.0 family | Documented | Responses function calling documented | model-dependent | Eligible; no live account test |
| MiniMax | MiniMax M3 / M2.7 / M2.5 | Not established from reviewed page | tool generation and OpenAI SDK access documented | M3: 1M | Adapter/canary required |
| OpenAI | GPT-5.6 Luna (current code default) | Native | Native | model-dependent | Local SDK contract only; no live call |

Important: “OpenAI compatible” does not necessarily mean “OpenAI Responses compatible.” Kimi's
official API page is Chat Completions; GLM and MiniMax documentation reviewed here does not prove the
exact Responses event contract CourseMate consumes. They remain valid benchmark candidates only
after an adapter or a successful canary.

## Embedding decision

Alibaba's current `text-embedding-v4` documentation says it is multilingual, supports configurable
64–2048 dimensions, and is priced in Singapore at CNY 0.514 per million input tokens. CourseMate's
existing embedding client and batch-of-10 behavior remain locally tested. However, changing an
embedding model or dimension requires full corpus re-embedding and retrieval regression; never mix
vectors from different model/dimension contracts in one index.

**Provisional embedding candidate:** `text-embedding-v4` in the same compliant region as the corpus.

The independent embedding runner re-embeds all chunks from only the selected official/public
courses into memory, embeds the eight queries, ranks strictly within each course, and reports
Recall@K/MRR, latency, dimension, usage and cost. It writes only case/course/chunk identifiers and
metrics—never chunk text or vectors. Like the generation runner, it requires explicit billable
opt-in, current price/currency and a conservative total-cost ceiling, refuses output overwrite and
uses zero SDK retries.

Example after billing is approved:

```powershell
services\rag-api\.venv\Scripts\python.exe scripts\run_embedding_benchmark.py `
  --provider "candidate" --model "candidate-embedding-model" `
  --base-url "https://provider.example/v1" --api-key-env "CANDIDATE_API_KEY" `
  --database "data\rag.sqlite3" --output "work\benchmarks\candidate-embedding.json" `
  --input-price-per-million <verified-current-price> `
  --max-total-cost <approved-maximum> --currency <ISO-4217-code> --allow-billable
```

Run every candidate at least three times. Compare retrieval metrics first, then dimension/storage,
latency, cost, region and operational stability. This harness uses the currently available local
official course corpus; production data is neither required nor authorized.

**Final status:** runnable real-corpus comparison exists; live candidate results and the winner are
still pending paid-run authorization.

## Provisional deployment positions (not benchmark winners)

- **Tutor:** keep the currently configured Qwen 3.7 Plus intent until a 50-case live comparison
  shows a better quality/cost/latency trade-off. This minimizes migration risk; it is not a claim that
  Qwen won.
- **Agent:** use only a model whose exact endpoint passes all tool cases and multi-round call-id replay.
  Qwen, DeepSeek V4, and Doubao have documented Responses paths and are the first canary candidates.
- **Embedding:** `text-embedding-v4` is the first candidate because of multilingual retrieval support,
  deployment-region alignment, and low documented input cost.
- **Fallback:** disabled by default. A fallback provider is not selected until both primary and
  fallback pass the same benchmark and a cost ceiling is approved.

## Fallback safety design

Do not silently retry a full generation on another paid provider. A later fallback implementation
must include all of the following:

1. one short connect/read timeout and no retry for validation/auth/rate-limit failures;
2. at most one cross-provider attempt for explicitly classified transient failures;
3. idempotency protection for Agent tools—model fallback occurs before executing any mutation;
4. circuit state with cooldown to stop repeated double charges;
5. structured logs containing provider, model, request ID, latency, token usage and failure class, but
   never prompts containing private course text or credentials;
6. per-request and monthly cost ceilings plus a feature flag to disable fallback instantly.

Until those controls exist, `primary failure -> explicit error` is safer than automatic double billing.

## Official sources reviewed

- Alibaba model availability/pricing: https://help.aliyun.com/zh/model-studio/model-pricing
- Alibaba Responses API: https://help.aliyun.com/zh/model-studio/openai-responses-api/
- Alibaba `text-embedding-v4`: https://help.aliyun.com/zh/model-studio/text-embedding-v4
- DeepSeek model/pricing and Responses/tool support: https://api-docs.deepseek.com/quick_start/pricing/
- Kimi Chat Completions/tool API: https://platform.kimi.ai/docs/api/chat
- Kimi model/pricing overview: https://platform.kimi.ai/docs/pricing/chat
- GLM-5.2 capabilities: https://docs.bigmodel.cn/cn/guide/models/text/glm-5.2
- Doubao Responses tool calling: https://www.volcengine.com/docs/82379/1958524?lang=zh
- Doubao pricing: https://www.volcengine.com/docs/84458/1585097?lang=zh&redirect=1
- MiniMax API/model overview: https://platform.minimaxi.com/docs/api-reference/api-overview
- OpenAI model guide: https://developers.openai.com/api/docs/models

Prices and model aliases are time-sensitive. Recheck these pages immediately before any paid run or
production switch.

## Stage 5 acceptance

- 50-case eval dataset: **PASS**
- fail-closed, credential-safe, budget-capped and checkpointed runner: **PASS**
- official-course embedding retrieval dataset and budget-capped runner: **PASS locally**
- independent tutor / Agent / embedding variables with legacy fallback: **PASS**
- local Responses/configuration contract tests: **PASS**
- real provider quality, latency, cost comparison: **BLOCKED — paid calls not authorized**
- final recommended winners and production migration: **BLOCKED — benchmark evidence absent**

Therefore final acceptance criterion G remains **NOT PASS**. No provider change should be represented
as benchmark-driven until real result artifacts and human rubric scores are committed.
