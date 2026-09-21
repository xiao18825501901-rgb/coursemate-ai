# Laya inference service — Aliyun deployment runbook

Private single-model deployment of the Laya multilingual decision model
(`convaiinnovations/laya`, subfolder `multilingual`, Apache-2.0) for CourseMate.

> **Workstream status:** this runbook is written by the service workstream. The
> real model download and `REAL_LAYA_INFERENCE` are **NOT_RUN** here — a separate
> agent performs the actual snapshot download and the first real-model load.

## 1. Architecture

```
CourseMate backend (VPC, private security group)
        │  mTLS (client cert) on PRIVATE_VPC_IP:8443
        ▼
nginx (mTLS termination, allowlist by security-group CIDR)
        │  plain HTTP on loopback
        ▼
coursemate-laya.service  (uvicorn, ONE worker, 127.0.0.1:8105)
        │  thread-confined engine (concurrency=1, bounded queue)
        ▼
resident multilingual checkpoint (loaded once, warmed up)
```

* The Laya service **never** has a public IP, a public DNS name, or a public
  ingress rule.
* The only client is CourseMate's backend. mTLS is terminated at nginx; the
  service additionally requires a pre-shared service token on `/internal/v1/*`.

## 2. Node

* **Spec:** 8 vCPU / 16 GiB, x86_64, Ubuntu 24.04, in the same VPC as CourseMate.
* **CPU budget:** 8 vCPU = `CPUQuota=800%` in the unit.
* **Memory budget:** `MemoryMax=12G` leaves ~4 GiB for the OS page cache and the
  nginx sidecar. The model is ~647 MB of weights; FP32 activations for a
  ~1024-token batch are well within the remaining headroom.

## 3. VPC and security-group rules (owner MUST apply)

These are the exact, minimal rules. Anything more permissive is a defect.

| Direction | Source | Destination | Protocol/Port | Purpose |
|---|---|---|---|---|
| Ingress | CourseMate backend SG | Laya SG | TCP 8443 | mTLS decision API |
| Ingress | CourseMate backend SG | Laya SG | TCP 22 | SSH (operator only) |
| Egress | Laya SG | 0.0.0.0/0 | TCP 443 | one-time model download (then lock to HF) |
| Egress | Laya SG | CourseMate backend SG | — | none required (server never dials CourseMate) |

Hard requirements:

1. **No** `0.0.0.0/0` ingress to the Laya SG on any port.
2. **No** public/NAT gateway egress after install — the runtime is `HF_HUB_OFFLINE=1`;
   the node needs egress only once, for `fetch_laya_model.py` and `pip install`.
3. The Laya SG is attached only to this node. The mTLS listener binds a
   **private** VPC IP, never `0.0.0.0`.
4. After the model is fetched and dependencies installed, remove the 443 egress
   rule (or leave it, but the service never uses it at runtime).

## 4. Prerequisites

* Python 3.12 on the node (`python3.12 -m venv`).
* `scripts/fetch_laya_model.py` + `services/laya-inference/` + `deploy/laya/` in
  the repo checkout at `/srv/coursemate/current`.

## 5. Model snapshot (pinned, verified, atomic)

Run once (this is the step the separate download agent performs):

```bash
python3.12 scripts/fetch_laya_model.py \
  --repo convaiinnovations/laya \
  --subfolder multilingual \
  --revision 1c5edc17a7acd8701df6fc341c0d179f1c62c982 \
  --dest /srv/coursemate/laya/multilingual
```

Guarantees: `snapshot_download` at the pinned commit only (never `latest`), a
per-file SHA-256 is computed before landing, the directory appears atomically,
and a `model-manifest.json` is written inside it. Re-verify any time, offline:

```bash
python3.12 scripts/fetch_laya_model.py \
  --dest /srv/coursemate/laya/multilingual \
  --verify-only
```

## 6. Install

```bash
sudo REPO_ROOT=/srv/coursemate/current bash deploy/laya/install.sh
```

