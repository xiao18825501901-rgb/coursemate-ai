# Visual Learning Engine Phase A Architecture

Status: implemented locally with `MockComfyProvider`; real GPU/provider deployment is outside Phase A.

## Decision

Visual learning is an optional, asynchronous companion to the existing teaching answer. It does not replace or delay text generation. The server freezes the authenticated course, Pair, assistant message, evidence versions and requested action before it creates a job. The browser cannot supply answer text, source IDs, provider details, workflow JSON or storage keys.

The pipeline is:

```text
authenticated assistant message
  -> frozen server input
  -> versioned visual planner contract
  -> strict VisualSpec 1.0
  -> deterministic compiler/router
  -> allowlisted workflow metadata
  -> renderer/provider
  -> structural and media validation
  -> existing StorageBackend
  -> scoped asset projection in the original Pair/message
```

This separation preserves existing CourseJesus semantics: Question Engine, OpenJev receipts, LearningBridge, Map50, grades, history, Clerk identity and Task Agent are not made dependent on visual generation.

## Components

- `app/visual/spec.py`: strict `extra="forbid"` VisualSpec and grounding validation.
- `app/visual/planner.py`: versioned planner interface and deterministic Phase A mock planner.
- `app/visual/compiler.py`: deterministic prompt/diagram compilation; exact labels remain overlays.
- `app/visual/workflows.py`: server-owned workflow registry. Browser/model output cannot choose arbitrary workflows.
- `app/visual/service.py`: quotas, job lifecycle, cache, cancellation, validation and publication.
- `app/visual/store.py`: durable jobs, leases, events, assets and scoped cache.
- `app/visual/providers/`: provider interface, MockComfy implementation and a fail-closed Alibaba EAS seam.
- `app/visual/api.py`: authenticated UI API and owner/course/Pair/message enforcement.
- `app/visual/worker.py`: restart-safe worker loop using database leases.
- `VisualControls`, `VisualJobStatus`, `VisualAssetCard`: accessible Learn-page controls and status projection.

## State and recovery

Legal states are `QUEUED`, `PLANNING`, `RENDERING`, `VALIDATING`, `COMPLETED`, `FAILED`, `CANCELLED` and `RETRYING`. Every transition is validated and written to `visual_job_events`. A lease expiry makes unfinished work claimable after a process restart. Terminal jobs cannot be revived. Cancellation is authoritative in SQLite; a late provider result cannot publish an asset.

Requests are idempotent on `(user_id, request_id)`. Reusing a request ID with a different frozen payload is a conflict. Retry creates a child job with immutable parent lineage and a bounded retry count. Provider `UNKNOWN` remains failed/unknown-cost and is never silently billed as zero.

## Security boundaries

- Existing Clerk/test-auth middleware remains the only identity source.
- Course access is rechecked at create, status and asset-read time.
- Pair and message ownership are checked in the UI database; only assistant messages can be visualized.
- Private cache scope is `private:<owner>`; public cache scope is course-specific.
- Asset responses use private/no-store caching, `nosniff`, a verified content length and storage hash ETag.
- Planner inputs are data, not instructions. Strict schemas and allowlisted workflow metadata prevent workflow injection.
- Only the existing `StorageBackend` owns bytes. SQLite stores metadata, not media blobs.

## Alternatives rejected

- Synchronous rendering in the teaching request: rejected because visual failure would break valid text answers.
- Browser-selected workflows/models: rejected because it exposes infrastructure and creates injection/cost risks.
- A second asset store or public static paths: rejected because it would bypass existing storage and authorization.
- Real Alibaba/GPU calls in Phase A: rejected by the phase boundary. The seam fails closed until Phase B configuration, qualification and approval exist.

## Phase boundary

Phase A proves contracts, durability, security, UI integration and an end-to-end local provider. It does not prove real ComfyUI, GPU capacity, model quality, cloud cost or production readiness.
