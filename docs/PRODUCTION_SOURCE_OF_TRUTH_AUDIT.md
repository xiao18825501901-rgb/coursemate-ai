# CourseMate V3 — Production Source of Truth Audit

Initial audit time: 2026-09-13 04:22 CST / 2026-09-12 20:22 UTC

Last public-surface revalidation: 2026-09-13 18:02:25 CST / 2026-09-13 10:02:25 UTC

Status: `BLOCKED ON ALIBABA RESOURCE OWNERSHIP AND TRUSTED ACCESS TO CURRENT PUBLIC BACKEND`

Data migration authorized: `NO`

This audit records only non-secret infrastructure facts, aggregate database/upload evidence, and
public HTTP behavior. It does not contain credentials, private key material, environment secrets,
user IDs, conversation text, private filenames, course content, or database rows.

## Executive conclusion

`47.237.179.69` is the currently routed CourseMate public backend address and serves the 18-path RAG
API plus the Agent health/auth surface. It is not a transparent pass-through to the currently running
6-path RAG process on `8.210.58.22`.

However, no existing safe local key can authenticate to `47.237.179.69`, and its SSH host key has not
yet been verified through the Alibaba Cloud console. Its process topology, reverse-proxy upstreams,
release SHA, RAG DB, Agent DB, uploads and model configuration remain unknown. A split topology—such
as current RAG on `47.237.179.69` with Agent or storage elsewhere—cannot yet be excluded.

Therefore this audit does not issue Result A, B, or C and does not select a migration source. The
strongest candidate is `47.237.179.69`, but production data movement remains blocked until trusted
SSH inventory proves whether it is a complete application host, a gateway, or one part of a split
deployment.

## 1. DNS topology

The authoritative DNS servers are `nile.ns.cloudflare.com` and `walk.ns.cloudflare.com`.

| Domain | Observed DNS | TTL evidence | HTTP role | Proxy/CDN interpretation |
|---|---|---:|---|---|
| `qqttai.com` | A `75.2.60.5`, `99.83.231.61` | cached observations 0–137s | Netlify site, HTTP 200 | Netlify edge |
| `www.qqttai.com` | CNAME `coursemate-ai-qqtt.netlify.app` | 300s | HTTP 301 to apex | Netlify edge |
| `rag.qqttai.com` | A `47.237.179.69` | 300s | CourseMate RAG | direct visible origin IP |
| `agent.qqttai.com` | A `47.237.179.69` | 300s | CourseMate Agent | direct visible origin IP |

Both `1.1.1.1` and `8.8.8.8` returned the same backend address. Backend responses contain Caddy,
Uvicorn and Clerk-related headers but no Cloudflare edge headers. Cloudflare is therefore verified as
the DNS authority; “backend records are DNS-only rather than orange-cloud proxied” is a high-confidence
inference from the visible Alibaba address and HTTP headers, not a Cloudflare-dashboard fact.

### Phase A1 public revalidation — 2026-09-13 18:02:25 CST

The public surface was rechecked without changing DNS, services or data:

```text
1.1.1.1 rag.qqttai.com   -> 47.237.179.69, TTL 300
1.1.1.1 agent.qqttai.com -> 47.237.179.69, TTL 300
8.8.8.8 rag.qqttai.com   -> 47.237.179.69, TTL 300
8.8.8.8 agent.qqttai.com -> 47.237.179.69, TTL 300

Pinned HTTPS rag /health:   HTTP 200, remote_ip=47.237.179.69, TLS verify=0
Pinned HTTPS agent /health: HTTP 200, remote_ip=47.237.179.69, TLS verify=0
Pinned HTTPS rag OpenAPI:   HTTP 200, remote_ip=47.237.179.69, TLS verify=0
RAG OpenAPI paths:          18
RAG OpenAPI bytes:          31,745
RAG OpenAPI SHA-256:        3c7c74ef0b98c114403c46f798d10720198a4452860e226df1530ae7a2b30572
```

