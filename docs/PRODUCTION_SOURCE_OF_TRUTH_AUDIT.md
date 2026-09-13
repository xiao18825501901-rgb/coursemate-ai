# CourseMate V3 — Production Source of Truth Audit

Initial audit time: 2026-09-13 04:22 CST / 2026-09-12 20:22 UTC

Last public-surface revalidation: 2026-09-13 18:02:25 CST / 2026-09-13 10:02:25 UTC

Last trusted current-host inventory: 2026-09-13 20:02:07 CST / 2026-09-13 12:02:07 UTC

Last destination runtime revalidation: 2026-09-13 20:29:16 CST / 2026-09-13 12:29:16 UTC

Last destination candidate/private-TLS validation: 2026-09-13 23:13:06 CST / 2026-09-13 15:13:06 UTC

Final cutover attempt: 2026-09-14 02:00 CST / 2026-09-13 18:00 UTC

Status: `RESULT B REMAINS AUTHORITATIVE; TRUSTED TLS/RENEWAL/DEST CONFIG/V3 PREVIEW READY; SOURCE OUTAGE + INVALID PROVIDER KEY HARD BLOCK`

Data migration authorized: `YES — FINAL DRAIN/CUTOVER AUTHORIZED BUT NOT STARTED BECAUSE SOURCE IS UNREACHABLE`

This audit records only non-secret infrastructure facts, aggregate database/upload evidence, and
public HTTP behavior. It does not contain credentials, private key material, environment secrets,
user IDs, conversation text, private filenames, course content, or database rows.

## Executive conclusion

`47.237.179.69` is the currently routed CourseMate public backend address and serves the 18-path RAG
API plus the Agent health/auth surface. It is not a transparent pass-through to the currently running
6-path RAG process on `8.210.58.22`.

Owner-console evidence verified the host ED25519 fingerprint, login user, hostname and private IP.
The dedicated `coursemate-prod-current` identity then passed strict public-key BatchMode. Trusted
inventory proves that the host runs Caddy plus local RAG and Agent services, stores both SQLite
databases and the upload tree, and serves the same 18-path OpenAPI artifact observed publicly.

This audit therefore retains **Result B**: `47.237.179.69` is the authoritative CourseMate application
and data source. `8.210.58.22` is a legacy/standby candidate and is not a source for migration. The
initial backup/restore, exact-release validation, inactive production-shaped candidate preparation and
private V2/V3/proxy/monitor and loopback TLS smoke phases have passed. The destination now has a
trusted two-name Let's Encrypt certificate, a verified restricted DNS-01 renewal path, validated
inactive production env and a disabled HTTPS vhost. It still has no public CourseMate listener or
final production data.

