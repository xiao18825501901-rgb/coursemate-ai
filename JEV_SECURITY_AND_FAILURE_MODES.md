# JEV_SECURITY_AND_FAILURE_MODES

Security boundaries and the failure behaviour of the Jev semantic-decision layer. Written to be
checkable: each rule names where it is enforced and how it is verified, and anything unverified is
marked as such.

---

## 1. Credentials

| Rule | Enforcement |
|---|---|
| The TypeSafe key exists only in the backend env | `JevGateway` reads it from settings; it is never logged, never returned by an API, never sent to the browser and never stored in a receipt |
| The live transport is optional | `typesafe-sdk` is imported lazily inside `SdkTransport`; without the package or key it raises the typed `JEV_NOT_CONFIGURED` and the layer runs `off`/`shadow` unchanged |
| The browser never talks to TypeSafe | there is no Jev route in the RAG/agent APIs and no Jev key in any frontend build; the frontend calls CourseMate endpoints only |
| DeepSeek keys are equally backend-only | provider adapters read them from settings; the canary and DSH reports never echo a key (a test asserts the evidence JSON contains no key token) |
| No secret in Git | `.env` files are gitignored (the archived hold file is ignored by an explicit `.gitignore` rule) and no report contains a key value |

## 2. Data scope sent to Jev

Jev receives the minimum needed for one legal decision: a bounded state fragment, the candidate ids
the server generated, and the criteria text. It never receives:

* a full `.env`, a Clerk secret, a DeepSeek/TypeSafe key or any credential;
* another user's private material, or a course the caller is not authorized for;
* the whole course corpus, a whole chapter, or the full multi-turn chat history;
* plan text or hidden private answers (a state allowlist rejects plan/hidden-answer keys);
* hidden grading material before the student has submitted.

Ordering is mandatory: **identity authorization → course authorization → file-scope filtering →
field trimming → Jev call**. A decision is never made on a payload that skipped a step.

One surface is deliberately narrower than it looks: module A judges a question label read out of the
learner's **own message**, so the text it sends is the message the learner typed (normalised
whitespace) plus the label and its character span — never retrieved material, never another user's
content. The label itself is a query token, not course material, and its source is authorized for that
reason alone (`QueryTextSourceRegistry` refuses every other source id, so the verifier cannot be
pointed at material to launder authority through it).

### 2a. Cache scope is derived from the caller, never from the transport

Every judgment carries a server-derived scope, and the scope is built from the *caller's* identity and
authorization scope, **not** from the decision service. That distinction is a real defect found in round
30: the first version of the module-A wiring took the scope from an optional service argument, so a run
without a service object fell back to a single shared server-internal scope and the second learner was
served the first learner's cached judgment. `test_cache_scope_is_owner_scoped_and_never_crosses_users`
reproduces it (two owners, one repeated call: exactly two scopes, and the repeat served from the owner's
own cache) and now pins it. Any future call site should take `owner_user_id`/`authorization_scope` as
*required* arguments for the same reason.

## 3. Authority limits

Jev cannot write grades, LEARNED, coverage, permissions or budgets; it cannot open a transaction,
execute SQL beyond its own stores, or generate user-visible teaching text. The layer writes exactly two
tables: `jev_decision_receipts` (migration 028, every decision) and `entity_relations` (migration 029,
**proposals only**, `status='PROPOSED'` — the semantic layer can never write `ACCEPTED`/`REJECTED`, and
nothing on the retrieval path reads, merges, renames, reorders or deletes anything because of a row
there). Call-site tests assert that learning/grade/coverage row counts are unchanged across a fully
wired flow, and a database *without* migration 029 still retrieves the identical deterministic order
(`test_relation_bookkeeping_never_breaks_retrieval_without_the_store`).

Probability semantics are part of the safety story, not a detail: a Score is an ordered level, a Noul
is a probability, and neither is a mark, a mastery level, a permission or a completion state.
`probability_is_grade=false` is a contract, not a comment, and a Jev confidence is never authorization.

Two module-specific boundaries are enforced in code and proven by test:

