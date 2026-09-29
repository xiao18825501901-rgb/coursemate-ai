# P0 · Zero-call diagnostics (2026-09-30)

Three diagnostics that cost no model requests, run on the real candidate tree
`2f189df` against a verified **copy** of the live database.  The production
environment files were never sourced; every variable was set explicitly; the
copy was checked with `realpath`/`samefile` before use and deleted after.

* live DB: `/srv/coursemate/data/releases/20260919T202006Z/rag.sqlite3` (688 455 680 B)
* copy: `/srv/coursemate/staging/p0diag-<stamp>/copy/rag.sqlite3`
* live DB before and after: `integrity_check=ok`, provenance 49 READY / 9 NEEDS_REVIEW,
  `hybrid_quality_receipts` = 0.  Nothing was written to production.

---

## 1. CS3481 deterministic failure — root cause found

**Command** (zero provider calls):

```
PYTHONPATH=<stage>/services/rag-api RAG_DATABASE_PATH=<copy> V3_ENABLED=true \
  python diagnose_not_eligible.py <copy>
```

**Result over all nine recoverable candidates:**

| candidate | identity rendering | report | failing gate |
|---|---|---|---|
| `qe_c4cbbc509c144a19a7adb8aa0d05fa3f` | CANONICAL | NEEDS_REVIEW | — |
| `qe_493ce9e110b94036b629e8f477d54880` | CANONICAL | NEEDS_REVIEW | — |
| `qe_de9fc4628cba4190918382b8346d7231` | CANONICAL | NEEDS_REVIEW | — |
| `qe_83b8f8c1bd2f48139e2ceed806b732fd` | CANONICAL | NEEDS_REVIEW | — |
| `qe_da1da684685c456ab83742439aa7e726` | CANONICAL | NEEDS_REVIEW | — |
| `qe_fc260e7e290943e680926df37b372a0b` | CANONICAL | NEEDS_REVIEW | — |
| `qe_1c8e7b8e492c4deeb9eb0ef7bfc714c7` | CANONICAL | NEEDS_REVIEW | — |
| `qe_2e26998e021a4eb29491d8cadef97143` | CANONICAL | NEEDS_REVIEW | — |
| **`qe_22cfcc081c3e4fa2899d53fd400671e2`** | **INTEGRAL_FLOAT_AS_INT** | **REJECTED** | **INPUT_IDENTITY** |

**Exact cause.** Two stages of the same pipeline disagree about which rendering of
the blueprint identity is acceptable:

* **Stage 1, recovery** — `candidate_recovery.blueprint_identity_match()`
  (`app/learning/candidate_recovery.py:109`) accepts the canonical hash **and** one
  named legacy rendering: an integral float written as an integer, accepted only
  when it reproduces the recorded hash exactly.  All nine rebuild.
* **Stage 2, validator** — `question_validator._input_identity_matches()`
  (`app/learning/question_validator.py:147-163`, line 154) compares
  `candidate.blueprint_hash == blueprint.identity()`, i.e. the **current canonical
  rendering only**.  For the one legacy row the two differ, so the gate fails.

Measured on the copy for that candidate:

```
stored_blueprint_hash      = 8eb0ccf7bcc87f6027c2e116a16858370db21db7ab712050ffc3abfbfd1ec1f0
candidate_blueprint_hash   = 8eb0ccf7bcc87f6027c2e116a16858370db21db7ab712050ffc3abfbfd1ec1f0   (equal)
model_identity_now         = dc213311808a090d5adb60c2b76d6e039629652bd047522dc54c81624bf78371   (differs)
```

**Version / stage difference, exactly as asked.**  The stored version split is a
fact in the database, not an inference: provenance rows written **2026-09-25**
serialise `marks` as an integer (`20`), rows written from **2026-09-27** serialise
it as a float (`20.0`).  19 of the 58 provenance rows are in the earlier form.
Of the nine `NEEDS_REVIEW` candidates exactly one is in the earlier form —
`qe_22cfcc081c3e4fa2899d53fd400671e2`, created `2026-09-25T13:01:37.773Z` — and it
is the one that fails.  Every stored value is identical; only the JSON rendering
of `marks` differs.

So the earlier statement "all nine pass the six gates" was true of the **recovery
stage** and the later single failure is true of the **validator stage**; both are
the same data read by two different rules.  This is a legitimate old-data /
new-construction defect, **not** a wrong question: the correct handling is a
regression fix that routes the validator through the same named rendering, never
a human card over a hard FAIL.

---

## 2. Provider failures — what is measurable, and what is not

