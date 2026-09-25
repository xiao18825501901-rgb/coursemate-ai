# CourseJesus Question Engine P5 live acceptance

Date: 2026-09-25
Final local candidate: `a24fac535eda85358965f516964df0c40510e7a0`
Verdict: **LIVE ACCEPTANCE NOT PASSED**

This report deliberately separates real transports from offline contracts. No generated question
reached READY, no C1/C2 student journey completed, C3–C5 were not started, and no content was
eligible for human acceptance or production release.

## Frozen finite plan

The P5 runner used the actual DeepSeek provider, Jev gateway, Question Engine persistence and the
mounted UI path against isolated databases and a synthetic DBSCAN evidence file. It did not use
production user data.

| Control | Frozen value |
|---|---|
| Model | `deepseek-flash` at `https://api.deepseek.com` |
| Required Jev modes | ambiguity, answer agreement, MCQ distractor quality, rule violation quality = `on` |
| Unrelated Jev modes | retrieval support, source selection and exercise prototype = `off` after preflight correction |
| DeepSeek call cap | 8 for the C1/C2 slice |
| Jev call cap | 4 after correction |
| Output cap | 4,000 tokens per DeepSeek call |
| Conservative peak ceiling | USD 0.0744; not a bill and not a recurring budget |
| Retry policy | no automatic retry; never reuse an uncertain operation id |

The price inputs were frozen from DeepSeek's official price page for the model identity in use.
Actual cost must come from returned usage/provider billing; missing usage remains unknown.

## Real attempts

| Attempt | Real transport evidence | Result | Charge boundary |
|---|---|---|---|
| `20260925T060137Z` | 2 Jev shadow calls: `retrieval.support.v1`, `source.select_span.v1`; 0 DeepSeek calls | UI application-budget gate refused before Question Engine generation | DeepSeek zero; Jev exact usage/cost unavailable, therefore not declared zero |
| `20260925T061320Z` | 1 known Jev call: `exercise.prototype.v1`; the author path may have reached DeepSeek outside the durable ledger | `UPSTREAM_UNKNOWN`; no question completed | Possible DeepSeek call, outcome/usage/charge **UNKNOWN**; preserved rather than retried |
| `20260925T063014Z` | 0 DeepSeek and 0 Jev calls | Blueprint rejected an invalid observable objective before transport | zero for this attempt |

The second attempt exposed a real metering defect: the mounted operation id reached
`generate_one()` but not the author/blind pipeline. The fix creates the durable parent before
transport, meters author and blind roles, refuses same-id replay before transport, and retains the
prior attempt as an immutable `UPSTREAM_UNKNOWN` record. The third attempt then proved that an
invalid blueprint terminates before reservation/transport and is recorded without inventing a
provider result.

## Required acceptance layers

| Layer | Status | Evidence / reason |
|---|---|---|
| `LIVE_PROVIDER_CONTRACT` | **PARTIAL / NOT PASSED** | Real Jev calls occurred, but the required four positive `on` receipts were never reached; one possible DeepSeek call has unknown outcome |
| `QUESTION_ENGINE_LIVE_END_TO_END` | **NOT PASSED** | no author→blind→hard gates→required receipts→READY chain completed |
| `CONTENT_AUTOMATED_CHECKS` | **LOCAL CONTRACT PASS ONLY** | deterministic/offline suites pass; there is no successful live question to inspect |
| `HUMAN_CONTENT_REVIEW` | **PENDING / EMPTY** | no exact live question revision exists |
| `PRODUCTION_ACCEPTANCE` | **BLOCKED** | live quality and human gates precede deployment |

Known real Jev activity is only three calls across unrelated/shadow definitions. It is useful
provider-contract evidence, but it does **not** satisfy `LIVE_JEV_BASE_SIGNALS` or
`LIVE_JEV_SPECIALIZED_SIGNALS`.

## Evidence

- Sanitized attempt ledger: `docs/coursejesus/evidence/p5/live-attempt-summary.json`
- Private immutable states (gitignored): `work/p5-live-c1-c2-20260925T060137Z`,
  `work/p5-live-c1-c2-20260925T061320Z`, `work/p5-live-c1-c2-20260925T063014Z`
- State SHA-256: `ea5bd59a...3675f6`, `6fe5a0dc...75fc5`, `d1cf6b0f...572ed`
- Reconciliation SHA-256: `8e0b9add...6c70b`, `852770a5...ca35`

No further paid attempt was made after these failures. A future run requires an explicit resumption
of real-model testing, a new operation id linked to the unknown attempt, unchanged finite caps, and
successful C1–C5 artifacts before any production release can proceed.
