# Provider Capability Matrix — DeepSeek generation

Verification date: **2026-09-21** (UTC+08:00). Sources read directly at that
time (no cached copies, no SDK type inference, no model self-description):

- https://api-docs.deepseek.com/updates/ — model release + alias
- https://api-docs.deepseek.com/guides/responses_api/ — Responses API contract
- https://api-docs.deepseek.com/api/create-response/ — Responses request/response fields
- https://api-docs.deepseek.com/guides/vision/ — image schema + limits
- https://api-docs.deepseek.com/guides/thinking_mode/ — native thinking toggle
- https://api-docs.deepseek.com/guides/json_mode/ — Chat Completions JSON mode
- https://api-docs.deepseek.com/quick_start/pricing/ — models, features, pricing

## Model and endpoints (OFFLINE_CONTRACT)

| Field | Value | Evidence |
|---|---|---|
| Model alias | `deepseek-flash` | updates + pricing |
| Model version | DeepSeek-V4.1-Flash (released 2026-09-10) | updates |
| OpenAI-format base URL | `https://api.deepseek.com` | responses_api + pricing |
| Chat Completions path | `/chat/completions` | vision + json_mode |
| Responses path | `/responses` | create-response |
| Vision | native (JPEG/PNG/GIF/WebP) | vision |
| Context length | 1M | pricing |
| Max output | 384K (maximum) | pricing |

Retired aliases `deepseek-v4-flash` and `deepseek-v4-flash-vision-exp` route to
`deepseek-flash` and are **not** used by this migration.

## Evidence levels

- **OFFLINE_CONTRACT** — read and pinned from the official reference pages above.
- **LIVE_VERIFIED (updated 2026-09-24, round 96)** — proven against the real API. The credential
  arrived, and **ten roles are now live-verified** on `deepseek-flash` at `https://api.deepseek.com`
  (8,728 input + 4,477 output tokens, USD 0.0079908, every `observed_model` matching the pinned alias):
  `work/current-change/deepseek-live-evidence-r81e.json`, per-item verdicts in
  `DEEPSEEK_LIVE_ACCEPTANCE.md` §2. What that does **not** cover: pedagogical quality (the artifact
  says `manual_review_status: REQUIRED`), streaming (the canary pins `stream=False`), and tool replay
  (no tool role in the plan).
- **NOT_RUN** — still true for streaming, tool replay, and every production-host call; the original
  reason given here ("no credentials") no longer applies, the statuses that remain do.

## Role → protocol → model (explicit, no fallback)

| Role | Protocol | Model | Code path |
|---|---|---|---|
| UI teach / problem (cm_update) | Responses (default) or Chat Completions | `deepseek-flash` | `app/cm_update/provider.py::DeepSeekProvider` |
| UI exercise.v2 (structured) | Responses `text.format` json_schema | `deepseek-flash` | same, forced Responses |
| UI explanation | Responses (default) | `deepseek-flash` | same |
| UI classification | Responses (default) | `deepseek-flash` | same |
| V3 LearningProvider (plan/unit/problem/grade) | Responses | `deepseek-flash` | `app/learning/provider.py::LearningProvider` |
| Coverage reviewer | Chat Completions | `deepseek-flash` | `app/learning/coverage_review.py::deepseek_review_invoke` |
| Grounded QA | Responses | `deepseek-flash` | `app/rag/answers.py::DeepSeekAnswerProvider` |
| Node Task Agent | Responses | `deepseek-flash` | `services/agent-api/src/openai/client.ts` |

`qwen3.8-max` / `QwenProvider` / `qwen_review_invoke` / `OpenAIAnswerProvider`
remain **only as historical classes for reading old records**. A new generation
request can never be routed to Qwen: the selection is the explicit model string
above, and there is no silent provider switch.

## Capability × evidence level

### Chat Completions (`/chat/completions`)

| Capability | Evidence level | Notes |
|---|---|---|
| text | OFFLINE_CONTRACT | `messages` + `content` |
| text streaming | OFFLINE_CONTRACT | SSE; terminal `finish_reason=stop` |
| JSON mode (`response_format={"type":"json_object"}`) | OFFLINE_CONTRACT | json_mode guide |
| json_schema `response_format` | NOT_RUN | not documented on Chat Completions; use Responses `text.format` |
| image input | OFFLINE_CONTRACT | `image_url` content part + `detail`; user messages only |
| tool calls (function) | OFFLINE_CONTRACT | thinking_mode guide |
| thinking toggle (`thinking={"type":"disabled"}`) | OFFLINE_CONTRACT | thinking_mode guide |
| usage | OFFLINE_CONTRACT | `usage` in final chunk |

### Responses (`/responses`)

| Capability | Evidence level | Notes |
|---|---|---|
| text | OFFLINE_CONTRACT | `input` string or item list |
| text streaming | OFFLINE_CONTRACT | SSE, terminal `response.completed/incomplete/failed` |
| `text.format` json_schema | OFFLINE_CONTRACT | `{type, name, schema}` — no documented `strict` |
| image input | OFFLINE_CONTRACT | `input_image` + `image_url` + `detail` |
| function tools | OFFLINE_CONTRACT | `tools` (function) |
| function call replay (`function_call`/`function_call_output` + `call_id`) | OFFLINE_CONTRACT | create-response |
| reasoning effort control (`reasoning={"effort":"none"}`) | OFFLINE_CONTRACT | create-response |
| usage incl. cached + reasoning tokens | OFFLINE_CONTRACT | `input_tokens_details.cached_tokens`, `output_tokens_details.reasoning_tokens` |
| status completed/incomplete/failed | OFFLINE_CONTRACT | create-response |

### Live (NOT_RUN — needs credential)

| Capability | Evidence level | Credential / authorization required |
|---|---|---|
| live text streaming | NOT_RUN | `DEEPSEEK_API_KEY` + approved budget |
| live json_schema structured output | NOT_RUN | `DEEPSEEK_API_KEY` + approved budget |
| live vision (image) | NOT_RUN | `DEEPSEEK_API_KEY` + approved budget |
| live tool-call replay | NOT_RUN | `DEEPSEEK_API_KEY` + approved budget |
| live pricing/billing reconciliation | NOT_RUN | `DEEPSEEK_API_KEY` + approved budget + top-up |

## Payload contract (no Qwen-only fields)

The adapter never emits Qwen-only fields (`enable_thinking`, `max_pixels`) to
DeepSeek. Native thinking is explicitly disabled because the product implements
its own two-stage plan→work:

- Responses: `reasoning={"effort":"none"}`; structured output via `text.format`.
- Chat Completions: `thinking={"type":"disabled"}`.

Images use the documented `detail` field (`low`/`high`/`original`/`auto`), never
`max_pixels`.

## Boundaries

- **Embeddings stay independent.** Alibaba `text-embedding-v4` continues to serve
  the vector index (`app/rag/embeddings.py`, `rag_embedding_*` settings). No
  embedding dimension was changed and no index was rebuilt by this migration.
- **exercise.v2 is unchanged.** The private-answer structured contract
  (`app/cm_update/exercise_contract.py`) and its parser are byte-for-byte the
  same; only the transport (Chat Completions `response_format` json_schema →
  Responses `text.format` json_schema) is adapted inside `DeepSeekProvider`.
