# OPENJEV_50PCT_ROOT_CAUSE_AND_LOCAL_SCOPE

Status: `OPENJEV_DIAGNOSTICS_COMPLETE` · `OPENJEV_ADVISORY_SCOPE` ·
`LOCAL_RUNTIME_REUSED`

Scope: a *limited* fault-localisation of the recorded 0.50 held-out result and a
decision about what the local model may and may not do.  This is not a
re-tuning report: the model, dtype, tokenizer and thresholds were not changed to
make a number look better.

## 1. What was actually measured (recomputed from the frozen artifact)

Artifact: `artifacts/openjev-deployment/openjev-qualification-results-v2.json`
(`schema=coursejesus.openjev-qualification-run.v1`, sha256
`845dfc2f2eaee55412291e9e6a923967c84a3b82d1d4e269653a86d5b0cc3ef8`).
Recomputed by `work/hybrid-p0-20260929/diagnose_openjev_50.py`; no model call,
no network, no write.

| Fact | Value |
|---|---|
| candidates | 240 (4 definitions × 3 languages × 20) |
| gold provenance | `DETERMINISTIC_ORACLE` × 240 |
| `human_gold` | `false` × 240 |
| `truncated` | `false` × 240 |
| HTTP status | `200` × 240, zero transport errors |
| distinct `model_input_hash` | 240 (no cache collision, no duplicated input) |
| domains | `synthetic-formal-course-question` × 240 |
| served language | `en` × 80, `mixed` × 160 |
| mean top-1 probability | **0.3727** (median 0.3326, max 0.6054) |

Per-definition prediction distribution over all three languages:

| case | n | gold distribution | model predictions | degenerate? |
|---|---|---|---|---|
| `question.ambiguity.v1` | 60 | `CLEAR` 30 / `UNDER_SPECIFIED` 30 | `UNDER_SPECIFIED` 56, `AMBIGUOUS` 4 | near-constant |
| `question.answer_agreement.v1` | 60 | `AGREE` 30 / `DISAGREE` 30 | `AGREE` 60 | **constant** |
| `question.mcq_distractor_quality.v1` | 60 | `ACCEPTABLE` 30 / `WEAK` 30 | `WEAK` 60 | **constant** |
| `question.rule_violation_quality.v1` | 60 | `SUPPORTED` 30 / `UNSUPPORTED` 30 | `UNSUPPORTED` 60 | **constant** |

The runner assigns gold as `positive = index % 2` — an exactly balanced 10/10
binary split in every one of the twelve (case, language) groups.  A constant
predictor on balanced binary gold scores **exactly 0.50 in every subgroup, by
construction**.

### Conclusion 1 — the 0.50 is an evaluation-design artifact, not a capability measurement

"0.50 held-out accuracy" reads like "half right"; what it actually is, is
**no measurable signal**.  Three of four definitions emitted one label 60/60
times; the fourth scored 0.4333, i.e. *below* the constant-predictor baseline,
because four of its sixty outputs left the collapsed label.  The mean top-1
probability of 0.37 on a 4–5 option question (uniform would be 0.20–0.25) is
consistent with a near-uniform posterior.  No threshold can repair a
fixed-label classifier, and the source report itself already said so.

This also means the previously reported phrase "0.50 in every subgroup" **over-
stated** the model: the honest reading is "no signal", which is worse than 50 %.

## 2. The concrete, previously unrecorded defect behind it

The qualification harness and the production adapter were **not sending the same
input shape**.

* `services/openjev-service/scripts/run-qualification.mjs` sends the catalogue's
  real natural-language option descriptions, e.g.
  `CLEAR: "The supplied question is unambiguous and fully specified under the supplied rules"`.
* The production adapter sent **empty descriptions**: the four hard-gate call
  sites pass `candidate_labels=None`
  (`app/jev/service.py` — `question_ambiguity`, `question_answer_agreement`,
  `question_mcq_distractor_quality`, `question_rule_violation_quality`), which
  produced `criteria = {option_id: ""}` and reached the wire as
  `descriptions: {"CLEAR": "", "AMBIGUOUS": "", …}`.

Live probe against the running pinned service (`127.0.0.1:28765`, one shot, no
retry), recorded in `work/hybrid-p0-20260929/remote_probe_openjev2.sh`:

| request | result |
|---|---|
| `descriptions` all `""` (the production shape) | **HTTP 422 `INVALID_QUESTION`** |
| `descriptions` omitted entirely | HTTP 200 → `choice=UNCERTAIN` (bare option ids) |
| real catalogue descriptions | HTTP 200 → `choice=UNDER_SPECIFIED` |

So the four hard gates could not even succeed in production: the private service
rejects an empty description (`safeText` requires `length > 0`), and the gateway
turns any non-200 into `JevUnavailableError`.  Fail-closed, never a wrong
answer — which is exactly why this produced no visible production symptom.

