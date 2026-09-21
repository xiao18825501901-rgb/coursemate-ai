# Laya Replacement Architecture

This workstream replaces the TypeSafe "Jev" transport with the self-hosted **Laya**
transport (Apache-2.0, PyPI `laya` 0.3.4, HF `convaiinnovations/laya` @
`multilingual` @ `1c5edc17a7acd8701df6fc341c0d179f1c62c982`), and removes TypeSafe
from the production path. The 12 decision definitions and their authority rules are
unchanged — only the transport changed.

## What landed (owned by this workstream)

| Path | Change |
|---|---|
| `services/rag-api/app/laya/errors.py` | Typed Laya errors (`LayaError`, `LayaUnavailableError`, `LayaTimeoutError`, `LayaInvalidResponseError`, `LayaUnsupportedError`). |
| `services/rag-api/app/laya/models.py` | Frozen dataclasses (`LayaQuestion`, `LayaRequest`, `LayaAnswer`, `LayaDiagnostics`, `LayaReply`, `LayaScope`) + `request_content_hash`. |
| `services/rag-api/app/laya/adapter.py` | `LayaTransport` protocol, `HttpLayaTransport`, `FakeLayaTransport`, `CircuitBreaker`, `LayaConfig`, `LayaReceipt` + `LayaReceiptStore` protocol, `LayaGateway`, `LayaDecision`, strict validation. |
| `services/rag-api/app/laya/receipt_store.py` | `SqlLayaReceiptStore` (SQLite receipts + cache lookup on the `laya_decision_receipts` table). |
| `services/rag-api/app/jev/errors.py` | Added `JevRetiredError` (subclass of `JevNotConfiguredError`). |
| `services/rag-api/app/jev/gateway.py` | `SdkTransport` retired: no `typesafe_sdk` import, no TypeSafe credential read, any `call()` raises `JevRetiredError`. Historical gateway remains importable. |
| `services/rag-api/app/jev/__init__.py` | Export `JevRetiredError`. |
| `services/rag-api/app/jev/models.py` | Docstring updated to historical-shim wording. |
| `services/rag-api/app/config.py` | Added `laya_*` settings (`laya_base_url`, `laya_api_key`, `laya_model_revision`, `laya_compiler_version`, `laya_timeout_seconds`, `laya_max_request_chars`, `laya_default_mode`, breaker + calibration fields). |
| `services/rag-api/migrations/029_laya_decision_receipts.sql` | Additive neutral receipt table (see below). |
| `services/rag-api/tests/test_laya_adapter.py` | Adapter unit tests (parsing, validation, transport, temperature). |
| `services/rag-api/tests/test_laya_gateway.py` | Gateway semantics (modes, fallback, deadline, breaker, receipts, cache). |
| `services/rag-api/tests/test_typesafe_zero_egress.py` | Zero-egress proof (static + dynamic HTTP-spy). |
| `LAYA_REPLACEMENT_ARCHITECTURE.md` | This document. |

## Migration 029 — `laya_decision_receipts`

Migration `029_laya_decision_receipts.sql` is purely additive. It creates a neutral
receipt table and its cache index and records ledger version 29. It does **not**
rename anything (so there are no `*_new` / `*_old` leftovers) and it does **not**
touch migration 028's `jev_decision_receipts` table or its content — historical
rows stay readable.

