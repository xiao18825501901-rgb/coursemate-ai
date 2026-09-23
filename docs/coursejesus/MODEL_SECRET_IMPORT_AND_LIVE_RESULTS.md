# Model credentials: how they were imported, and what a live call actually did

**Status:** `DEEPSEEK_LIVE` — **10/10 roles completed against the real provider**, USD **0.0079908**
actual against a USD 0.0620016 conservative ceiling. `MODEL_SPENDING_POLICY_APPLIED` — this round's
necessary calls ran under `owner_authorized_unlimited_for_this_workflow`; no `99999`, no
auto-recharge, no infinite retry, and every call's cost is recorded as it was billed.
`JEV_LIVE_AND_EFFECT` — **PARTIAL**: the live TypeSafe path was run and **2 of the 3 typed
primitives validated** (Choice and Noul); the Score primitive returned a continuous value that the
typed validator refuses **by design**, so the level boundaries are a calibration decision rather
than something to invent. Jev's live *effect* on user-visible behaviour is **not** measured; §6
states both halves.

Evidence: `work/current-change/deepseek-live-evidence-r81e.json`, `deepseek-live-evidence-r81e.log`,
`run-live-canary.py`, `probe-responses-endpoint.py`, `confirm-output-text-defect.py`.
Measured 2026-09-23/24.

## 1. Where the credentials live, and what never happens to them

| Fact | Value |
| --- | --- |
| Protected store | `C:\Users\Hp\.coursemate\rag.env` — ACL reduced to this one account, one principal |
| Names in it | `DEEPSEEK_CHAT_API_KEY`, `DEEPSEEK_API_KEY`, `TYPESAFE_API_KEY` |
| Production expects them at | `/etc/coursemate/rag.env` (0640 root:admin), which is the release step, not this one |
| Printed anywhere | **No.** Only a fingerprint (first 6 + last 4 of a SHA-256) and a length were ever printed, and only to disambiguate two values |
| In Git | **No.** The file is outside the repository; the repository contains no key value and no `.env` with one |
| In the frontend bundle | **No.** The web app reads no model credential; the build-time scan covers token-shaped fields, and the model keys are server-side only |
| In a prompt, report, test fixture or log | **No.** The canary records usage and cost, never the key |

## 2. How they were parsed out of the Word document, and why that was awkward

`C:\Users\Hp\Desktop\1.doc` is a Word 97 binary. The obvious approach — reading the text range
described by the file information block's `fcMin`/`fcMac` — returned **187 characters**, which is not
a document with two credentials in it. The text lives in the **piece table**: the FIB flag selects
`0Table` or `1Table`, `fcClx`/`lcbClx` at `0x01A2`/`0x01A6` locate the `Clx`, the `PlcPcd` inside it
maps character positions to file offsets, and bit 30 of the file-offset entry means the piece is
single-byte at half the stored offset. A whole-stream scan then confirmed the document holds
**exactly two** candidate values — so nothing was silently missed and nothing invented.

## 3. Which key belongs to which provider was decided by asking the providers

Two candidates, two providers. Guessing from a `sk-` prefix would have been a guess. Each candidate
was sent to each provider's endpoint and the **status code** decided it: `200` from
`https://api.deepseek.com` and `401` from TypeSafe for one value, the reverse for the other. Nothing
but the fingerprint, the length and the status code was printed at any point.

## 4. What the live canary found — two real defects, both fixed

The first two attempts failed with `UnusableResponseError` on the `PLAN` role. Both causes were
measured rather than guessed, and both were defects on our side:

1. **`/responses` returns text in `output[].content[].text`, and there is no `output_text` field.**
   Our reader looked for `output_text`, so a perfectly good answer was read as an empty one. Fixed in
   `_responses_text`, which reads the documented shape and still honours `output_text` if a
   compatible provider sends it; four tests pin the shapes, including the one that must still be
   refused.
2. **A refused response was recorded as costing nothing while the provider billed 4,816 tokens.**
   The usage was in the body and we were ignoring it. `run_canary_call` now records the billed usage
   and the cost even on a refusal, and `error_detail` carries the reason, so an incomplete response
   says *why* (`incomplete_details.reason = max_output_tokens`) instead of looking like a network
   blip.
3. **The third finding was operational, not a defect:** `reasoning: {"effort": "none"}` is what makes
   this model complete within the output budget. Without it the model spends the whole budget
   reasoning and returns `status: "incomplete"`, which is exactly the state the canary now reports
   instead of hiding.

## 5. The live result, role by role

All ten roles completed on `deepseek-flash` at `https://api.deepseek.com`:

| Role | Status | Input | Output | Latency | Cost (USD) |
| --- | --- | --- | --- | --- | --- |
| `KNOWLEDGE_QA` | completed | 55 | 62 | 1,105 ms | 0.0000909 |
| `PLAN` | completed | 290 | 205 | 1,726 ms | 0.0003330 |
| `WORK` | completed | 30 | 46 | 597 ms | 0.0000642 |
| `CLASSIFICATION` | completed | 316 | 157 | 1,391 ms | 0.0002832 |
| `EXERCISE_V2` | completed | 2,466 | 2,622 | 10,792 ms | 0.0038862 |
| `PROBLEM` | completed | 1,721 | 162 | 1,362 ms | 0.0007107 |
| `EXPLANATION` | completed | 1,681 | 800 | 4,971 ms | 0.0014643 |
| `IMAGE_UNDERSTANDING` | completed | 1,706 | 112 | 886 ms | 0.0006462 |
| `ASSESSMENT_REFERENCE` | completed | 376 | 135 | 1,173 ms | 0.0002748 |
| `COVERAGE_REVIEW` | completed | 87 | 176 | 1,471 ms | 0.0002373 |
| **Total** | 10/10 | **8,728** | **4,477** | — | **0.0079908** |

