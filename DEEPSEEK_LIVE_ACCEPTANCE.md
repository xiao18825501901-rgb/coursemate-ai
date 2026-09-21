# DEEPSEEK_LIVE_ACCEPTANCE

What must be proven against the **real** DeepSeek API before the release, how it is run, and what the
current status honestly is.

**Status: `DEEPSEEK_LIVE_VALIDATION = NOT_RUN`.** No DeepSeek key exists in this environment, so no
live call has been made and no live result is claimed anywhere. Everything below is the plan plus the
locally verified half.

---

## 1. What is already proven locally (not a substitute for the live run)

| Claim | Evidence |
|---|---|
| Every generative role is wired to the DeepSeek contract | `tests/test_deepseek_contract.py`, `tests/test_deepseek_provider_roles.py` |
| The payloads use DeepSeek-native fields only (native thinking explicitly disabled, images via `detail`, structured output via the Responses `text.format` schema) | same suites |
| No silent Qwen fallback and zero Qwen egress from the migrated paths | host-spy tests (4) |
| A non-DeepSeek base URL is rejected | `validate_deepseek_base_url` + tests |
| A whole-batch cost ceiling is printed **before** any call, and the run refuses to start without `--allow-billable`, a key, explicit prices and `--max-cost` | `scripts/run_deepseek_canary.py` (preflight exit 0 with ten roles, refusal exit 2 without a key) |

Roles covered by the canary plan (ten calls, two on `/chat/completions` and eight on `/responses`):
knowledge QA, plan, work, classification, exercise.v2 (structured, hidden private answer), problem,
explanation, image understanding (vision), assessment reference, coverage review.

## 2. What the live run must show

1. The observed model identity returned by the API matches the alias configured for the release.
2. Text streaming, the structured `exercise.v2` payload, and the vision payload all complete.
3. The plan→work pair keeps the plan private (it never appears in student-visible output).
4. Tool replay for the agent path behaves as the deterministic harness expects.
5. Classification, exercise, problem, explanation, assessment reference and grading feedback are
   produced with the pinned alias, and any refusal is recorded rather than retried.
6. The recorded usage is inside the approved ceiling; failures and unknown usage count toward it.

## 3. Commands

```
# preflight only: no key, no network
services\rag-api\.venv\Scripts\python.exe scripts\run_deepseek_canary.py --preflight-only

# the real run (owner places the key in the protected backend env first)
services\rag-api\.venv\Scripts\python.exe scripts\run_deepseek_canary.py \
    --allow-billable --max-cost <approved> \
    --input-price-per-million <price> --output-price-per-million <price> \
    --out work\current-change\deepseek-canary.json
```

The evidence file records the plan, per-call role/status/latency/tokens/observed model id/cost and the
ceilings. It never contains a key.

## 4. Acceptance criteria (and what would fail it)

* Pass: every planned role either completes with the configured alias or fails with a typed error that
  the deterministic fallback handles, and the totals stay inside the ceiling.
* Fail: a role silently falls back to another provider; the observed model differs from the configured
  alias without an explicit configuration change; a refusal is retried; the ceiling is exceeded; a key
  or a raw private payload lands in the evidence file.

A successful canary proves the integration works against the real API. It does **not** prove teaching
quality — that requires the labelled ablation, which is also `NOT_RUN`.

## 5. Blockers

`DEEPSEEK_API_KEY` (and the confirmed alias) placed by the owner in `/etc/coursemate/rag.env` and
`/etc/coursemate/agent.env` on the production host, plus an approved batch ceiling. Until then the
local suites, the canary preflight and the whole structured-enhancement layer continue to be developed
and verified offline, exactly as they have been.

## 6. Production model switch (separate, and gated)

The live site currently answers with **Qwen/Model Studio** (`V3_MODEL=qwen3.8-max`,
`AGENT_MODEL_NAME=qwen3.8-max`, `OPENAI_CHAT_MODEL=qwen3.7-plus`). Rotating the generative path to
DeepSeek happens in the same release window, with its own confirmation, and the rollback path is the
previous release directory plus the pre-migration database backup — never a silent reversion to Qwen.