Both public services negotiated TLS 1.3. The RAG certificate is valid for `rag.qqttai.com` from
2026-08-12 23:15:02 UTC through 2026-11-10 23:15:01 UTC; the Agent certificate is valid for
`agent.qqttai.com` from 2026-08-12 23:17:04 UTC through 2026-11-10 23:17:03 UTC. Both chains were
accepted by the local trust store. Allowlisted response headers still show Caddy, exact
`Access-Control-Allow-Origin: https://qqttai.com`, HSTS and restrictive security headers.

```text
RAG certificate SHA-256:   3738e7792b7e5d7991defb40da214e1814d30b476ed500ee9a2cc9b5771f7b0f
Agent certificate SHA-256: a35de5c00c1210d429cd92dd0f1ef876f40a7079428cc4ebcc929c4b2ff72c98
Issuer: Let's Encrypt YE1
```

This proves that `47.237.179.69` still terminates or routes the live CourseMate HTTPS surface. It does
not prove whether the address is an ECS interface, EIP, load balancer, NAT/proxy, or which backend
stores the production data.

```text
Browser -> qqttai.com / www.qqttai.com -> Netlify
Browser -> rag.qqttai.com   --+
Browser -> agent.qqttai.com --+-> 47.237.179.69 -> Caddy -> UNKNOWN upstream/runtime/storage

8.210.58.22  -> Caddy -> local RAG :8000 + local Agent :8001 (not current DNS target)
47.114.34.175 -> nginx -> existing SRSZQ :8080/:8081 (future CourseMate destination)
```

## 2. Inventory — 8.210.58.22

### Role and host

```text
SSH alias: coursemate-prod-old — READY / BatchMode PASS
Observed role: running legacy/standby CourseMate candidate
Hostname: iZj6chenajfmlqwq8i5x9pZ
Region / zone: cn-hongkong / cn-hongkong-b
OS: Ubuntu 24.04.4 LTS
Release: ef7795b1e41aefbfdf9738e88a7eca053ea621db
Branch: main, clean, one commit ahead of origin/main
Restart required: YES
```

### Runtime

```text
RAG: coursemate-rag.service, active/enabled, admin, 127.0.0.1:8000
Agent: coursemate-agent.service, active/enabled, admin, *:8001
Proxy: Caddy active/enabled
RAG env file: /etc/coursemate/rag.env
Agent env file: /etc/coursemate/agent.env
UFW: active, inbound default deny, 22/80/443 allowed
```

### Storage and aggregate health

```text
RAG DB: /srv/coursemate/rag/rag.sqlite3
  bytes=131072, WAL, integrity=ok, FK violations=0, schema migration=1
  courses=2, documents=1, chunks=0, ingestion_jobs=1
  conversations=0, messages=0

Agent DB: /srv/coursemate/agent/agent.sqlite3
  bytes=32768, WAL, integrity=ok, FK violations=0, schema migration=1
  tasks=0, rate_limit_windows=0

Uploads: /srv/coursemate/rag/uploads
  files=1, bytes=229, symlinks=0, special files=0
  manifest SHA-256=672a2a76ea75d8ad7da3eaf569cf184757061a1e30d29f23286180ac0519e170
```

### Activity assessment

```text
RAG DB content-file mtime: 2026-08-13 06:00:48 CST
Agent DB content-file mtime: 2026-08-13 03:12:39 CST
Latest upload mtime: 2026-08-13 06:00:47 CST
Uploads modified in last 30 days: 0
CourseMate services: active with zero systemd restarts
Caddy access logging: not configured; no /var/log/caddy files
Current public DNS target: NO
```

Recent SQLite `-shm` timestamps and empty WAL timestamps were excluded as evidence of business writes;
they can change when a process opens a database or when read-only checks run. Service journals prove
the processes are alive, not that users are reaching them.

Classification: `LEGACY/STANDBY CANDIDATE`. It is not the current public RAG endpoint. A possible
split Agent/storage role cannot be fully excluded until the current host's proxy and runtime are read.

### Non-secret runtime configuration

This host reports OpenAI-compatible mode using `gpt-5.6-luna` for chat and
`text-embedding-3-small` for embeddings. Protected endpoints return 401 without a Clerk session and
CORS allows the exact origin `https://qqttai.com`. These are facts about this host only.

## 3. Inventory — 47.237.179.69

### Verified public surface

