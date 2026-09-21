# LEARNING_STATE_AND_EVIDENCE

Scope: how the knowledge-node learning state is decided after this round, why the previous
projection was wrong, and what evidence can (and cannot) move a node forward.

## 1. The bug that was reproduced

`KnowledgeService._atomic_learning` decided the node state purely from the coverage count:

```
required == 0 -> SPEC_UNAVAILABLE
covered  == 0 -> NOT_STARTED      <-- even when the learner had really started
covered  <  required -> LEARNING
otherwise -> LEARNED
```

The pack's isolated probe (`ISOLATED_SOURCE_PROBES.json`, `learning_projection`) seeded a real
`learning_journeys` row with `status = LEARNING`, two REQUIRED items and zero coverage; the
method still returned `NOT_STARTED`. The shell already created real journeys through
`ui_extension/domain.py::_begin_learning` and linked runs via `cmui_run_v3`, so the state the
student saw contradicted the fact the server had already accepted.

## 2. The authoritative semantics now

```
no accepted start, no coverage                 -> NOT_STARTED (未学习)
accepted start, coverage not complete          -> LEARNING    (学习中)
all current REQUIRED items have accepted evidence -> LEARNED   (已完成)
no spec / zero REQUIRED items                  -> SPEC_UNAVAILABLE
```

Rules that follow from the governing plan and are enforced here:

* An accepted start is a **server-confirmed teaching request** for that
  owner/workspace/node/spec — not a created workspace, not a hovered node, not a restored
  history view, and not a model claim.
* Start and coverage are independent: a started node with zero coverage is `LEARNING`, and
  coverage is still the only thing that can produce `LEARNED`.
* A failed or cancelled run is still an accepted start (the failure is reported on the run),
  and it must never book coverage.
* Assessment results are a separate dimension and never change the learning state.

## 3. Implementation

* **Migration 026** `learning_start_events`:
  `id, workspace_id, node_id, spec_version, operation_id, source, accepted_at`, with
  `UNIQUE(workspace_id, node_id, spec_version, operation_id)` so replays of the same accepted
  operation (or a retried UI request id) insert nothing. `source ∈ {UI_RUN, V3_TEACH,
  DELIVERY, BACKFILL}`.
* **Writer (shell path)**: `V3DomainAdapter._begin_learning` records the fact inside the same
  transaction that creates/continues the journey, using the run's `operation_id` (the UI
  request id passed by `cm_update/app.py`) with a deterministic per-node fallback.
* **Projection**: `_learning_start_fact(connection, workspace, node, spec)` reads the fact and
  returns `(accepted_at, source)`:
  * primary: a `learning_start_events` row for the same spec version;
  * legacy fallback (pre-026 data): a `learning_journeys` row **that carries a real accepted
    artifact** — a delivered teaching unit, coverage, delivery evidence, or `LEARNED`
    status. A bare journey shell is deliberately NOT a start, because failed/cancelled/
    rejected submissions can leave one behind (this distinction was found by the test suite
    during this round, not assumed).
  * `_atomic_learning` returns `started`, `started_at`, `start_source` in addition to the
    counts, and promotes `NOT_STARTED → LEARNING` when a start fact exists.
* **Backfill**: migration 026 inserts a `BACKFILL` start event for every legacy journey that
  has a real artifact, with `accepted_at = MIN(teaching_units.created_at)` (or the earliest
  delivery evidence), so historical learners are not shown as "never started". The insert is
  idempotent (`INSERT OR IGNORE` + deterministic id).
* **DTO**: `_knowledge_tree` already forwards the whole `learning` object, so the shell receives
  `progress`, `started`, `started_at`, `covered_required` and `required_total` without a
  separate endpoint.

## 4. Evidence rules that did not change

Coverage keeps its existing severity: only `VALIDATED`, `LEGACY_PRESERVED` (legacy) and
`REVIEWED` (shell delivery with an independent reviewer) evidence counts for a REQUIRED item.
Keyword echoing, a model claiming "已讲完", a cancelled/truncated run, the wrong course, or a
stale spec version all fail to book coverage — the regressions
`test_keyword_only_content_does_not_cover`, `test_failed_and_truncated_runs_never_cover`,
`test_cancel_never_books_coverage`, `test_wrong_user_course_and_stale_spec_never_cover` still
assert exactly that (their progress expectation is now `LEARNING` with
`covered_required == 0`, which is the corrected contract, not a weakened one).

## 5. COMPOSITE nodes

COMPOSITE aggregation is unchanged in kind: it summarizes the atomic descendants' states and
never invents a grade. With atomic descendants now reporting `LEARNING` after a real start, a
parent shows 学习中 as soon as any descendant was really started, and still requires full
REQUIRED evidence for 已完成.

## 6. Verification in this round

| Check | Command | Result |
|---|---|---|
| started + zero coverage = LEARNING | `pytest tests/test_jev_deepseek_gap_regressions.py -q` | pass (was failing before the fix) |
| never-started stays NOT_STARTED | same file | pass |
| coverage still gates LEARNED | `pytest tests/test_ui_extension_coverage_submission.py -q` | pass |
| journey + cross-reference unchanged | `pytest tests/test_ui_extension_learning_closure.py -q` | pass |
| migration initializes and replays | `work/current-change/mig_probe.py` | first + second init ok, `integrity=ok`, `fk_violations=0`, no `*_old` leftovers |

## 7. Not run

* Production backfill: the migration is verified on isolated copies only; running it against the
  live database belongs to the deployment round (no production authorization in this session).
* Any claim that a *model* can mark a node LEARNED remains false by construction.
