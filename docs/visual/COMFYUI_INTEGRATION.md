# ComfyUI Integration Boundary

## Phase A provider

`MockComfyProvider` is a local deterministic provider used to prove orchestration without a GPU or network. It supports success, provider failure, unknown outcome, invalid output and late-result modes. Provider job IDs are deterministic by idempotency key, so repeated submit calls do not create duplicate work.

## Workflow registry

`app/visual/workflows/registry.example.json` contains server-owned metadata: workflow ID/version, renderer family, provider, allowed inputs, output types and model version. The UI and planner never submit arbitrary Comfy workflow JSON. Unknown or disabled combinations fail closed.

## Real-provider seam

`AlibabaEASComfyProvider` deliberately returns `NOT_CONFIGURED` and performs no network call. Phase A settings reject any enabled provider other than `mock`. Phase B must supply and separately verify:

1. pinned workflow and model artifacts with hashes;
2. private endpoint authentication and TLS;
3. submit/status/result/cancel protocol implementation;
4. bounded timeouts, queue capacity and provider idempotency;
5. output MIME/magic/size/dimension/duration validation;
6. semantic qualification per renderer/domain/language;
7. measured GPU latency, utilization and cost;
8. canary, monitoring and rollback evidence.

## Output publication

Provider bytes are not published directly. The service verifies MIME magic, declared dimensions, maximum bytes and duration, then writes immutable bytes through the existing StorageBackend, records SHA-256/version metadata and links the asset to the authenticated job. Invalid or cancelled results never create a published asset.
