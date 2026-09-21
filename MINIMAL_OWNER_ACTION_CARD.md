# MINIMAL OWNER ACTION CARD — Jev + DeepSeek round

Only what cannot be done without you. No secret is requested in chat: every item says where the value
belongs. Everything else (source work, call sites, dataset, calibration, tests, release rehearsal) is
being done without you.

Scope note: the **Laya direction is stopped** and the request for a Laya ECS node in the previous
version of this card is **withdrawn** — no Laya resource was ever created
(`LAYA_PRODUCTION_RESOURCE_CREATED = false`). The architecture is DeepSeek (generation) + TypeSafe Jev
(typed semantic decisions) + the deterministic backend.

---

## 1. TypeSafe Jev credentials + budget (blocks `JEV_LIVE_VALIDATION`, `CALIBRATION`, `ABLATION`)

| Item | Value |
|---|---|
| What is missing | TypeSafe account/API access for the Jev SDK: endpoint + key + the licensed SDK version to pin |
| Where it must live | Backend env only, on `47.114.34.175`: the `JEV_*` variables read by `JevGateway` in `/etc/coursemate/rag.env` (mode 640, `root:coursemate`, exactly like the existing keys). The browser never sees them and the frontend never calls TypeSafe |
| Who provides | You (account owner) |
| Install step | `typesafe-sdk` is deliberately **not** a default dependency (the live transport imports it lazily and raises `JEV_NOT_CONFIGURED` without it, so off/shadow mode works today). Install the pinned MIT package in the backend venv when the key is provisioned: the exact pin is recorded in `DEEPSEEK_AND_JEV_RUNTIME_CONTRACTS.md` and the commented line in `services/rag-api/requirements.txt` |
| Budget request | **One bounded batch, requested now, with the ceiling stated in advance** (see the consolidated plan below). Hard ceilings: **≤ 1,500 Jev decisions**, **≤ 5.0M input+output tokens**, and the USD ceiling you confirm. Failure/timeout attempts count toward it; there is no automatic retry |
| Cost evidence I will produce before spending | the planned call count, per-definition input-token ceilings, the official price applied, and the combined ceiling (Jev + DeepSeek) — printed **before any call**, as `scripts/run_jev_ablation.py --allow-billable --max-cost …` requires |
| Data scope confirmation | Jev receives only the fragments one legal decision needs (course fragment + candidates + criteria) after identity/course/file authorization filtering, and never a full `.env`, Clerk secret, DeepSeek key, other users' private data or unauthorized course text. Please confirm you accept sending course fragments to TypeSafe and whether region/retention restrictions apply |
| One decision that is yours | the Jev arms/definitions that may leave `shadow` for `on`/`advisory`. My default: promote `retrieval.support.v1` plus **one** of context/intent/pedagogy once the calibration gate passes, and keep coverage/assessment advisory — never authoritative |

## 2. DeepSeek API key (blocks `DEEPSEEK_LIVE_VALIDATION`)

| Item | Value |
|---|---|
| What | the API key for the current DeepSeek platform account |
| Where | `/etc/coursemate/rag.env` and `/etc/coursemate/agent.env` on `47.114.34.175`, by you, in the protected env file — not in chat, Git or any report |
| Also confirm | the model alias to pin (`deepseek-flash` per the verified contract) |
| Budget | the cumulative test/annotation cap for this round — see the consolidated ceiling below. I will preflight the exact call plan and refuse to exceed it |

## 1b. Consolidated live-gate budget (one ask, not one per call)

Everything is bounded and printed before the first call. Definitions: the 12 case ids + the 7
structured ids = **19 definitions**; the labelled dataset has **310 samples** (train 196 / calibration
47 / test 67), so nothing here needs a fresh annotation pass.

