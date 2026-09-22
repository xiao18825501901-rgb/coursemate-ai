# LEARNING_AND_ASSESSMENT_STATE_SPEC

The two independent state machines a knowledge node carries, what may move each one, and what is
forbidden. Written from the implemented code and its tests after this round's fixes.

Companion: `docs/jev-deepseek/LEARNING_STATE_AND_EVIDENCE.md` (learning-start fact details).

---

## Part 1 — Learning progress (教学进度)

### 1.1 States and authority

| State | Meaning | Set by |
|---|---|---|
| `NOT_STARTED` (未学习) | no accepted learning start and no coverage | projection only |
| `LEARNING` (学习中) | an accepted start exists, REQUIRED coverage not complete | accepted teaching request and/or partial evidence |
| `LEARNED` (已完成) | every current EFFECTIVE `REQUIRED` teaching item has accepted evidence | accepted delivery evidence only |
| `SPEC_UNAVAILABLE` | no effective spec / zero REQUIRED items (a started node can still show "已进入") | projection only |

Authority: the deterministic backend. No model (DeepSeek or Jev) can write `LEARNED`, and a
model claiming "已讲完" is not evidence.

### 1.2 What counts as a start (this round's fix)

* An **accepted teaching request** for that owner/workspace/node/spec — recorded in
  `learning_start_events` (migration 026), idempotent per
  `(workspace, node, spec_version, operation_id)`, written by
  `V3DomainAdapter._begin_learning` from the accepted run (source `UI_RUN`; legacy rows may carry
  `BACKFILL`).
* A legacy journey counts only if it carries a **real accepted artifact** (delivered teaching unit,
  coverage, delivery evidence, or `LEARNED`). A bare journey shell left by a failed/cancelled/
  rejected submission is deliberately NOT a start.
* Creating a workspace, hovering a node, restoring history, opening an assessment, or starting a
  new assessment do NOT count.

### 1.3 What counts as coverage

Only `teaching_delivery_evidence` rows with `validation_status ∈ {VALIDATED, LEGACY_PRESERVED,
REVIEWED}` for the current spec version. Excluded: keyword echoing, a cancelled/truncated run, the
wrong course, a stale spec version, a model self-claim, and evidence attached to another user's
journey. Assessment results never create coverage; low grades never remove it.

### 1.4 Independence rules

* Learning progress and assessment results are **orthogonal**: a graded 0 does not un-learn a
  node, and a perfect score does not make it `LEARNED`.
* Starting an assessment does not start learning.
* A failed/cancelled teaching run still counts as a start (the failure is reported on the run
  itself) and never books coverage.

---

## Part 2 — Assessment state (测评)

### 2.1 Session states (existing `AssessmentService`, reused — no parallel system)

| State | Meaning |
|---|---|
| `NOT_ASSESSED` | no session for this workspace+node |
| `IN_PROGRESS` | an open session exists (five frozen questions); the previous valid result stays visible |
| `SUBMITTED` | answers submitted, grading not finished → projected as `NEEDS_REVIEW` |
| `GRADED` | a `grade_snapshots` row exists for the session |
| `PARTIALLY_ASSESSED` | composite aggregation where only some atomic descendants are graded |

### 2.2 Frozen blueprint rules (unchanged)

* Five questions, five **distinct families**, marks from the existing scheme
  `(10, 15, 20, 25, 30)` summing to 100 — unequal marks, enforced by the
  `freeze_valid_assessment_blueprint` trigger.
* Frozen per session: spec version, questions, reference answers, rubric, source and template
  versions. The pool filter keeps `validation_status='VALIDATED'` and still excludes
  `verification_method='MODEL_ONLY'`.
* Both the question and its per-item verification method are frozen into
  `assessment_blueprint_items`, and the freeze trigger rejects a blueprint that is not
  five-unequal-marks-total-100.

### 2.3 Projection rules (this round's fix)

* "Latest result" = newest valid **graded** result by `graded_at` then snapshot `revision`.
  Independent-eligible results are reported **separately** instead of being promoted into the
  latest slot (the previous ordering preferred independence over recency and misreported the most
  recent attempt).
* A new in-progress session keeps the previous valid result visible (the DTO carries
  `active_session` **and** `latest_result`); starting a session must never blank the panel.
* `raw_score` without a school grade mapping is displayed as e.g. `78/100 · AI自测`; a missing
  letter grade is never rendered as 未测评 and no A/B/GPA mapping is invented.
* Composite nodes aggregate only independent-eligible atomic results and label the aggregation
  (`UNIQUE_INDEPENDENT_ATOMIC_MEAN_V1`); they never fabricate a grade for a group that has no
  testable spec.

### 2.4 Answer, grading and explanation separation

