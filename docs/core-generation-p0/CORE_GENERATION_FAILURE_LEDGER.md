# CourseJesus core generation failure ledger

Task: `COURSE_GENERATION_CORE_RELIABILITY_20260928`
Priority: `P0`
Status: `DEPLOYED_WITH_OPEN_QUALITY_AND_IDENTITY_ACCEPTANCE_BLOCKERS`

This ledger separates source defects, provider outcomes, durable recovery, and the
semantic quality gate.  The same Chinese fallback message in the old UI was not
treated as evidence of a common cause.

## Production evidence and deployed repair

- Investigation baseline application: `b63401e479829eac9c6e25884e5fc5f155396145`, RAG Schema 63.
- Deployed application: `916b76ce0534e4ce50a589521b0b618850df6956`, RAG Schema 64.
- Netlify production deploy: `6abacab3d2f4fb9cbfb7d8e9`; `coursejesus.com/build-info.json`
  returned the exact application SHA and all 18 production artifacts.
- Post-deploy SQLite checks: `integrity_check=ok`, zero foreign-key violations,
  87 courses, 850 documents, 22,909 chunks, 11 Assessment configurations and
  7 Assessment sessions.
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
| CG-02 | Campus/private “做一题” with an unbound Pair | UI adapter selected no node, then dereferenced the absent projection before the owner-scoped domain could select an active-Spec node | No; production failures completed in milliseconds with no usage | Source fixed, integrated contract PASS and deployed; a newly authored production READY item remains blocked by OpenJev qualification |
| CG-03 | Private node teaching / first-node Thinking | DeepSeek Responses planner returned an explicit incomplete terminal at the old 2,500-token ceiling; prior code discarded partial plan/usage evidence | Yes, planning stage | Default planner ceiling 6,000; typed terminal; checkpoint and usage persisted privately; deployed, authenticated browser acceptance unavailable |
| CG-04 | Exercise stream disconnect | Browser stopped observing after SSE failure even if the same run completed on the server | No replacement request was needed | Same-run read-only reconciliation added; stale Pair/course guard tested |
| CG-05 | SQL Assessment local blueprint | Observable objective validation rejected ordinary course objectives such as “List …” and relied on substring matching | No | Whole-word/CJK action contract and SQL regression added |
| CG-06 | Assessment preparation lifecycle | Model work could not be safely observed/resumed as a durable configured job; UI required a manual retry and had no status projection | Potentially, depending on slot | Schema 64, leased worker, progress, recovery receipt, GET polling and auto-open implemented and deployed |
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

## Live acceptance boundary

The production application and matching web bundle are deployed, but automated
authenticated acceptance could not be established.  The protected Clerk Backend
API credential installed on the application host returned HTTP 403 both for a
bounded synthetic-user create and for a read-only user-list request.  No test
identity was created.  A real learner account was not impersonated and MFA was
not bypassed.  Consequently campus/private browser flows remain `NOT VERIFIED`
at the authenticated-live layer even though their production source, offline
contracts and deployment are verified.
