# MINIMAL OWNER ACTION CARD — Jev + DeepSeek round

> ## Update 2026-09-24 (rounds 83–84) — read this before §1 and §2 below
>
> **The requests in §1 and §2 are answered and no longer block anything.** The TypeSafe key and the
> DeepSeek key are in the protected local store (`C:\Users\Hp\.coursemate\rag.env`, ACL reduced to one
> principal), `typesafe-sdk==0.7.0` is installed, and both providers have now been called live:
> 31 live Jev cases over all **19** definitions, plus a live DeepSeek baseline (162 answered calls).
> **No key was requested in chat and none was sent.**
>
> What the live validation changed, stated plainly: **the quality gate does not pass.** Against a real
> DeepSeek baseline on the 47-sample calibration split, Jev improves citation support (0.667 → 0.833)
> and the unsupported-claim rate (0.667 → 0.500), worsens `criterion_error` (0.000 → 0.333, one case
> of three) and `key_fact_retention` (1.000 → 0.000, one case of two), **ties** on `intent_accuracy`
> (0.667 both sides), and ties elsewhere. So **every definition stays `shadow` and nothing is
> promoted**, including the retrieval-rerank promotion §1 previously proposed as the default. The
> per-definition populations are 1–8 samples, so the promotion decision belongs on the test split
> once thresholds are frozen (`JEV_CALIBRATION_AND_ABLATION_REPORT.md` §9).
>
> **What is still yours, in this order:**
>
> 1. **Production native approvals and one real login** — the release sequence in §15 of the task
>    (local final green → live validation → freeze release → consistent backup → isolated restore →
>    migrations rehearsal → rollback check → immutable backend → protected env → frontend build →
>    Netlify → real users → post backup → monitoring → push → final report). The backend release needs
>    your server-side approval; the frontend needs one real sign-in.
> 2. **The school's Canvas Developer Key** — still the only gate on the *public* OAuth path
>    (`CANVAS_OAUTH_LIVE = WAITING_INSTITUTION`), and the reason the owner-mode one-off token path
>    exists at all.
> 3. **Revoke the two Canvas tokens pasted into chat** and supply a replacement through the local
>    hidden prompt, so your own small-sample live test can run
>    (`scripts/canvas_owner_smoke_test.py`).
> 4. **Two decisions, not blockers:** whether to take the promotion decision on the test split now
>    that calibration numbers exist, and separately whether the campus qualification policy moves to
>    `verified_only` (its count must be measured on the production database with the read-only tool —
>    it is stated as unmeasured, not estimated).
>
> A production **budget** request is still owed before the live production journeys, with the ceiling
> stated before any call; it is not made here yet because the local gate has not finished.

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

## 1b. Consolidated live-gate budget (one ask, not one per call) — **re-measured 2026-09-24**

The version of this section that stood here was written from estimates before any live call. It is
replaced with measurements, because the live runs have now happened and the real per-call cost is
three orders of magnitude smaller than the estimate assumed. Everything is still bounded and printed
before the first call; only the numbers changed.

**What the live runs actually cost** (`work/current-change/deepseek-live-evidence-r81e.json`,
`jev-ablation-live-baseline3.json`, `jev-live-cases.json`; computed by
`work/current-change/compute-live-budget.py`):

| Measured fact | Value |
|---|---|
| DeepSeek per call, 10 canary roles | min **$0.0000642**, mean **$0.0007991**, max **$0.0038862** (the `EXERCISE_V2` role) |
| DeepSeek, 10 roles total | 8,728 input + 4,477 output tokens → **$0.0079908** |
| DeepSeek, ablation baseline | **43** calls (not 162: memoising the baseline removed 119 repeat calls) at 267 in / 7 out tokens per call |
| Jev live decisions made so far in this work | **315**: 99 (31 case sweep + 53 A–E ablation + 15 probes) + **169** (the structured browser run, round 90) + **47** (the promoted exact-locator run, round 92 — 9 `retrieval.support.v1` in mode `on` and 38 shadow decisions the same runs make). Every one `outcome=ok` and every one carrying a `model_version` |
| Jev token usage | **not reported by the transport** — it returns a request id and a model, not usage |
| Jev decision latency | **0.65–1.36 s** observed across those decisions (an observation, not a percentile) |