The script: creates the `coursemate` user and directories, builds
`/srv/coursemate/runtime/laya` (torch CPU wheel + pinned `requirements.txt`),
fetches the model, writes `/etc/coursemate/laya.env` and
`/etc/coursemate/laya-definitions.json`, installs and enables the unit.

## 7. Environment

```bash
sudo install -m 0600 deploy/laya/laya.env.example /etc/coursemate/laya.env
# then set LAYA_SERVICE_TOKEN to `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`
```

Key settings (see `services/laya-inference/app/settings.py` for all):

* `LAYA_MODEL_BACKEND=real`, `LAYA_MODEL_DIR=/srv/coursemate/laya/multilingual`.
* `LAYA_TORCH_THREADS=8`, `LAYA_TORCH_INTEROP_THREADS=1` — one intra-op thread per
  vCPU; interop 1 because `concurrency=1` means a second parallel op stream only
  thrashes the cache (see §11).
* `LAYA_CONCURRENCY=1`, `LAYA_QUEUE_SIZE=8`, `LAYA_MAX_DEADLINE_MS=30000`.
* `LAYA_DEFINITIONS_PATH=/etc/coursemate/laya-definitions.json`.

## 8. Definitions registry (server-managed allowlist)

Edit `/etc/coursemate/laya-definitions.json` to the real allowlist (see the
service README for the shape and the example in `deploy/laya/`). **Empty or
absent = fail closed** — every definition is rejected as `UNSUPPORTED_DEFINITION`.
The CourseMate-side compiler workstream must hand over the canonical
`(decision_definition_id, definition_version)` → questions map.

## 9. mTLS reverse proxy

Copy `deploy/laya/nginx-laya-mtls.conf.example` into the nginx config, replacing
placeholders with the private VPC IP, the server cert/key, and the CA that signed
CourseMate's backend client cert. Set `ssl_verify_client on`. The listener must
allow only the CourseMate backend security-group CIDR.

## 10. Start and verify

```bash
sudo systemctl daemon-reload
sudo systemctl start coursemate-laya.service
sudo systemctl status coursemate-laya.service
```

`/health/live` is `200` before the model finishes loading; `/health/ready` flips
to `200` only after a real load **and** a lightweight warmup inference.

## 11. Thread / concurrency / queue / memory rationale

| Setting | Value | Why |
|---|---|---|
| `torch_threads` | 8 | One intra-op thread per vCPU; a single forward pass can use the whole socket. |
| `torch_interop_threads` | 1 | Only one inference runs at a time (`concurrency=1`), so parallel op overlap only thrashes. |
| `concurrency` | 1 | One resident model object; two simultaneous CPU forwards double memory-bandwidth pressure and p50 latency. |
| `queue_size` | 8 | Bounded backpressure: beyond 8 waiting requests the service returns `QUEUE_FULL` instead of buffering. |
| `max_deadline_ms` | 30000 | A server-side ceiling so one request cannot pin the single worker. |
| `MemoryMax` | 12G | Headroom under the 16 GiB node for the OS cache + nginx. |
| `CPUQuota` | 800% | Caps the process at the node's 8 vCPUs. |

## 12. Smoke test

```bash
sudo TOKEN='<the service token>' BASE_URL=http://127.0.0.1:8105 bash deploy/laya/smoke.sh
```

Covers live, ready, model-info, one accepted decision, an oversized-body
rejection, a deadline-exceeded rejection, and an auth rejection.

## 13. Rollback

* The unit is pinned to one snapshot directory. Roll back by swapping
  `LAYA_MODEL_DIR` to the previous verified snapshot (its `model-manifest.json`
  carries its own revision + hashes) and `systemctl restart`.
* The service has no database and no state; there is nothing to migrate.

## 14. This workstream did NOT do

* Real model download / `REAL_LAYA_INFERENCE` — **NOT_RUN** (separate agent).
* Per-file SHA-256 of the real snapshot — **UNKNOWN** until that download lands
  and `fetch_laya_model.py --verify-only` is run against it.
