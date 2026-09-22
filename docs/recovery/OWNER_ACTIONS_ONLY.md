# OWNER ACTIONS ONLY

Everything in this file is something **only you can do** — because it needs your account, your
credential, your money, your production authority, or a product decision that is yours to make.
Everything else is already done or is being done by me; see `CURRENT_BLOCKER_LEDGER.md`.

**Read this first:** there are exactly **four** actions. Doing #1 and #2 unlocks every remaining
technical item; #3 and #4 are one-way-door decisions for the release.

| # | Action | Unlocks | Cost | Reversible? |
|---|---|---|---|---|
| 1 | Put a TypeSafe Jev credential into the backend's protected env | live Jev validation, calibration, all ablations, any promotion out of `shadow` | paid per call | yes (remove the var) |
| 2 | Put a DeepSeek API key into the same protected env + approve a token ceiling | DeepSeek live acceptance, and the full real-user teaching path | paid per call | yes |
| 3 | Approve a production window (or explicitly defer it) | deployment, migration rehearsal, real acceptance | infra only | yes, but a deploy writes data — see rollback |
| 4 | Answer one product question about document-side extraction | closes the last local design gap | free | yes |

---

## Action 1 — TypeSafe Jev credential

**Why it must be you.** The key authorises paid model calls against *your* TypeSafe account. I cannot
create an account, accept terms, or pay on your behalf, and the key must never travel through chat.

**Exact platform.** TypeSafe (`docs.typesafe.ai`). The SDK is already a dependency: `typesafe-sdk`
0.7.0, vendored under `services/rag-api` (the adapter is `app/jev/gateway.py::SdkTransport`, which
lazy-imports it and fails **typed** — `JevNotConfiguredError` — when the key is absent, before any
network access).

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

**Existing access — what I checked.** No DeepSeek variable exists in the production env files. The
canary CLI (`app/evaluation/deepseek_canary.py`) and its preflight (which prints a token ceiling
*before* calling) are already in the repo and ready to run.

**Which app to open / where to type it.** Same protected path as Action 1 — add to
`/etc/coursemate/rag.env` (and `/etc/coursemate/agent.env` if the agent should generate too):

```
DEEPSEEK_API_KEY=<your key>
```

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
