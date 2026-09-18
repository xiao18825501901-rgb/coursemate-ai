# PLAN_WORK_AND_PRIVACY

## Two teaching modes (server-side field: `teaching_mode = normal | thinking`)

- Stored per run: `cmui_runs.teaching_mode` (schema 6 column, default `normal`).
  Retries/recovery replay the SAME mode; toggling only affects later requests.
- `normal` (default): one direct provider call. Teach lane uses a compact
  course-faithful instruction; problem lane uses the owner's 题目 Word prompt.
  No plan call, no professional template, no reuse of a previous plan.
- `thinking`: plan → work. Stage 1 (`planning`) composes the selected professional
  template (or OTHER) + course context via the internal plan-writer instruction and
  produces a full natural-language teaching prompt; that exact text is stored server-side
  and fed verbatim to the stage-2 work call (`generating`).
- Status labels: queued/planning → `正在思考中`; generating → `正在输出中`;
  idle → no running label; failures/cancels keep their own status.
  Coverage post-processing stays a separate event and never re-shows 输出中.
- Native model reasoning flags are NOT conflated with teaching_mode: `enable_thinking`
  remains False; the two-stage flow is the product feature.

## Plan privacy (engineering boundary)

- Storage: the plan is persisted in `cmui_runs.generated_prompt` for audit only.
- Exposure removed/blocked for old AND new records:
  - `GET /runs/{rid}` now returns a whitelist WITHOUT `generated_prompt`,
    `lease_worker`, `lease_heartbeat` (response DTO whitelist, not UI hiding).
  - SSE `prompt_ready` carries only `{characters}`.
  - Conversation/pair restore endpoints never selected the column.
  - No export/share path includes run rows (share snapshots copy only visible messages).
- The old UI "查看本次教学 Prompt" button and `inspectPrompt()` were removed.
- Tests: `test_run_response_never_exposes_plan_text` asserts the whitelist and the SSE
  contract. Model-level reproduction of the prompt by the work stage is a residual
  risk that is NOT mathematically eliminated (honest scope statement): the work
  instruction forbids exposing the prompt and chain-of-thought, and anti-leak filtering
  of literal plan text is applied only at the response boundary, not content-level.

## Billing separation

Classification, plan (stage 1), work (stage 2), exercise, explanation and coverage-review
calls are recorded separately (stage-tagged usage rows; coverage via the existing
submission ledger). Cancel/failure/recovery paths reuse existing conditional terminal
writes — no implicit retries, no double billing.
