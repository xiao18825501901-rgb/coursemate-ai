# CourseJesus P5 recovery: three-attempt diagnosis and local correction evidence

Date: 2026-09-25
Branch at diagnosis: `fix/codex-dsh-audit-20260919`
Document baseline: `dd46121a66e7cb4bc0470986f9e66965d0d2916d`
Application baseline supplied for recovery: `a24fac535eda85358965f516964df0c40510e7a0`
Frozen recovery application candidate: `978e3f714ee9a1a39a34e1969c82615346a60f82`
Test-harness checkpoint: `c36782e69a51becd1fd690f782b0ae458115c987`

This document corrects the earlier high-level wording without changing any original attempt
artifact. It does not declare model quality failure: none of the three attempts produced enough
complete DeepSeek content to judge quality.

## Evidence boundary

- The immutable attempt states and SQLite databases remain under
  `work/p5-live-c1-c2-20260925T060137Z`, `...061320Z` and `...063014Z`.
- The second attempt's `UPSTREAM_UNKNOWN` reconciliation remains unchanged. Its unknown charge is
  not converted to zero and its operation ID must never be retried.
- The first attempt did not preserve its raw UI error response. Its exact earliest exception below
  is a source/control-flow reconstruction plus a zero-network replay of the same missing
  configuration, not a claim that an absent HTTP body was recovered.
- The third attempt did preserve enough database and constructor evidence to identify the rejected
  field and prove that no provider transport occurred.

## Attempt 1 — mounted UI price configuration refusal

| Fact | Finding |
|---|---|
| Attempt | `20260925T060137Z`; application `2d61ca069b7e240f548f3e134a59621101753740` |
| Observed transports | DeepSeek 0; Jev shadow 2 (`retrieval.support.v1`, `source.select_span.v1`) |
| Exact earliest local exception | `BudgetPriceUnavailable`; code `BUDGET_PRICE_UNCONFIGURED`; message `input token price is not configured` |
| Configuration source | The old runner configured provider identity and credentials, but did not configure `CMUI_OPERATION_INPUT_USD_PER_MILLION`, `CMUI_OPERATION_OUTPUT_USD_PER_MILLION`, `CMUI_OPERATION_USD_BASELINE`, or the bounded answer-token estimate before mounting the UI app. |
| Scope | The mounted UI's per-operation Question Engine estimate, before UI run creation. It was not a DeepSeek provider rejection and not a statement about generated-content quality. |
| Evidence limitation | The old `run-state.json` kept only `RuntimeError`, so the exact exception is reconstructed from the frozen source ordering and reproduced locally without network. |

The old control flow called `estimate_question_engine()` before `evaluate_operation_budget()`.
Therefore the missing input price is the first failing value; the baseline was also absent but was
not reached in that execution. The two unrelated shadow calls happened before this UI refusal,
which is why the replacement preflight must be truly transport-free.

Correction:

- the live runner now requires explicit input/output prices and an explicit product baseline;
- the owner workflow ceiling is no longer reused as product baseline `B`;
- the published product baseline remains `B = USD 0.20`, so medium=`B`, high=`2B`, max=`null`;
- the real static preflight exercises the mounted estimate and budget decision with network count 0.

## Attempt 2 — possible unmetered author request

| Fact | Finding |
|---|---|
| Attempt | `20260925T061320Z`; application `0b05f51718bf53fd939d0037b854529726fb750c` |
| Known transport | one Jev `exercise.prototype.v1` call |
| Failure stage | The UI operation ID reached `generate_one()`, but the author/blind pipeline did not receive it as `model_operation_id`. The provider proxy therefore bypassed `learning_model_call_reservations`, `learning_model_run_evidence`, and the harness DeepSeek counter. |
| Persisted result | no READY question; generic UI `QUESTION_ENGINE_FAILED` / `C1_QUESTION_NOT_COMPLETED` |
| Financial boundary | Up to one author request may have been sent. Outcome, response, usage and charge remain `UNKNOWN`. There is not enough output to assess model quality. |
| Immutable link | reconciliation SHA-256 `8e0b9addcc61a837906866e5b67bdd581567cd37fafd4c2a5d76ad398766c70b` |

Correction already present before this recovery: `8f8f06d59939a1765d73e451642ff8b595ce3ef6`
routes author and blind roles through the claimed operation and refuses same-ID replay. This
recovery adds a private durable transport ledger: every new DeepSeek/Jev send records intent first,
then records the full received result and usage before business-schema validation. SDK retries are
explicitly zero. A network exception after send intent is preserved as `UNKNOWN`.

## Attempt 3 — invalid `objective_text` blueprint field

| Fact | Finding |
|---|---|
| Attempt | `20260925T063014Z`; application `f2876415c22f6b9d91fa015fbbc7bfea37833a1b` |
| Rejected field | `objective_text` |
| Pydantic location in the original model-level error | root `loc=()` / `value_error`; the underlying failed rule was the observable-action constraint on `objective_text` |
| Construction source | synthetic teaching item `p5-objective-density`, passed by `QuestionEngineRuntime._blueprint` |
| Invalid value | `Use the stated epsilon and MinPts rule to count A's neighbours and decide whether A is a core point.` The contract's observable-action vocabulary did not accept `count`/`decide`. |
| Transport proof | DeepSeek 0, Jev 0, reservations 0, run-evidence rows 0; charge zero for this attempt |
| Persistence defect at that SHA | a parent generation operation was claimed before blueprint validation and remained `RUNNING` |

`4305955` changed the synthetic objective and closed the parent operation on validation failure.
This recovery moves all deterministic objective/evidence/blueprint validation earlier still: an
invalid local field creates no parent operation and cannot consume a Jev shadow call. The validator
now reports `loc=("objective_text",)` explicitly.

