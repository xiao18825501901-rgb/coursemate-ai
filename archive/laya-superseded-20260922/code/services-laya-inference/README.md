# CourseMate Laya inference service

A **private, single-model** HTTP service that wraps the Laya multilingual
System 1 decision model (`convaiinnovations/laya`, subfolder `multilingual`)
for CourseMate's backend. It is a **CourseMate-internal API** — it is NOT
byte-compatible with any third-party API (not the Laya SDK, not TypeSafe Jev),
and it is never exposed to the public internet.

* One resident multilingual checkpoint, loaded once at startup. We **never** use
  the Laya `Router` (which reloads a checkpoint per language flip: ~7.4 s median
  on CPU).
* Inference runs in a dedicated worker thread off the asyncio loop, with
  `concurrency = 1`, a bounded queue, and explicit deadline handling.
* The answer shapes passed through are the Laya `system_one`/`predict` contract
  (`{"model", "answers", "usage"}`), preserved verbatim.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health/live` | Process liveness (independent of model). `200` as soon as the process serves. |
| `GET` | `/health/ready` | Model loaded **and** warmed up. `200` ready / `503` not ready. |
| `GET` | `/internal/v1/model-info` | Resident model/SDK/tokenizer identity. |
| `POST` | `/internal/v1/decisions` | Evaluate one decision. |

`/health/*` is unauthenticated (load-balancer probes). `/internal/v1/*`
requires the pre-shared service token (see [Auth](#auth)).

### Request (`POST /internal/v1/decisions`)

```json
{
  "request_id": "req-0001",
  "decision_definition_id": "course-triage",
  "definition_version": "1",
  "compiled_state": {"body": "billed twice, please refund"},
  "questions": {
    "department": {
      "type": "choice",
      "instructions": "Which department should handle this request?",
      "criteria": {"billing": "payments, refunds", "technical": "bugs, outages"}
    }
  },
  "deadline_ms": 5000,
  "model_revision": "1c5edc17a7acd8701df6fc341c0d179f1c62c982",
  "compiler_version": "1.0.0"
}
```

`compiled_state` may be a string or any JSON value (it is serialized before
tokenization). `questions` must exactly match the server-managed definition
(see [Definitions](#server-managed-definitions)); a client cannot submit an
arbitrary schema.

### Response

Every decision attempt returns the same envelope; `status` is authoritative and
the client must branch on it (not on the HTTP code alone):

```json
{
  "request_id": "req-0001",
  "receipt_id": "a1b2...",
  "status": "OK",
  "error": null,
  "answers": {
    "department": {
      "type": "choice",
      "choice": "billing",
      "probabilities": {"billing": 0.86, "technical": 0.14},
      "confidence": 0.72,
      "rl_agent": {"act_probability": 0.0}
    }
  },
  "diagnostics": {
    "input_tokens": 42,
    "state_tokens": 12,
    "questions_seen": 1,
    "max_len": 1024,
    "head_max_len": 256,
    "truncated": false,
    "options_not_fit": [],
    "deadline_clamped": false
  },
  "model": {
    "model_name": "laya-multilingual",
    "model_revision": "1c5edc17a7acd8701df6fc341c0d179f1c62c982",
    "sdk_version": "0.3.4",
    "tokenizer_revision": "unknown",
    "encoder": "jhu-clsp/mmBERT-base",
    "max_len": 1024,
    "head_max_len": 256,
    "vocab_size": 256000,
    "backend": "real"
  },
  "timings": {"queue_wait_ms": 1.2, "inference_ms": 214.0, "total_ms": 217.5},
  "calibration_version": "none"
}
```

`calibration_version` is `"none"` because the multilingual checkpoint ships with
no fitted temperatures; its probabilities are raw and over-confident (see the
Laya model card). Treat confidence as a ranking signal, not a calibrated number,
until a temperature fit is done on our own data.

## Failure semantics

`status` is one of:

| status | meaning | HTTP |
|---|---|---|
| `OK` | answered | 200 |
| `MODEL_NOT_READY` | model still loading or failed to load | 503 |
| `QUEUE_FULL` | bounded queue full, shed load and retry | 503 |
| `DEADLINE_EXCEEDED` | deadline elapsed before an answer was ready | 408 |
| `UNSUPPORTED_DEFINITION` | unknown definition/version or compiler version | 422 |
| `INPUT_TOO_LONG` | request exceeds token budget or options don't fit | 422 |
| `INVALID_REQUEST` | schema mismatch / non-finite fields / malformed body | 422 |
| `INFERENCE_ERROR` | model raised | 500 |

A readiness failure is **never** shaped like a successful decision: on failure
`answers` is `null` and `error` is populated.

## Thread, concurrency, queue, memory

The node is **8 vCPU / 16 GiB**, x86, CPU-only.

* `torch.set_num_threads(8)` (intra-op) and `torch.set_num_interop_threads(1)`.
  **Why:** one thread per vCPU lets a single forward pass use the whole socket
  without oversubscription; interop = 1 because `concurrency = 1` means only one
  inference runs at a time, so parallel-op overlap would only thrash the cache
  and add scheduler noise.
* `concurrency = 1`: the model is one resident object; running two simultaneous
  forwards on CPU doubles memory bandwidth pressure and latency for both.
* `queue_size = 8` (bounded): beyond 8 waiting requests the service returns
  `QUEUE_FULL` immediately rather than buffering unboundedly.
* `max_deadline_ms = 30_000` (server cap): the server clamps a client deadline
  to this ceiling so one request cannot pin the single worker.

**Deadline semantics (important):** a request that times out does **not** free
the worker slot early — CPU inference is not interruptible. The worker finishes
the in-flight forward, then discards the late result and marks the job
`DEADLINE_EXCEEDED`. A late result is therefore never delivered and can never be
written into a newer request.

**Process/memory limits** are enforced in the systemd unit
(`deploy/laya/coursemate-laya.service`): `MemoryMax=12G` (leaves headroom under
the 16 GiB node for the OS cache and the nginx sidecar), `CPUQuota=800%` (the
8 vCPUs), `TasksMax`, `LimitNOFILE`, and the usual hardening (see the runbook).

## Auth

`/internal/v1/*` requires a pre-shared service token from `LAYA_SERVICE_TOKEN`,
sent as `Authorization: Bearer <token>` or `X-Laya-Service-Token: <token>`.
Comparison is constant-time. It is **never** a browser Clerk token.

The real backend refuses to start without `LAYA_SERVICE_TOKEN`. The fake backend
(local dev/tests) allows an unset token.

mTLS is terminated at the private reverse proxy in front of this service (see
`deploy/laya/nginx-laya-mtls.conf.example`); the service itself only ever
listens on `127.0.0.1:8105`.

## Validation and anti-abuse

* `max_body_bytes` (2 MiB) enforced in middleware before parsing.
* `max_questions` (10), `max_options_per_question` (20), `max_instruction_chars`,
  `max_state_chars` enforced at the schema layer.
* `max_request_tokens` (8192) measured with the **real tokenizer at load time**
  using the authoritative `build_sequence` truncation rules; oversized requests
  get `INPUT_TOO_LONG`.
* Finite numeric fields (`deadline_ms` must be finite and `> 0`).
* Server-managed definition allowlist (below); unknown definitions are rejected
  with `UNSUPPORTED_DEFINITION` (fail closed when the registry is empty).

## Server-managed definitions

The server owns the only truth about which decision schemas exist. A browser or
any client cannot introduce a new schema or an oversized judgment. The registry
is a JSON file at `LAYA_DEFINITIONS_PATH`:

```json
{
  "definitions": [
    {
      "decision_definition_id": "course-triage",
      "definition_version": "1",
      "compiler_versions": ["1.0.0"],
      "max_questions": 10,
      "max_options_per_question": 20,
      "questions": {
        "department": {
          "type": "choice",
          "instructions": "Which department should handle this request?",
          "criteria": {"billing": "payments, refunds", "technical": "bugs, outages"}
        }
      }
    }
  ]
}
```

The submitted `questions` must match the canonical schema exactly (same ids,
types, instructions, criteria); the submitted `compiler_version` must be in the
entry's `compiler_versions` when that list is non-empty.

## Running

Real (production, see the runbook for the full sequence):

```bash
LAYA_MODEL_BACKEND=real \
LAYA_MODEL_DIR=/srv/coursemate/laya/multilingual \
LAYA_SERVICE_TOKEN=... \
LAYA_DEFINITIONS_PATH=/etc/coursemate/laya-definitions.json \
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8105
```

Fake (local dev / smoke, no torch, no network, no download):

```bash
LAYA_MODEL_BACKEND=fake \
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8105
```

## Logging / privacy

Logs contain only ids, hashes, lengths, timings and error codes/types. Student
answers, private material, plans and credentials are never logged. `request_id`
is charset-restricted so it cannot be used for log injection.
