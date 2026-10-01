# ADR-004: Server-owned visual consent and a pinned PAI-EAS workflow

## Status

Accepted

## Date

2026-10-01

## Context

Phase A proved visual orchestration with a deterministic local provider. Phase B must call the
existing Alibaba PAI-EAS ComfyUI service without giving the browser authority over credentials,
workflow topology, checkpoints, storage keys, or model inputs. Generated visuals may incur a
continuing GPU cost, and a learner must explicitly opt in per course before any provider submit.

The reviewed PAI-EAS shared-gateway endpoint is unusual: Alibaba's ComfyUI documentation exposes it
as an HTTP origin with a raw `Authorization` token. Substituting HTTPS for the supplied host fails
certificate hostname verification. This exception must not become a general permission for
plaintext provider endpoints.

## Decision

- Keep the existing Phase A job, event, immutable asset, cache, permission and worker model.
- Store the visual-assistance preference on the server, keyed by user and course. Missing rows mean
  OFF. The API checks current course access on every read and write.
- Enforce the preference again inside `VisualService` before an Alibaba image/video submit. Browser
  state is advisory and cannot bypass this gate.
- Pin the reviewed API workflow by SHA-256, checkpoint, output node and an allowlist of seven input
  bindings. Recheck the workflow hash at every submit so a post-start file change fails closed.
- Use the raw EAS token only in the backend process. The operator injects endpoint and token through
  one controlled process environment. The authentication canary makes exactly one non-retried
  `/prompt` request, never records either variable value, and limits a 401 receipt to the status and
  a short token fingerprint. The legacy document-carrier path is retired.
- Permit HTTP only for an exact origin whose hostname is under the multi-label
  `*.pai-eas.aliyuncs.com` shared-gateway namespace. All other real-provider endpoints require
  HTTPS; credentials in URLs, ports, paths, queries and fragments are rejected.
- Keep video disabled until a separately reviewed video workflow and qualification exist.
- Treat the EAS GPU lifecycle independently from CourseJesus. Production uses EAS native
  scale-to-zero on the public-resource Standard shared gateway (`min=0`, `max=1`, activation=1),
  not a CourseJesus-held Alibaba management AccessKey. Manual stop remains maintenance/emergency
  only because stopped services do not wake from traffic.
- Reserve a deterministic ComfyUI prompt ID and a cold-start-length worker lease before `/prompt`.
  Project the active job as `WAITING_FOR_RENDERER` until the gateway returns an accepted prompt,
  record the wait duration, and retry only explicit pre-inference gateway rejections with bounded
  backoff. Ambiguous outcomes are never automatically resent.

## Alternatives considered

### Browser-to-EAS requests

Rejected. They would expose the EAS token and allow arbitrary workflow/checkpoint manipulation.

### Default-on assistance

Rejected. It would create unrequested paid work and violate the explicit product consent contract.

### CSS-only consent or a browser-only flag

Rejected. Crafted API requests could still reach the provider.

### Force HTTPS on the shared-gateway hostname

Rejected after measured certificate principal failure and comparison with Alibaba's documented HTTP
ComfyUI endpoint. TLS verification remains mandatory for every endpoint outside the narrow official
shared-gateway exception.

### Enable animation through the image workflow

Rejected. A still image is not a verified video workflow and must not be presented as one.

## Consequences

- Migrations 068 and 069 are additive and preserve all Phase A jobs, assets and links.
- Turning the feature off is immediate and does not delete history or generated assets.
- Cancelling a CourseJesus job suppresses later publication, but does not claim provider-side
  cancellation because that capability has not been verified.
- Production activation remains blocked until the current EAS token authenticates, the bounded real
  image-quality acceptance passes, and an authenticated live CourseJesus flow passes.
- Without a management profile or ECS RAM role, the autoscaler must be configured and read back in
  the PAI console. CourseJesus cannot infer control-plane authority from an inference token.
