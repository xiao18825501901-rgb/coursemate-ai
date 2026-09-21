# User-initiated feedback triage (module G)

A lightweight, user-initiated feedback triage in `app/jev/feedback_triage.py`.
DeepSeek generates; TypeSafe Jev classifies a report; the deterministic backend
owns everything that acts.  Jev produces a **triage suggestion only** — a human
reviews and decides.

Two catalog definitions already registered in `decision_catalog.json` are used
(no new definition is invented):

* **`feedback.category.v1`** (Choice) — `ANSWER_WRONG`, `CITATION_WRONG`,
  `QUESTION_INCOMPLETE`, `IMAGE_RECOGNITION`, `GRADING_DISPUTE`,
  `COURSE_CLASSIFICATION`, `SERVICE_FAULT`, `OTHER`.
* **`feedback.severity.v1`** (Score, ordered `0/1/2`) — cosmetic → a real defect
  with a workaround → blocks learning or grading.

There is no live Jev call anywhere; only the offline `FakeTransport` has run.

---

## Behaviour

### 1. Only a user-initiated report is ever recorded

There is **no passive scanning**. Nothing reads other messages, other users'
data, or a whole conversation to "find" problems. `FeedbackTriage.submit(...)`
is the only entry point; if it is never called, the module does nothing and
spends **zero** Jev calls.  (Pinned by
`test_no_report_means_zero_jev_calls`, `test_off_mode_makes_no_call`,
`test_no_service_falls_back_without_any_call`.)

### 2. Minimal default payload

By default only the identifiers are stored: `message_id`, `run_id`, `course_id`,
`model`, `template_version`, `app_version`, plus the reporter's own scope (the
server-derived `owner_scope_hash` + `course_id`).  The free-text description
(`report_text`) and the question/answer body (`question_text`, `answer_text`)
are stored **only** when `attach_body` is true, and a body without that flag is
refused (`FeedbackValidationError` code `BODY_NOT_OPTED_IN`; the HTTP route maps
it to a 400).  (Pinned by `test_default_payload_is_identifiers_only`,
`test_api_refuses_body_without_opt_in`, `test_opt_in_path_stores_body`.)

### 3. One batched Jev call

`feedback.category.v1` and `feedback.severity.v1` are two independent questions
asked on the **same** state in **one** `JevCall` (one transport call), scoped by
owner + course via `build_feedback_scope` (a server-derived `owner_scope_hash`
plus `course_id`), so one user's cached judgement can never be reused for
another and the receipt write can never fail on a NULL `owner_scope_hash`.
Definition/version, the validated result, confidence, `path` (`jev` vs
`fallback:<reason>`), receipt ids and latency are all recorded.  (Pinned by
`test_normal_report_classified_and_queued_with_one_jev_call`.)

### 4. Review queue, not automation

The module produces a triage suggestion — `(category, severity, suggested
queue)` — and stores the report for human review.  Jev may **never** close a
ticket, delete feedback, change a mark, or ban/limit a user; those calls do not
exist on the module, and no grade/user/permission/coverage row is ever touched.
The only persistent write is the Jev receipt ledger (`jev_decision_receipts`).
(Pinned by `test_no_grade_user_permission_coverage_rows_changed`,
`test_no_automatic_action_callable_exists`.)

### 5. Privacy guarantees

* **No mood/personality/ability inference** — the catalog instructions forbid it
  and the module never asks for or records such a signal.
* **No cross-user reads** — the only inputs are the reporter's own identifiers
  and opt-in content; there is no conversation scan.
* **Duplicates are related by the real object id + version + authorization
  scope, not by scanning private text** — `report_key(...)` hashes
  `course_id`/`message_id`/`run_id`/`model`/`template_version`/`app_version` plus
  the `owner_scope_hash`, and deliberately omits the body.  (Pinned by
  `test_report_key_ignores_body_and_tracks_scope`,
  `test_duplicate_reports_share_key_across_text`.)
* **An admin viewing the queue sees only reports that were actually submitted,
  with their scope respected** — every queued record carries its
  `owner_scope_hash`/`course_id`, and nothing is synthesized or read across
  users.  (Pinned by `test_two_owners_produce_distinct_receipt_scopes`.)

