# DEEPSEEK_AND_JEV_RUNTIME_CONTRACTS

The two external contracts CourseMate now depends on, as implemented — not as designed. Every
statement below is either verified by a test in this workspace or explicitly marked NOT_RUN.

Companion deep-dives: `docs/jev-deepseek/PROVIDER_CAPABILITY_MATRIX.md` (per-capability evidence
levels), `docs/jev-deepseek/DECISION_CATALOG_AND_CALIBRATION.md` (the 12 Jev decisions),
`JEV_APPLICATION_DECISION_MATRIX.md` (where each decision is applied).

---

## Part A — DeepSeek generation contract

### A1. Verified provider facts (checked 2026-09-21 from the official pages, not from caches)

| Field | Value |
|---|---|
| Model alias | `deepseek-flash` (DeepSeek-V4.1-Flash, released 2026-09-10) |
| Base URL (OpenAI-format) | `https://api.deepseek.com` |
| Paths | `/chat/completions`, `/responses` |
| Vision | native (JPEG/PNG/GIF/WebP) |
| Context / max output | 1M / 384K |
| Retired aliases | `deepseek-v4-flash`, `deepseek-v4-flash-vision-exp` — **not used** |

Evidence level: **OFFLINE_CONTRACT**. `LIVE_VERIFIED` for all of these is **NOT_RUN** (no
credential/budget in this session).

### A2. Role → protocol → model (explicit; no silent switch)

| Role | Protocol | Code path |
|---|---|---|
| UI teach / problem (normal + plan→work) | Responses (default) or Chat Completions | `app/cm_update/provider.py::DeepSeekProvider` |
| `exercise.v2` structured output | Responses `text.format` json_schema | same |
| 详解 (step explanation) | Responses | same |
| Course classification | Responses | same |
| V3 learning (plan / unit / problem / grade) | Responses | `app/learning/provider.py::LearningProvider` |
| Coverage reviewer | Chat Completions | `app/learning/coverage_review.py::deepseek_review_invoke` |
| Grounded QA | Responses | `app/rag/answers.py::DeepSeekAnswerProvider` |
| Node Task Agent | Responses | `services/agent-api/src/openai/client.ts` |

`QwenProvider`, `qwen_review_invoke` and `OpenAIAnswerProvider` survive **only as historical
classes for reading old records**. New generation cannot reach Qwen: the model string is explicit
per role and there is no fallback branch.

### A3. Payload rules

* No Qwen-only fields are ever emitted to DeepSeek (`enable_thinking`, `max_pixels`).
* Native thinking is explicitly disabled because the product owns the two-stage flow:
  Responses → `reasoning={"effort":"none"}`; Chat Completions → `thinking={"type":"disabled"}`.
* Structured output: Responses `text.format` json_schema (no invented `strict` field).
* Images use the documented `detail` field (`low`/`high`/`original`/`auto`).
* URL policy: HTTPS + explicit host/path allow-list, with a dedicated DeepSeek rule added
  **alongside** the existing Model Studio validator (the old validator was not weakened).
* `exercise.v2`'s private-answer contract and parser are unchanged; only the transport changed.

### A4. Boundaries

* **Embeddings remain an independent contract** (Alibaba `text-embedding-v4`,
  `app/rag/embeddings.py`). No dimension change, no index rebuild, no invented DeepSeek
  embedding API. Replacing embeddings would require separate retrieval-evaluation evidence.
* Historical Qwen messages keep their original provider identity; nothing is rewritten.

### A5. Verification

| Evidence | Result |
|---|---|
| `tests/test_deepseek_contract.py` + `tests/test_deepseek_provider_roles.py` (+ the pack/template suites) | 53 passed |
| Qwen-egress host spy across roles in the official configuration | covered by the role tests (see provider matrix) |
| Any live DeepSeek call, image understanding, structured output, tool replay, pricing | **NOT_RUN** — needs `DEEPSEEK_API_KEY` + approved budget (see `MINIMAL_OWNER_ACTION_CARD.md`) |

---

## Part B — TypeSafe Jev semantic-decision contract

### B1. SDK facts used (verified 2026-09-21)

