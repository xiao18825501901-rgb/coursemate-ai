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

## 3. Authority limits

Jev cannot write grades, LEARNED, coverage, permissions or budgets; it cannot open a transaction,
execute SQL beyond the receipt table, or generate user-visible teaching text. The only table the layer
writes is `jev_decision_receipts` (migration 028). Call-site tests assert that learning/grade/coverage
row counts are unchanged across a fully wired flow.

Probability semantics are part of the safety story, not a detail: a Score is an ordered level, a Noul
is a probability, and neither is a mark, a mastery level, a permission or a completion state.
`probability_is_grade=false` is a contract, not a comment, and a Jev confidence is never authorization.

## 4. Failure matrix

| Condition | Deterministic behaviour | User impact |
|---|---|---|
| Jev timeout / unavailable | original RRF for retrieval; MUST_KEEP + recent window for context; template default for pedagogy; `PENDING_REVIEW` for coverage; existing review for assessment | none — the product keeps working |
| Jev returns an unknown candidate id | rejected (`JEV_INVALID_RESPONSE`) and the deterministic value is used | none |
| Jev returns non-finite / out-of-range numbers | rejected, fallback recorded | none |
| Input exceeds the decision budget | deterministic fallback; the half-question is never sent | none |
| Circuit breaker open | fail fast for the cooldown, fallback recorded, no retry storm | none |
| Repeated identical failure | one attempt per decision; receipts record outcomes; no automatic paid retry | none |
| Coverage service down | `PENDING_REVIEW` — the student is never marked "not learned" | a review item appears instead of a wrong state |
| Assessment criterion review down | marks come from the existing grader/review path; never zero because a tool failed | grading completes |
| Receipt write fails | the decision still degrades deterministically; the failure is logged without payload contents | none |

Every fallback is labelled (`path=fallback:<reason>`) so a result is never presented as a Jev decision
that never happened.

## 5. Logging and privacy

Logs record identifiers, hashes, lengths, timings and typed errors — never full student answers,
private course text, plan content or keys. Receipts store the decision metadata (definition id and
version, model/calibration version, mode, outcome, cache-scope keys, latency) and not the raw private
payload.

## 6. Cost safety

* One attempt per decision, no automatic retry, no automatic paid escalation.
* Independent questions on one state are batched into a single call; dependent decisions run in later
  rounds; deterministic rules cost **0** Jev calls.
* Before any billable run the harness prints the call count, per-definition input-token ceilings, the
  price applied and the combined ceiling, and refuses to start when the ceiling exceeds `--max-cost`.
* A Jev outage never triggers a silent surge of DeepSeek calls: generation still obeys the user's
  strength setting and the existing operation budget.

## 7. Local-attack surface

There is no public Jev endpoint: the service is private and the model node (had the abandoned Laya
direction continued) was never created. The layer accepts no client-supplied schema: definition ids
and versions are server-managed, candidate ids are server-generated, and request size, candidate count
and definition version are validated server-side. There is no URL-fetch or file-read capability in the
layer, so a model answer cannot be turned into an SSRF, an arbitrary read or a command.

## 8. Verification status

| Claim | Evidence |
|---|---|
| Zero Qwen egress from the migrated provider paths | host-spy tests |
| Jev cannot invent a candidate / write state | gateway + wiring tests |
| Failure paths degrade deterministically | gateway/callsite tests with a failing fake transport |
| Keys never appear in artifacts | canary/ablation artifact assertions |
| **Live** TypeSafe behaviour, retry/pricing reality, and real fallback rates | **`NOT_RUN`** — no credential; no live evidence is claimed |

The live failure-rate numbers (timeout rate, queue/meltdown behaviour, per-definition cost) can only be
produced once the credential and budget in `MINIMAL_OWNER_ACTION_CARD.md` exist.