| Item | Planned calls | Token estimate | Worst case reserved | Hard ceiling |
|---|---|---|---|---|
| Jev canary + calibration (calibration split 47 × ≤2 decisions, retries counted) | ≤ 200 | ≤ 0.6M | +50% for timeouts/failures | **≤ 400 decisions / 1.0M tokens** |
| Jev A/B/C/D/E ablation + module ablation (test split 67, 5 arms + 6 module arms, ≤2 decisions per sample) | ≤ 900 | ≤ 2.5M | +50% | **≤ 1,100 decisions / 3.5M tokens** |
| **Jev total** | **≤ 1,100** | **≤ 3.1M** | — | **≤ 1,500 decisions / 5.0M tokens** |
| DeepSeek canary (10 roles: text, structured, vision, tool replay, plan→work, classification, exercise, problem, explanation, assessment reference, grading feedback) | 10 | ≤ 60k | 2× | ≤ 20 calls |
| DeepSeek live acceptance (real teaching journeys incl. image problems, exercise, five-question grading + feedback) | ≤ 120 | ≤ 1.2M | +50% | ≤ 180 calls / 1.8M tokens |
| **DeepSeek total** | **≤ 130** | **≤ 1.3M** | — | **≤ 200 calls / 2.0M tokens** |
| Embeddings (only if the acceptance re-indexes a document; the deterministic local provider is used otherwise) | ≤ 300 chunks | ≤ 0.1M | — | ≤ 500 chunks |

**Total hard ceiling: ≤ 1,700 paid model calls and ≤ 7.0M tokens.** The USD ceilings stay **yours to
set** — I will apply your published price list to the printed plan and will not start without a number.
Proposed, and easy to lower: Jev **USD 15**, DeepSeek **USD 10**, embeddings **USD 2** → **USD 27**
combined, with any unspent remainder returned in the final report rather than reused.

Still yours to confirm for this batch: region/retention constraints for the course fragments Jev sees
(item 1 above), and which definitions may leave `shadow` (my default: `retrieval.support.v1` plus one of
context/intent/pedagogy; coverage and assessment stay advisory, never authoritative).

Production today still answers with **Qwen/Model Studio** (`V3_MODEL=qwen3.8-max`,
`AGENT_MODEL_NAME=qwen3.8-max`, `OPENAI_CHAT_MODEL=qwen3.7-plus`), so this key is what switches the
generative path to DeepSeek during the release window.

## 3. Production release window (authorization + two confirmations)

You authorized backup, isolated rehearsal, migration, release and acceptance. Two points need a
yes/no because they change the live product:

1. **Model switch on the live site** — publishing this release switches every generative role from
   Qwen to DeepSeek. Confirm it may happen in one window, or tell me to ship the rest first and hold
   the model switch.
2. **Frontend publish** — the site is Netlify project `coursemate-ai-qqtt` (qqttai.com), current deploy
   `6ab02278b7fae664934df25d`. I will publish a locally built artifact with `netlify deploy --prod`
   (rollback = restore the previous deploy) unless you prefer a merge to `main`.

Facts for the same window: production is schema **25** and must go to **29** (migrations 026–029; 029 is
the proposal-only `entity_relations` store), the live release is `4ef5064`, and the rollback rehearsal
will use that real release.

## 4. Real login for browser acceptance (blocks `BROWSER_ACCEPTANCE` / `PRODUCTION_ACCEPTANCE`)

Local Playwright journeys against an isolated identity adapter need no login and are being run
regardless. The **production** acceptance journey does need one real sign-in (学业/课程 → 知识点 →
学习进度 shows 学习中 → 开始测评 → five questions → submit → 测评结果 raw score → 详解 → history /
shared / theme / qualification). I will not bypass Cloudflare/Clerk or create accounts; a short-lived
session or a screen-share is enough.

## 5. Deliberately not requested

* No Laya ECS/GPU/CPU node, no Laya deployment, no Laya package — that direction is closed.
* No new user accounts, no DNS change, no SRSZQ change, no force-push, no old-Singapore writer.
* No additional budget beyond the Jev batch above and the DeepSeek cap.
