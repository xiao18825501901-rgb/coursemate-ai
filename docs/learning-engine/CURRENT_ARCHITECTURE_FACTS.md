# CURRENT ARCHITECTURE FACTS

One bounded map of what exists in the working tree, taken **2026-09-24 (round 98)** on branch
`fix/codex-dsh-audit-20260919`, so the Question Engine upgrade extends these surfaces instead of
building parallel ones. Every row names the symbol and the file:line the claim was read from.

**Read this as measured facts, not design.** Where something does not exist it says so, because the
expensive mistake here is to assume a name implies an implementation — the plan's own example
(`lecture5.pdf#page=18`) is a filename in a suggestion, not evidence that the code resolves it.

| # | Question | Verdict | Anchor |
|---|---|---|---|
| 1a | 做一题 entry point and write path | **EXISTS** | `POST /courses/{cid}/exercises` → `exercise_create` `app/cm_update/app.py:2298`; worker `generate_exercise_run` `app.py:2214`; provider `app/cm_update/provider.py:362`; client `apps/web/src/ui/api.js:84` |
| 1b | Five-question assessment entry points | **EXISTS (two stacks)** | V3 `app/api/learning.py:487` start / `:515` submit / `:501` view; CM-UI `app/cm_update/app.py:1194` → `app/ui_extension/domain.py:1641` → `app/learning/orchestrator.py:211` |
| 2 | `exercise.v2` contract and its student-visible projection | **EXISTS** | schema + validator `app/cm_update/exercise_contract.py` (`answer_steps` / `question` / `references`); the private answer is hidden in the projection at `app/cm_update/app.py` (reveal gates it) and the provider never streams it (`provider.py:362-376`) |
| 3 | Teaching content templates | **PARTIAL** | registry `app/cm_update/templates.py:94` with V1/V2 and pinned hashes; 14 content templates + `OTHER` + `EXERCISE_PROMPT_V2`. The exercise / problem / explanation prompts **do not select a template** (`provider.py:114`, `:144`, `:153`); `template.match.v1` feeds the thinking-mode planner instead (`app.py:1715`) |
| 4 | Five-question blueprint, marks, freeze, grade snapshot | **EXISTS** | `MARK_SCHEME = (10, 15, 20, 25, 30)` `app/learning/assessments.py:34`; the session freezes its questions at `assessments.py:268-393`; marks/slot triggers `migrations/017_assessment_runtime.sql:199`, `:244-257`; grade snapshot insert `assessments.py:1813-1841`; raw score `:569`; table `migrations/018:109` |
| 5 | Reference solutions and verification levels | **PARTIAL** | reference generation `orchestrator.py:526-577`, storage `assessments.py:1120-1146`, table `migrations/027:370`; the level is a **pair**, not one field: `validation_status ∈ {CANDIDATE, VALIDATED, NEEDS_REVIEW, REJECTED}` and `verification_method ∈ {OFFICIAL, OWNER_AUTHORED, DETERMINISTIC, HUMAN_REVIEWED, AI_REVIEWED, MODEL_ONLY}` (`027:56-62`). Pool filter `assessments.py:167-168` (`validation_status='VALIDATED' AND verification_method!='MODEL_ONLY'`), insufficiency `ASSESSMENT_POOL_INSUFFICIENT` `:232-237`. There is **no** `verification_level` symbol anywhere |
| 6 | Learning objectives | **PARTIAL** | `teaching_items.objective` / `.acceptance` (`migrations/014:90`, `app/learning/models.py:14-19`) are free text; the only machine check is an acceptance-sentence heuristic in `app/learning/coverage_review.py:87-120` (reviewer defaults **off**). Rubric criterion → `item_id` binding `assessments.py:1054-1070`; next exercise choice is deterministic `pick_exercise_node` `app/cm_update/app.py:2199-2212` |
| 7 | Blind solve / independent solver | **MISSING** | zero matches for `blind_solve` / `blind_solution` / `independent_solver` / `second_solver` across `services/rag-api/app`. The nearest second model calls are the Jev criterion review (`assessments.py:1522`) and the layer-3 citation audit (`assessments.py:1223`); the exercise path has **no validation model call at all** |
| 8 | Schema | **EXISTS** | `LATEST_V3_SCHEMA_VERSION = 35` `app/db.py:36`; `LATEST_V2_SCHEMA_VERSION = 10` `:35`; CM-UI `SCHEMA_VERSION = 13` `app/cm_update/db.py:23`. Question/assessment DDL: migrations 016, 017, 018, 027 (+014 teaching items, 022 delivery evidence): `assessment_question_revisions` (`017:4`), rubric criteria (`017:89`), grade snapshots (`018:109`), preparation/reference/receipts (`027:350-427`), CM-UI `cmui_exercises` (`app/cm_update/db.py:237`) |
| 9 | Tests that cover these surfaces | **EXISTS** | `test_assessment_runtime.py` (13), `test_assessment_preparation_contract.py` (11), `ui_extension/test_upgrade.py` (11), `test_codex_exercise_privacy.py` (7), `ui_extension/test_exercise_contract.py` (2), `test_jev_reference_verification.py` (18), `test_reference_evidence_verification.py` (6), `test_problem_runtime.py` (6), `test_teaching_plan_runtime.py` (6) — counts of `def test_`, measured by reading the files |
| 10 | Which Jev definitions the learning paths consume, and where the mode is read | **PARTIAL (see §2)** | `assessment.criterion_review.v1` `assessments.py:1522`; `pedagogy.next_method.v1` `orchestrator.py:1983`; `coverage.item_support.v1` `ui_extension/domain.py:1578`; `graph.prerequisite.v1` `learning/knowledge.py:143`; `template.match.v1` `app.py:1715`; `corpus.quality.v1` `app.py:758`; `extraction.field_grounded.v1` `jev/extraction.py`; `intent.next_action.v1` `app.py:1494`; `context.keep_segment.v1` `app.py:1506`. Mode: `JevGateway.mode_for` `app/jev/gateway.py:347`, `MODES = {off, shadow, on}` `:69`, default `shadow` (`decision_catalog.json:6`), overridden by `Settings.jev_definition_mode_map` `app/config.py:176-205` → `app/main.py:140-145`. **All 19 definitions are `shadow` in the committed configuration** |
| 11 | Answer visibility from server to screen | **PARTIAL — one path fixed this round (§3)** | `POST /conversations/{id}/runs` `app/cm_update/app.py:1410`; SSE `GET /runs/{rid}/events` `:1632-1660`; assistant row committed before the terminal event `:1374-1376`; client `apps/web/src/ui/pages.jsx` `ask` `:502`, `watch` `:552`, `reconcile` (new this round) |

