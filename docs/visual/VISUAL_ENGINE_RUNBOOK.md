# Visual Learning Engine Phase A Runbook

## Scope

This runbook operates the local/mock Phase A implementation. It does not authorize a GPU, cloud endpoint, production deployment or billable model call.

## Enable locally

Use an isolated database and storage directory, then set:

```text
APP_ENV=test
V3_ENABLED=true
UI_EXTENSION_ENABLED=true
VISUAL_ENGINE_ENABLED=true
VISUAL_PROVIDER=mock
VISUAL_AUTO_ENABLED=false
VISUAL_VIDEO_ENABLED=false
```

Initialize the RAG service normally. Migration 067 creates visual jobs, assets, cache entries, asset links and event tables. The visual worker starts only when the engine is enabled.

## Health and behavior checks

1. Confirm `/health` and `/api/ui/v1/config` are healthy and `visual_engine_enabled=true` only in the intended environment.
2. In an authenticated Learn Pair, send a teaching question and wait for a valid assistant answer.
3. Select “生成视觉”. The job should progress through queued/planning/rendering/validating to completed.
4. Confirm the asset is shown inside the same message and remains after refresh.
5. Confirm a different user receives 404 for the job/asset and a user without course access cannot read it.
6. Confirm cancellation remains terminal, retry creates a child, and repeated request IDs are idempotent.

## Diagnostic data

Use `visual_jobs` for current status, `visual_job_events` for transition history, `visual_job_assets`/`visual_assets` for publication, and `visual_cache_entries` for scoped cache reuse. Safe API projections intentionally omit frozen answer text, full VisualSpec, prompts, storage keys, provider IDs and workflow internals.

Never change failed/unknown rows to completed manually. Never retry an unknown real-provider request until the provider has been reconciled. Phase A MockComfy has no monetary cost, but the same ledger semantics are retained.

## Failure handling

- `QUOTA_EXCEEDED`: wait for active jobs to finish or the daily window to reset; do not raise limits without capacity review.
- `INVALID_PROVIDER_OUTPUT`: retain the failed job; inspect provider contract and validator evidence. No asset should exist.
- `PROVIDER_UNKNOWN`: preserve unknown cost and provider identity; reconcile before retry.
- `VIDEO_DISABLED`: expected while Phase A video remains off.
- `VISUAL_PROCESSING_FAILED`: use the job/event ID; API text is intentionally sanitized.

## Rollback

1. Set `VISUAL_ENGINE_ENABLED=false` and restart the RAG service. Text teaching remains available and no visual worker starts.
2. Revert the application/frontend release if necessary. Do not restore an old production database over newer conversations, files, grades or assessments.
3. Leave migration 067 tables and stored assets intact; the migration is additive and historical messages can keep their links.
4. If cleanup is later authorized, use a separately reviewed retention job. Do not manually delete storage objects or job rows.

## Phase B gate

Do not select `aliyun_eas` in Phase A. Proceed only after the final report says `READY_FOR_GPU=true`, then perform a new provider/infrastructure review, explicit cost authorization and a reversible canary.
