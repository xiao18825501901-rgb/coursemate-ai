# OWNER ACTIONS ONLY

Everything in this file is something **only you can do** — because it needs your account, your
credential, your money, your production authority, or a product decision that is yours to make.
Everything else is already done or is being done by me; see `CURRENT_BLOCKER_LEDGER.md`.

**Read this first:** there are exactly **four** actions. Doing #1 and #2 unlocks every remaining
technical item; #3 and #4 are one-way-door decisions for the release.

| # | Action | Unlocks | Cost | Reversible? |
|---|---|---|---|---|
| 1 | Put a TypeSafe Jev credential into the backend's protected env | live Jev validation, calibration, all ablations, any promotion out of `shadow` | paid per call | yes (remove the var) |
| 2 | Put a DeepSeek API key into the same protected env (**exact variable names differ per service — see Action 2**) + approve a token ceiling | DeepSeek live acceptance, and the full real-user teaching path | paid per call | yes |
| 3 | Approve a production window (or explicitly defer it) | deployment, migration rehearsal, real acceptance | infra only | yes, but a deploy writes data — see rollback |
| 4 | Answer one product question about document-side extraction | closes the last local design gap | free | yes |

---

## Action 1 — TypeSafe Jev credential

**Why it must be you.** The key authorises paid model calls against *your* TypeSafe account. I cannot
create an account, accept terms, or pay on your behalf, and the key must never travel through chat.

**Exact platform.** TypeSafe (`docs.typesafe.ai`). The adapter is
`app/jev/gateway.py::SdkTransport`, which lazy-imports the SDK and fails **typed** — `JevNotConfiguredError`
when no credential is present, `JevUnavailableError` when the SDK is missing — before any network access.

**Two things are needed, and one of them was wrong until this round.** Written down plainly, because
both were defects in the previous version of this document:

1. **The credential variable.** The adapter used to accept the key **only** as a constructor argument,
   while the gateway builds `SdkTransport()` with no arguments — so the service never read
   `TYPESAFE_API_KEY` and *no* environment change could have enabled the live path. That is **fixed in
   code** (`SdkTransport` now resolves the key from the environment, an explicitly passed key still
   wins, and `TYPESAFE_MODEL` overrides the default model id). Verified by running it: with the variable
   set the guard passes and the next failure is only the missing SDK; without it the typed
   `JevNotConfiguredError` still fires.
2. **The SDK itself is not installed.** This document previously said the SDK was "already a dependency,
   vendored under `services/rag-api`" — that was **false**. `services/rag-api/requirements.txt` carries
   it **commented out** as an optional extra (`#   typesafe-sdk==0.7.0`), and it is absent from the venv
   (checked: `importlib.util.find_spec("typesafe_sdk")` is `None`). So the key alone is not enough: the
   package must be installed into the service's virtualenv as part of the same change, otherwise every
   live call fails typed with `JevUnavailableError: typesafe-sdk is not installed`. I can do that
   installation when you approve the window, or you can; it is one `pip install` against the pinned
   version, and it is reversible.

**Read or write?** Read-only usage: the adapter asks typed questions and records the answers in
`jev_decision_receipts`. It writes nothing to your TypeSafe account beyond the calls themselves.

**Existing access — what I checked.** There is **no** `TYPESAFE_*` or `JEV_*` variable in
`/etc/coursemate/{rag,agent,monitor}.env` (verified read-only 2026-09-22T01:59Z, variable *names*
inspected, values never printed). So no access exists today; this is not a "key stopped working"
situation.

**Which app to open / where to type it.** Use the protected path you already use for the other
secrets: edit `/etc/coursemate/rag.env` (mode 640, `root:coursemate`) over your existing admin SSH
session, or your normal secret manager if that is how the other keys got there. **Do not paste the key
into this chat, a report, a ticket, or a commit.** The variable name to set is:

```
TYPESAFE_API_KEY=<your key>
```

