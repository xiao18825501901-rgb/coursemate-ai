# Visual Learning Engine Phase A/B Runbook

## Scope

The local section operates the Phase A mock. The production section activates the reviewed Phase B
Alibaba EAS image workflow only after its independent gates pass. CourseJesus and the EAS GPU have
separate lifecycles.

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
3. Select “显示图解” for the deterministic path. For images, “生成图片” must first open the consent
   dialog while the course preference is OFF.
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

## Phase B real-provider gate

1. Confirm the EAS service identity is `coursejesus_visual_comfyui` /
   `eas-m-imgxrfj2kqws288ccf` in `cn-hangzhou` and the reviewed workflow/checkpoint are present.
2. Keep EAS at zero replicas during source work and offline tests. CourseJesus remains online.
3. Configure the public-resource Standard service with the reviewed native autoscaler in
   `ops/eas/coursejesus-visual-autoscaler.json`: min `0`, max `1`, activation `1`, intercepted
   scale-from-zero traffic, and the two 300-second idle windows. Do not use a dedicated gateway.
4. Do not place Alibaba management credentials in CourseJesus. With no management profile, apply
   and read back the policy once in the PAI console. Manual `StopService` is maintenance/emergency
   only; a manually stopped service cannot wake from inference traffic.
5. Inject the current endpoint and inference token only into one controlled PowerShell process as
   `COMFYUI_EAS_ENDPOINT` and `COMFYUI_EAS_TOKEN`. Never paste either value into chat, source, command
   arguments, frontend variables or a canary artifact.
6. From that same process, run `scripts/run_visual_eas_env_canary.py`. It performs exactly one
   non-retried `POST /prompt`; after acceptance, it only observes that same deterministic job through
   history/view. A 401 report contains only the status and a short token fingerprint.
7. A 401/403 blocks only the real-provider branch. Do not relabel it as a visual-quality failure and
   do not deploy the real provider with an unverified token. After this authentication canary passes,
   run the separately bounded Phase B quality acceptance without hidden generation retries.

Production settings after a passing canary:

```text
V3_ENABLED=true
VISUAL_ENGINE_ENABLED=true
VISUAL_PROVIDER=aliyun_eas
VISUAL_AUTO_ENABLED=true
VISUAL_VIDEO_ENABLED=false
COMFYUI_EAS_ENDPOINT=<external process/secret setting>
COMFYUI_EAS_TOKEN=<external secret only>
```

Apply migrations 067, 068 and 069 from the frozen release. Deploy backend/worker compatibility first,
then the production web build. Verify default OFF, consent, two independent user/course preferences,
text-first completion, `WAITING_FOR_RENDERER`, recorded renderer-wait seconds, image generation,
refresh/relogin restoration, immutable asset access and a zero-submit OFF request. Observe EAS
scale from `0` to `1`, then back to `0` after the idle windows.

## Production rollback

1. Set `VISUAL_ENGINE_ENABLED=false` and restart only `coursemate-rag`; the site, teaching and Agent
   stay online.
2. If application rollback is required, repoint `/srv/coursemate/current` to the prior immutable
   release. Do not overwrite databases with a pre-release backup.
3. Leave additive migrations 067/068/069 and all post-release conversations, grades, files, preferences,
   jobs and assets in place.
4. Disable autoscaling or manually stop EAS only for maintenance/emergency containment. Normal idle
   cost control is scale-to-zero, not daily Start/Stop.
