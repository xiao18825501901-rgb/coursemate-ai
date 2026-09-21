# Laya inference service — security and failure modes

This documents the trust boundaries, the security controls, and — most
importantly — how CourseMate's backend must degrade **deterministically** for
every failure status the service can return.

## 1. Trust boundaries

```
Public internet ──(no route)──► Laya service
CourseMate backend ──(mTLS + service token)──► nginx ──(loopback)──► uvicorn
Browser / any third party ──(no credential, no route)──► nothing
```

* The Laya node has **no public ingress** and the service binds `127.0.0.1:8105`
  only. See the runbook §3 for the exact security-group rules.
* `/internal/v1/*` requires a pre-shared service token (constant-time compare)
  **or** mTLS terminated at nginx. It never accepts a browser Clerk token.
* There is no CORS configuration at all (the service is not browser-facing), no
  file/URL-fetch endpoint, and no permissive listener.

## 2. Auth

| Layer | Mechanism |
|---|---|
| Network | private VPC only; nginx `allow` CIDR + `ssl_verify_client on` |
| Application | `Authorization: Bearer <LAYA_SERVICE_TOKEN>` or `X-Laya-Service-Token` |
| Identity | the service credential, never a browser/Clerk identity |

`LAYA_SERVICE_TOKEN` is a `SecretStr`; it is never logged. The real backend
refuses to start without it (Settings validation fails fast).

## 3. Failure semantics

`POST /internal/v1/decisions` always returns the same envelope. The `status`
field is **authoritative**; the HTTP code is advisory. On any failure `answers`
is `null`, so a readiness/inference failure can never be mistaken for a
successful decision.

| status | HTTP | Trigger | Backend must |
|---|---|---|---|
| `OK` | 200 | answered within deadline | use the answers |
| `MODEL_NOT_READY` | 503 | model loading or failed to load | retry with backoff; alert on sustained not-ready |
| `QUEUE_FULL` | 503 | bounded queue full | shed load; retry later / mark for async retry |
| `DEADLINE_EXCEEDED` | 408 | deadline elapsed | do not block on it; retry with a longer deadline or degrade |
| `UNSUPPORTED_DEFINITION` | 422 | unknown definition/version/compiler | treat as a compiler↔server version skew; recompile or update registry |
| `INPUT_TOO_LONG` | 422 | token budget / options don't fit | shrink the state or split the questions |
| `INVALID_REQUEST` | 422 | schema mismatch / non-finite / malformed | treat as a client bug; fix the compiled payload |
| `INFERENCE_ERROR` | 500 | model raised | degrade to the non-AI path; alert |

**Deadline nuance:** a request that times out does not free the worker slot
early. The in-flight forward runs to completion and its late result is then
discarded (never delivered, never written into a newer request).

## 4. Readiness

* `/health/live` → `200` for the life of the process, **independent** of the
  model. Load balancers use this.
* `/health/ready` → `200` only after a real load **and** a warmup inference. It
  is `503` with a load-error while loading or after a load failure.
* The model is loaded exactly once at startup; there is no per-request loading.

## 5. Anti-abuse (server-side)

| Control | Default | Where |
|---|---|---|
| Max body size | 2 MiB | ASGI middleware (Content-Length 413 + streaming truncation) |
| Max questions | 10 | schema + registry |
| Max options/question | 20 | registry (entry `max_options_per_question`) |
| Max instruction/state size | 2000 / 200000 chars | schema |
| Max request tokens | 8192, measured with the real tokenizer | engine pre-check |
| Finite numerics | `deadline_ms` finite and `> 0` | schema validator |
| Definition allowlist | server-managed; empty = fail closed | registry |
| Deadline ceiling | 30000 ms | engine clamps |

A browser or any client cannot submit an arbitrary schema or an oversized
judgment: the submitted `questions` must match the registered canonical schema
byte-for-byte (ids, types, instructions, criteria), and the submitted
`compiler_version` must be in the entry's allowlist.

## 6. Logging / privacy

Logs contain **only** ids, hashes, lengths, timings and error codes/types.
Student answers, private material, plans and credentials are never logged.
`request_id` is charset-restricted (`[A-Za-z0-9._:-]{1,128}`) to prevent log
injection. Exception *messages* are not logged — only the exception type.

## 7. Failure of the real model loader (NOT_RUN in this workstream)

The real loader (torch/laya/transformers) has **not been executed** here. When
the download agent lands the snapshot, the first real load + warmup must be
watched for: (a) the `laya.load` local-directory invocation matching the actual
SDK signature, (b) the snapshot file layout matching the loader's expectations
(`rl_agent_config.json`, `tokenizer/`, `encoder/`, `model.safetensors`), and
(c) `torch.set_num_threads` taking effect before construction. A load failure
keeps `/health/ready` at `503` and decisions at `MODEL_NOT_READY` — never a
silent "successful" answer.