```text
Current DNS backend: YES
Alibaba resource type/ownership: UNKNOWN — manual console discovery required
Effective local coursemate-prod-current alias: ABSENT
Local Alibaba CLI: UNAVAILABLE
Reachable ports: 22, 80, 443
Common alternative SSH ports checked and closed: 2022, 2200, 2222, 8022, 8822
SSH banner: OpenSSH_9.6p1 Ubuntu-3ubuntu13.19
SSH authentication advertised: publickey,password
Previously observed candidate ED25519 host fingerprint:
SHA256:xrg8yao3PqVrTPP5Qx0st1pxeHt4jVR13L7CY38D8iw
Host fingerprint trust: TOFU ONLY — not authoritative until Alibaba-console verified
```

Existing local keys were tried non-interactively against the plausible `root`, `admin`, `ubuntu`,
and `ecs-user` accounts. No combination authenticated. No password was requested, collected, placed
on a command line, or stored. No `coursemate-prod-current` alias was created because neither the login
identity nor the host fingerprint is yet trusted.

The temporary TOFU-only host-key file used for the key matrix was deleted after the probe and was
never referenced by the main SSH configuration.

### Public API facts

```text
RAG title: CourseMate RAG API
RAG version: 0.1.0
RAG path count: 18
RAG OpenAPI SHA-256:
3c7c74ef0b98c114403c46f798d10720198a4452860e226df1530ae7a2b30572

RAG /health: HTTP 200
Agent /health: HTTP 200
Unauthenticated RAG /api/courses: HTTP 401
Unauthenticated Agent /api/tasks: HTTP 401
CORS preflight from https://qqttai.com: HTTP 200, exact allow-origin
Observed proxy/application headers: Via: 1.1 Caddy; Server: uvicorn; Clerk signed-out headers
```

Current RAG paths:

```text
/health
/api/courses
/api/courses/{course_id}
/api/courses/{course_id}/documents
/api/courses/{course_id}/documents/{document_id}
/api/ingestion-jobs/{job_id}
/api/admin/retrieval/diagnostics
/api/conversations
/api/conversations/{conversation_id}
/api/qa/chat
/api/teaching-profiles/preview
/api/courses/{course_id}/teaching-profiles
/api/courses/{course_id}/teaching-profiles/{version}/restore
/api/courses/{course_id}/publication-requests
/api/courses/{course_id}/publication-requests/current
/api/admin/publication-requests
/api/admin/publication-requests/{request_id}/review
/api/admin/courses/{course_id}/publication
```

### Unknown until trusted login

```text
Hostname / private IP / region / full OS: UNKNOWN
CourseMate process and service units: UNKNOWN
Caddy upstream target: UNKNOWN
Current release SHA or artifact version: UNKNOWN
CURRENT_RAG_DATABASE_PATH: UNKNOWN
CURRENT_AGENT_DATABASE_PATH: UNKNOWN
CURRENT_UPLOAD_ROOT: UNKNOWN
Database integrity, schema, counts and last writes: UNKNOWN
Upload count, bytes, manifest and last writes: UNKNOWN
Environment-file names: UNKNOWN
Provider/model configuration: UNKNOWN
Whether Agent/storage is split to 8.210.58.22: UNKNOWN
```

Classification: `CURRENT PUBLIC COURSEMATE BACKEND / INTERNAL ROLE UNKNOWN`.

## 4. Destination inventory — 47.114.34.175

```text
SSH alias: coursemate-prod-new — READY / BatchMode PASS
Role: DESTINATION + EXISTING SRSZQ
Hostname: iZbp1f0vqhds2341pdqqiyZ
Public / private IP: 47.114.34.175 / 172.20.170.40
Region / zone: cn-hangzhou / cn-hangzhou-k
OS: Ubuntu 22.04.5 LTS
Restart required: YES
CourseMate directories, units, DBs and uploads: ABSENT / NOT TRANSFERRED
```

This is not an empty destination:

```text
nginx.service: active/enabled, owns :80
enabled nginx site: srszq-api
pm2-root.service: active/enabled
existing SRSZQ Node listeners: 127.0.0.1:8080 and :8081
UFW: inactive
Caddy: not installed
SQLite CLI: not installed
```

