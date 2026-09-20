# Exercise and Problem-step production hotfix

Status: **PRODUCTION DEPLOYED AND ACCEPTED**

Application release SHA: `46415bde81df28f4dc18629219bc9ddc50e4c215`

Branch: `fix/codex-dsh-audit-20260919`

## Defects

### A. 做一题 mixed public and private answer text

The previous contract asked the model for a question followed by a delimiter and a private answer.
The server attempted to split a streamed text response. That design made correctness depend on a
delimiter being emitted exactly once and recognized across arbitrary stream boundaries.

The repair replaces new generation with the strict `exercise.v2` structured contract. The provider
stream is buffered at the trusted boundary, the whole JSON object is validated, and only the final
question is projected into run polling, SSE and history until the user explicitly reveals the saved
answer. Invalid or incomplete output fails closed and is never silently retried.

### B. Ordinary Problem steps disappeared

The server correctly parsed normal Problem answers into steps, but the React projection cleared
`steps` whenever a message carried any exercise state. Ordinary supplied problems also receive an
exercise record so they can reuse explanation/history machinery; treating every such record as a
hidden generated exercise removed the visible solution and its LearningBridge buttons.

The repair distinguishes the server-derived source:

- generated + unrevealed: hide answer steps;
- generated + revealed: show the persisted saved answer steps;
- user_problem: show the ordinary parsed solution steps immediately.

The two behaviors share persistence and explanation machinery without sharing their visibility
policy.

## Files changed

- `services/rag-api/app/cm_update/exercise_contract.py`
- `services/rag-api/app/cm_update/prompts/EXERCISE_RUNTIME_CONTRACT_V2.txt`
- `services/rag-api/app/cm_update/templates.py`
- `services/rag-api/app/cm_update/provider.py`
- `services/rag-api/app/cm_update/app.py`
- `apps/web/src/ui/pages.jsx`
- focused backend/provider/privacy/share tests
- `tests/e2e/codex-audit.spec.ts`

No database schema changed. Existing course IDs, Pair IDs, messages, exercises, reveal receipts,
LearningBridge records, official trees, publication releases and user data remain in place.

## Security invariants retained

- Plans and generated teaching prompts remain server-only.
- Generated answers do not appear in partial runs, SSE, Pair history or exercise GET before reveal.
- Explanation is forbidden before reveal.
- Reveal is owner-scoped, idempotent and non-model.
- Course gates, Clerk identity, campus verification and cross-user isolation are unchanged.
- Model references are intersected with the server-authorized source set.
- Shared frozen exercise history keeps the frozen saved answer/version instead of reading a newer
  sender file.
- There is no global auto-verification, test provider, fixed model success or relaxed assertion in
  production code.

## Production disposition

The fix was deployed to `/srv/coursemate/releases/46415bd` and is the active backend. Netlify
production deploy `6aaf951c45a27f7ea503df44` serves the same SHA. The release did not republish
course content or change a schema. Post-cutover read-only verification confirms that the CS3481 and
GE2324 tree, snapshot and ACTIVE release identities are unchanged.

Live `qwen3.8-max` acceptance passed generated-exercise hidden/reveal/detail flows for CS3481 and
GE2324, an ordinary four-step CS3481 Problem, saved detail rendering, a real LearningBridge teaching
run and return to the original step. See `EXERCISE_AND_STEPS_TEST_REPORT.md` and
`PRODUCTION_HOTFIX_EXECUTION.md` for the exact evidence and cost ledger.
