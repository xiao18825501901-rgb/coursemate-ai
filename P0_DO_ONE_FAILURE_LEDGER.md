# P0 Do-One Failure Ledger

Date: 2026-10-02

| Surface | Observed failure | Root cause | Fix | Regression evidence |
|---|---|---|---|---|
| READY question reuse | A compatible READY revision was ignored and Do-One always entered authoring. | The mounted operation called `generate_one` directly. | `reuse_ready_or_generate` now selects only owner/workspace/course/node/spec/objective/evidence-compatible READY revisions that have not been exposed to that user. | `test_question_runtime.py`; mounted HTTP regression in `test_ui_extension_question_engine.py`. |
| Duplicate click/reconnect | A new browser request id could create another paid run while an equivalent run was active. | Idempotency was request-id-only. | Active run reuse is keyed by owner, course, pair and canonical payload hash; a different payload conflicts. | Double-submit mounted regression; browser immediate-refresh journey records exactly one POST. |
| First-render exposure | A plain displayed question stayed “unseen” until hint/reveal/history. | Ordinary exercise reads did not write the canonical STEM exposure. | The persisted exercise display path writes one idempotent `STEM / PROBLEM_PANE` exposure; learning-loop assignments retain their existing assignment exposure. | Red/green mounted regression plus Chrome Do-One journey. |
| Refresh during generation | The UI could appear to lose the task and tempt a duplicate submit. | Recovery relied too heavily on the live stream. | The same durable run is polled and its saved conversation is restored; observers remain GET-only. | Immediate-refresh browser regression. |

No failure was fixed by weakening qualification, crossing private scope, treating AI review as human gold, or auto-passing when Jev is unavailable.