### 2.1 Census of every stored run

| run | manifest rows | outcome rows | provider failures | rows lost | reviewer calls | failures / call |
|---|---|---|---|---|---|---|
| run1 | 43 | 40 | 3 | 3 | 86 | 3.49 % |
| run3 | 27 | 26 | 1 | 1 | 54 | 1.85 % |
| run4 | 30 | 28 | 2 | 2 | 60 | 3.33 % |
| run6 | 64 | 55 | 9 | 9 | 128 | 7.03 % |
| run7 | 69 | 65 | 4 | 4 | 138 | 2.90 % |
| run8 | 67 | 60 | 7 | 7 | 134 | 5.22 % |
| run9 | 66 | 60 | 6 | 6 | 198 | 3.03 % |
| **all stored** | **366** | | **32** | | **798** | **4.01 %** |

run2 and run5 have **no stored artifact**; run5 is `REPORTED_SUMMARY_ONLY /
ARTIFACT_LOST` and is not used for any recomputable conclusion.

The manifest/outcome arithmetic reproduces the reported 9/64, 7/67 and 6/66 exactly.

### 2.2 The layer taxonomy the adapter can already produce

`app/learning/provider.py` sets `run["error_class"]` to exactly one of:

| value | layer |
|---|---|
| `MODEL_LIVE_BLOCKED`, `MODEL_ENDPOINT_INVALID` | local configuration (`status=BLOCKED`) |
| `CONTEXT_BUDGET`, `IMAGE_MODEL_LIMIT` | local input validation |
| `MODEL_INCOMPLETE` | provider returned, terminal `status != completed` |
| `AUTO_LEDGER_WRITE_FAILED` | local durability failure (`status=UNKNOWN`) |
| `SCHEMA_INVALID` | **complete** response that did not match the schema |
| `APITimeoutError`, `APIConnectionError`, `RateLimitError`, `APIStatusError`, `InternalServerError`, … | upstream transport / HTTP |

and `run["status"]` to `BLOCKED`, `FAILED` or `UNKNOWN`.

### 2.3 The per-request layer is **not** recoverable — and that is a defect

The only keys persisted in `row_failures` are `code`, `row_id`, `step`.  There is
no `error_class`, no `status`, no latency, no provider response id, no token
count — and the staging copies that held the call ledger were removed by design.

The information existed: `ProviderCallFailure` carries
`run["error_class"]` and `run["status"]`; `DeepSeekStrongReviewer._one()`
re-raises it as `StrongReviewError(provider_run=failure.run)`; and
`hybrid_quality` then persists **only the code string**.  So this is a plumbing
gap, not missing evidence in principle.  **Per-request layer for the 32 stored
failures = UNKNOWN**, and it is recorded as UNKNOWN rather than guessed.

The same gap explains the real-candidate failure: 7 receipts × 3 calls = 21 rows
in `hybrid_review_calls`, and the eighth candidate's failed call left no row at all.

### 2.4 What *is* determinable

1. **Every recorded failure is row-scoped.**  In all seven runs the number of
   failed rows equals the number of rows missing from `row_outcomes`
   (3/3, 1/1, 2/2, 9/9, 4/4, 7/7, 6/6).  A provider failure therefore reduces
   coverage; it is never scored as a semantic negative, and it is not removed
   from the completion denominator silently.
2. **Short transient windows, not per-content rejection.**  Three runs show two
   consecutive calls failing on the same base item
   (`rule_explanation-2` steps 36 & 39; `rule_explanation-6` steps 63 & 64;
   `rule_explanation-6` steps 64 & 66).  A per-prompt schema incompatibility
   cannot produce that pattern, and cannot explain a family that passes in the
   next run with the same prompt version.
3. Failure counts by defect kind (DISAGREEING_SOLUTION 10, UNSUPPORTED_RULE 9,
   positive 8, MISSING_CONDITION 4, DUPLICATE_CORRECT_OPTION 1) track the row
   mix, not any one shape — 55 % of all rows are `rule_explanation`.
4. Author/blind provider failures are a **separate** class
   (`BlindSolveError` 4, `AuthorGenerationError` 4) and are not mixed into the
   reviewer failure rate.

### 2.5 The fix this requires

Persist the provider failure's own record (`error_class`, `status`, latency,
response id, usage) with the failure code, and persist the **complete response
body before any schema or citation processing**.  Without that, no future run can
be diagnosed either, and the documented rule "a complete response that failed
JSON/schema validation is not an upstream outage" stays unenforceable.

---