**I went over the ceiling stated here, and it is recorded rather than absorbed.** That ceiling was
≤300 decisions; the total is **315**. The overspend is the round-92 locator run: I estimated 10–20
decisions for it and it cost 47, because a promoted definition does not replace the rest of the
pipeline — every teach run also makes its shadow-mode decisions for the other definitions, and my
estimate counted only the promoted one. The run closed a §16 item that had been marked PARTIAL
("an exact question number is never replaced by a semantic ranking", now asserted end-to-end against a
**live** rerank), which is why it was spent rather than deferred. No further live run has been started
since, and none will be without the decision below.

**One production setting this measurement changes.** The tool-intent guard (`module F`) defaults to a
**1500 ms** budget, and the live decision measured 1.35 s — so on the first attempt at the
explicit-write acceptance journey the guard gave up before the answer arrived and a legitimate,
explicit write was refused. Fail-closed is the correct behaviour; the margin is not. Any deployment
that sets `JEV_TOOL_INTENT_MODE=enforce` should also set `JEV_TOOL_INTENT_TIMEOUT_MS` to at least
**5000** (the agent bounds it to 100–10 000). This is an operator setting, not a code change, and it
belongs in the release checklist next to the Jev env values.


**The request, scaled to §16's production journeys** (4 course shapes × 15 steps = 60 operations):

