# Visual Learning Engine Cost and Capacity Model

## Phase A actuals

Phase A uses no real visual model, GPU or network provider. MockComfy reports `gpu_seconds=0` and unknown monetary cost (`actual_cost_micros=NULL`), rather than inventing a zero provider bill. Deterministic SVG is local and provider-free.

## Controls implemented

- Per-user concurrent jobs: default 2.
- Global concurrent jobs: default 4.
- Daily images per user: default 20.
- Daily videos per user: default 2, while video generation is separately disabled.
- Optional daily GPU-second ceiling: `0` means the GPU-time ceiling is not configured, not unlimited provider capacity.
- Maximum output: 10 MiB, 2048 × 2048, 15 seconds.
- Retry count: default 1, with immutable parent lineage.
- Cache reuse binds source/spec/prompt/workflow/model/language/access scope.

Concurrency is checked before job creation. Renderer-specific daily quotas are checked after planning but before provider submission. Tests prove that a daily image rejection does not increment provider submit count.

## Phase B measurements required

For each approved workflow/model/hardware combination record:

```text
cost_per_job = gpu_seconds_per_job * gpu_price_per_second
daily_cost = successful_jobs * cost_per_job + failed_billable_jobs * failure_cost
peak_capacity = workers * jobs_per_worker / p95_runtime_seconds
```

Measure cold/warm latency, queue wait, peak VRAM/RAM, output sizes, cancellation waste, cache-hit rate, validation failure rate and UNKNOWN reconciliation. Do not infer total memory from model weight size or advertise a currency hard stop unless the provider and application can enforce it before submission.

## Budget boundary

No Phase A code or report grants a Phase B budget. GPU provisioning, paid canary calls and production enablement require a new explicit authorization package with provider, region, model/workflow hashes, maximum spend, time window and rollback conditions.