## 1. Two stacks that do not meet (a design constraint, not a bug to fix blindly)

A 做一题 exercise (`cmui_exercises`) never becomes an assessment pool question
(`assessment_question_revisions`); the pool's `source_problem_revision_id` points at
`problem_revisions` (V3), not at `cmui_exercises`. The Question Engine must therefore decide, per
入口, which one it writes — the plan's "one engine, two entrances" is a mapping job across these two
tables, not a new table. Nothing in this round changed that.

## 2. Jev call sites that are wired but **inert** (found and labelled this round)

`exercise.prototype.v1` is **called and its result discarded**: `callsites.select_exercise_prototype(...)`
at `app/cm_update/app.py:2221` is a bare statement, and the generation below is unchanged, so the
decision has no effect on the exercise a learner receives. The comment there now says so
explicitly, and `JEV_EXERCISE_SELECTION` must not be reported as "wired to a business effect" until
the prototype/blueprint object it needs exists (P1). The receipt is still written, which is why the
call is kept rather than deleted.

Also checked and **not** a defect, recorded because it looks like one: `_verify_candidate`
(`assessments.py:962`) returns `AI_REVIEWED` for concept/open questions while the row is stored with
`validation_status='VALIDATED'` (`:1038`). Migration 027 makes `verification_method` the honest
field (`AI_REVIEWED` is explicitly not human review) and reserves `validation_status` for
"may this row be used"; the pool still excludes `MODEL_ONLY`. The docstring said "never VALIDATED",
which conflated the two columns, and that wording is what was corrected.

## 3. Answer visibility: what the code did, and what changed

The defect behind "the server finished, the browser never showed it until reload" was located
precisely, not guessed:

* `ask()` created the run and then, if the Pair revision moved while the request was in flight,
  **returned silently**: no watcher, no `run` id, no status — and `busy` stayed `true`, so the
  composer was dead too (`pages.jsx` before this round: the single `if (… revision !== …) return`).
* The guard tested only `pairRevision`, but `restore()` moves the pane's conversation **without**
  bumping it, so a reply could also be written over a pane that had already moved.
* `watch()`'s terminal branch reconciled only when the pane still showed the run's conversation;
  otherwise `recoverOrphanedAnswer` announced the answer **without fetching it**.
* A cut stream cleared `busy` and said "history is on the server", but never re-read the canonical
  record, and the browser suite's own helper reloaded the page once before asserting.

Now: `Learn.reconcile(lane, cid, rid, controller)` performs one bounded, model-free canonical read
(`GET /conversations/{id}` + `GET /runs/{rid}`) and merges idempotently, refusing when the pane
shows another conversation, when a newer run owns the lane, or when the controller was superseded;
the composer input, the attachments and the Pair binding are never touched. It is called from the
three paths that used to lose the answer, with **one** reconnect attempt per run on a cut stream.

## 4. Not verified here

Which definitions are promoted in any deployed configuration (no deployment config was read);
detailed consumers of `entity.relation.v1`, `teaching.capability.v1`, `tool.intent.v1` and
`feedback.*` (grep-level only); whether the two stacks in §1 have any live data path; the production
application SHA and schema. Each is named so a later round does not inherit it as an assumption.