During the authorized final cutover attempt, the authoritative source became unreachable from three
independent networks before any drain or final backup. In parallel, the protected Singapore key was
rejected by both the exact workspace and shared Singapore APIs with `401 invalid_api_key`; the
bounded canary stopped at its first Planner call with zero tokens and estimated CNY 0. Backend DNS,
Netlify production, source data, destination service activation and SRSZQ remain unchanged. The
current incident evidence and safe stop state are detailed in the final section and the final
deployment report.

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
Owner-console host identity: VERIFIED
Alibaba resource attachment ID/region: NOT RECORDED IN REPOSITORY EVIDENCE
Effective local coursemate-prod-current alias: READY
Alias target: admin@47.237.179.69:22
BatchMode public-key acceptance: PASS
Dedicated public-key fingerprint:
SHA256:60v7oW8NOi6YEdRCBGY4b3xIfyW4Fy94thVTAhRWWi8
Verified login user: admin
Verified hostname: iZt4n0k005125h6vlxoiloZ
Verified private IP: 172.17.61.74
Local Alibaba CLI: UNAVAILABLE
Reachable ports: 22, 80, 443
Common alternative SSH ports checked and closed: 2022, 2200, 2222, 8022, 8822
SSH banner: OpenSSH_9.6p1 Ubuntu-3ubuntu13.19
SSH authentication advertised: publickey,password
Verified ED25519 host fingerprint:
SHA256:xrg8yao3PqVrTPP5Qx0st1pxeHt4jVR13L7CY38D8iw
Host fingerprint trust: PASS — Owner-console value matches strict local known_hosts validation
```

A dedicated encrypted ED25519 key was created with restrictive Windows ACLs and loaded into
`ssh-agent`. The Owner installed only its public half under the verified `admin` account after backing
up `authorized_keys` to
`/home/admin/.ssh/authorized_keys.pre-coursemate-20260913T115433Z`. No password was requested in chat,
put on a command line, logged or stored. The temporary verification file was removed after the exact
host public key was promoted into the normal strict `known_hosts` file.

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
ECS instance ID: i-bp1f0vqhds2341pdqqiy
Hostname: iZbp1f0vqhds2341pdqqiyZ
Public / private IP: 47.114.34.175 / 172.20.170.40
Region / zone: cn-hangzhou / cn-hangzhou-k
OS: Ubuntu 22.04.5 LTS
System disk: d-bp1f0vqhds2341pces7h; ESSD PL0; 40 GiB; unencrypted
Restart required: YES
CourseMate candidate root: /srv/coursemate — PREPARED, INACTIVE, NOT SERVING TRAFFIC
Candidate release/runtime: exact 9806a55 under /srv/coursemate; independent Python 3.12.14 venv
Final candidate data: DIRECTORY SKELETON ONLY — 0 files; RAG/Agent DB absent
Initial recovery copies: PRESENT under /srv/coursemate-migration and /srv/coursemate/backups
CourseMate RAG/Agent: INSTALLED/LOADED, inactive and disabled
CourseMate monitor: service static/inactive; timer disabled/inactive
CourseMate nginx site: sites-available only; not enabled; nginx not reloaded
Pre-runtime system-disk snapshot: s-bp13r5gqocjif1jtieav (disk d-bp1f0vqhds2341pces7h)
Exact validated release: 9806a553a30c0531f727ba1538543fe6225e4c44
Schema 10 -> 21 rehearsal: PASS on copied databases only
Private V2/V3/proxy/monitor smoke: PASS on disposable copied data; all transient listeners stopped
Destination source validation: PASS; no live or paid provider calls
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

No apt/system/global package replacement, firewall change, enabled proxy change, PM2 change, reboot or
public service activation was made. Python 3.12.14, locked virtual environments and release-local Node
dependencies were installed only inside the isolated migration and independent CourseMate candidate
roots after explicit Owner approval; system Python remains 3.10.12. Root-owned candidate environment,
systemd units and an unenabled nginx site were prepared and validated without reloading nginx.

Owner-console screenshots confirm the instance, its single attached system disk, the pre-runtime
snapshot above, and one associated normal Security Group. The full inbound table shows four allow
rules from IPv4 `0.0.0.0/0`: TCP/80 and TCP/443 at priority 1, all ICMP-IPv4 and TCP/22 at priority
100. This proves 443 is permitted at the Security Group; the failed external 443 check is explained by
the confirmed absence of a listener. No rule was changed. Public SSH exposure remains a hardening risk
that must not be narrowed without a stable Owner source range and tested fallback access.

Nginx has TLS support and Certbot/timer exist, but the destination has no trusted production
certificate or public 443 listener. TLS issuance/key handling therefore remains an explicit Owner
gate.

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
| Role | legacy/standby only | authoritative current application/data source | destination + existing SRSZQ |
| Public DNS receives traffic | no | yes | no |
| CourseMate RAG present | yes | yes | final candidate installed; inactive |
| RAG API path count | 6 | 18 | exact candidate validated privately; not routed |
| RAG release SHA | `ef7795b1e41aefbfdf9738e88a7eca053ea621db` | `cb7d0633e5026d042014512b72273f4439c9cff4` detached release | candidate `9806a553a30c0531f727ba1538543fe6225e4c44` |
| RAG DB | `/srv/coursemate/rag/rag.sqlite3` | `/srv/coursemate/rag/rag.sqlite3` | pristine restore + disposable smoke copies; final DB absent |
| RAG schema | migration 1 | migration 10 | V2 smoke 10; V3 disposable smoke 21; no final live DB |
| RAG aggregate rows | 2 courses, 1 document, 0 chunks, 1 job, 0 conversations/messages | 2 courses, 66 documents, 1,936 chunks, 69 jobs, 39 conversations, 86 messages | restored aggregates match; not serving |
| Agent present | active local service | active local service | final candidate installed; inactive |
| Agent DB | `/srv/coursemate/agent/agent.sqlite3` | `/srv/coursemate/agent/agent.sqlite3` | pristine restore + disposable smoke copy; final DB absent |
| Uploads | `/srv/coursemate/rag/uploads`; 1 file / 229 bytes | `/srv/coursemate/rag/uploads`; 67 files / 124,209,790 bytes | verified restore/smoke copies; final uploads empty |
| Reverse proxy | Caddy -> local 8000/8001 | Caddy -> local 8000/8001 | live nginx -> SRSZQ; CourseMate site prepared but disabled |
| Auth config | Clerk-protected; exact production CORS | Clerk-protected; exact production CORS | secret-safe candidate; private auth/CORS smoke pass; inactive |
| Model config | OpenAI-compatible; named models verified | Alibaba DashScope international OpenAI-compatible endpoint; `qwen3.7-plus` + `text-embedding-v4` | compatibility config prepared; qwen3.8 intent inactive/unverified; no paid call |
| Last activity | content/storage stale since 2026-08-13; no access log | messages through 2026-09-07; services restarted 2026-09-12; live HTTP verified 2026-09-13 | SRSZQ active; CourseMate private smoke completed then stopped |
| Authoritative source | no | **yes — Result B** | no |

## 7. Database comparison

| Fact | 8.210.58.22 | 47.237.179.69 | 47.114.34.175 |
|---|---|---|---|
| RAG DB | `/srv/coursemate/rag/rag.sqlite3` | `/srv/coursemate/rag/rag.sqlite3` | restore/rehearsal/smoke copies; final DB absent |
| RAG schema | migration 1 | migration 10 | V2 copied smoke 10; V3 copied smoke 21; not live |
| RAG aggregate rows | 2 courses, 1 document, 0 chunks | 2 courses, 66 documents, 1,936 chunks | copied aggregates match |
| Agent DB | `/srv/coursemate/agent/agent.sqlite3` | `/srv/coursemate/agent/agent.sqlite3` | restore/smoke copies; final DB absent |
| Agent schema | migration 1 | migration 1 | isolated migration 1 |
| Agent aggregate rows | 0 tasks | 1 task | copied aggregate matches |
| Integrity / FK | both OK / 0 violations | both OK / 0 violations | copied DBs OK / 0 violations |

Database size was not used as the production decision criterion.

## 8. Upload comparison

| Fact | 8.210.58.22 | 47.237.179.69 | 47.114.34.175 |
|---|---|---|---|
| Root | `/srv/coursemate/rag/uploads` | `/srv/coursemate/rag/uploads` | verified restore/smoke copies; final uploads empty |
| Files / bytes | 1 / 229 | 67 / 124,209,790 | copied 67 / 124,209,790 |
| Fresh normalized manifest digest | `53e037ba...941e` | `c5fb27c3...0a2d` | copied digest matches source |
| Latest content mtime | 2026-08-13 06:00:47 CST | 2026-08-11 15:15:45 CST | preserved in archive; private names not read |

No private filename or file content was printed.

## 9. Reverse-proxy topology

Verified:

```text
8.210.58.22 Caddy:
  rag.qqttai.com   -> 127.0.0.1:8000
  agent.qqttai.com -> 127.0.0.1:8001

