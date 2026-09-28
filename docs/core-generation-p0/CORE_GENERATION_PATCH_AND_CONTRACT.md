# Core generation patch and contract

## Teaching

- Ordinary private-course teaching does not require publication, a node binding,
  an Assessment pool, or a seed pack.  Access to the course and READY source
  material remains mandatory.
- Thinking remains `plan -> work`.  The plan and native reasoning are internal.
- Planner checkpoints and usage are persisted before an explicit incomplete
  terminal is handled.  `generated_prompt` is excluded from run GET and SSE.
- A completed answer wins over later optional coverage bookkeeping failure; no
  bookkeeping failure grants `LEARNED`.

## Exercise generation

- An explicit node is authorized through the effective owner-scoped tree.
- An unbound Pair delegates selection to the integrated domain, which chooses the
  first accessible ATOMIC node with an active Teaching Spec.
- Node id/title returned by that canonical selection are stored on the exercise.
- Question authoring still follows blueprint -> author -> blind solve ->
  deterministic validation -> applicable semantic gates -> READY.
- Missing or unqualified semantic review remains a hard failure.  The legacy UI
  exercise generator is never used as a fallback.

## Browser run recovery

- Observers are bound to user session, course, Pair, pane and run id.
- SSE failure is followed only by bounded GETs for the same run id.
- Switching Pair/course or replacing the current run invalidates the old
  observer.  A stale completion cannot overwrite the new pane.
- A RUNNING snapshot cannot replace a later terminal result.
- No timer invokes a generation POST.

## Configured Assessment

- Configuration is frozen before authoring and contains 5–30 slots totalling
  100.00 marks.
- `0 READY` is a cold start: a durable PREPARING job is created.
- A lease-owning background worker fills only missing slots and records current
  ordinal/stage and prepared count.
- Complete compatible bindings recover a BLOCKED/PREPARING record to READY with
  a zero-model-call recovery receipt.
- Partial progress is retained.  UNKNOWN/RESERVED provider operations block
  automatic resends.
- Browser polling reads the preparation status and automatically opens the frozen
  session when READY.  Preparation time is separate from answer time.
- Formal submit/grade/reference/explanation contracts remain unchanged.

## Security and privacy

- Private courses are not made public as a repair.
- Public SSE uses an allowlist of stable error codes/messages.
- Provider exception text, internal plan text, private answer/rubric and service
  credentials are not projected.
- Existing Pair, history, exposure, grade and in-progress Assessment versions are
  not rewritten.

## Current hard blocker

OpenJev is operational but unqualified for the four Question Engine gates.  The
measured candidate must not publish new READY questions.  Full live closure of
new “做一题” and cold-start Assessment therefore requires a separately qualified
semantic reviewer or independently reviewed compatible questions; it cannot be
manufactured by changing an application flag.
