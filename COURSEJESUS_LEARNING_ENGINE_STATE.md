# COURSEJESUS LEARNING ENGINE STATE

**Round 98 (2026-09-24).** This is the current state of the learning-engine work: what was frozen,
what was fixed, what is measured, and what is deliberately not done yet. Read it with
`docs/learning-engine/CURRENT_ARCHITECTURE_FACTS.md` (the code map), `CAMPUS_FINAL_BATCH_CLOSURE.md`
(the frozen batch) and `MINIMAL_OWNER_ACTION_CARD.md` (what only the owner can decide).

Working tree: `D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY`, branch
`fix/codex-dsh-audit-20260919`, current local application HEAD `df8694b`, nothing deployed, no production
system contacted during this continuation.

## Codex continuation update — 2026-09-25

Current application HEAD is `df8694b0b4d97347f1c75baaca70c7e725e94a6e`. Question Engine
Stages 1–7, the real single-question practice journey, five complementary assessment slots and the
local P3 specialization now exist. P1 landed at `0fc77fc190ed3f5ac89111ba918469341204139b`: 做一题 preserves
attempt, hint, feedback, reveal and different-family re-practice state through the existing Pair and
exercise APIs. P2 landed at `1df8dbc29aa4f71c3954cb367d41ef320aecccbd`: five server-owned intents run through the same
evidence-bound author, blind-solve, hard-gate, exact-Jev-receipt and READY pipeline before the
existing Assessment service freezes those exact revisions in `10/15/20/25/30` order. P3 landed in
three slices: `bb68eca` binds every MCQ wrong option to a recorded misconception, `a2987c3` binds
rule-violation questions to exact course-rule quotations, and `f00f3e3` adds separate non-authoritative
module quality receipts without creating a combined score or granting Jev publication authority.

Migration 038 adds immutable preparation-slot bindings and widens the existing model-call ledger
roles so each of the five author and five blind-solver calls is separately reserved and recorded.
Resume reuses only exact current READY slots; missing or invalidated semantic receipts fail closed.
READY remains `AI_REVIEWED`, not deterministic, human or institutional correctness proof.

Exact-code local evidence for the latest P3 slice: 99 related backend assessment, Question Engine,
assessment-preparation and UI-extension tests passed with one dependency warning. A fresh targeted
real-Chrome empty-pool five-question journey passed 1/1 with no retry; its isolated database contains
the private MCQ mapping and third specialized receipt. Focused Ruff, byte compilation and diff checks
passed. P2 additionally retained its earlier 54 related backend assessment, Question Engine,
migration/rollback tests passed with one dependency warning; the isolated real-Chrome audit suite
passed 15/15, including an empty-pool five-question journey. Focused Ruff, byte compilation and
diff checks passed. Strict mypy retains the already-recorded imported legacy debt; no claim is made
that the old UI adapter is globally typed. No live model, production, DNS, hosting or identity-system
call was made.

P4 is now locally complete. The first wide run correctly stopped on 11 failures: two stale Jev
matrix assertions and nine restart failures caused by replaying migration 027 after migration 038
had widened the model-call ledgers. Commit `df8694b` preserves the historical migrations, skips
migration 027's superseded replay only after 38 is recorded, and pins repeated Question Engine roles through a
normal database restart. The fixed candidate passes 1818 backend tests (2 environmental skips),
115 Web tests, 92 Agent tests, four real-Chrome suites plus the V3 private-image journey, and a
verified synthetic backup/restore/schema-25-to-38 rehearsal. Exact evidence and limits are in
`docs/coursejesus/QUESTION_ENGINE_P4_RELEASE_EVIDENCE.md`.

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

* **做一题**: the existing create endpoint now resolves the active bound node and routes generated
  practice through the Question Engine. Public projections keep the answer private until reveal;
  attempt, hint, specific feedback and re-practice are persisted and browser-recoverable. Supplied
  user problems keep their existing independent explanation-window path.
* **Five-question assessment**: `MARK_SCHEME = (10, 15, 20, 25, 30)` remains authoritative. An
  empty eligible pool creates five complementary pre-generation slots, persists each exact READY
  revision, and immutably binds it to the preparation job. Session start freezes those exact five;
  grading and learning progress remain in their pre-existing systems.
* **Learning objectives** remain authored text, but Question Engine generation now resolves the
  exact current REQUIRED `teaching_items` row and binds its item id, node spec hash and immutable
  evidence versions into the blueprint and provenance.
* **Jev**: the current catalog has 23 definitions, including two base Choice-only question gates
  (`question.ambiguity.v1` and `question.answer_agreement.v1`) and separate MCQ-distractor and
  rule-violation quality signals. The committed default remains `shadow`; a READY specialized
  question requires exact durable `on`-mode receipts for both base gates and its own module gate.
  Jev still cannot decide permissions, publication, grades, `LEARNED` or a combined quality score.

## 4. What is next, in the order the plan fixes