47.237.179.69 Caddy:
  rag.qqttai.com   -> 127.0.0.1:8000
  agent.qqttai.com -> 127.0.0.1:8001
  RAG/Agent processes, databases and uploads are local to the same host

47.114.34.175 nginx:
  default :80 -> SRSZQ 127.0.0.1:8080 / :8081
  CourseMate candidate -> 127.0.0.1:28000 / :28001 (sites-available only; disabled)
  private proxy smoke -> 127.0.0.1:29080 (completed and stopped)
```

The trusted current-host inventory identifies both Caddy upstreams and both local services. Together
with the local database/upload paths and the exact public/local OpenAPI digest match, this rules out
the previously plausible split Agent/storage topology for the current deployment.

## 10. Source-of-truth decision

```text
AUTHORITATIVE COURSEMATE MIGRATION SOURCE:
47.237.179.69 (`coursemate-prod-current`)

Result A (8.210.58.22): NOT SUPPORTED by current RAG/DNS/activity evidence
Result B (47.237.179.69): PROVEN — SELECTED
Result C (SPLIT PRODUCTION): REJECTED by trusted proxy/process/database/upload evidence

SAFE TO START INITIAL BACKUP / OFF-HOST COPY / ISOLATED RESTORE: YES
SAFE TO START FINAL WRITE DRAIN / CUTOVER / DNS CHANGE: NO — LATER OWNER GATES APPLY
```

The decision uses trusted runtime and data evidence, not API size or DNS alone.

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

1. Owner selects the production certificate issuance/key method now that TCP/443 ingress is verified.
   Prefer a fresh Let's Encrypt DNS-01 bootstrap certificate; do not copy an existing private key
   without explicit authorization.
2. Owner states whether running `srszq-staging` must survive a reboot; it is absent from the saved PM2
   resurrection dump. Do not reboot or run an indiscriminate `pm2 save` before that decision.
3. Agree an exact paid-call ceiling and credential scope for the `qwen3.8-max` capability probe and
   benchmark. Current evidence remains local/fake-provider only.
4. Approve a final source write window, create and verify the drained snapshot/delta, and copy it into
   the still-empty final destination data paths. This is not covered by the initial online snapshot.
5. After TLS, final data, rollback and private acceptance pass, separately gate service/site activation,
   pinned-IP HTTPS smoke and DNS cutover.

### Initial recovery slice completed

At 2026-09-13 20:15 CST, the corrected backup tool from commit `105ccda` created a standalone initial
online recovery unit containing both SQLite databases and all uploads. The first pre-fix pack remains
preserved but is superseded because WAL-mode source databases left unverified zero-byte sidecars in
that directory. The corrected pack contains exactly the six expected files, no sidecars, verified
checksums, integrity `ok`, FK 0, 67 uploads / 124,209,790 bytes and the source aggregate row counts.

The corrected recovery unit was copied to `/srv/coursemate-migration/incoming/` on
`47.114.34.175`, checksum-verified again and restored under `/srv/coursemate-migration/restores/`.
Both restored database binaries match their backup SHA-256 values, and the restored upload manifest
digest matches the source. Commit `105ccda` was cloned from a verified Git bundle into the isolated
migration root for the first migration rehearsals. It remains preserved.

Owner-console evidence then recorded destination system-disk snapshot
`s-bp13r5gqocjif1jtieav`; after explicit approval, Python 3.12.14, uv 0.12.13, hash-locked production
and test virtual environments, and release-local Node dependencies were installed only below
`/srv/coursemate-migration`. System Python and global Node/npm were not replaced.

Schema 10 -> 21 passed twice on independent fresh copies and again on exact release `9806a55`, with
old-row fingerprints unchanged, migration continuity 1..21, integrity `ok`, FK 0 and all V3
invariants true. Evidence JSON is content-free and reproducibly hashes to
`a9a7bb9b1751317be2ebae4fddb58bdb1470409875457e84275c18a7557f2a7f`.

A clean-clone-only benchmark safety issue was fixed in commit
`9806a553a30c0531f727ba1538543fe6225e4c44`: static URL validation and conservative query-cost refusal
now occur before corpus/database/client access. Exact release validation on the destination reports
322 Python tests passed / 6 corpus-only skips, Ruff pass, mypy pass, Web 49/49, Agent 66/66,
typecheck pass and production build pass. All model behavior in these tests was fake/local; no paid or
live-provider call occurred. Nginx and both SRSZQ PM2 applications remained healthy, with PIDs 1182
and 48185 unchanged, and public source RAG/Agent health remained HTTP 200.

### Inactive final candidate and private smoke completed

The exact clean release was cloned into `/srv/coursemate/releases/9806a55`, with an independent
Python 3.12.14 runtime/venv under `/srv/coursemate/runtime` and a `current` symlink. Locked Node
dependencies passed build validation and were production-pruned. The candidate is owned for execution
by the unprivileged `coursemate` account. The initial recovery unit was also copied into
`/srv/coursemate/backups` and its five manifest-covered artifacts revalidated; final data paths remain
an empty uploads directory skeleton because the drained source snapshot has not been authorized or
created. File count is 0 and both final database files are absent.

Source secrets moved directly through protected server files and an allowlisted transform; no value
was printed. Candidate RAG/Agent/monitor environment files are root-owned and group-readable only.
Four systemd unit files are loaded and inactive: RAG/Agent/timer are disabled and monitor service is
static. The CourseMate nginx configuration is only
in `sites-available`; it is not enabled and nginx was not reloaded. The V3 branch was published by
non-force push, so exact application commit `9806a55` is reachable from the remote branch history.

Disposable V2 and V3 smoke runs exercised health, authentication, authorization, CORS, compatibility,
Schema 10 -> 21, non-leaking workspace behavior and unchanged base data/upload invariants. A separate
localhost-only nginx smoke verified both host routes, and the actual monitor probe returned status
`ok` (RAG 12 ms, Agent 2 ms). No model evidence or reservation rows were created. All transient units
were stopped and ports 28000, 28001 and 29080 were confirmed closed. Content-free smoke evidence:
`bde19f160d7957f63abf64154e54180c7a8d9b077ce9a200107c9431a338f4ba`.

A subsequent read-only source check still found Schema 10/1, the same aggregate row counts,
integrity/FK results and upload count/bytes/digest as the initial slice. This is a drift signal only:
equal aggregates do not prove unchanged row content and cannot replace the final drained snapshot.

A second, independent TLS smoke used a generated one-day synthetic certificate with SANs for only the
two CourseMate domains. A separate nginx bound to `127.0.0.1:29443` and proxied to transient RAG/Agent
units. HTTPS health returned 200/200; protected routes returned 401/401; SNI mismatch rejection,
certificate verification, configured TLS protocol policy, HSTS, security headers and exact CORS all
passed. The temporary key was removed, all test listeners closed, final data files remained 0, and
both model-run evidence and call-reservation counts remained 0. Live nginx/SRSZQ PIDs stayed
897/1182/48185. Failure injection immediately after nginx readiness returned the expected 97 and
independently left no listener or key. The repaired normal-path evidence SHA-256 is
`f1b0fd8e63c33b9a02768ad6f080a5cf01fc907cfbc3d982ddbb84db77429ffe`.

Public DNS showed no CAA record and no existing `_acme-challenge` TXT record for either CourseMate
hostname. A manual DNS-01 bootstrap therefore has no observed record conflict, but no DNS write or
certificate request is authorized yet.

Production certificate issuance and reboot are unresolved. The destination still has no trusted
certificate or public 443 listener. It also reports a pending `libc6` reboot; the saved PM2 dump
contains SRSZQ production but not the currently running `srszq-staging` process. Neither production
TLS activation nor reboot is authorized by this preparation.

## Safety ledger

```text
Production DB copy: YES — initial SQLite-online snapshots only
Uploads transfer: YES — initial verified archive to isolated and candidate backup roots only
Schema migration: COPIED-DATABASE REHEARSAL ONLY — PASS; SOURCE/LIVE NO
Candidate release/runtime/env/units: PREPARED — ALL INACTIVE; RAG/AGENT/TIMER DISABLED; MONITOR STATIC; DATA FILES=0
Private smoke service starts: YES — TRANSIENT/LOCALHOST ONLY; STOPPED; PORTS CLOSED
Private TLS smoke: PASS — LOOPBACK/SYNTHETIC CERT ONLY; KEY REMOVED; NO PUBLIC 443
Existing service stop/restart/replacement: NO
Nginx configuration: CANDIDATE FILE VALIDATED; NOT ENABLED; NO RELOAD
Security Group evidence: VERIFIED — PUBLIC TCP/80, TCP/443, TCP/22 AND ICMP ALLOWED; UNCHANGED
DNS change: NO
Package install: ISOLATED MIGRATION + COURSEMATE CANDIDATE ROOTS; APT/SYSTEM/GLOBAL NO
Successful paid model inference: NO — later auth-rejected canary attempt used zero tokens and CNY 0
Password collected/stored: NO
Private key exposed: NO
User/course content read: NO
Reboot: NO
Authorized remote writes: dedicated public key; initial backup/restore; isolated/candidate runtime and config; private smoke; non-force branch push
```

## Final cutover revalidation and incident evidence

The following evidence was collected after the earlier safety ledger and supersedes only its
time-sensitive runtime statements:

| Surface | Final observed fact |
|---|---|
| Authoritative source | `47.237.179.69`; previously proven complete source; now TCP 22/80/443 timeout and ICMP 100% loss from local, new ECS and legacy ECS |
| Public backend DNS | `rag.qqttai.com` and `agent.qqttai.com` still resolve through DNS-only Cloudflare A records to `47.237.179.69`; automatic TTL |
| Frontend | `https://qqttai.com` HTTP 200; production deploy unchanged |
| Destination | `47.114.34.175`; SSH ready; final data has zero files and one empty uploads directory |
| Destination CourseMate | RAG, Agent and monitor timer inactive/disabled; vhost disabled; no public 443 listener; `V3_ENABLED=false` |
| Destination TLS | Let's Encrypt YR2; SANs `rag.qqttai.com`, `agent.qqttai.com`; expires 2026-12-12 16:17:46 UTC; chain and renewal dry-run pass |
| Destination provider | Exact workspace reachable, but installed `sk-ws` key receives `401 invalid_api_key` from workspace and shared Singapore APIs |
| SRSZQ | nginx/production/staging processes remain active with PIDs 897/1182/48185; no reboot, PM2 save, config edit or signal |

