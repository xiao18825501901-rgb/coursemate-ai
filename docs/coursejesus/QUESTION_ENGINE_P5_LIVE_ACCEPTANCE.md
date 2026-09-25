# CourseJesus Question Engine P5 live acceptance

Date: 2026-09-25
Application candidate: `978e3f714ee9a1a39a34e1969c82615346a60f82`
Test-harness checkpoint: `c36782e69a51becd1fd690f782b0ae458115c987`
Verdict: **BOUNDED LIVE C1-C5 WORKFLOW PASSED; OWNER CONTENT REVIEW PENDING; PRODUCTION NOT PASSED**

This report separates real transports, automated business acceptance, human content judgment and
production acceptance. New controlled operations produced exact READY revisions for C1-C5, all
required Jev definitions returned real `on + ok` receipts, and private material is available for
the Owner. Automated success does not authorize production until the Owner signs the exact review
bundle.

## Frozen finite plan

The P5 runner used the actual DeepSeek provider, Jev gateway, Question Engine persistence and the
mounted UI path against isolated databases and a synthetic DBSCAN evidence file. It did not use
production user data.

| Control | Frozen value |
|---|---|
| Model | `deepseek-flash` at `https://api.deepseek.com` |
| Required Jev modes | ambiguity, answer agreement, MCQ distractor quality, rule violation quality = `on` |
| Unrelated Jev modes | retrieval support, source selection and exercise prototype = `off` after preflight correction |
| DeepSeek call cap | 8 for C1/C2; 13 for C3-C5 |
| Jev call cap | 4 for C1/C2; 14 for C3-C5 |
| Output cap | 4,000 tokens per DeepSeek call |
| Conservative peak ceiling | C1/C2 USD 0.0744; C3-C5 USD 0.1209; neither is a bill or recurring budget |
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

## Recovery live operations

| Slice | Exact evidence | Result | Usage boundary |
|---|---|---|---|
| C1/C2 practice | revisions `qe_2b66a37d422649c3b0157c202bab0c49` and `qe_1fdf1412e5c34304bbf60678a771a36a`; public summary SHA `279e7b63...cbf1` | READY, hidden answer, non-leaking hint, independent/assisted feedback, reveal/detail, refresh restore and different-family re-practice | 8 complete DeepSeek transports; 4 real Jev calls; 16,061 input + 3,922 output tokens; estimated USD 0.0095247 |
| C2 completed-response recovery | source `p5-attempt-assisted-0001`; new recovery id `p5-attempt-assisted-recovery-0002`; frozen source state `514975f1...979794` | local response length rejected after the provider response was durably saved; the corrected parser reused that exact response | zero additional provider calls; no old operation replay |
| C3/C5 | assessment `4f89fe55378d44109c12ae39c121ce4e`; five revisions frozen at 10/15/20/25/30; public summary SHA `f1c28065...b011f` | MCQ mapping private, answer hidden before submit, assessment frozen/submitted/graded, database integrity and FK checks green | 10 author/blind + 1 grader DeepSeek calls; required base and MCQ Jev receipts real |
| C4 | revision `qe_2fd0b9a365e8441c83859d544d335b8d` | rule-specific private analysis persisted; learner projection excludes private mapping | 2 author/blind DeepSeek calls + real rule-specific Jev receipt |

Across the two recovery slices there were 21 complete DeepSeek transports and 18 Jev calls, with
no SDK/transport automatic retry. Estimated new-workflow cost at the Owner-provided prices is
USD `0.0350511`. This estimate does not overwrite Attempt 2: its possible call and charge remain
`UNKNOWN` under reconciliation SHA `8e0b9add...6c70b`.

## Final local regression matched to the candidate

- Backend at application `978e3f7`: 1,854 passed, 2 platform skips, 0 failed.
- Web: 117 passed; Agent: 92 passed; both TypeScript checks passed.
- Browser: refreshed shell 23 passed; core 4 passed; V3 learning 3 passed; structured Jev offline
  12 passed with 5 intentional live-only skips.
- Production-shaped Web and Agent builds passed; the Web artifact scan found no token field and
  retained the required credential notice.
- The structured Jev suite initially exposed a test-harness 429 because the host set `APP_ENV=test`
  while the mounted UI extension reads `CMUI_ENV`. Checkpoint `c36782e` adds the missing isolated
  test variable plus a 2-case regression guard. It changes no application runtime source and does
  not relax production rate limiting.

## Required acceptance layers

| Layer | Status | Evidence / reason |
|---|---|---|
| `LIVE_PROVIDER_CONTRACT` | **PASS FOR THE BOUNDED SYNTHETIC WORKFLOW** | 21 complete DeepSeek transports, 18 real Jev calls, full usage/response saved before parse, zero automatic retries |
| `QUESTION_ENGINE_LIVE_END_TO_END` | **PASS FOR C1-C5** | author→blind→hard gates→required receipts→READY, practice and five-question assessment completed |
| `LIVE_JEV_BASE_SIGNALS` | **PASS** | ambiguity and answer-agreement receipts are `on`, `ok`, `jev-latest` for every generated revision |
| `LIVE_JEV_SPECIALIZED_SIGNALS` | **PASS** | MCQ distractor and rule-violation receipts are `on`, `ok`, `jev-latest` |
| `CONTENT_AUTOMATED_CHECKS` | **PASS** | exact revisions, private mappings, answer visibility, persistence and database integrity verified |
| `HUMAN_CONTENT_REVIEW` | **PENDING / MATERIAL AVAILABLE** | only the Owner may judge the exact private review card |
| `PRODUCTION_ACCEPTANCE` | **BLOCKED** | Owner review and production deployment/signed-in acceptance remain required |

## Evidence

- Sanitized attempt ledger: `docs/coursejesus/evidence/p5/live-attempt-summary.json`
- Recovery root-cause and correction report: `docs/coursejesus/P5_RECOVERY_ROOT_CAUSES.md`
- C1/C2 public summary (gitignored controlled evidence):
  `work/p5-live-c1-c2-20260925T093340Z/public-summary.json`
- C3-C5 public summary (gitignored controlled evidence):
  `work/p5-live-c3-c5-20260925T102555Z/public-summary.json`
- Owner private review card (gitignored controlled material):
  `work/p5-owner-review-20260925T103415Z/OWNER_REVIEW_CARD_PRIVATE.md`; manifest SHA
  `fc91704466ef1b1082d7833dc9965e9a587d462da89cdd88118b18a4993d7ad4`
- Private immutable states (gitignored): `work/p5-live-c1-c2-20260925T060137Z`,
  `work/p5-live-c1-c2-20260925T061320Z`, `work/p5-live-c1-c2-20260925T063014Z`
- State SHA-256: `ea5bd59a...3675f6`, `6fe5a0dc...75fc5`, `d1cf6b0f...572ed`
- Reconciliation SHA-256: `8e0b9add...6c70b`, `852770a5...ca35`

The old UNKNOWN was never overwritten or retried. The new review material is complete; the next
gate is an Owner decision on the exact manifest, not another model run. Production deployment must
not begin until that decision is recorded as PASS.