No package, firewall, proxy, PM2, service or application change was made.

## 5. API surface comparison

| Fact | 8.210.58.22 | 47.237.179.69 |
|---|---|---|
| RAG title/version | CourseMate RAG API / 0.1.0 | CourseMate RAG API / 0.1.0 |
| RAG route count | 6 | 18 |
| OpenAPI SHA-256 | `767cc1c...acec5a06` | `3c7c74...30572` |
| RAG health | 200 | 200 |
| Agent health | 200 | 200 |
| CORS origin | exact `https://qqttai.com` | exact `https://qqttai.com` |
| Unauthenticated protected routes | 401 | 401 |
| Visible proxy | Caddy | Caddy |

The current public API adds course mutation, document deletion, retrieval diagnostics, conversation
listing/rename/delete, teaching profiles and publication governance. A transparent proxy to the old
local RAG process would return the same OpenAPI artifact; these artifacts differ materially.

## 6. Runtime comparison

### PRODUCTION SOURCE COMPARISON

| Fact | 8.210.58.22 | 47.237.179.69 | 47.114.34.175 |
|---|---|---|---|
| Role | legacy/standby candidate; split role not excluded | current public backend; internals unknown | destination + existing SRSZQ |
| Public DNS receives traffic | no | yes | no |
| CourseMate RAG present | yes | yes | no; deployment target only |
| RAG API path count | 6 | 18 | not deployed |
| RAG release SHA | `ef7795b1e41aefbfdf9738e88a7eca053ea621db` | unknown | not deployed |
| RAG DB | `/srv/coursemate/rag/rag.sqlite3` | unknown | absent |
| RAG schema | migration 1 | unknown | not deployed |
| RAG aggregate rows | 2 courses, 1 document, 0 chunks, 1 job, 0 conversations/messages | unknown | none |
| Agent present | active local service | public health/auth surface only; runtime unknown | no CourseMate Agent |
| Agent DB | `/srv/coursemate/agent/agent.sqlite3` | unknown | absent |
| Uploads | `/srv/coursemate/rag/uploads`; 1 file / 229 bytes | root and aggregate unknown | absent |
| Reverse proxy | Caddy -> local 8000/8001 | Caddy -> unknown upstreams | nginx -> SRSZQ 8080/8081 |
| Auth config | Clerk-protected; exact production CORS | Clerk-protected; exact production CORS | CourseMate absent |
| Model config | OpenAI-compatible; named models verified | unknown | CourseMate absent |
| Last activity | content/storage stale since 2026-08-13; no access log | current HTTP responses only | SRSZQ active; CourseMate absent |
| Candidate authoritative source | unsupported as sole RAG source | strongest candidate; unproven | no |

## 7. Database comparison

| Fact | 8.210.58.22 | 47.237.179.69 | 47.114.34.175 |
|---|---|---|---|
| RAG DB | `/srv/coursemate/rag/rag.sqlite3` | unknown | absent |
| RAG schema | migration 1 | unknown | not deployed |
| RAG aggregate rows | 2 courses, 1 document, 0 chunks | unknown | none |
| Agent DB | `/srv/coursemate/agent/agent.sqlite3` | unknown | absent |
| Agent schema | migration 1 | unknown | not deployed |
| Agent aggregate rows | 0 tasks | unknown | none |
| Integrity / FK | both OK / 0 violations | unknown | not applicable |

Database size was not used as the production decision criterion.

## 8. Upload comparison

| Fact | 8.210.58.22 | 47.237.179.69 | 47.114.34.175 |
|---|---|---|---|
| Root | `/srv/coursemate/rag/uploads` | unknown | absent |
| Files / bytes | 1 / 229 | unknown | 0 / 0 for CourseMate |
| Manifest digest | `672a2a76...9e170` | unknown | not applicable |
| Latest content mtime | 2026-08-13 06:00:47 CST | unknown | not applicable |

No private filename or file content was printed.

## 9. Reverse-proxy topology

Verified:

```text
8.210.58.22 Caddy:
  rag.qqttai.com   -> 127.0.0.1:8000
  agent.qqttai.com -> 127.0.0.1:8001

47.237.179.69 public headers:
  HTTPS edge/proxy = Caddy
  RAG upstream = UNKNOWN
  Agent upstream = UNKNOWN

47.114.34.175 nginx:
  default :80 -> SRSZQ 127.0.0.1:8080 / :8081
```