| Item | Planned calls | Worst case reserved | Hard ceiling | Measured basis |
|---|---|---|---|---|
| Jev live acceptance | ≤ 180 decisions | +50% for timeouts | **≤ 300 decisions** | **315 already made**, all answered; 1–3 decisions per operation |
| Jev live **component ablation** (§10's six modules) | **93 decisions** | — | included above | **counted, not estimated**: `work/current-change/count_component_ablation_calls.py`, 58 of them `M-CITATION` and 7 for each of the other five; 0 DeepSeek calls |
| DeepSeek live acceptance (teaching, image problem, exercise, five-question grading, feedback) | ≤ 120 calls | 3× operations, every call at the measured **maximum** | **≤ 200 calls** | measured max $0.0038862/call |
| Embeddings | ≤ 500 chunks | — | ≤ 500 chunks | unchanged; the deterministic provider is used unless a journey re-indexes |
| **Total** | **≤ 300 paid model calls** | — | **≤ 500 calls** | the estimate this replaces was ≤ 1,700 |

**One decision I am asking for inside this item.** The component ablation is the last piece of §10 that
is local-and-ready: the harness runs, the six arms read the right populations, and the command is
`services\rag-api\.venv\Scripts\python.exe scripts\run_jev_semantic_ablation.py --arm all-components
--transport live --allow-billable --out <fresh path>` — 93 Jev decisions, no DeepSeek. It is **not
run**: 315 + 93 = **408**, which crosses the ≤300 ceiling stated above (and I have already gone over
that ceiling once, see the note in the table). The request is therefore **≤ 450 decisions** in total,
which covers the ablation with 42 to spare; the alternative is to skip the ablation and say so in the
final report. Until that decision arrives it stays recorded as NOT_RUN.

**The data blocker for §14 is cleared as of round 95; the budget is now the only one.** The promotion
the task lists first is `retrieval.support.v1`, and until this round it could not be fitted at all: all
ten of its groups happened to hash outside the calibration slot, so it had 36 train and 22 test samples
and **zero** calibration samples. The dataset now carries 345 samples (from 310) with a 58-sample
calibration split (from 47), `retrieval.support.v1` has 10 calibration samples, and the three other
definitions that had no usable slot (pedagogy, entity, extraction) are covered too. Every added label
comes from its family's own deterministic rule, and the previous hashes are kept in the reports because
the live results already measured refer to them. So what the promotion now needs is exactly what is
requested above: the live ablation (93) **plus** a fit over the new calibration split — I estimate
**≤ 60 further decisions** for the fit and the single test-split evaluation that follows it. Add it to
the same decision: **≤ 500 decisions** would cover the ablation and the first promotion's calibration
end to end, with no DeepSeek call in either.

**USD.** DeepSeek: the worst case above is **$0.70** (180 calls × the measured maximum $0.0038862), so
a cap of **USD 3** leaves more than 4× headroom and is what I am asking for. Jev: **I cannot state a
USD figure honestly** — the transport reports no token usage and no TypeSafe price list is available
to this environment, so any number from me would be invented. The call count is ≤ 300; please apply
your plan's rate and set that figure. **Combined cap requested: USD 3 + your Jev figure.**

Two things that have not changed: unspent remainder is returned in the final report rather than
reused, and I do not start a paid run without the ceilings in hand.

**Also still yours in this item, unchanged:** region/retention constraints for the course fragments
Jev sees, and which definitions may leave `shadow`. On the second: my earlier default was
`retrieval.support.v1` plus one of context/intent/pedagogy, and **the measurements do not support
promoting any of them yet** — citation support improves and `criterion_error` / `key_fact_retention`
worsen, on populations of one to eight samples (§9 of `JEV_CALIBRATION_AND_ABLATION_REPORT.md`). The
mechanism now exists (`JEV_DEFINITION_MODES`); the evidence for using it does not.

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

Facts for the same window: production is schema **25** and must go to **30** (migrations 026–030; 029 is
the proposal-only `entity_relations` store and 030 the durable feedback queue), the live release is
`4ef5064`, and the rollback rehearsal will use that real release.

## 3b. Two production risks I found in the read-only verification (2026-09-22T01:59Z)

Both are outside the release's own scope, both need your decision, and neither was caused by this work.

| Finding | Evidence | What I recommend |
|---|---|---|
| **The backend services are not enabled at boot.** `coursemate-rag` and `coursemate-agent` declare `WantedBy=multi-user.target` but are `disabled`; `list-dependencies --reverse multi-user.target` shows neither is boot-wired. They are running only because they were started by hand. A reboot would leave nginx up in front of nothing. | `systemctl is-enabled` = `disabled` for both; uptime 15 days, so the risk has not been exercised yet | one zero-downtime command in the release window: `systemctl enable coursemate-rag coursemate-agent`. Say yes and I include it as release step 8; say no and I will leave it untouched and record it as an accepted risk |
| **Backups are not scheduled, so the readiness monitor reports failure.** The newest snapshot is 32 hours old while the monitor's own policy is 26 hours (`MAX_BACKUP_AGE_SECONDS=93600`), so `coursemate-monitor` (a 5-minute timer) exits non-zero and systemd marks the unit `failed`. Its log is otherwise green: rag healthy, agent healthy, disk 27 GB free. There is no `coursemate-backup.timer`; SRSZQ has one, CourseMate's snapshots are manual. | `journalctl -u coursemate-monitor` shows `{"status": "failing", … "backup": "latest backup is stale (191857s old)"}`; `systemctl list-timers` has no CourseMate backup timer | the release takes a fresh pre-release backup anyway (step 4), which clears the check; decide separately whether to add a scheduled backup timer so it stays clear |

Also confirmed on that pass, so the plan's assumptions hold: `current` → `4ef5064` (also the newest
release directory), RAG schema 25 with `integrity_check=ok` and 20 courses / 67 documents / 1963 chunks
/ 16 workspaces, the official CS3481 + GE2324 knowledge nodes present and untouched, uploads 119 MB,
backups 1.3 GB, disk 27 GB free, TLS valid to November/December 2026, and `qqttai.com` +
`rag.`/`agent.qqttai.com` answering 200. No `JEV_*`/`TYPESAFE_*` variable exists in the protected env
yet, and I read only variable **names**, never values.

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
* No production change outside the release window: the read-only verification made **no** changes to
  the live host (no writes, no restarts, no unit enablement) — the two findings in §3b are reported for
  your decision instead of being fixed silently.