The source failure was observed before any final-drain command. No attempt was made to treat the
initial online backup as current or to start destination production from it. The source did not
receive a service stop, migration, database write, DNS change or destructive action during this
attempt.

Cloudflare API access was separately proven through the restricted destination-to-legacy egress.
The captured pre-cutover state is mode 0600 and has SHA-256
`8a71816ff1346da1c5185761a31461d627f8ecfabcbb25628a6129c3d39f7c1a`. Certificate renewal uses the
same destination-held Cloudflare token without copying it to the legacy server. Before retiring the
legacy server, this egress dependency must be replaced and renewal dry-run repeated.

The qwen failure checkpoint is content-free except for synthetic benchmark output metadata. It
records a maximum of three authorized calls, CNY 0.79255405 conservative ceiling, one rejected
Planner request, zero input/output tokens, no provider response ID, no retry and CNY 0 estimated
cost. SHA-256:
`b9cb250633cd3763d37505d300e3c8292a2def40fe2b8a9aab4c1bd85765d68f`.

This is an external hard-block stop, not a production acceptance. Exact human recovery actions and
the gates that must be rerun are in
[`COURSEMATE_V3_FINAL_PRODUCTION_DEPLOYMENT_REPORT.md`](COURSEMATE_V3_FINAL_PRODUCTION_DEPLOYMENT_REPORT.md).
