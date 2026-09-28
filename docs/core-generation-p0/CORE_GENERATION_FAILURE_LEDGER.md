# CourseJesus core generation failure ledger

Task: `COURSE_GENERATION_CORE_RELIABILITY_20260928`
Priority: `P0`
Status: `IN_PROGRESS`

This ledger separates source defects, provider outcomes, durable recovery, and the
semantic quality gate.  The same Chinese fallback message in the old UI was not
treated as evidence of a common cause.

## Production evidence at investigation time

- Application source symlink: `/srv/coursemate/releases/b63401e`.
- RAG schema: 63; UI database and RAG database passed read-only inventory access.
- UI runs since the current production round included both immediate
  `QUESTION_ENGINE_FAILED` rows with no usage and longer
  `INCOMPLETE_PROVIDER_RESPONSE` rows that reached `planning`.
- Configured Assessments: 4 READY and 7 BLOCKED.
- Question pool: 49 VALIDATED / AI_REVIEWED revisions and 5 NEEDS_REVIEW /
  MODEL_ONLY revisions.
- The private SQL course's two blocked configurations each have five frozen
  slots and zero bound families.  They are genuine cold starts, not complete
  pools hidden behind a stale BLOCKED job.

## Failure classification

| ID | User path | Earliest proven failure | Model request | Repair/status |
|---|---|---|---|---|
| CG-01 | Campus knowledge teaching | No failure reproduced; retained as healthy control | Existing successful runs | Protected by integration regression |
| CG-02 | Campus/private “做一题” with an unbound Pair | UI adapter selected no node, then dereferenced the absent projection before the owner-scoped domain could select an active-Spec node | No; production failures completed in milliseconds with no usage | Source fixed; offline integrated contract PASS; live pending |
| CG-03 | Private node teaching / first-node Thinking | DeepSeek Responses planner returned an explicit incomplete terminal at the old 2,500-token ceiling; prior code discarded partial plan/usage evidence | Yes, planning stage | Default planner ceiling 6,000; typed terminal; checkpoint and usage persisted privately; live pending |
| CG-04 | Exercise stream disconnect | Browser stopped observing after SSE failure even if the same run completed on the server | No replacement request was needed | Same-run read-only reconciliation added; stale Pair/course guard tested |
| CG-05 | SQL Assessment local blueprint | Observable objective validation rejected ordinary course objectives such as “List …” and relied on substring matching | No | Whole-word/CJK action contract and SQL regression added |
| CG-06 | Assessment preparation lifecycle | Model work could not be safely observed/resumed as a durable configured job; UI required a manual retry and had no status projection | Potentially, depending on slot | Schema 64, leased worker, progress, recovery receipt, GET polling and auto-open implemented |
| CG-07 | New Question Engine publication | Self-hosted OpenJev candidate is installed but achieved 0.50 held-out accuracy in every tested hard-gate subgroup | Local semantic inference only | **BLOCKED BY QUALITY QUALIFICATION**; modes remain off and no unreviewed question is promoted |
| CG-08 | Generic error projection | Stable local/provider/review codes were collapsed into one generic sentence | N/A | Safe typed Chinese messages added without reflecting arbitrary exceptions |

## Regression evidence

- The first full run retained two failures because legacy tests still required
  TypeSafe calls in soft routing and reference-label parsing. Those expectations
  contradicted the approved TypeSafe retirement: both paths now use deterministic
  logic and record zero provider calls. The updated contract passed 5/5 targeted
  tests and the subsequent complete RAG suite passed 2006 tests with 3 explicit
  platform/retired-SDK skips.
- Web: 32 files / 146 tests; Agent: 13 files / 100 tests; OpenJev service:
  8 tests and 0 production dependency vulnerabilities.

## Important non-findings

- Private-course authorization was not the cause of the observed teaching run
  failures.  An integrated private course with no node or seed pack now completes
  both normal and Thinking paths under the production business code and fake HTTP
  provider contract.
- A stream disconnect is not a model failure.  The browser now reads only the
  original run and never POSTs a replacement from a timer.
- OpenJev HTTP 200/readiness is not semantic qualification.  The production
  Question Engine remains fail-closed while qualification is UNSET.
- The 13 remaining Map50 over-limit trees stay paused and are not reported as
  compressed.