Columns: `id`, `provider` (default `'laya'`), `definition_id`, `definition_version`,
`model_revision`, `compiler_version`, `calibration_version`, `temperature` (NULL
when the model's identity all-1.0 temperature is in effect), `mode`
(`off|shadow|on|advisory`), `outcome`, the cache-scope keys (`owner_scope_hash`,
`course_id`, `workspace_id`, `material_revision`, `node_id`, `spec_version`,
`question_hash`, `input_hash`), `output_json`, `latency_ms`, `created_at`.

The cache index maps the catalog `provider_model_version` dimension to
`model_revision`.

## Frozen interface notes (deviations are additive, not renames)

* `LayaReply.diagnostics` is `LayaDiagnostics | None` (defaults `None`) instead of
  always-required — the name is unchanged.
* `LayaDecision` adds one optional field `answer: LayaAnswer | None` so `advisory`
  (and `on`) can surface the validated suggestion; `shadow` keeps it receipt-only.
* `LayaGateway.decide(request, *, scope, fallback=None)` adds an optional
  keyword-only `fallback` so `value` can hold the deterministic fallback directly.
  `request` and `scope` are unchanged; callers may still call
  `decide(request, scope=scope)` and apply their own fallback when `used_laya` is
  False.

## Rules → verification mapping

| Rule | How it is verifiable |
|---|---|
| 1. No TypeSafe in production path | `tests/test_typesafe_zero_egress.py::test_no_module_imports_typesafe_sdk` (AST: no `typesafe_sdk` import in `app/jev/**` or `app/laya/**`), `::test_jev_gateway_source_has_no_typesafe_construction` (no `typesafe_sdk`/`TYPESAFE_API_KEY`/`TypeSafeClient(`/`api.typesafe.ai` in `gateway.py`), and `SdkTransport.call()` raises `JevRetiredError` (asserted in `::test_semantic_layer_zero_egress_to_typesafe_or_qwen`). |
| 2. Catalog stays the Laya catalog | `tests/test_jev_catalog.py` (unchanged, still green) — same 12 ids/versions; no rename of historical provider fields or migration 028. |
| 3. Receipts record the truth | `tests/test_laya_gateway.py::test_receipt_records_the_truth` + migration probe (`provider='laya'`, `model_revision`, definition id+version, `calibration_version`, `latency_ms`, `outcome`, cache-scope keys). |
| 4. Validation matches the official output | `tests/test_laya_adapter.py::test_choice_rejects_invented_id`, `::test_choice_rejects_invented_probability_key`, `::test_choice_rejects_nonfinite_probability`, `::test_choice_rejects_probability_mass_not_one`, `::test_score_rejects_out_of_range_index`, `::test_score_valid_and_exposes_legend`, `::test_noul_uses_p_true_only_and_never_a_confidence`, `::test_noul_rejects_out_of_range`, `::test_concentration_peak_is_one_uniform_is_zero`, `::test_identity_temperature_records_none`, `::test_calibration_temperature_is_recorded_explicitly`. |
| 5. Modes + deterministic fallback, no Jev/Qwen fallback | `tests/test_laya_gateway.py::test_mode_for_defaults_to_shadow`, `::test_off_*`, `::test_shadow_*`, `::test_on_uses_laya_value`, `::test_advisory_*`, `::test_invalid_choice_falls_back_with_reason_and_no_retry`, `::test_transport_failure_falls_back_with_reason`; `test_typesafe_zero_egress.py` proves no Jev/Qwen fallback. |
| 6. Deadline + circuit breaker | `tests/test_laya_gateway.py::test_deadline_passed_before_call_skips_transport`, `::test_late_reply_is_discarded`, `::test_circuit_breaker_opens_and_fails_fast`. |
| 7. Zero-egress proof | `tests/test_typesafe_zero_egress.py` (patches `urllib.request.urlopen`, runs all modes + a live-transport failure, asserts every outbound URL is our Laya node and none matches `typesafe`/`qwen`/`dashscope`/`aliyuncs`/`modelstudio`). |
| 8. UI test-provider label | Recorded below (integration request) — not edited here because `apps/web/src/ui/pages.jsx` is owned by another workstream. |

## Integration requests (files owned by other workstreams — NOT edited here)

1. **`services/rag-api/app/db.py`** — append `"029_laya_decision_receipts.sql"` to
   `V3_MIGRATIONS` and bump `LATEST_V3_SCHEMA_VERSION` from `28` to `29`, so
   `Database.initialize()` applies the new table and `is_ready()` requires it.
   Until then migration 029 is applied only in this workstream's probe/tests.

2. **`apps/web/src/ui/pages.jsx`** — one-line label change (see below).

3. **`apps/web/src/ui/App.jsx`** — related (different) strings still read
   `测试 Provider，不是真实千问` (line ~153) and `本地测试 Provider` (line ~729).
   Recommend harmonizing all three to `本地测试 Provider`; the required change is
   only the `· 非真实千问` string in `pages.jsx`.

4. **`services/rag-api/requirements.txt`** — the commented `typesafe-sdk==0.7.0`
   note (lines 12–16) is stale now that TypeSafe is retired; recommend removing it.

5. **Shared package note** — `services/rag-api/app/laya/__init__.py`,
   `app/laya/budget.py` and `app/laya/compiler.py` are owned by the **input-compiler
   workstream** (their `__init__.py` deliberately does not import this workstream's
   `adapter.py`/`models.py`/`errors.py`). This workstream's modules are imported by
   submodule path (`from app.laya.adapter import ...`). The compiler workstream's
   `content_hash` (provenance hash) and this workstream's
   `app.laya.models.request_content_hash` (request digest) are intentionally
   distinct functions.

## Exact one-line UI label change (for the other workstream)

File `apps/web/src/ui/pages.jsx`, line 735 — replace the test-provider label string
only:

```jsx
// BEFORE
... this.props.config.provider_mode === 'test' ? '测试 Provider · 非真实千问' : this.props.config.model}</span>
// AFTER
... this.props.config.provider_mode === 'test' ? '本地测试 Provider' : this.props.config.model}</span>
```

This removes the ambiguous `测试 Provider · 非真实千问` string from the UI. (The same
string also appears in three historical markdown reports in the repo root; those are
not code and were left untouched.)

## NOT_RUN / could not do

* **No live Laya call was made** — there is no model server yet. `HttpLayaTransport`
  is exercised only against injected spy openers that fail without a network call.
  Live state: **NOT_RUN**.
* No `pip install`, no venv creation, no network calls were performed; tests ran with
  the existing `services/rag-api/.venv/Scripts/python.exe`.
* The 12 business call-sites (in `app/ui_extension/**`, `app/learning/**`,
  `app/rag/**`, `app/cm_update/**`, `app/evaluation/**`) are wired by another
  workstream and were not edited.

## Verification results

* `pytest tests/test_laya_adapter.py tests/test_laya_gateway.py tests/test_typesafe_zero_egress.py -q` → **41 passed**.
* `pytest tests/test_jev_catalog.py tests/test_jev_gateway.py tests/test_jev_service.py tests/test_jev_wiring.py -q` → **23 passed**. The one test that encodes the retired transport (`test_jev_gateway.py::test_live_sdk_transport_raises_not_configured_without_key`) still passes because `JevRetiredError` subclasses `JevNotConfiguredError` (retirement is a permanent "not configured").
* Migration probe (fresh temp DB): `PRAGMA integrity_check = ok`, `foreign_key_check = []`, no `*_new`/`*_old` tables, legacy `jev_decision_receipts` row readable, `provider='laya'` + `model_revision` persisted, ledger versions `[28, 29]`.
* `ruff check` on every touched file → **All checks passed!**.