## What `a24fac5` did and did not fix

`a24fac535eda85358965f516964df0c40510e7a0` changed the P5 runner tests so process environment
changes cannot leak into later tests. That was a valid test-isolation fix. It did not itself fix the
Attempt 1 product-budget configuration, add a zero-network production-path preflight, preserve
transport bodies before parsing, or unify practice/assessment blueprint construction.

## Recovery implementation now present in the frozen candidate

1. A zero-transport static preflight builds the actual workspace, Teaching Spec, evidence pack and
   production `QuestionBlueprint`; validates schema 39, disk, call caps, required Jev modes and the
   mounted UI budget; and does not create the requested live run directory.
2. Practice UI generation, live runner generation and all five assessment slots now delegate to
   one canonical `QuestionBlueprint` constructor.
3. Local-invalid objectives fail as `QUESTION_BLUEPRINT_INVALID` before operation claim, Jev or
   model transport.
4. DeepSeek Responses calls record `SEND_INTENT`, then full response text, response identity and
   token usage before schema parsing; a ledger failure before intent prevents the send.
5. Jev uses `RetryPolicy(max_retries=0)` and the acceptance wrapper records intent and full answers
   around its one SDK call.
6. The live runner persists the first author→blind→two required Jev receipts→READY→hidden UI
   projection as an immediate checkpoint before hint, marking, explanation or repractice calls.
7. A new run must include the immutable Attempt 2 state and reconciliation hashes and obtains a new
   generated UI operation ID. The old UNKNOWN record remains untouched.

## Live recovery result

- C1/C2 ran under a new controlled operation and produced READY revisions
  `qe_2b66a37d422649c3b0157c202bab0c49` and
  `qe_1fdf1412e5c34304bbf60678a771a36a`. The slice recorded 8 complete DeepSeek
  transports, 4 real Jev calls and estimated cost USD `0.0095247`.
- A completed assisted-feedback response was durably stored before a stricter local 500-character
  parser rejected its 512-character criterion. Recovery id `p5-attempt-assisted-recovery-0002`
  reused the frozen response from `p5-attempt-assisted-0001`; it did not send a second paid call.
- C3-C5 produced five frozen assessment revisions and the separate rule revision
  `qe_2fd0b9a365e8441c83859d544d335b8d`. The slice recorded 13 complete DeepSeek
  transports and 14 real Jev calls, including real MCQ and rule-specific receipts; estimated cost
  was USD `0.0255264`.
- Across both new slices: 21 completed DeepSeek transports, 18 real Jev calls, 54,441 input tokens,
  15,599 output tokens, zero automatic retries and estimated new-workflow cost USD `0.0350511`.
- The old Attempt 2 record remains `UPSTREAM_UNKNOWN` under reconciliation SHA-256
  `8e0b9addcc61a837906866e5b67bdd581567cd37fafd4c2a5d76ad398766c70b`; none of its values were
  overwritten and its operation id was not reused.
- Automated contract and business acceptance passed for the bounded synthetic C1-C5 workflow.
  Owner content review is still PENDING, so production deployment has not started.

## Local verification at this checkpoint

- Targeted recovery suite: **76 passed** after the canonical-builder and durable-ledger changes.
- Full backend regression at application `978e3f7`: **1854 passed, 2 platform skips, 0 failed**. The skips cover Windows
  symlink privilege and POSIX permission-bit behaviour.
- Web and task-agent unit regressions: **117 passed** and **92 passed**; both TypeScript checks
  passed.
- Native-browser regressions: refreshed shell **23 passed**; core application **4 passed**; V3
  learning **3 passed**; structured Jev offline deployment **12 passed, 5 live-only skips**.
- Production-shaped Web and agent builds passed. The built Web bundle scan found no token field and
  retained the required user notice.
- The refreshed shell additionally fixed an auth-bridge mount race: `CourseMateApp` now mounts only
  after the Clerk or test bridge exists. Its regression failed on the old ordering, passed 6/6 after
  the change, and the full 23-journey refreshed-shell browser suite then passed.
- Fake HTTP business orchestration: real `LearningOrchestrator`, `LearningProvider`, OpenAI
  Responses client, Jev gateway and receipt store; author + blind + ambiguity + agreement reached
  READY with two completed reservations and two durable on-mode receipts.
- Static preflight result: `STATIC_PREFLIGHT_PASSED`; schema 39; network calls 0; blueprint
  `question-blueprint.v1`; medium estimate USD 0.046674; product cap USD 0.20.
- Provider invalid-contract test proves `RESPONSE_COMPLETE` with full text and usage precedes
  `CONTRACT_REJECTED`.
- Ledger fail-closed test proves the provider is not called when `SEND_INTENT` cannot be saved.
- TypeSafe SDK contract test proves explicit credential, model, timeout and zero retries.

The structured Jev browser run initially reproduced a test-harness-only 429 after enough model
journeys. Both browser configs set `APP_ENV=test`, but the mounted UI extension reads `CMUI_ENV`;
it therefore retained the development limit of 8 model runs per minute. A source guard failed 2/2
before the fix. Test checkpoint `c36782e` sets `CMUI_ENV=test` in both isolated configurations;
the guard then passed 2/2, the structured Jev suite passed 12 runnable journeys with its 5
live-only skips, and the refreshed shell passed 23/23. This changes no application runtime source
and does not alter production rate limiting.

The local/offline results and the bounded live-provider results are distinct evidence layers. Live
DeepSeek/Jev contract acceptance is complete for the frozen synthetic C1-C5 bundle. Human content
approval, production deployment and signed-in production acceptance remain pending.