* **Evidence resolution (module D).** The production resolver is read-only, is constructed per request
  with the server-derived subject, reuses the canonical document ACL (`can_read_document_version` →
  `_authorize_document_version`) and chunk scope (`_source_access`) rather than copying either, answers
  `ok`/`missing`/`unauthorized` instead of raising, and bounds the text it can hand to a model. Tests
  prove another user's private document and another course's document both come back `unauthorized` with
  empty text on a real migrated database.
* **Tool intent (module F).** The guard can only ever *withhold* a write: a `CONSISTENT` verdict cannot
  grant a permission the actor lacked, read-only tool calls are never gated, and the mode defaults to
  `off`, where no HTTP call is made at all and the existing synchronous path is byte-identical.

## 4. Failure matrix

| Condition | Deterministic behaviour | User impact |
|---|---|---|
| Jev timeout / unavailable | original RRF for retrieval; MUST_KEEP + recent window for context; template default for pedagogy; `PENDING_REVIEW` for coverage; existing review for assessment; `INSUFFICIENT_CONTEXT` for a citation card; no conflict note; the capability baseline for routing | none — the product keeps working |
| Jev returns an unknown candidate id | rejected (`JEV_INVALID_RESPONSE`) and the deterministic value is used | none |
| Jev returns non-finite / out-of-range numbers | rejected, fallback recorded | none |
| Input exceeds the decision budget | deterministic fallback; the half-question is never sent | none |
| Circuit breaker open | fail fast for the cooldown, fallback recorded, no retry storm | none |
| Repeated identical failure | one attempt per decision; receipts record outcomes; no automatic paid retry; identical claim+source states de-duplicate to one call | none |
| Coverage service down | `PENDING_REVIEW` — the student is never marked "not learned" | a review item appears instead of a wrong state |
| Assessment criterion review down | marks come from the existing grader/review path; never zero because a tool failed | grading completes |
| Citation audit fails outright | the citation cards are returned un-annotated with `audit_error` recorded on them; the answer is still delivered | none — an audit can never lose an answer that was already generated |
| Cited document is stale, missing or unauthorized at the message revision | the card is annotated (`REJECTED` + reason); the citation is never silently dropped | the learner sees an explicit "not verifiable" marker |
| Tool-intent guard unavailable (enforce mode) | `CONFIRMATION_REQUIRED`, the write does not run, the model is told to ask the user | the learner is asked to confirm instead of a silent write |
| Receipt write fails | the decision still degrades deterministically; the failure is logged without payload contents | none |

Every fallback is labelled (`path=fallback:<reason>`) so a result is never presented as a Jev decision
that never happened.

## 5. Logging and privacy

Logs record identifiers, hashes, lengths, timings and typed errors — never full student answers,
private course text, plan content or keys. Receipts store the decision metadata (definition id and
version, model/calibration version, mode, outcome, cache-scope keys, latency) and not the raw private
payload.

The one place where user-authored content is stored is the feedback queue, and its rule is structural
rather than procedural (migration 030): a `feedback_reports` row carries identifiers by default, and a
CHECK constraint refuses any question/answer/description text unless the submitter set `attach_body`.
A future code path therefore cannot store a body without consent even if it wanted to; the endpoint
and the triage module enforce the same rule earlier, and the shipped form only enables the free-text
field once the consent box is ticked. Only an admin can list the queue (`GET /api/feedback/queue`), a
user can list their own reports (`GET /api/feedback/mine`), and nothing in the module resolves,
deletes, sanctions or grades anything — the store exposes read/append methods only, which a test
pins.

## 6. Cost safety

* One attempt per decision, no automatic retry, no automatic paid escalation.
* Independent questions on one state are batched into a single call; dependent decisions run in later
  rounds; deterministic rules cost **0** Jev calls. Explicit commands (继续/只回答/做一题/交卷) are
  answered by the deterministic router and never reach the model at all — proven by asserting the
  receipt count is 0.
* Per-answer bounds are enforced, not assumed: the citation audit checks at most 6 cards per answer and
  the test asserts the transport call count matches, and identical claim+source states de-duplicate to a
  single call at the gateway.
* Before any billable run the harness prints the call count, per-definition input-token ceilings, the
  price applied and the combined ceiling, and refuses to start when the ceiling exceeds `--max-cost`.