Every `observed_model` was `deepseek-flash`, so no request silently landed on a different model. The
recorded `status` is `LIVE_CALLS_COMPLETED_MANUAL_REVIEW_REQUIRED` and
`manual_review_status: REQUIRED`: the calls worked and the output has **not** been reviewed by a
human for pedagogical quality, and no document in this repository claims otherwise.

**Unbilled-usage honesty:** the ceiling USD 0.0620016 is the worst case computed from the published
peak prices (input cache-miss $0.30 / output $1.20 per 1M tokens) applied to the maximum output the
caller allowed. The actual USD 0.0079908 is the sum of what the provider reported per call. Where a
response was refused, the tokens were billed and are counted; the earlier behaviour that recorded
them as free is the defect described in §4.2.

## 6. The live Jev path: run, and what it found

`typesafe-sdk==0.7.0` was installed (it is the optional dependency `requirements.txt` names), the
key was read from the protected store into the environment the SDK itself reads, and three real
decisions were run through the **real** gateway with caching disabled and the runtime mode set to
`on` rather than the catalogue's `shadow`, so a stored receipt could not be mistaken for a live
answer. One decision per primitive:

| Definition | Primitive | Live outcome | Answer |
| --- | --- | --- | --- |
| `intent.next_action.v1` | Choice | **`ok`** | `ANSWER_AND_RESUME` (3,740 ms) |
| `source.supports_claim.v1` | Noul | **`ok`** | `noul = 0.9`, `probability = 0.9` (1,006 ms) |
| `retrieval.support.v1` | Score | **`invalid_response`** | the provider returned `3.99` |

Evidence: `work/current-change/jev-live-evidence.json`, `jev-live-run.log`.

So `JEV_LIVE = PARTIAL`: **two of the three typed primitives are validated against the real
service, and the third is blocked by a measured mismatch**, not by a missing credential.

### The Score mismatch, measured rather than guessed

The typed validator (`app/jev/gateway.py:497-510`) accepts a declared level key (`0`–`4`) or a level
*description*, and refuses anything else. The live provider does not return either: it returns a
**continuous value on the 0–4 scale**, consistently.

Three further live calls, with candidates of deliberately different quality:

| Candidate | Raw score | Type | A declared level? |
| --- | --- | --- | --- |
| Text that directly supports the query | `3.92` | str | no |
| An unrelated timetable note | `0.0` | str | no |
| A partially related note | `1.3` | str | no |

The values are *semantically right* — unrelated `0.0` < partial `1.3` < direct `3.92` — and they are
never a level key. The five discrete levels are the catalogue's, not the provider's; the SDK's
`.score` return type is explicitly marked unverified in the validator with that comment.

**What was deliberately not done:** the level boundaries were not invented to make the value fit.
The catalogue's own `thresholds` field says
`UNSET_UNTIL_CALIBRATED_ON_LABELLED_DATA`, which is a standing instruction, and quietly mapping
`3.99 → "4"` would turn a calibration question into a hidden guess. Two honest options exist, and
choosing between them is a decision:
1. calibrate the level boundaries on labelled data — which is what the ablation/calibration harness
   exists for — and only then map continuous values to levels;
2. treat the value as what it is (a bounded relevance score on a known scale) and leave the level
   unset for `Score` decisions, instead of forcing a five-way label onto a continuous answer.

### What is and is not claimed about Jev's effect

| Claim | State |
| --- | --- |
| The live transport reaches TypeSafe and returns typed answers | **Verified** for Choice and Noul |
| The deterministic half (permissions, locators, state machines, transactions, scores, coverage, `LEARNED`, DB writes) never depends on Jev | Verified by the architecture's own tests: 94 Jev/canary tests pass, and the rule that Jev writes no teaching text, grade, `LEARNED` value, permission or tool execution is enforced in code |
| Jev's suggestions change user-visible behaviour in a live run | **Not measured.** The business callsites are wired and covered by tests against the deterministic path; a live end-to-end run with a real course is the owner's acceptance step, and nothing here claims it |

## 7. Cost policy, recorded exactly as applied

* This round: `execution_cost_policy = owner_authorized_unlimited_for_this_workflow`. The canary
  prints the policy and **still records the ceiling** — unlimited is a permission, not an absence of
  accounting.
* `--max-cost` is required in the default `capped` mode and is not accepted as a magic number: the
  string `99999` appears nowhere, and neither does an auto-recharge or an unbounded retry. A retry
  policy that could spend without bound would make the recorded cost meaningless.
* Every call's input/output tokens, observed model, latency and cost are recorded per role, so the
  spend can be reconstructed from the artifact rather than from a summary line.

## 8. Limits of this document

* **Manual review is outstanding.** "10/10 roles completed" means the provider answered within the
  budget, not that the answers are good.
* **One model, one provider.** `deepseek-flash` was exercised; `deepseek-v4-pro` was listed by the
  provider and not called, so nothing here says anything about it.
* **Prices are the published ones at the time of the run**, and they are recorded in the artifact
  alongside the tokens so a later price change does not silently rewrite history.
* **The keys are in a local protected file, not in production.** Moving them to
  `/etc/coursemate/rag.env` is part of the release sequence and has not happened.
