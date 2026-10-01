# Alibaba EAS scale-to-zero boundary

## Intended production policy

The visual renderer is independent from the always-on CourseJesus site, RAG, teaching and
assessment services. The intended PAI-EAS policy for `coursejesus_visual_comfyui` is:

- public-resource Standard service and the existing shared gateway;
- no dedicated gateway;
- minimum replicas `0`, maximum replicas `1`;
- one activation replica when traffic arrives at zero;
- gateway traffic interception enabled while the first replica starts;
- 300 seconds of scale-in stabilization plus about 300 seconds of zero-instance grace, producing
  an intended idle-to-zero window of roughly ten minutes (actual timing must be read back from EAS
  events and metrics);
- QPS threshold `1` and no CourseJesus-held Alibaba control-plane AccessKey.

The reviewable configuration is `ops/eas/coursejesus-visual-autoscaler.json`. It is a desired-state
artifact, not proof that the cloud policy has been applied.

## Application behavior

Only a user/course with the server-side visual-assistance preference enabled can create a job that
selects `COMFY_IMAGE` or `COMFY_VIDEO`. Text is returned first and never waits for the renderer.

Before `/prompt`, the worker persists a deterministic ComfyUI `prompt_id`, the renderer-wait start
time and a lease spanning the cold-start boundary. While the gateway wakes a replica, the API
projects `WAITING_FOR_RENDERER`; this is active and cancellable, not failed. The accepted response
records renderer-ready time and wait seconds. Polling and the only safe resubmissions use bounded
exponential backoff. Automatic resubmission is limited to Alibaba responses documented as rejected
before inference (`429`, `450`, `503`) and always reuses the deterministic prompt id. Timeout,
ambiguous gateway failure and unknown outcomes are not automatically resent.

## Cloud application gate

Apply or update the autoscaler only after a management identity can read the current service and
autoscaler, and only if read-back confirms the service is public-resource Standard and not behind a
dedicated gateway. The current workstation and production ECS have no usable Alibaba management
profile or RAM role, so this policy is currently **UNAPPLIED / REQUIRES CONTROL-PLANE READ-BACK**.

Console path: PAI console → region `cn-hangzhou` → EAS →
`coursejesus_visual_comfyui` → Auto Scaling → Enable/Update.

If an authenticated `eascmd` profile becomes available, the reviewable command is:

```text
eascmd autoscale cn-hangzhou/coursejesus_visual_comfyui -s ops/eas/coursejesus-visual-autoscaler.json
```

Read back the policy, observe `0 → Waiting → Scaling → Running → 1` on the first opt-in visual job,
then verify return to `0` after the configured idle windows. Do not use `StopService` for normal
idling: a manually stopped service does not wake from traffic. Stop is reserved for maintenance or
emergency suspension.