### 6. Degradation

Jev unavailable/invalid → `category=OTHER`, the middle severity (`1`), and
`path=fallback:<reason>` (`no_service`, `off`, `unavailable`, `not_configured`,
`timeout`, `invalid_response`).  The report is still accepted and queued for a
human; a Jev failure never loses the user's report.  (Pinned by
`test_unavailable_transport_still_accepts_and_queues`.)

---

## Module API

```python
from app.jev.feedback_triage import (
    FeedbackReport, FeedbackTriage, FeedbackValidationError,
    build_feedback_scope, report_key, suggested_queue, submit_feedback,
)

report = FeedbackReport(
    course_id="cs3481",
    message_id="msg-1",
    run_id="run-1",
    model="deepseek-v4",
    template_version="tpl-1",
    app_version="app-1",
    # optional structured self-selection (not free text, not the body):
    category_hint="ANSWER_WRONG",
    # opt-in gated free text / body:
    report_text="the answer is wrong",
    question_text="what is 2+2",
    answer_text="4",
    attach_body=True,
)

triage = FeedbackTriage(service)  # SemanticDecisionService | None
result = triage.submit(
    report,
    owner_user_id=user_id,        # server-derived, never client-supplied
    authorization_scope="feedback",
)
# result.category, result.severity, result.suggested_queue, result.path,
# result.used_jev, result.jev_calls, result.receipt_ids, result.report_key, ...
```

`FeedbackTriage.reports` is the in-memory human review queue (in submission
order) and `summary()` exposes `submitted`, per-category/path counts and the
queued reports.  `suggested_queue(category, severity)` is a deterministic routing
hint (`priority`/`service`/`grading`/`content`/`triage`) — never an action.

The owner/course scope is built with `build_feedback_scope`, the same
genuinely-scoped `CacheScope` pattern the P1 modules (`capability_router`,
`tool_intent`) use; it never falls back to an all-NULL scope.

---

## Backend route

`services/rag-api/app/api/feedback.py` adds one route:

* `POST /api/feedback` (201) — auth via `require_user`; validates the opt-in
  rule (refuses `report_text`/`question`/`answer` without `attach_body`) and the
  category enum; builds the report, runs `FeedbackTriage.submit` with the
  server-derived `user.user_id`, and returns the triage result.

It is registered from `app/main.py` with a one-line include
(`application.include_router(feedback_router)`).  The route builds a
`JevGateway` with the default `SdkTransport` (which fails typed with
`JevNotConfiguredError` while no TypeSafe credential exists) and a
`SqlReceiptStore` over the existing `jev_decision_receipts` table, so it degrades
to `OTHER` + middle severity and still queues the report today.

---

## UI entry (additive, small)

In `apps/web/src/ui/pages.jsx`, the learning workspace toolbar gains a secondary
**报告问题** button that opens a small `FeedbackForm` dialog:

* a category `<select>` (the eight categories, optional — the system otherwise
  classifies);
* an optional free-text description;
* an explicit **opt-in checkbox** for attaching the current conversation's
  question/answer body;
* a clear note that only the identifiers (plus the chosen category) are sent
  unless the box is ticked.

The submit path calls `submitFeedback` (added to `apps/web/src/ui/api.js`), which
posts to the backend `POST /api/feedback` endpoint.

No new global navigation and no redesign: the change is a single toolbar button
plus one dialog form.

---

## Verification

* `pytest tests/test_jev_feedback_triage.py -q` — the module's own suite (see the
  per-rule pin notes above).
* The existing Jev + no-Laya suite stays green.
* `ruff check` on every touched Python file; `python -m mypy` on the new module
  (the four pre-existing `gateway.py` errors remain, none added).

## Not done / explicitly out of scope

* No live Jev call; only `FakeTransport` has run.
* No new database table: the report's persistent audit trail is the existing
  `jev_decision_receipts` ledger (the two category/severity receipts carry the
  owner/course scope and the report input hash), and the human review queue is
  the in-memory `FeedbackTriage.reports`.  A persistent report queue is a
  follow-up owned by the workstream that owns migrations.
* Host wiring stays default-off: no definition is promoted from `shadow` to `on`
  until a TypeSafe credential exists and the layer is calibrated.