* A Jev outage never triggers a silent surge of DeepSeek calls: generation still obeys the user's
  strength setting and the existing operation budget.

## 7. Local-attack surface

The layer exposes **one** internal endpoint, added for the tool-intent guard:
`POST /api/jev/tool-intent` in the RAG service. Its defence is explicit and tested: a constant-time
comparison against `JEV_TOOL_INTENT_TOKEN` (never logged, never echoed), **503 when that token is not
configured** so an unconfigured deployment cannot be called at all, 401 on a mismatch, and a bounded
pydantic body (message/tool/permission/revision lengths plus a serialized `tool_arguments` cap). It
returns a verdict and writes nothing except the Jev receipt. Everything else is private: definitions
and versions are server-managed, candidate ids are server-generated, and request size, candidate count
and definition version are validated server-side. There is no URL-fetch or file-read capability in the
layer, so a model answer cannot be turned into an SSRF, an arbitrary read or a command — and the
evidence resolver of module D reads only already-authorized local rows.

## 8. Verification status

| Claim | Evidence |
|---|---|
| Zero Qwen egress from the migrated provider paths | host-spy tests |
| Jev cannot invent a candidate / write state | gateway + wiring tests |
| Jev writes only its receipts and proposal-only relations | `test_schema_rollback_compat.py` additive-table list, entity-relation tests, no-state-write invariant test |
| Failure paths degrade deterministically | gateway/callsite tests with a failing fake transport; byte-identity tests for shadow/off/unavailable/no-Jev in modules B and C |
| The citation audit cannot leak or lose anything | `test_jev_citation_evidence.py` (cross-user and cross-course `unauthorized`), `test_citation_audit_binding.py` (byte-identical cards with no semantic layer; failure recorded, answer kept) |
| The tool-intent endpoint fails closed | `test_api_tool_intent.py` (503 without a configured token, 401 on mismatch, bounded body) |
| Keys never appear in artifacts | canary/ablation artifact assertions |
| **Live** TypeSafe behaviour, retry/pricing reality, and real fallback rates | Measured in rounds 83–90 and recorded in `JEV_CALLSITE_MATRIX.md`: 31 definition-level live cases over 19 definitions, and a structured browser run whose receipt store records **169 decisions, every one `outcome=ok` and every one carrying a `model_version`** (no fallback answered any of them). Bounded work in a disabled path may still be unmeasured — a *priced* per-definition cost table is not yet produced, and the 0.68–1.35 s latency spread is an observation, not a percentile |

### 8a. The tool-intent guard's timeout is close to the model's own latency (measured, round 90)

`JEV_TOOL_INTENT_TIMEOUT_MS` defaults to **1500 ms** and the agent bounds it to 100–10 000 ms. The
live decision measured in round 90 took **681 ms once and 1352 ms on average across two calls** — so
on the first attempt at the explicit-write journey the guard gave up before the answer arrived, the
record became `{verdict: REQUIRE_CONFIRMATION, path: fallback:unavailable, jevCalls: 0}`, and a
perfectly legitimate, explicit write was refused.

Three things are worth stating separately:

1. **The behaviour is correct.** An unavailable verdict must not be treated as ALLOW; fail-closed is
   the whole point of this guard, and the journey "a write whose intent check cannot answer is not
   executed" now asserts that path *deterministically* (an intentionally unreachable endpoint) rather
   than racing the default timeout.
2. **The margin is not.** A 1.5 s budget against a 0.68–1.35 s decision means an ordinary slow call
   turns into "please confirm what you already said". A deployment that sets
   `JEV_TOOL_INTENT_MODE=enforce` should raise the budget (the explicit-write journey requires ≥5 s
   for exactly this reason), and this is recorded as an operational requirement rather than a tuning
   nicety.
3. **The empty string is not a valid value and the failure is loud.** The agent refuses to start with
   `Expected an integer between 100 and 10000`, which is the right behaviour — but it is worth knowing
   because a Playwright config's `?? ""` passes exactly that, and PowerShell *deletes* an env var
   assigned `""`, so the same misconfiguration cannot be reproduced by hand in the shell. Both facts
   cost a run in round 90 and are written into `playwright.jev.config.ts`.