If your TypeSafe account names the model something other than the adapter's default (`jev`), also set
`TYPESAFE_MODEL=<model id>` — that is a *name*, safe to state in chat if you are unsure.

**What you should see afterwards (non-sensitive proof).** On the next backend start, the service logs
and the health surface stop reporting the Jev layer as unconfigured; the first decision writes a
receipt row whose `mode` is `shadow` and whose `model_version` is non-null. I can verify this from my
side with one bounded call — **you do not need to test anything.**

**What it unlocks.** Ledger B-01 → B-05(ii) → B-07 (the whole quality chain).

**Cost.** Paid per call, no subscription. Nothing is spent until the first call I make, and I will not
make one until #2's ceiling is approved (see below).

**Reversible.** Yes: remove the variable and restart; every definition stays in `shadow` regardless,
so the product keeps its current behaviour.

---

## Action 2 — DeepSeek key + one token ceiling

**Why it must be you.** Same reasons: your account, your money.

**Exact platform.** DeepSeek's API (the product's production stack already points at Qwen today:
`V3_MODEL=qwen3.8-max`, `RAG_CHAT_MODEL=qwen3.8-max`, `AGENT_MODEL_NAME=qwen3.8-max`,
`OPENAI_EMBEDDING_MODEL=text-embedding-v4`). The code is DeepSeek-only with **no Qwen auto-fallback**
(asserted by an egress-spy test), so once the key is present the generation path switches.

**Read or write?** Generation calls only. Embeddings are a separate contract and are **not**
re-embedded as part of this work.

**Existing access — what I checked.** No DeepSeek credential variable exists in the production env
files, and no `TYPESAFE_*`/`JEV_*` either. Note the distinction that the variable table below makes
concrete: the *variables that will carry* the switch (`V3_MODEL`, `RAG_CHAT_MODEL`,
`AGENT_MODEL_NAME`, and their key/base-url companions) **do** exist and currently hold the Qwen path,
so this action re-points them rather than adding new ones. The canary CLI
(`app/evaluation/deepseek_canary.py`) and its preflight (which prints a token ceiling *before* calling)
are already in the repo and ready to run.

**Which app to open / where to type it.** Same protected path as Action 1. **The variable names differ
per service — this matters more than it looks.** An earlier version of this document said
`DEEPSEEK_API_KEY`, which **no code in this repository reads**; in the RAG service an unrecognised
variable name is silently ignored (its settings model sets `extra="ignore"`), so that single line would
have produced no error and no switch. Corrected from the code, one service at a time:

| Service (systemd unit) | Variables to set | Where |
|---|---|---|
| `rag-api` — V3 teaching/generation path (`coursemate-rag`) | `V3_MODEL=deepseek-flash`, `V3_MODEL_API_KEY=<your key>`, and either **remove** `V3_MODEL_BASE_URL` or set it to `https://api.deepseek.com` | `/etc/coursemate/rag.env` |
| `rag-api` — grounded QA / answer role (same unit) | `DEEPSEEK_CHAT_API_KEY=<your key>` | `/etc/coursemate/rag.env` |
| `rag-api` — the UI backend API (same unit) | `CMUI_PROVIDER_MODE=deepseek`, `CMUI_DEEPSEEK_API_KEY=<your key>`, **and `CMUI_ALLOW_BILLABLE=true`** (optionally `CMUI_DEEPSEEK_MODEL`, `CMUI_DEEPSEEK_BASE_URL`) | `/etc/coursemate/rag.env` |
| `agent-api` (TypeScript, `coursemate-agent`) | `AGENT_MODEL_NAME=deepseek-flash`, `AGENT_MODEL_API_KEY=<your key>`, with `AGENT_PROVIDER_MODE` left at `openai` (its `deterministic` value never calls a provider) | `/etc/coursemate/agent.env` |

