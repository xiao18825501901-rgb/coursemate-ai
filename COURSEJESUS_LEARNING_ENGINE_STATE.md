# COURSEJESUS LEARNING ENGINE STATE

**Round 98 (2026-09-24).** This is the current state of the learning-engine work: what was frozen,
what was fixed, what is measured, and what is deliberately not done yet. Read it with
`docs/learning-engine/CURRENT_ARCHITECTURE_FACTS.md` (the code map), `CAMPUS_FINAL_BATCH_CLOSURE.md`
(the frozen batch) and `MINIMAL_OWNER_ACTION_CARD.md` (what only the owner can decide).

Working tree: `D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY`, branch
`fix/codex-dsh-audit-20260919`, base `93d502c`, nothing deployed, no production system contacted.

## Codex continuation update — 2026-09-25

Current application HEAD is `1d3d7a4f2a45e27001203ef4101606ea3ff1edec`. Question Engine
Stages 1–7 now exist locally. Stage 7 reuses the existing Assessment question, rubric and
reference-solution tables and adds only migration 036's immutable provenance table. A revision can
be READY only when its current owner/workspace evidence, author and blind input identities, and
both exact durable Jev receipt inputs still match. READY is recorded as `AI_REVIEWED`, not as a
deterministic, human or institutional correctness proof; model-reviewed MCQ/numeric answers do not
enter the deterministic grader. Revoked evidence removes a revision from future pools without
mutating frozen sessions or its audit record.

Exact-commit local evidence: 51 Question/Jev/provider/persistence tests passed; 33
migration/rollback/Assessment tests passed with one dependency warning; Ruff and diff checks
passed. Strict mypy still exposes four inherited errors in `course_access.py`/`workspaces.py` and
three inherited `assessments.py` `no-any-return` errors; no Stage 7 file diagnostic was added. No
live model, production, DNS, hosting or identity-system call was made. The next slice is the real
`做一题` integration and browser-visible single-node journey.

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
| P1 | One real node end-to-end: objective → evidence pack → single-question blueprint → author call → **blind solve** → deterministic + semantic validation → READY → 做一题 shows it | Stages 1–7 through scoped READY persistence have landed. The remaining P1 work is to route the existing 做一题 entry through the READY revision while preserving attempt, hint/reveal, independent detail, history recovery and re-practice behavior. |
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

## 7. Gate results for this revision

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
