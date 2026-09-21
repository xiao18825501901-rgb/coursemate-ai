# SUPERSEDED_BY_JEV_DECISION

This document belongs to the abandoned Laya direction (2026-09-22). The owner stopped Laya
and restored the TypeSafe Jev backend semantic layer. Nothing here is a production source of
truth; it is retained only as history and for the reusable ideas listed in
DSH_JEV_DEEPSEEK_EXECUTION_STATE.md.

---

# DSH_LAYA_DEEPSEEK_EXECUTION_STATE

Round state for the Laya replacement. Everything in 搂1鈥撀? was read live from the estate during this
round (read-only); nothing is inherited from an earlier report.

---

## 1. Verified production baseline (read-only, this round)

| Item | Verified value |
|---|---|
| Source root | `D:/CourseMate_COMPLETE_ARCHIVE_20260918/01_SOURCE_REPOSITORY` |
| Branch / HEAD at round start | `fix/codex-dsh-audit-20260919` / `6b85df75257ede8b88b4034ceb08ca2e66654f90` |
| Production host | `47.114.34.175` 鈥?instance `i-bp1f0vqhds2341pdqqiy`, hostname `iZbp1f0vqhds2341pdqqiyZ` |
| Region / zone / private IP | `cn-hangzhou` / `cn-hangzhou-k` / `172.20.170.40` |
| Host capacity | **2 vCPU / 3 GiB** (load ~0.00) 鈥?cannot host Laya |
| VPC / VSwitch | `vpc-bp1384ux5srgabb6h8se1` / `vsw-bp13nh63x221tquuysvi0` |
| Live release | `/srv/coursemate/current` 鈫?`/srv/coursemate/releases/4ef5064` |
| Services | `coursemate-rag.service` (uvicorn `app.main:create_app` on `127.0.0.1:28000`), `coursemate-agent.service` (node `dist/src/server.js` on `127.0.0.1:28001`), nginx (80/443, `agent.qqttai.com`, `rag.qqttai.com`, `api.srszq.com`) |
| Coexisting, out of scope | SRSZQ on `8.210.58.22` (`api.srszq.com`) and local `/var/www/SRSZQ*` processes 鈥?untouched |
| Live RAG database | `/srv/coursemate/data/releases/20260919T202006Z/rag.sqlite3` 鈫?**schema 25**, migrations 1鈥?5, `integrity_check=ok`, 76 tables |
| Live data volumes | courses 20 (18 private, **2 published**), documents 67, chunks 1,963, learning_workspaces 16, conversations 0, messages 0, assessment_sessions 0, grade_snapshots 0 |
| Live UI-extension database | `/srv/coursemate/data/releases/20260919T202006Z/ui-extension/ui.sqlite3` (3.3 MB, written within the last hour 鈥?the active chat/share store) |
| Live agent database | `/srv/coursemate/data/releases/20260919T202006Z/agent.sqlite3` |
| Uploads | `/srv/coursemate/data/releases/20260919T202006Z/uploads` (119 MB; release data dir 130 MB) |
| Frontend | Netlify project **`coursemate-ai-qqtt`** (`qqttai.com`, `www` 鈫?301), GitHub-linked to `main`, deploy `6ab02278b7fae664934df25d`, live bundle `/assets/ui-UCeSo0VK.js`; Netlify CLI on this machine is authenticated (Qiu Tian / team `Q_WCTJ`) |
| Backups | `/srv/coursemate/backups` 鈥?1.3 GB, latest `20260921-four-changes-final-before-schema13`, also `20260921-four-changes`, `post-hotfix-46415bd`, `pre-hotfix-6e0b8d7`, `post-content-20260920`, `pre-content-20260920`, `post-aa3ffc2` |
| Env files (paths only) | `/etc/coursemate/{rag,agent,monitor}.env` (mode 640, `root:coursemate`), `/etc/coursemate/secrets/`, `/etc/coursemate/env-backups/` |
| Production generative models **today** | Qwen only: `V3_MODEL=qwen3.8-max`, `RAG_CHAT_MODEL=qwen3.8-max` (maas workspace endpoint), `OPENAI_CHAT_MODEL=qwen3.7-plus`, `AGENT_MODEL_NAME=qwen3.8-max`; embeddings `text-embedding-v4` at `dashscope-intl` |
| Uptime | 15 days |

Corrections to older reports (they were stale, as the owner warned): the live release is
**`4ef5064`**, not `5ba6a3a`; the live host is **`47.114.34.175`**, not `47.237.179.69`; the live RAG
schema is **25**, not an assumed 28. `47.237.179.69` is idle (2 vCPU / 1 GiB, ap-southeast-1) and is
**not** reusable for Laya (too small, wrong region).

## 2. Instance search for the dedicated Laya node

