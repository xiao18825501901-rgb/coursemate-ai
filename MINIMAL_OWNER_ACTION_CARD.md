# MINIMAL OWNER ACTION CARD

One page. Everything below is **only** what cannot be done locally without your explicit
authorization. No secret value is requested in chat — each item says where the value belongs.

## 1. DeepSeek generation credentials (blocks: live model validation)

| Item | Value |
|---|---|
| What is missing | API key + account/region confirmation for the current DeepSeek API |
| Where it must live | Server env for the RAG service (`/etc/coursemate/rag.env` on production, or a local untracked `.env` for a local canary): `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, plus the per-role model alias variable(s) the provider factory reads |
| Who provides | You (account owner). The implementation reads keys only from backend config; nothing is written to source, logs, reports or the frontend |
| Model alias to confirm | The implementation records the alias verified at configuration time; the governing plan expects the current `deepseek-flash` (V4.1-Flash family) — please confirm or correct the alias after checking https://api-docs.deepseek.com/updates/ |
| Budget request | A single bounded batch for the canary: **[to fill: max total CNY/USD, max calls, max input+output tokens]** — covering text streaming, plan/work, structured exercise.v2, five-question generation, image understanding, grading feedback and one Agent tool call |
| What it unlocks | `DEEPSEEK_TEXT`, `DEEPSEEK_VISION`, `DEEPSEEK_AGENT`, `LIVE_MODEL_VALIDATION` statuses |

## 2. TypeSafe Jev credentials (blocks: live semantic layer)

| Item | Value |
|---|---|
| What is missing | TypeSafe account/API access for the Jev SDK (endpoint + key + the licensed SDK version to pin) |
| Where it must live | Server-side gateway configuration only (same env file): `JEV_*` variables read by `JevGateway`; the gateway never exposes them to the browser |
| Who provides | You (account owner) |
| Budget request | Bounded batch for calibration/canary: **[to fill: max total cost, max decisions (12 definitions × cases), max input tokens]** |
| Data scope confirmation | Jev receives only the fragments a single legal decision needs (course fragment + candidates + criteria). Please confirm you accept sending course fragments to TypeSafe, and whether any restriction (region/retention) applies |
| One install step | `typesafe-sdk` is deliberately **not** in `requirements.txt` (the live transport imports it lazily and raises `JEV_NOT_CONFIGURED` without it, so off/shadow mode works today). To enable the live path, install the pinned MIT package: `pip install typesafe-sdk==0.7.0` (a commented line is left in `services/rag-api/requirements.txt` for the release build) |
| What it unlocks | `JEV_GATEWAY` live path, `JEV_RERANK`, `JEV_CONTEXT_AND_INTENT`, `JEV_COVERAGE_REVIEW`, `JEV_ASSESSMENT_REVIEW` (the last two only after calibration passes) |

## 3. Production operations (blocks: PRODUCTION_DEPLOYMENT / PRODUCTION_ACCEPTANCE)

| Item | Value |
|---|---|
| What is missing | Explicit authorization for this session to (a) back up and migrate the three live databases, (b) deploy a new immutable release, (c) run the browser acceptance on the live site with a real login |
| Where | Production host `admin@47.237.179.69` (release dirs `/home/admin/coursemate-v3-releases/`, DBs `/srv/coursemate/{rag,agent,data}`), Netlify for the web app, Clerk for login |
| What it unlocks | `PRODUCTION_DEPLOYMENT`, `PRODUCTION_ACCEPTANCE` |
| Note | The earlier round already recorded that live signed-in acceptance was blocked by Cloudflare/Clerk; a real login (or a prepared test account) from your side is required for the browser journey. I will not bypass the captcha |

## 4. What is already done without any of the above

* Both pack probes converted into permanent failing→passing regressions; learning-start fact and
  global retrieval fusion implemented and covered.
* 16 V2 templates imported with manifest-hash verification and a versioned registry (V1 kept).
* Provider adapters, Jev gateway/catalog, assessment preparation and the fullscreen assessment
  workspace implemented with injected fake transports and contract tests.
* Local regression, typecheck and build run in this workspace.

## 5. How to hand me the values safely

Put them in the backend env file yourself (or a local untracked `.env`), then tell me only:
"DeepSeek configured" / "TypeSafe configured" plus the approved budget numbers. I will run the
canary, record the actual model identity, and report the results (including failures) without
ever printing the key.