| Stage | Source of truth | Rule |
|---|---|---|
| Reference solution | 题目 prompt, compiled per blueprint item **before** seeing the student's answer | frozen with a revision id; not recomputed at submit time |
| Student answer | unified composer (text and/or uploaded images) mapped to the five stable blueprint ids | drafts are not submissions; unmapped/ambiguous items ask for confirmation instead of guessing |
| Grading | `AssessmentGradeProposal` v3.2 + criteria ids; deterministic types stay deterministic; concept answers use the semantic rubric path | the reference solver never receives student answers; the grader input hash is persisted; a probability/Score is never converted into marks |
| Sum | backend only | rubric weights stay 100 *inside* a question, converted into the question's marks; the paper total stays 100 |
| 详解 | 详解 prompt per reference step | authorized by assessment id + blueprint item + solution revision + step id; never reveals answers before submit; never re-asks the left teaching pane |
| Failure | — | an unfinished or needs-review attempt never overwrites the previous valid result; a tool failure never writes 0 |

### 2.5 Migration and rollback

* Schema additions in this round: RAG **026** (learning start events), **027** (assessment
  preparation + widened `verification_method` enum including the `AI_REVIEWED` diagnostic
  channel), **028** (Jev decision receipts). UI schema unchanged at **13**.
  **⚠ Two later migrations exist as of round 31: `029` (proposal-only `entity_relations`) and `030`
  (`feedback_reports`, the durable user-feedback queue), so `LATEST_V3_SCHEMA_VERSION = 30` and a
  production migration must apply **026–030**, not 026–028.** Current database facts live in
  `docs/jev-structured/MIGRATION_AND_ROLLBACK.md` and
  `FINAL_COURSEMATE_JEV_DEEPSEEK_PRODUCTION_REPORT.md` §3.
* The 027 table rebuild drops and recreates **all ten** triggers that reference the rebuilt tables
  (including triggers defined on other tables, e.g. `validate_assessment_rubric_context`,
  `freeze_valid_assessment_blueprint`, `validate_assessment_question_attempt`,
  `validate_performance_evidence_context`); verified by `work/current-change/mig_probe.py`:
  first init ok, replay ok, `integrity=ok`, `fk_violations=0`, no `*_old` leftovers.
* Rollback keeps data: the new tables are additive, older releases ignore them, and the previous
  release can be restored without deleting new grades, chats or learning evidence. Restoring data
  is a separate, explicit operation from the archived backups — never a silent side effect of a
  code rollback.
* **Rollback compatibility is verified, not assumed.** `scripts/verify_rollback_compat.py` exports
  the previous release (`git archive b05fd294`), builds a database with the current code, runs the
  previous release's own code against it, and compares the release's *own* schema (taken from a
  database it creates itself) with the migrated one. Result on the real release:
  `ROLLBACK_SAFE_WITH_MIGRATED_DB` — the old code opens the Schema-28 database, `integrity=ok`,
  `fk_violations=0`, **no missing column, no retyped column and no narrowed CHECK enum** among the
  four tables rebuilt by 027, and the assessment pool filter is byte-identical, so old and new code
  select the same pool. `tests/test_schema_rollback_compat.py` freezes the pre-027 column, table
  and enum snapshot permanently, so a future migration that drops a column or narrows an enum fails
  the suite instead of shipping a database the deployed release cannot use.
* Both guards were negative-controlled: temporarily deleting `HUMAN_REVIEWED` from the
  `verification_method` CHECK makes the test fail with `values no longer accepted
  ['HUMAN_REVIEWED']` and makes the verifier return `ROLLBACK_REQUIRES_DB_RESTORE` (exit 3). A
  verifier that cannot fail is not evidence.

### 2.5.1 Two axes, deliberately separate: `validation_status` and `verification_method`

A prepared question is stored with `validation_status='VALIDATED'` **and** an honest
`verification_method`: `DETERMINISTIC` for MCQ / NUMERIC / enumerated SHORT_TEXT, `AI_REVIEWED` for
concept or open questions with no provable external standard. The two columns answer different
questions:

* `validation_status` — may this question enter the pool at all (backend checks on source,
  integrity, reference solution, duplicate family and verification level);
* `verification_method` — *how* it was verified, and therefore which grading channel it uses
  (`DETERMINISTIC` → validated channel, `AI_REVIEWED` → diagnostic channel).

This is not "把 MODEL_ONLY 假装成 VALIDATED": the preparation path never writes `MODEL_ONLY` and
never relabels an existing `MODEL_ONLY` row. When a question has no provable external standard the
row says `AI_REVIEWED` and the grading path records the weaker channel. Pinned by
`tests/test_assessment_preparation_contract.py` (the `EXPLANATION` candidate must be
`AI_REVIEWED`, every other candidate `DETERMINISTIC`).

### 2.6 Not run

* Real DeepSeek question generation, image transcription and grading feedback: **NOT_RUN**
  (credentials/budget).
* Production migration rehearsal on the live databases: **NOT_RUN** (no production authorization);
  verified on isolated copies only.
