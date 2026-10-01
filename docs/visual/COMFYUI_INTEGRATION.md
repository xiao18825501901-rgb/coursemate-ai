# ComfyUI Integration Boundary

Phase B status: the real Alibaba EAS adapter is implemented and locally contract-tested. Real image
quality and production activation remain separate evidence gates.

## Phase A provider

`MockComfyProvider` is a local deterministic provider used to prove orchestration without a GPU or network. It supports success, provider failure, unknown outcome, invalid output and late-result modes. Provider job IDs are deterministic by idempotency key, so repeated submit calls do not create duplicate work.

## Workflow registry

`app/visual/workflows/registry.example.json` contains server-owned metadata: workflow ID/version, renderer family, provider, allowed inputs, output types and model version. The UI and planner never submit arbitrary Comfy workflow JSON. Unknown or disabled combinations fail closed.

## Real provider

`AlibabaEASComfyProvider` implements the reviewed ComfyUI API contract: raw EAS authorization,
`POST /prompt`, bounded `GET /history/{prompt_id}` polling and `GET /view`. The server-owned workflow
registry pins the workflow SHA-256, `Anything-v5.0-PRT-RE.safetensors`, output node 9 and the only
fields a compiled VisualSpec may replace. The hash is checked at registry load and again at submit.

CourseJesus supplies the same deterministic UUID as ComfyUI `prompt_id` and `client_id`, persists it
before the network call, and extends the worker lease across the EAS cold-start window. Migration
069 records renderer-wait start, renderer-ready time and elapsed seconds. During that interval the
API projects `WAITING_FOR_RENDERER`; text output remains independent. Bounded retry is limited to
Alibaba gateway responses that explicitly reject before inference (429, 450 and 503).

The PAI-EAS shared-gateway endpoint supplied for this service is documented by Alibaba as HTTP.
Settings allow that scheme only for an exact origin under the multi-label
`*.pai-eas.aliyuncs.com` namespace; other provider origins remain HTTPS-only. Browser code never
receives the endpoint or token.

Provider cancellation is local suppression only. A cancelled job will not publish late bytes, but
the application does not claim that EAS stopped GPU execution. Video remains disabled because no
reviewed video workflow exists.

Real-provider evidence is still required independently: two authenticated canary images, measured
latency/output hashes, storage promotion, authenticated CourseJesus acceptance and production
monitoring. A 401/403 is an authentication blocker, not a failed image-quality result.

## User opt-in gate

Migration 068 stores a server-authoritative preference per user and course. Missing rows mean OFF.
The UI asks for explicit confirmation, and the backend rechecks the preference immediately before
any Comfy image/video submit. Auto mode also checks before planning. Deterministic SVG diagrams stay
available while OFF because they make no EAS request.

## Output publication

Provider bytes are not published directly. The service verifies MIME magic, declared dimensions, maximum bytes and duration, then writes immutable bytes through the existing StorageBackend, records SHA-256/version metadata and links the asset to the authenticated job. Invalid or cancelled results never create a published asset.