| Candidate | Spec | Region | Idle? | Verdict |
|---|---|---|---|---|
| `47.114.34.175` (production) | 2 vCPU / 3 GiB | cn-hangzhou-k | no | rejected: cannot host Laya, must not be squeezed |
| `47.237.179.69` | 2 vCPU / 1 GiB | ap-southeast-1 | yes | rejected: too small, wrong region/VPC |
| `8.210.58.22` (SRSZQ) | 鈥?| ap-southeast-1 | no | out of scope |
| **new instance** | 8 vCPU / 16 GiB, 60 GiB, Ubuntu 24.04 | cn-hangzhou-k, same VPC/VSwitch | 鈥?| **required** |

No RAM role on the production instance, no `aliyun` CLI, no credential file 鈫?I cannot create it
myself; the request is in `MINIMAL_OWNER_ACTION_CARD.md` 搂1 (spec + key fingerprint + the
scoped-RAM alternative).

## 3. Model and dependency facts (verified from the official sources this round)

| Item | Value |
|---|---|
| Model | `convaiinnovations/laya`, subfolder **`multilingual`** |
| HF revision | `1c5edc17a7acd8701df6fc341c0d179f1c62c982` (lastModified 2026-09-20, not gated) |
| License | Apache-2.0 |
| Python package | `laya` **0.3.4** (PyPI, Apache-2.0) 鈥?deps `torch>=2.0`, `transformers>=4.45`, `safetensors>=0.4`, `huggingface_hub>=0.20`, `numpy>=1.20` |
| Encoder | `jhu-clsp/mmBERT-base` (ModernBertForMaskedLM, 22 layers, hidden 768, vocab 256,000, `max_position_embeddings` 8192) |
| Chain budget | `max_len 1024`, **`head_max_len 256`**, `max_prefixes 6` |
| Temperature | `[1.0, 1.0, 1.0]`, `temperature_by_options {}` 鈫?**no calibration applied by default** |
| Request shape | Jev-compatible: `{id: {"type": "choice"|"score"|"noul", "instructions", "criteria"}}` over a `state` |
| Response shape | `choice` 鈫?`{choice, probabilities{key}, confidence, rl_agent.act_probability}`; `score` 鈫?`{score = 危 i路p_i (0..K鈭?), legend, probabilities}`; `noul` 鈫?`{noul = P(true)}` |
| `confidence` semantics | `1 鈭?normalized entropy` of the answer distribution 鈫?**distribution concentration**, never `p_correct` |
| CPU behaviour | official code enables autocast only on CUDA 鈫?**CPU runs FP32** (matches our requirement) |
| Silent-truncation sites (must be pre-checked) | per-option `[:48]` tokens; `opt_budget < 16` 鈫?every option re-cut to `per = max(4,(head_max_len鈭?6)/n)`; `head_ids[:max(8, opt_budget)]`; state `st[:room]` |
| Official limitations we must design around | >20 options at the default head budget collapse (their Banking77: 77 labels 鈫?0.425 vs 0.870); `Router` reloads a checkpoint per language flip on CPU (7.4 s median) 鈫?**serve one resident multilingual checkpoint, never use Router**; the 33 ms figure is GPU and must never be quoted as our measurement |

## 4. Round scope

Replace TypeSafe Jev with self-hosted Laya end to end: adapter + input compiler + 12 real callsites +
receipts (`provider=laya`) + a private inference service + dataset/calibration/ablation (A/B/C/D/E) +
zero-TypeSafe-egress proof + mypy/TypeScript/local-browser checks + staged production release and real
acceptance. Keep DeepSeek for generation/vision/plan-work/explanations/grading feedback, and keep
every already-verified feature (learning-start fact, RRF retrieval + exact locator, raw-score and
latest-valid-result projection, the 16 V2 templates, migration 027 assessment flow, the five-question
fullscreen workspace, `exercise.v2` hidden answers).

## 5. Workstream status (this round)

| # | Workstream | State |
|---|---|---|
| 1 | TypeSafe removal + Laya adapter/gateway/receipts + zero-egress proof | in progress |
| 2 | Laya input compiler (token budget, no silent truncation, provenance) | **DONE** 鈥?`app/laya/{budget,compiler}.py`; 21 tests pass; ruff clean; emits `INPUT_TOO_LONG`/`INSUFFICIENT_CONTEXT` instead of truncating; the emitted `input_ids`/`markers`/`input_tokens` are asserted equal to an independent transcription of the official `build_sequence` on fits **and** truncating cases |
| 3 | Private inference service (FastAPI, health/live vs ready, model-info, single load, queue/deadline, service auth) + packaging | in progress (`services/laya-inference/**` written; tests/verification running) |
| 4 | Real Laya bring-up on this machine | **`REAL_LAYA_INFERENCE` = PASS (dev machine)** 鈥?see 搂5.1 |
| 5 | Judgment dataset (~300 items, label tiers, leakage-safe splits) + calibration + A/B/C/D/E ablation | in progress (`benchmarks/laya-judgments.dataset.json` 275 KB, `laya-calibration.split.json`, `app/evaluation/laya_{calibration,ablation}.py`, `scripts/build_laya_dataset.py`) |
| 6 | 12 business callsites (`LAYA_CALLSITE_MATRIX.md`) | queued behind 1 |
| 7 | mypy / real TypeScript check / local browser journeys | queued 鈥?the repo already has a working Playwright suite (`tests/e2e/*`, 4 configs) with an isolated identity adapter (`scripts/prepare_full_e2e.py`) and a deterministic provider, so no production login is needed |
| 8 | Alibaba Cloud node + deployment | **blocked**: needs the instance (action card 搂1) |
| 9 | DeepSeek live canary | **blocked**: needs the key (action card 搂2) |
| 10 | Production release + real acceptance | **blocked**: needs 搂1鈥撀? |

