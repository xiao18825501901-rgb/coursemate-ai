# R3 Dynamic-K integration boundary

Status: implementation boundary frozen; no production change in this document.

## Current stable behavior

The restored stable runtime implements only `legacy.configurable.v1`:

- setup advertises 5–30 questions;
- `AssessmentStartInput` rejects a non-empty selection shorter than five;
- configuration and blueprint freezing require 5–30 items;
- the assessment start path prepares a pool when fewer than five distinct families exist.

Those checks are correct for existing legacy assessments and must remain unchanged for
legacy configurations and historical readers.

## Existing production authority that must be preserved

The current production database already contains the accepted forward-only schema for:

- `assessment_point_configuration_plans` (migration 078);
- `assessment_point_question_provenance` and
  `assessment_point_question_targets` (migration 079).

The stable source tree ends at migration 069, but the R1 startup rehearsal proved that it
can read the newer database without attempting a reverse migration. R3 must restore code
parity with the accepted 078/079 contracts. It must not allocate new migrations with those
numbers, replace the tables, or rewrite their immutable rows.

## Minimum server-authoritative path

R3 may admit fewer than five questions only when all of the following are true:

1. the configuration declares `cj.assessment.points.v1`;
2. a complete immutable point plan exists for the same owner, workspace, course, node,
   Teaching Spec version, content language, source snapshot, catalog hash, and content hash;
3. every independently assessable point occurs once or twice and every point is covered;
4. the frozen slots equal the private plan exactly and total 10,000 basis points;
5. every bound question is VALIDATED, answer-safe, rubric-complete, and tied to the same
   point plan and source lineage;
6. all N required questions are READY before the paper is frozen and opened.

The browser cannot supply K, verified point status, source identity, provenance receipts,
marks, or readiness. K is the number of independently assessable verified points, not the
number of Teaching Spec items, source fragments, knowledge-tree nodes, or currently READY
questions.

## Required learner-visible states

- No completed catalog for the current source identity: `ASSESSMENT_POINTS_NOT_READY`.
- A completed catalog with zero independently assessable points: a distinct confirmed-zero
  state; opening is refused without inventing points.
- A valid catalog with K greater than zero: default N=K and allowed K through 2K.
- Preparation in progress: expose bounded per-slot progress and the actual blocked/failed
  reason; never report READY early and never load indefinitely.

## Integration decisions

- Keep the existing Question Engine, `AssessmentService`, operation ledger, idempotency,
  scoring, history, Pair, and legacy assessment reader.
- Add a policy adapter at setup/configuration/start boundaries; do not lower the global
  legacy minimum from five.
- Use the existing 078/079 rows as the durable authority. Port only the smallest compatible
  service/model/store surface required to read and write those accepted contracts.
- Do not import the later parallel qualification framework wholesale. Catalog compilation,
  review, deterministic question authoring, and cross-configuration reuse are separate
  bounded slices and may not weaken the 078/079 invariants.
- Reuse a compatible READY question before any provider call. A missing slot alone may enter
  the existing generation pipeline; historical UNKNOWN operations remain read-only and do
  not globally block a new independently identified request.
- Preserve all historical 5-question, 8-question, and other legacy papers, answers, marks,
  scores, and history without recalculation.

## First test slice

Before behavior code changes, add failing tests proving:

1. a legacy 1–4-slot request remains rejected;
2. a point-policy plan with K=1 freezes one default item and permits an explicit second item;
3. K=2 permits N=2, 3, or 4 and rejects a third item for either point;
4. a client-supplied K or forged point identity is rejected;
5. missing catalog authority is reported as not ready, never as confirmed K=0;
6. point-first basis-point allocation totals exactly 10,000;
7. old assessments remain readable byte-for-byte after the policy adapter is enabled.

This slice does not qualify any real course catalog and does not authorize a production
release by itself.
