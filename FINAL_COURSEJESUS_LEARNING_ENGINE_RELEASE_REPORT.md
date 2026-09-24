# FINAL COURSEJESUS LEARNING ENGINE RELEASE REPORT

**Status: work in progress, honestly reported.** This is the release report for the learning-engine
upgrade (the seven-stage Question Engine on the existing `KnowledgeNode` / `TeachingSpec` /
`exercise.v2` / `AssessmentService` surfaces). It is **not** a production acceptance report: nothing
has been deployed, no production system has been contacted, and the parts that are not built are
listed as not built.

Round 98 (2026-09-24). Branch `fix/codex-dsh-audit-20260919`. Companion documents:
`COURSEJESUS_LEARNING_ENGINE_STATE.md`, `docs/learning-engine/CURRENT_ARCHITECTURE_FACTS.md`,
`CAMPUS_FINAL_BATCH_CLOSURE.md`.

## 1. The six things success is defined by, one by one

| Definition of success | State | Evidence |
|---|---|---|
| The final campus batch is closed by scope, later local expansion is paused with no residual trigger, and unpublished items are explicit | **MET** | 1,921 files frozen with per-file terminal states; discovery and ingestion refuse while the switch is unset; the synthetic-file probe exited 3 and wrote nothing; 1,715 files are explicitly withheld pending one owner decision; no watcher/cron/timer exists to remove (verified, not assumed) |
| A new single question and a five-question set both carry a real objective, blueprint, source and question version, inside the existing business services | **NOT MET** | The five-question path already has marks, freeze and grade snapshots; the **single-question blueprint does not exist** and 做一题 has no objective binding. Mapped, not built |
| The independent solve never sees the author's answer, and the verification evidence matches the level it claims | **NOT MET** | There is no blind-solve call in the codebase at all (zero matches for `blind_solve` / `independent_solver`). The existing verification levels are a `validation_status` + `verification_method` pair, which is honest and already distinguishes `AI_REVIEWED` from human review |
| A bad question cannot become READY on the strength of a model's own score, and no old question or grade is given a fabricated history | **PARTIALLY MET** | The assessment path already refuses `MODEL_ONLY` from the pool and stores the method; the exercise path has no validation gate yet, so nothing there can be READY *or* rejected — the state simply does not exist |
| A learner can go learning → practice → feedback → re-practice → five-question assessment, with state visible immediately and history recoverable | **PARTIALLY MET** | The learning → practice → assessment loop exists and is exercised in a real browser. The **feedback → substantive re-practice** half is not built. The "visible immediately" half was **defective and is now fixed** (§2) |
| The first streamed answer is visible without a reload | **FIXED, verification in progress** | Three loss paths repaired in `apps/web/src/ui/pages.jsx` with 6 unit tests; a strict browser journey that never reloads was added, and the suite now *reports* any journey that still needed one |

The remaining definitions — Jev adopted only where validated, and production artefacts/SHA/schema
having on-site evidence — are reported in §3 and §4 rather than claimed.

## 2. The reliability defect this round fixed (priority work)

The real defect class was located by reading the code, not by guessing: after `ask()` created a run,
a Pair revision that moved mid-request made the function **return silently** — no watcher, no run
id, no status, and `busy` left set, so the learner saw their question, no answer, and a dead
composer until a reload. Two more paths lost the answer the same way (a terminal reconcile that only
ran when the pane still showed the conversation, and a cut stream that cleared `busy` without
re-reading anything), and the browser suite's own helper treated a reload as a pass.

Now one bounded, model-free reconciliation (`Learn.reconcile`) reads the canonical conversation and
the run record and merges idempotently, refusing when the pane shows another conversation, when a
newer run owns the lane, or when the controller was superseded; a cut stream gets exactly **one**
reconnect attempt per run. Nothing here calls a model, and the composer's draft, attachments and
Pair binding are never touched.

**Proof offered, separated as the task requires:** (1) first-answer visibility has its own browser
journey that performs no reload; (2) recovery after a cut stream is covered by a unit test that
counts the reconnect attempts; (3) history persistence is covered by the existing reload-based
journeys in other suites. These are not merged into one "reload works" claim.

## 3. Jev's role, stated against the measured result rather than the intention

The small-sample live result is unfavourable on two metrics and nothing has been promoted; all 19
definitions remain `shadow`. In the learning paths, the answer text is persisted verbatim and the
score path is Jev-free (a Jev signal can at most force `needs_review`). One call site —
`exercise.prototype.v1` — is called and its result discarded; it is now labelled as such in the code
so it cannot be counted as an integrated capability. The task's rule ("Jev must not control key-fact
trimming or the formal score") is therefore satisfied **today**, and the work that would let Jev earn
more of a role is the per-module quality gate in P3.

## 4. Production

Nothing was deployed, and no production claim is made anywhere in this report. The production
sequence (consistent backup → isolated restore → migration rehearsal → rollback check → immutable
release → protected env → frontend → Netlify → real journeys → post-release backup → monitoring)
remains blocked on the owner's release window, one real sign-in and native approvals. The local
numbers in this report are local.

## 5. What a reader should not infer from this report

* That the campus library is live: **0 of 1,921 files are published**, and 1,715 await one rights
  decision.
* That questions are verified: there is **no blind solve and no validation gate on the exercise
  path** yet.
* That the learning loop is complete: the feedback → substantive re-practice half is not built.
* That a passing local gate is a production result: it is not, by construction.