No config on `8.210.58.22` references `47.237.179.69`, and its current RAG artifact differs from the
public one. This rejects the narrow hypothesis “47.237.179.69 transparently proxies the running old
RAG process,” but does not identify the current Caddy upstream or rule out split Agent/storage.

## 10. Source-of-truth decision

```text
AUTHORITATIVE COURSEMATE MIGRATION SOURCE:
NOT YET DETERMINED

Result A (8.210.58.22): NOT SUPPORTED by current RAG/DNS/activity evidence
Result B (47.237.179.69): LEADING CANDIDATE, but DB/storage/runtime proof is missing
Result C (SPLIT PRODUCTION): STILL POSSIBLE until current proxy/process/storage inventory is read

SAFE TO START DATA MIGRATION: NO
```

The required evidence threshold deliberately prevents selecting a host from API size or DNS alone.

## 11. New-ECS coexistence constraints

Default plan: retain nginx as the edge proxy and extend it with separate CourseMate virtual hosts only
after backups and config validation. CourseMate must use:

- an independent unprivileged Linux user;
- independent repository/release directories;
- independent systemd units;
- unused localhost ports that do not collide with 8080/8081;
- independent root-owned environment files;
- independent RAG DB, Agent DB and uploads paths;
- nginx routes scoped only to CourseMate domains;
- no replacement, stop, overwrite or PM2 change for SRSZQ.

An alternate nginx-to-internal-Caddy design is permissible only if it has a clear operational need.
Caddy must not bind public ports 80/443 while nginx owns them. Replacing nginx is not the default.

## 12. Next migration action

### Manual action required

```text
MANUAL ACTION REQUIRED: 需要为 47.237.179.69 建立 SSH public-key login。
```

In the Alibaba Cloud console, search for `47.237.179.69` in this order without changing any resource:

1. ECS public IPv4;
2. EIP / Elastic IP and its associated resource;
3. NAT Gateway forwarding/DNAT;
4. SLB / ALB / NLB listeners and backend server groups;
5. other network resources and, if absent, other Owner-controlled accounts/regions.

Do not assume that a public address is attached directly to an ECS network interface. Record only the
resource type, region, associated resource identifier/name and backend private IP/port topology; do
not expose cloud credentials or unrelated resources.

If the address resolves to a Linux ECS or an associated backend ECS, enter it through Workbench,
Session Manager, VNC or another already trusted console channel and run:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
whoami
hostname
hostname -I
```

The prior network probe recorded this candidate fingerprint:

```text
SHA256:xrg8yao3PqVrTPP5Qx0st1pxeHt4jVR13L7CY38D8iw
```

If the console fingerprint matches, record `HOST_IDENTITY_VERIFIED`. If it differs, do not regenerate
or change host keys, disable verification, or accept the network key blindly. Record
`FINGERPRINT_RECONCILIATION_REQUIRED` and investigate IP/EIP reassociation, a changed system disk,
load-balancer/proxy topology and the provenance of the old TOFU value. The identity observed inside the
current Alibaba console instance has higher evidentiary priority than the prior unverified text.

Report only the resource type, whether the fingerprint matches, the actual login user, hostname and
private IP. Do not send a password, private key, token, `.env`, database, or screenshot containing
secrets. After the resource and host identity are reconciled, create/authorize a dedicated public key
through a visible terminal password prompt or the trusted console, then add `coursemate-prod-current`
with strict public-key BatchMode settings.

Only after that alias passes may the next automated phase read the current host's systemd/process,
Git/artifact, proxy upstream, allowlisted path configuration, aggregate DB health, upload manifest and
last-activity evidence. The source decision and coordinated backup plan must then be updated before
any data transfer.

## Safety ledger

```text
Production DB copy: NO
Uploads transfer: NO
Schema migration: NO
Service stop/restart/replacement: NO
DNS change: NO
Package install: NO
Paid model call: NO
Password collected/stored: NO
Private key exposed: NO
User/course content read: NO
```