| Step | Work | Why it is this order |
|---|---|---|
| P1 | ~~One real node end-to-end through 做一题, including attempt, hint/reveal, feedback, history recovery and different-family re-practice~~ | **Completed at `0fc77fc`**; included in the current 15/15 browser suite |
| P2 | ~~Five complementary slots through the existing `AssessmentService`~~ | **Completed at `1df8dbc`**; exact prepared revisions freeze in slot order and all ten provider stages use the existing reservation ledger |
| P3 | ~~MCQ distractors with recorded misconceptions; rule-violation questions from real course rules; per-module Jev quality gates~~ | **Local implementation completed at `f00f3e3`**; live-model and human quality evidence remain separate external acceptance work |
| P4 | ~~Migration/rollback rehearsal, same-SHA regression, real image/text journeys, immutable local candidate~~ | **Completed locally at `df8694b`**; live model, human quality and production gates remain external |

The campus pause (§1) is independent of all of it and is already in force.

## 5. Owner-only items (unchanged, and not silently blocking anything local)

| Item | Why it is the owner's | State |
|---|---|---|
| Material publication rights for the campus batch | A licence judgement about redistributing course material to every registered user | **Waiting**; 1,715 rows on one list; nothing is published until it arrives |
| Human review of the ten DeepSeek canary answers | `manual_review_status: REQUIRED`; "completed" is not "good" | Waiting |
| Production release window, native approvals, one real sign-in | §15 of the task | Waiting; local work continues |
| Institution Canvas Developer Key | The school's, not ours | `CANVAS_OAUTH_LIVE = WAITING_INSTITUTION`; the local upload fallback is in place |
| The remaining live-run budget | TypeSafe/DeepSeek spend beyond the current authorization | The card states the ceiling; no live call was made this round |

## 6. Execution mode (recorded 2026-09-25, round 98)

The owner asked for the **神临 / shenlin** execution mode. What is verifiably true, so a later round
does not have to re-derive it:

* **`shenlin` is installed** as an agent preset: `~/.dsh/.agent-presets/shenlin/` with `preset.yml`
  (`name: 神临`, `order: 6`), a 22 KB `agent.cordis.yml` composition and three skills. `pojia`
  (破甲) is installed beside it; the shipped presets are `code`, `cordis`, `minimal`, `standard`.
* **Its composition is `pojia` plus exactly one row: `shenlin-laya`** — a local System-1 (Laya)
  decision layer injected as `<shenlin-system1>` notices. Nothing else differs. For this project the
  Laya layer is `DISABLED_FOR_THIS_PROJECT`, and the preset's own instructions already say what to do
  in that case ("work exactly as 破甲模式 would: do not retry Laya, do not mention the outage, and do
  not narrow the task"), so **shenlin-with-Laya-disabled and pojia are the same execution contract**.
  Laya itself stays untouched: no service started, no model downloaded, no provider replaced.
* **Which preset is active is a client-side choice, not something this agent can set.** There is no
  preset/mode tool in the session's tool surface, and the launcher exposes only `--profile`,
  `--patch` and `--dump-config` (`lib/bin.js`) — no `--preset`. Switching is therefore done in the
  client that owns the session (the Web GUI's preset picker) and is **not** claimed as done here.
* What this session *does* adopt, because it is an execution posture rather than a switch: the
  high-autonomy, evidence-driven loop (observe → model → plan → execute → verify → critique → repair
  → re-verify → continue), with the project's own providers unchanged (DeepSeek generative, Jev
  semantic) and no new permission or safety boundary weakened.

## 7. Inherited round-98 gate results

**Revision `c039dd6`** (round-98 work committed; tree clean, nothing pushed). Every number below was
measured on this tree:

| Gate | Result |
|---|---|
| Backend full regression | **1729 passed / 2 skipped / 0 failed** in 1878.50 s (31:18), exit 0 — `work/current-change/full_run_round98.log`. The +7 over the round-95 baseline are the new campus-growth tests; the same two environmental skips (symlink privilege, POSIX permission bits) |
| Web unit tests | **113 passed** (24 files) via `npm run test --workspace @coursemate/web` — 107 before, +6 for the answer-visibility tests. **Do not run `vitest` from `apps/web` with the root binary**: that invocation reported 33 false failures on this same tree (kept here so the next round does not chase them) |
| Web type-check | `tsc -b` exit 0 |
| Browser `jev-structured` | **12 passed / 5 skipped / 0 failed** (2.6 m) — the +1 is `the first answer is visible without a reload, and the composer comes back`, which passed in 14.3 s. The suite's own report: **0 journeys needed a page reload** |
| Browser `ui-refresh` / `coursemate` | **23 passed** / **4 passed**, both exit 0 |
| Agent service | **92 passed** (12 files), `tsc --noEmit` exit 0 |
| Production build + PAT scan | exit 0 — `7 built files, no token field, notice present` |
| ruff | **0 findings added**: the new files pass clean, and the 13 findings my own edits introduced were fixed (import sorting, unused `noqa`, line length) rather than left; the legacy `cm_update/app.py` debt is unchanged and counted separately |
| Campus closure probe | scan CLI exit 3, ingest CLI exit 3, no inventory and no database written, source directory back to its 202 files |

Not claimed: nothing is deployed, no production system was contacted, no live model call was made
this round, and the 1,715 withheld campus files are still waiting on the owner's rights decision.
