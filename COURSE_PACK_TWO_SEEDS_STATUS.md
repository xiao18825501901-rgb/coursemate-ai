# Two Real Seed Course Pack Status

Date: 2026-09-28

The package's synthetic CS3481/CS4335 fixtures were not imported. The adapter inspected the real
production authorities and created only reference-based pack metadata.

| Course | Status | Real authority preflight | Action |
|---|---|---|---|
| CS3481 | **ACTIVE** | 38 READY documents; 22 published nodes (15 atomic); 17 Teaching items; 9 question revisions, 8 READY. Eligible targets: `association-analysis-core`, `kmeans-clustering`. | Activated pack `learning-pack-bc42f73a482f9fec8e26f0da` with 1 revision and 2 targets. Existing source/node/question/rubric IDs are referenced. |
| CS4335 | **DRAFT / WAITING_SOURCE** | 8 READY documents; 192 candidate nodes; 355 Teaching items; 0 READY question revisions; course is private/unpublished. | Not activated. No synthetic questions, publication flag or permission was invented. |

## Integrity rules

- Pack revisions do not copy course bodies, answers, rubrics or Teaching Specs.
- Source/review/licence status comes from current CourseJesus authorities; absence stays unknown or
  blocks activation.
- A pack revision cannot make a private course public.
- Pack update creates a new revision and impact record; it does not mutate old assessment anchors.
- Current production scan found no synthetic reference IDs in the activated data.

## What remains for CS4335

CS4335 needs real READY Question Engine revisions and an explicit publication/permission state. It
must then rerun the same read-only preflight before a separately authorized apply. It is not counted
as an active production seed today.