The upstream contract (`questions.ts`) renders `"{option}: {description}"` and
falls back to the bare option id when the description is empty, so even the
"tolerated" variant asks a DeBERTa classifier to guess what `CLEAR` and `AGREE`
mean from the tokens alone.

The same bug class had been found and fixed once before for a *different*
module (`evidence_consistency.py`, recorded in
`DSH_JEV_DEEPSEEK_EXECUTION_STATE.md`); the four Question Engine gates still had
it.

### Repair applied

`SemanticDecisionService.definition_labels()` now adopts the catalogue's own
declared criteria when a call site supplies none **and** the catalogue's option
IDs match the requested option IDs exactly, with no empty value.  Matching is
exact, so a drifted vocabulary falls back to the previous behaviour instead of
describing the wrong option.  `bounded_choice_input_hash` uses the same
resolution, so a decision's input identity and its persistence-time re-check
still agree.

This is a real input-contract fix, and it changes the input hash for those four
definitions — correctly, because the input genuinely changed.  Historical
receipts are untouched and are not retro-validated against the new shape.

## 3. Other hypotheses checked and **not** confirmed

| Hypothesis | Result |
|---|---|
| wrong model / `kev` substitution | **No.** Boot asserts `family === "open-jev"` and `dtype === manifest.dtype`; the manifest is hash-verified (all five file hashes, `weightsHash` and `tokenizerHash` recompute exactly). |
| tokenizer mismatch | **No.** One tokenizer, loaded from the same verified snapshot. |
| label mapping reversed or index-misaligned | **No.** Labels are strings end to end with membership checks in the gateway and in the service; there is no index arithmetic to invert. |
| cache key too weak / a miss scored as a default | **No.** The local service has no cache; the gateway keys on definition + state + criteria + instructions + model version. A miss performs the call; failures are recorded and excluded from reuse. The 240 inputs are 240 distinct hashes. |
| truncation silently cutting the item | **No.** `truncation` must be the string `"error"`; the service refuses an over-long state (`INPUT_TOO_LONG`) rather than cutting it; the library's `"cut"` default is always overridden. Only a *non-token* character budget can drop optional state fields in the adapter, and that drop is recorded. |
| constant prediction caused by a constant/NaN logit | **Yes, in effect** — but as a collapsed posterior on a semantically empty option set, not as NaN. The empty-description defect is the mechanism; no NaN was observed and probabilities are finite and normalised. |
| default-positive fallback on INELIGIBLE | **No.** The deterministic fallback for all four gates is `UNCERTAIN`, and `used_jev` stays `False`. |

## 4. Three-layer consistency

| layer | model | tokenizer | option text sent | label mapping |
|---|---|---|---|---|
| upstream library | one `open_jev` DeBERTa family | single `AutoTokenizer` | `"{option}: {description}"`, bare id when empty | `options[argmax]` |
| HTTP wrapper (`services/openjev-service`) | manifest-pinned, family + dtype asserted at boot | same | forwards caller descriptions, requires non-empty | passthrough after contract checks |
| CourseJesus adapter (`app/jev/gateway.py`) | revision equality enforced on every response | same | **was: empty descriptions** → now: catalogue descriptions | passthrough, double membership check |

Same model and tokenizer at all three layers; same label mapping; the option
text was the one layer that diverged, and that is the repaired defect.

## 5. What OpenJev may and may not do after this round

The local candidate stays **advisory**.  `app/learning/openjev_observer.py`
records one observation per required case and exposes no field that can grant or
veto a decision:

* a local positive result **cannot** publish a question;
* a local negative result **cannot** veto one;
* an outage, timeout, over-long input or non-English item records a typed
  `UNAVAILABLE`/`SKIPPED` observation and the qualified strong review continues
  unaffected;
* the observer never deletes evidence, never truncates an item, and never
  triggers regeneration;
* observations are recorded under their own `UNQUALIFIED_ADVISORY`
  qualification with model revision, dtype, tokenizer hash, transform version,
  encoded token count, probability distribution and latency.

Chinese, mixed-language, image-bearing and over-long items are **skipped with a
recorded reason**, not translated or compressed into English to make the local
model applicable.

No local qualification is claimed.  The recorded status remains `UNSET`; the
repair makes a local observation *possible*, which is not the same as making the
model *right*.  A local qualification would require a fresh held-out evaluation
with real descriptions and genuinely independent negatives, and it would still
not be allowed to publish without the strong review in this policy revision.

## 6. Cost and runtime

The local path has no per-call vendor fee.  Its real costs are the ~1.45 GB
resident model, one pinned inference worker and the CPU time on a 2 vCPU / 4 GB
host; the service runs at `CPUWeight=25`, `MemoryHigh=1650M`, `MemoryMax=1800M`
with a queue limit of 8 and one inference at a time.  The DeepSeek review calls
added by this round are separate, billable and metered in their own receipt.