### 5.1 Real Laya inference evidence (verified, `work/laya-recon/REAL_LAYA_BRINGUP.{json,md}`)

| Item | Measured |
|---|---|
| Status | `REAL_INFERENCE_OK` 鈥?official `laya==0.3.4` API, local directory, `HF_HUB_OFFLINE=1`, no network at load time |
| Model | revision `1c5edc17a7acd8701df6fc341c0d179f1c62c982`, 14 files, 685,377,472 B; `multilingual/model.safetensors` 643,835,514 B (sha256 `9d628fd9鈥8f204`); every file's SHA-256 recorded |
| Resolved deps | torch `2.14.0+cpu`, transformers `5.17.0`, laya `0.3.4`, safetensors `0.8.0`, huggingface_hub `1.32.0`, numpy `2.5.3` (no transformers downgrade needed) |
| Runtime | device `cpu`, dtype `torch.float32` (weights stored F16, upcast; **no quantization**) |
| Chinese results | choice 鏁板 `0.9951` (concentration `0.9746`); noul true `0.9879`; noul false `P(true)=0.4159`; score expected index `0.1244` with legend and `{0.88, 0.1156, 0.0044}` |
| Head-budget behaviour | 6 options 鈫?2 tokens each, concentration `0.9547`; 14 options 鈫?2鈥? tokens each, `0.8833`; **25 long options 鈫?silently re-cut to ~9 tokens each, mass `0.4546/0.3796`, concentration `0.5349`, no `ValueError`** |
| State truncation | 8,000 Chinese chars = 4,973 tokens 鈫?**999 state tokens kept (~1,609 chars)**, `input_tokens=1024`, silent right-side cut |
| Latency (2 torch threads) | p50 **426.0 ms**, p95 **557.2 ms**, mean 440.5 ms (n=25) on an i7-13620H; 1 thread = 717.7 ms |
| Load / memory | load 81鈥?00 s (official loader random-inits a 256k-vocab encoder then overwrites weights), warmup 0.48鈥?.73 s, RSS after load **1,336 MB** |
| Determinism | two identical requests 鈫?bit-identical probabilities |
| Honest limits | 鈮? threads measured only; single-question calls only (no batch amortization measured); no 8 vCPU comparison yet; no peak-memory sampling |


## 6. Facts a successor must not re-derive

* Do not deploy to `8.210.58.22`, do not start the old Singapore writer, do not touch SRSZQ.
* The Laya model must be served from a **local directory** at a pinned revision; no runtime
  `latest` download, no unofficial mirror, no TLS relaxation.
* Production must go **25 鈫?(our new highest)** on migrations; the rehearsal must use the *actual*
  rollback release (`4ef5064`) rather than assuming schema-28 compatibility.
* The published CS3481/GE2324 trees (2 published courses) must not be regenerated.
* `MINIMAL_OWNER_ACTION_CARD.md` is the only outstanding request list.

## 7. Resume instructions

```
RESUME FROM: stage "local implementation" (workstreams 1鈥?), then the cloud gate.
FIRST FILES: MINIMAL_OWNER_ACTION_CARD.md, DSH_LAYA_DEEPSEEK_EXECUTION_STATE.md,
             work/laya-recon/{gh_readme.md,hf_readme.md,rl_agent_api.py,rl_common.py,ml_*},
             docs/jev-deepseek/DECISION_CATALOG_AND_CALIBRATION.md
FIRST COMMANDS (read-only):
  git rev-parse HEAD; git status --short
  services\rag-api\.venv\Scripts\python.exe -m pytest -q --ignore=work     (from services\rag-api)
  services\rag-api\.venv\Scripts\python.exe -m ruff check <files>
NEXT CODE TASK: finish workstreams 1鈥?, then wire the 12 callsites into the business flow.
NEXT TEST: the new Laya suites + the full backend regression on the frozen SHA.
DO NOT REDO: the DeepSeek migration, migration 026/027, V2 templates, the five-question flow,
             the rollback verifier, the ablation harness skeleton.
DO NOT TOUCH: production data, SRSZQ, DNS, secrets, the published course trees.
```

