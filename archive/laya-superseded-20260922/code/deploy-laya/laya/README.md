# deploy/laya

Deployment artifacts for the private CourseMate Laya inference service.

| File | Purpose |
|---|---|
| `coursemate-laya.service` | systemd unit: one worker, loopback-only, hardened, resource-capped. |
| `laya.env.example` | Environment template (all `LAYA_*` settings, redacted secret). |
| `nginx-laya-mtls.conf.example` | Private reverse-proxy + mTLS sketch (the only mTLS termination point). |
| `laya-definitions.example.json` | Server-managed definition allowlist example. |
| `install.sh` | Node install: venv, pinned deps, model fetch, unit install. |
| `smoke.sh` | curl-based smoke probe against a running service. |

The service itself is bound to `127.0.0.1:8105`. The owner must apply the exact
VPC / security-group rules documented in `LAYA_ALIYUN_DEPLOYMENT_RUNBOOK.md`
(repo root): no public ingress, and only CourseMate's backend security group may
reach the mTLS listener.