`CMUI_ALLOW_BILLABLE=true` is the **money switch** and is not optional for the UI backend: without it
five generation endpoints answer `402`, and the provider itself raises `BILLING_NOT_AUTHORIZED` (the
coverage reviewer's own message is "enable CMUI_ALLOW_BILLABLE only after the budget is approved"). It
exists precisely so that spending is an explicit, revocable decision rather than a side effect of
setting a mode — so setting it *is* the ceiling approval, and I will not set it before you give the
number.

**This is a re-pointing, not an addition.** Production already has `V3_MODEL`, `RAG_CHAT_MODEL`,
`AGENT_MODEL_NAME` (and the matching key/base-url variables) carrying the Qwen path, so the switch
changes existing values. I will re-read the current variable *names* immediately before the window —
if any name has changed since my read-only check, I will tell you rather than guess.

**Every wrong combination fails loudly instead of silently generating on the wrong provider** — I
verified each of these in the code, and this round added tests that pin the fourth:

* `V3_MODEL=deepseek-flash` with a Model Studio base URL → `503 MODEL_ENDPOINT_INVALID`, "Use the
  official DeepSeek base URL".
* `V3_MODEL=deepseek-flash` with no key → `503 MODEL_LIVE_BLOCKED`, "Configure the explicit model
  endpoint key" (the key variable is `V3_MODEL_API_KEY`, not `V3_MODEL`-adjacent guesses).
* `AGENT_MODEL_NAME=deepseek-flash` without an allowlisted DeepSeek endpoint → the agent refuses to
  start (`"deepseek-flash requires the official DeepSeek base URL"`).
* `CMUI_PROVIDER_MODE=deepseek` with a non-DeepSeek host, a `/v1` path, a missing key, or any model
  other than `deepseek-flash` → the UI backend refuses to **boot**, before it opens its database.
* `CMUI_PROVIDER_MODE=deepseek` with billing not authorised → generation answers `402`, the provider
  raises `BILLING_NOT_AUTHORIZED`, and nothing is spent.

The one silent case is a **misspelled variable name** in the RAG service, because unknown keys are
ignored there. That is why the table above names them exactly; if a step seems to do nothing, tell me
and I will read the running configuration's variable *names* rather than asking you for values.

**For my own verification runs:** the canary CLI takes the credential variable as an argument
(`--api-key-env`), so I will point it at whichever of the names above holds the key on the host, rather
than assuming a name. It prints the token ceiling and refuses to call anything without an explicit
budget flag, so nothing is spent by running it in preflight mode.

**The ceiling I need from you (a number, not a key).** I will not start without it. Current proposal,
all of which is a **request, not an approval** — nothing inherited, nothing already spent (spend to
date is 0):

| Batch | Calls | Tokens | Purpose |
|---|---|---|---|
| Jev canary + calibration | ≤ 200 | ≤ 0.6M | one call per definition, then thresholds fitted on the calibration split only |
| Jev A/B/C/D/E + 6 module arms | ≤ 900 | ≤ 2.5M | the ablation on the frozen splits |
| Jev subtotal (hard) | **≤ 1,100 (cap 1,500)** | **≤ 3.1M (cap 5.0M)** | |
| DeepSeek canary | 10 | ≤ 60k | text → structured → vision → tool replay |
| DeepSeek acceptance (real teaching journeys incl. an image problem, exercise, five-question grading) | ≤ 120 | ≤ 1.2M | the real-user path |
| DeepSeek subtotal (hard) | **≤ 130 (cap 200)** | **≤ 1.3M (cap 2.0M)** | |
| Embeddings, only if a rehearsal needs them | ≤ 300 chunks (cap 500) | — | no full-corpus re-embed |
| **Worst-case reserve** | +50% on each row above | | a failed call still bills |
| **Grand total** | **≤ 1,700 paid calls** | **≤ 7.0M tokens** | |

**USD:** I have deliberately not fixed this. Proposed and easy to lower: Jev **15** + DeepSeek **10**
+ embeddings **2** = **27 USD combined**, against your published price list. **Set the number (or tell
me to use 27) and I will stop at whichever of the three limits — calls, tokens, USD — is hit first.**

**Reversible.** Yes: remove the key; the product falls back to its current behaviour. There is no
automatic failover to another provider, by design.

---

## Action 3 — Production window (or an explicit "not yet")

**Why it must be you.** Deploying, migrating production data, and publishing the frontend are your
authority. I have deliberately made **no** production change: production is still on release `4ef5064`
with schema 25 and Qwen models, and every production contact so far has been read-only.

**What I need, in one of two forms.**
* **Approve a window** — then I run, in this order, and stop on the first failure:
  read-only re-verification → consistent backup → **isolated restore** → migration **026–030**
  rehearsal (proving `integrity_check=ok`, empty `foreign_key_check`, no leftovers) → rollback check
  against the real `4ef5064` → immutable release directory → protected env → frontend build →
  publish → real-user acceptance → post-release backup + monitoring.
* **Or defer** — say so and I will keep the release prepared and unexecuted, and keep working on
  everything that does not need it.

**Two production findings that need your decision regardless of the window** (both recorded, not fixed
by me):

1. **`coursemate-rag` and `coursemate-agent` are `disabled` at boot** although both units declare
   `WantedBy=multi-user.target`. **The next reboot is an outage.** Fixing this is one command
   (`systemctl enable coursemate-rag coursemate-agent`) — approve it and I will run it, or run it
   yourself. This is the highest-value 10-second action in this document.
2. **There is no CourseMate backup timer.** `coursemate-monitor` is `failed` *because of its own
   backup check*: the newest snapshot is older than `MAX_BACKUP_AGE_SECONDS` (191857 s vs 93600 s).
   Either add a timer (I can prepare the unit for your approval) or relax the monitor threshold —
   your call. SRSZQ has its own timer and is untouched.

**Netlify:** the publish method for the frontend is unchosen (current deploy
`6ab02278b7fae664934df25d`). Tell me which method you want, or leave it to me to propose one for your
approval.

**Not touched, by standing rule:** DNS, SRSZQ (`8.210.58.22`), the published CS3481/GE2324 trees, and
anything on the old Singapore host.

---

## Action 4 — One product decision: document-side extraction

**The question.** Module A (extraction verification) is wired to the **query-side** exact-locator
surface (`parse_query_reference` → a hard chunk-metadata filter) because that label has a real
consumer. The **document-side** parser (`app/rag/structure.py::extract_structured_blocks`) still has
**no place to record a per-field review outcome** — `problem_index_entries` has no verification
column — and **no consumer that would act on one**.

**Why I am asking instead of building it.** Adding a column plus an annotation that nothing reads is
exactly the "a helper exists" pattern this project refuses to count as integration. Building it
properly means a migration and a real consumer.

**The choice (pick one, one line is enough):**

* **(a) Leave it unwired** — default, zero risk, recorded as such. Nothing in the shipped product
  changes.
* **(b) Add a per-field review slot + surface it** — I add the column and a UI/API consumer so a
  flagged document label is visible and actionable. Costs a migration (**031**), so it lands in the
  same release window as Action 3, and it must not change today's retrieval behaviour.
* **(c) Only flag, never act** — record the verdict in the receipt ledger alone. I do **not**
  recommend this: it is observability without effect, and I would have to report it as such.

---

## Things I will not ask you for

* API keys, tokens, passwords or private keys **in chat** — only the variable *names* above, typed
  into the protected env by you.
* Blanket admin on your cloud account, or disabling any host protection.
* A copy of the production database in a public or shared location (the rehearsal restore stays
  isolated on the host).
* Approval to "do everything". Each action above has a named scope, a named platform and a stated
  reversibility.
* Re-approval of anything you already approved with the same scope — if a scope changes, I will say
  so and ask again rather than assume.

## What I do while waiting

Nothing in the ledger's `LOCAL_*` rows depends on any action above. I keep closing those, and every
number I publish will name its revision, its command and its log path — no percentages, no
"all done", no substituting a shadow receipt or an HTTP 200 for a real effect.