## 3. The nine stored candidates — one mutually exclusive disposition each

| # | candidate | course | type | marks | created | failed gates | case outcomes | disposition |
|---|---|---|---|---|---|---|---|---|
| 1 | `qe_22cfcc081c3e4fa2899d53fd400671e2` | cs3481 | EXPLANATION | 20 | 09-25T13:01 | INPUT_IDENTITY | — | **DETERMINISTIC_HARD_FAIL** |
| 2 | `qe_2e26998e021a4eb29491d8cadef97143` | ge2324 | EXPLANATION | 20 | 09-25T19:40 | none | ambiguity FAIL, agreement FAIL | **SUBSTANTIVE_DISAGREEMENT** |
| 3 | `qe_1c8e7b8e492c4deeb9eb0ef7bfc714c7` | ge2324 | EXPLANATION | 20 | 09-25T21:14 | none | ambiguity FAIL, agreement PASS | **AMBIGUITY_ONLY** |
| 4 | `qe_fc260e7e290943e680926df37b372a0b` | ge2324 | SHORT_TEXT | 15 | 09-25T21:17 | none | ambiguity FAIL, agreement FAIL | **SUBSTANTIVE_DISAGREEMENT** |
| 5 | `qe_da1da684685c456ab83742439aa7e726` | ge2324 | EXPLANATION | 30 | 09-28T11:28 | none | ambiguity FAIL, agreement PASS | **AMBIGUITY_ONLY** |
| 6 | `qe_83b8f8c1bd2f48139e2ceed806b732fd` | course-de7b… | MCQ_SINGLE | 10 | 09-28T20:42 | none | ambiguity FAIL, agreement PASS, mcq PASS | **AMBIGUITY_ONLY** |
| 7 | `qe_de9fc4628cba4190918382b8346d7231` | course-de7b… | MCQ_SINGLE | 10 | 09-28T20:42 | none | ambiguity FAIL, agreement FAIL, mcq FAIL | **SUBSTANTIVE_DISAGREEMENT** |
| 8 | `qe_493ce9e110b94036b629e8f477d54880` | ge2324 | EXPLANATION | 100 | 09-28T20:43 | none | no receipt | **PROVIDER_FAILURE_NO_RECEIPT** |
| 9 | `qe_c4cbbc509c144a19a7adb8aa0d05fa3f` | ge2324 | EXPLANATION | 100 | 09-28T20:47 | none | ambiguity FAIL, agreement PASS | **AMBIGUITY_ONLY** |

Census: **4 ambiguity-only · 3 substantive disagreement · 1 provider failure ·
1 deterministic hard failure = 9**, mutually exclusive and complete.  The report's
4 + 3 + 1 + 1 is confirmed by recomputation rather than by summary.

### 3.1 The version/stage difference, stated once

* **9 candidates pass six gates** — stage 1, the recovery rebuild, which accepts
  the named legacy rendering.
* **1 candidate fails INPUT_IDENTITY** — stage 2, the validator, which does not.

One data set, two stages, two rules.  The row in question is the single candidate
written on 2026-09-25; the other eight were written on 2026-09-25T19:40 or later
and render canonically.  This is not corruption, not a lost value, and not a
wrong question.

### 3.2 Next action per disposition

| disposition | next action |
|---|---|
| `qe_22cfcc08…` DETERMINISTIC_HARD_FAIL | fix the validator's named-rendering regression, then re-run the gates on the same stored revision.  The card is **not** used to override a hard FAIL. |
| `qe_2e26998e…`, `qe_fc260e7e…`, `qe_de9fc462…` SUBSTANTIVE_DISAGREEMENT | real author/blind divergence: decide with the checker who is wrong, then re-author under a **new revision** with a new hash.  A card cannot repair these. |
| `qe_1c8e7b8e…`, `qe_da1da684…`, `qe_83b8f8c1…`, `qe_c4cbbc50…` AMBIGUITY_ONLY | re-examine under the new public task contract and the constructive-witness protocol: either exhibit a real witness (then revise) or record a positive completeness certificate for a registered bounded profile.  No receipt is rewritten to PASS. |
| `qe_493ce9e1…` PROVIDER_FAILURE_NO_RECEIPT | keep the existing paid result; the failure's layer is UNKNOWN.  Any new attempt is a new linked operation. |

### 3.3 Prices and evidence that are kept

All original receipts keep their identity, their `QUALITY_NOT_ACCEPTED` status and
their `UNQUALIFIED` qualification id.  Nothing here rewrites a historical result
to PASS, and no human name is signed by a machine.