| Item | Value |
|---|---|
| Package | `typesafe-sdk` **0.7.0**, MIT (PyPI) |
| Client | `TypeSafeClient(model="jev").system_one(state, questions)` |
| Primitives | `Choice(instructions, criteria={…})`, `Score(instructions, criteria=[…])`, `Noul(instructions)` |
| Response accessors | `.choices[k].choice`, `.scores[k].score`, `.nouls[k].noul` (0..1 float) |
| Credential | `TYPESAFE_API_KEY` — read server-side only; never exposed to the browser, logs or reports |
| UNKNOWN (not relied on) | the exact meaning of a returned `Score` (level key vs index vs description) — the validator accepts all three and records what it saw |
| Dependency policy | the SDK is imported lazily inside `SdkTransport` only; no new runtime dependency |

### B2. Gateway contract

Implemented in `app/jev/` (`gateway.py`, `service.py`, `catalog.py`, `receipt_store.py`,
`errors.py`, `models.py`) with migration `028_jev_decision_receipts.sql`.

* **Modes**: `off | shadow | on` per decision key. Default `shadow` for all 12.
* **Injectable transport**: `FakeTransport` in tests, `SdkTransport` for the real SDK. Without a
  credential the real path raises the typed `JEV_NOT_CONFIGURED` instead of degrading silently.
* **Bounds**: request size, batch size, timeout, concurrency and cancellation are explicit; there
  is no per-token chatty calling and **no automatic paid retry**.
* **Receipts**: every call records definition key, primitive, mode, caller role, owner scope hash,
  course/workspace, material revision, node/spec, question hash, input hash, outcome, latency and
  model version. Debug material is never stored as raw private text in receipts.
* **Cache scope**: authorization scope, course, workspace, material revision, node spec version,
  question definition hash, input hash, provider/model version. Deleting material, revoking
  access or changing the revision invalidates entries; a cached judgement is never reused across
  users.
* **Ordering rule**: independent questions over the same state may be batched; questions with
  dependencies must be issued in later rounds.
* **Pre-filtering**: inputs are filtered for user/course/file authorization *before* the call; the
  model never chooses what the user may see.

### B3. Authority rules (enforced, tested)

* `Choice` may only select ids the server supplied; an unknown id is rejected and never becomes a
  user-visible choice.
* `Noul` yes-probability and `Score` are **signals**: never a grade, a permission, a mastery
  state or a budget change. `probability_is_grade=false`.
* Jev never writes database state: permissions, transactions, sums, ids, official grades and
  completion remain in the deterministic services. A failed Jev call leaves learning state,
  coverage and grades untouched (tested).
* Jev confidence is never authorization.

### B4. The 12 decisions and current mode

All twelve are **shadow**; none is `on` (thresholds are `UNSET_UNTIL_CALIBRATED_ON_LABELLED_DATA`
and calibration requires labelled data plus credentials). Wired live-in-shadow today: retrieval
re-rank (reorder only, exact-target hits protected) and coverage item-support (recorded in
delivery provenance). Intent/context/pedagogy/assessment helpers exist and are tested but have no
live `on` call site. Full table: `JEV_APPLICATION_DECISION_MATRIX.md`.

### B5. Safe degradation (required behaviour)

| Failure | Behaviour |
|---|---|
| Jev unavailable / timeout / invalid response | retrieval falls back to the deterministic fused ranking; intent falls back to rule-based routing; coverage stays **pending**; assessment review falls back to the existing grader or `NEEDS_REVIEW` |
| Never | a wrong 0/full score, a fake LEARNED, an unverified citation, or any Qwen fallback |

### B6. Verification

| Evidence | Result |
|---|---|
| `pytest tests/test_jev_catalog.py tests/test_jev_gateway.py tests/test_jev_service.py tests/test_jev_wiring.py -q` | 23 passed (re-run by the responsible engineer, not only reported) |
| exact-target preservation under Jev reorder; shadow byte-identical to Jev-off | covered by `test_jev_wiring` |
| cache invalidation + cross-user isolation | covered by `test_jev_service` |
| live TypeSafe call | **NOT_RUN** — no credentials (typed `JEV_NOT_CONFIGURED`) |
| A/B/C/D ablation on labelled data | **NOT_RUN** — plan's 200 judgements / 40 trajectories / 30 image cases are a plan |
