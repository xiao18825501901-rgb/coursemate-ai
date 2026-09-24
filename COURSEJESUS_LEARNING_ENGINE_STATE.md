# COURSEJESUS LEARNING ENGINE STATE

**Round 98 (2026-09-24).** This is the current state of the learning-engine work: what was frozen,
what was fixed, what is measured, and what is deliberately not done yet. Read it with
`docs/learning-engine/CURRENT_ARCHITECTURE_FACTS.md` (the code map), `CAMPUS_FINAL_BATCH_CLOSURE.md`
(the frozen batch) and `MINIMAL_OWNER_ACTION_CARD.md` (what only the owner can decide).

Working tree: `D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY`, branch
`fix/codex-dsh-audit-20260919`, base `93d502c`, nothing deployed, no production system contacted.

## 1. What this round changed

| Item | State | Evidence |
|---|---|---|
| Final campus batch | **FROZEN**, 1,921 files, content hash `f0b452705cf8bf1f…`, 0 changed, 0 missing, 0 unlisted (2 personal files represented by path hashes) | `CAMPUS_FINAL_BATCH_MANIFEST.json`, `scripts/freeze_campus_final_batch.py` |
| Local campus expansion | **CLOSED** — discovery and ingestion refuse while `CMUI_CAMPUS_CATALOG_GROWTH` is unset (fail-closed); an unknown value is refused rather than ignored | `services/rag-api/app/campus_growth.py`; 7 tests in `tests/test_campus_growth_pause.py` |
| The closure proof | a synthetic file added to `D:\Canvas` was not discovered, not ingested and not published; both CLIs exited **3** and wrote nothing; the file was then removed and the directory returned to its 202 files | measured, recorded in `CAMPUS_FINAL_BATCH_CLOSURE.md` §2 |
| Campus publication | **NOT STARTED — and not startable here.** 1,715 files wait on one owner rights decision; all 28 campus courses are private and 0 files are published | `docs/coursejesus/CAMPUS_RIGHTS_REVIEW_LIST.csv`; manifest `publication` block |
| First-answer visibility | **FIXED in source, with tests.** `ask()` no longer discards a run whose pane moved; `Learn.reconcile` performs one bounded, model-free canonical read; a cut stream reconnects once and then reconciles instead of telling the learner to reload | `apps/web/src/ui/pages.jsx`; 6 tests in `apps/web/src/LearnAnswerVisibility.test.tsx`; strict journey in `tests/e2e/jev-structured.spec.ts` |
| Reload-dependent browser assertions | **made visible.** The helper still reloads as a last resort *for other journeys*, but every recovery is counted and printed; the first-round claim has its own journey that never reloads | same spec, `afterAll` report |
| Architecture mapping | **done, once** — 11 questions answered with anchors, no parallel-service assumptions | `docs/learning-engine/CURRENT_ARCHITECTURE_FACTS.md` |

## 2. Three defects this round found that were not on the list

1. **`restore()` switched the pane's conversation without bumping the revision**, so a reply to the
   old conversation could be rendered over the new one. Found by a unit test written for the
   visibility fix, fixed in the same change, and pinned by
   `does not write one conversation over a pane that moved without a Pair revision`.
2. **Every integrity failure in `create_course` was reported as `409 COURSE_EXISTS`** — including
   the NOT NULL failure of an ownerless private course. That is a false cause *and* an actionable
   one: `ui_extension/domain.py` retries `COURSE_EXISTS` three times with fresh random ids, so the
   real reason would have been retried away. Now: a missing owner is `422 COURSE_OWNER_REQUIRED`,
   only a UNIQUE violation is `COURSE_EXISTS`, anything else is `422 COURSE_CREATE_FAILED`.
3. **`exercise.prototype.v1` is called and its result discarded** (`app/cm_update/app.py:2221`), so
   the decision has no effect on the exercise. The comment now says so. This is the one Jev call
   site in the learning path that must **not** be described as wired-to-effect, and it is listed as
   P1 work rather than quietly left looking finished.

## 3. What the learning path really is today (measured)

* **做一题**: `POST /courses/{cid}/exercises` → `exercise_create` (`app/cm_update/app.py:2298`) →
  `generate_exercise_run` (`:2214`) → DeepSeek provider (`provider.py:362`); `exercise.v2` is
  validated and the private answer is hidden from the client projection. There is **no validation
  model call and no blind solve** on this path.
* **Five-question assessment**: `MARK_SCHEME = (10, 15, 20, 25, 30)` (`assessments.py:34`), questions
  frozen when the session starts (`:268-393`), grade snapshot written at `:1813-1841`. The pool
  admits `validation_status='VALIDATED'` with any `verification_method` except `MODEL_ONLY`
  (`:167-168`), so an `AI_REVIEWED` candidate is usable by design — and `AI_REVIEWED` is explicitly
  not human review.
* **Learning objectives** are free text (`teaching_items.objective`); nothing binds a node to an
  observable objective yet, and the only machine check is an acceptance-sentence heuristic in a
  reviewer that defaults to off.
* **Jev**: all 19 definitions are `shadow` in the committed configuration. In these paths the
  decisions that are consumed at all are criterion review, pedagogy, coverage, prerequisites,
  template match, corpus quality, extraction, intent and context; key facts and final scores are
  **not** decided by Jev (the answer text is persisted verbatim and the score path is Jev-free,
  with a Jev signal only able to force `needs_review`).

## 4. What is next, in the order the plan fixes

| Step | Work | Why it is this order |
|---|---|---|
| P1 | One real node end-to-end: objective → evidence pack → single-question blueprint → author call → **blind solve** → deterministic + semantic validation → READY → 做一题 shows it | The blueprint and the blind solve do not exist yet, and everything else (five slots, variants, feedback) is assembled from them |
| P2 | Five complementary slots through the existing `AssessmentService`; assistance state; feedback and a substantive variant ("再练同类"); independent explanation windows | Reuses the frozen-session machinery that already exists |
| P3 | MCQ distractors with recorded misconceptions; rule-violation questions from real course rules; per-module Jev quality gates | Needs the validated-item pipeline from P1 |
| P4 | Migration/rollback rehearsal, same-SHA regression, real image/text journeys, immutable release | Needs P1–P3 stable |

The campus pause (§1) is independent of all of it and is already in force.

## 5. Owner-only items (unchanged, and not silently blocking anything local)

| Item | Why it is the owner's | State |
|---|---|---|
| Material publication rights for the campus batch | A licence judgement about redistributing course material to every registered user | **Waiting**; 1,715 rows on one list; nothing is published until it arrives |
| Human review of the ten DeepSeek canary answers | `manual_review_status: REQUIRED`; "completed" is not "good" | Waiting |
| Production release window, native approvals, one real sign-in | §15 of the task | Waiting; local work continues |
| Institution Canvas Developer Key | The school's, not ours | `CANVAS_OAUTH_LIVE = WAITING_INSTITUTION`; the local upload fallback is in place |
| The remaining live-run budget | TypeSafe/DeepSeek spend beyond the current authorization | The card states the ceiling; no live call was made this round |

## 6. Gate results for this revision

*(filled in below once the round's gates finish — see the dated block at the end of this file)*
