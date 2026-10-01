# Visual Learning Engine Phase B Implementation Plan

Status: implementation baseline frozen at repository HEAD `9d2c4f33af0e692fc03feeb1029b48676045dfc5`.

This plan implements the supplied Phase B/C production contract without replacing the Phase A
pipeline. It is an execution traceability document, not a new product specification.

## Ordered delivery slices

1. Add migration 068 for a server-authoritative per-user/per-course assistance preference and
   migration 069 for renderer cold-start timing receipts.
2. Add failing contract tests for preference isolation and the Alibaba EAS ComfyUI transport.
3. Import and pin the reviewed API workflow, its SHA-256, checkpoint, bindings and output node.
4. Implement the provider adapter, deterministic prompt reservation, cold-start receipt, bounded
   backoff/polling, lease renewal, output validation and immutable
   `StorageBackend` publication through the existing Phase A service.
5. Add GET/PUT preference APIs and enforce `VISUAL_ASSISTANCE_NOT_ENABLED` before any EAS submit.
6. Add the toolbar toggle, confirmation modal, persistent reload behaviour and manual/automatic
   controls without delaying the text response.
7. Run focused backend and frontend tests, then the required repository regression/build gates.
8. From the PowerShell process that owns the current endpoint/token environment variables, run the
   one-POST, no-retry EAS authentication canary without disclosing or recording either value. After
   it succeeds, continue the separately bounded Phase B image-quality acceptance.
9. Back up, migrate, release backend/worker/frontend, verify live Owner flows, monitor and record
   rollback evidence. External credential or control-plane blockers remain scoped to their branch.

## Invariants

- No preference row means OFF. Browser state can never override the server-side provider gate.
- Deterministic diagrams remain available while assistance is OFF.
- The browser cannot choose endpoints, workflows, checkpoints, models or arbitrary node inputs.
- Only the reviewed workflow bindings may change: positive, negative, seed, width, height, steps,
  and cfg. The checkpoint and graph topology stay pinned.
- Secrets are process-only and never enter source, logs, databases, artifacts or test snapshots.
- Cancelling a local job prevents late publication; it does not claim provider-side cancellation.
- Private cache and assets remain scoped to the authorized user/course source snapshot.
- EAS production idling uses native min-zero autoscaling; manual stop is not an auto-wake mechanism.
- CourseJesus stores no Alibaba control-plane credential and text completion never waits for EAS.

## Verification gates

- Migration replay and default-OFF persistence.
- Cross-user and cross-course isolation.
- OFF image/video requests make zero provider submissions; ON permits the next eligible request.
- EAS request shape, raw Authorization header, bounded timeouts, malformed responses, output node
  lookup, view download, output size/type validation and local cancel suppression.
- UI location/copy, keyboard accessibility, responsive layout, persistence and no auto request OFF.
- Secret scan, one-attempt authentication canary, bounded real image-quality evidence and cache
  proof when the current process environment is available.
- Production backup/restore, migration, release identity, authenticated live acceptance and rollback.
