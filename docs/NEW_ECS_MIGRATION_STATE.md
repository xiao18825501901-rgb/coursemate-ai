# CourseMate V3 — New Alibaba ECS Migration State

Last updated: 2026-09-13 20:29:16 CST / 2026-09-13 12:29:16 UTC

Current phase: `Initial backup/isolated restore PASS; destination runtime installation Owner gate`

Production data copied: `YES — INITIAL ONLINE BACKUP ONLY; FINAL DELTA NOT STARTED`

Production writes changed: `NO`

DNS changed: `NO`

Rollback-ready application backup: `INITIAL RESTORE VERIFIED; FINAL CUTOVER SNAPSHOT NOT CREATED`

This is the non-secret migration control record. It separates live evidence, repository facts,
Owner-designated roles, and unresolved production authority. It must never contain credentials,
private key material, private course content, database rows, upload names, prompt bodies, or raw
provider responses.

## Executive gate

All three dedicated aliases pass strict, public-key-only BatchMode authentication:

```text
coursemate-prod-old -> root@8.210.58.22     READY
coursemate-prod-new -> root@47.114.34.175   READY
coursemate-prod-current -> admin@47.237.179.69 READY
```

Public DNS, pinned-IP HTTPS/TLS, Owner-console host identity and trusted SSH inventory identify
`47.237.179.69` as the complete current CourseMate application and data source. The source decision is
**Result B**. Initial backup/off-host copy/isolated restore work is authorized; final drain, production
cutover, DNS, paid model calls, destructive actions and destination reboot remain gated. The full
three-host evidence ledger is in
[`PRODUCTION_SOURCE_OF_TRUTH_AUDIT.md`](PRODUCTION_SOURCE_OF_TRUTH_AUDIT.md).

## SSH access result

```text
SSH ACCESS RESULT

coursemate-prod-old:
READY
Target: 8.210.58.22
Host: iZj6chenajfmlqwq8i5x9pZ
Authentication: PUBLIC KEY
BatchMode: PASS
Dedicated public-key fingerprint:
SHA256:lK+LhdVhtIX58VR0ZHWPRpbuAshW3UweAQsA5HzPBy0

coursemate-prod-new:
READY
Public IP: 47.114.34.175
Private IP: 172.20.170.40
Host: iZbp1f0vqhds2341pdqqiyZ
Authentication: PUBLIC KEY
BatchMode: PASS
Dedicated public-key fingerprint:
SHA256:QPnw/QX3kIXsMxRys4GB8BTnjAsTUICw4c8o9TH6tZg

New server ED25519 host fingerprint:
SHA256:TWqeYbYv83dw67sg6BWf3gv3C4LjRWeioaA5/qbq4k4
Verification: PASS against the Owner's ECS-console fingerprint and strict known_hosts validation

coursemate-prod-current:
READY
Public IP: 47.237.179.69
Private IP: 172.17.61.74
Host: iZt4n0k005125h6vlxoiloZ
User: admin
Role: AUTHORITATIVE CURRENT COURSEMATE APPLICATION/DATA SOURCE (RESULT B)
Alibaba resource attachment ID/region: NOT RECORDED IN REPOSITORY EVIDENCE
Authentication advertised: publickey,password
Verified server ED25519 fingerprint:
SHA256:xrg8yao3PqVrTPP5Qx0st1pxeHt4jVR13L7CY38D8iw
Fingerprint verification: PASS against Owner-console evidence and strict known_hosts validation
Authentication: PUBLIC KEY
BatchMode: PASS
Dedicated public-key fingerprint:
SHA256:60v7oW8NOi6YEdRCBGY4b3xIfyW4Fy94thVTAhRWWi8
Remote authorized_keys backup:
/home/admin/.ssh/authorized_keys.pre-coursemate-20260913T115433Z

Password included in scripts/files: NO
Private key exposed: NO
Ready for old/destination-host read-only preparation: YES
Ready for current-host inventory: YES — COMPLETED
Ready for initial backup/off-host copy/isolated restore: YES
Ready for final drain/cutover: NO — LATER OWNER GATES APPLY
```

The verified destination fingerprint
`SHA256:TWqeYbYv83dw67sg6BWf3gv3C4LjRWeioaA5/qbq4k4` belongs only to `47.114.34.175`. It is not
expected to equal the separately verified current-source fingerprint
`SHA256:xrg8yao3PqVrTPP5Qx0st1pxeHt4jVR13L7CY38D8iw`.

### Local SSH state and rollback

- The old/destination keypairs pre-existed. A separate passphrase-protected
  `C:\Users\Hp\.ssh\coursemate-prod-current` ED25519 keypair was created for the authoritative source;
  no old/destination private key was reused.
- Windows `ssh-agent` is `Running` with startup type `Automatic`. All three CourseMate identities were
  loaded for acceptance. Re-run BatchMode validation after a Windows reboot or agent reset.
- The three alias blocks specify exact hosts/users/port 22, dedicated identities, `IdentitiesOnly yes`,
  `PreferredAuthentications publickey`, and `BatchMode yes`.
- All three private-key ACLs are limited to the current user, `SYSTEM`, and local Administrators; no
  `Everyone` or ordinary `Users` grant was observed.
- Before the current-source public key was appended, `/home/admin/.ssh/authorized_keys` was backed up
  as `/home/admin/.ssh/authorized_keys.pre-coursemate-20260913T115433Z`. Earlier root-owned backups for
  the old/destination aliases remain separate.
- Rollback of the key append is possible through the corresponding backup, but only while retaining
  another verified management path. No rollback was needed.
- `PASSWORD ROTATION REQUIRED`: the Owner reported that server passwords had appeared in an external
  chat context. Rotation is recommended after access stabilization, but no password was requested,
  collected, changed, logged, or stored in this run.

## Production reality reconciliation

### Current public runtime evidence

As rechecked at 2026-09-13 18:02:25 CST, two independent public resolvers agree:

```text
rag.qqttai.com   A 47.237.179.69
agent.qqttai.com A 47.237.179.69
```

Both public health endpoints return HTTP 200. The public RAG OpenAPI currently has 18 paths and
SHA-256:

```text
3c7c74ef0b98c114403c46f798d10720198a4452860e226df1530ae7a2b30572
```

Pinned-IP HTTPS checks for RAG health, Agent health and RAG OpenAPI all connected to
`47.237.179.69`, returned HTTP 200 and passed TLS verification. The two domain certificates are
currently valid through 2026-11-10 UTC; TLS 1.3, Caddy, the exact production CORS origin, HSTS and
restrictive security headers were observed. This proves only the current public routing/edge, not the
Alibaba resource type or data location.

Owner-console evidence confirmed ED25519 fingerprint
`SHA256:xrg8yao3PqVrTPP5Qx0st1pxeHt4jVR13L7CY38D8iw`, user `admin`, hostname
`iZt4n0k005125h6vlxoiloZ` and private IP `172.17.61.74`. A dedicated key then passed BatchMode.
Trusted inventory found Ubuntu 24.04.2 LTS, Caddy on 80/443, local RAG on 127.0.0.1:8000 and local
Agent on 127.0.0.1:8001. All three services are active/enabled.

The running code is detached release `cb7d0633e5026d042014512b72273f4439c9cff4` under
`/home/admin/coursemate-v2-candidate-cb7d0633309c`. The older `/home/admin/coursemate-ai` directory
is `main@e1ef57a...`. Systemd drop-ins explicitly select the detached release, and its local 18-path
OpenAPI SHA-256 exactly matches the public artifact. No daemon-reload, restart or service mutation
was performed.

The same host owns `/srv/coursemate/rag/rag.sqlite3`, `/srv/coursemate/agent/agent.sqlite3` and
`/srv/coursemate/rag/uploads`. Both databases report integrity OK and zero FK violations. RAG is at
migration 10 with 2 courses, 66 documents, 1,936 chunks, 39 conversations and 86 messages; Agent is
at migration 1 with one task. Uploads contain 67 files / 124,209,790 bytes. The runtime uses the
Alibaba DashScope international OpenAI-compatible endpoint with `qwen3.7-plus` and
`text-embedding-v4`; secret values were not read or printed.

This proves `RESULT B`: `47.237.179.69` is the authoritative application/data source. The trusted
local Caddy upstreams, services, databases and uploads reject the previous split-production case.

### Owner-designated old server evidence

The repaired `coursemate-prod-old` alias authenticates to `8.210.58.22`. Its local RAG OpenAPI has
only 6 paths and a different SHA-256:

```text
767cc1c7a37a7ae6b7edc8cda76fed06d98e1de7e9d91369fc8800a8acec5a06
```

This proves that `8.210.58.22` and the current DNS backend do not expose the same RAG release. Its
database content and upload mtimes are stale since 2026-08-13 and its Caddy access logs are not
configured. It is therefore classified as `LEGACY/STANDBY`; it is not part of the selected migration
source.

## Local release candidate

```text
Repository root:
C:\Users\Hp\Documents\Codex\2026-08-11\files-mentioned-by-the-user-coursemate\outputs\coursemate-ai

Branch: feature/coursemate-v3-persistent-learning
Baseline HEAD before this state update: 6367f9f2e190834dba3a9ee1d59edb96df387415
Baseline subject: docs(ops): record phase A1 production revalidation
Working tree at start: two preserved Owner untracked files; no tracked or staged changes
Owner files preserved: ACTUAL_IMPLEMENTED_CHANGES_AUDIT.md, curl
Origin main last observed: 73e7595dc8fc7179e4cd9693dd024e7a983792c2
V3 branch on origin: absent at this check
Schema source: migrations 1-21
```

The Stage 8 report records 327 Python, 49 Web, 66 Agent, 3 V3 Playwright, and 4 V2 Playwright tests
passing at its recorded code state. They were not re-run for this SSH/inventory slice and are not
live-model or production evidence.

## SOURCE SERVER — Owner-designated old server

### Host and release

```text
SSH alias: coursemate-prod-old
Host: iZj6chenajfmlqwq8i5x9pZ
Public IP: 8.210.58.22
Private IP: 172.19.63.160
Region / zone: cn-hongkong / cn-hongkong-b (ECS metadata)
OS: Ubuntu 24.04.4 LTS
Kernel: 6.8.0-63-generic
Root disk: 40G total, 6.2G used, 32G available (17%)
Memory: 1.6GiB total; 2.0GiB swap
Restart required: YES
Repository: /home/admin/coursemate-ai
Branch: main
Tracked/untracked changes: 0 / 0
Git HEAD: ef7795b1e41aefbfdf9738e88a7eca053ea621db
HEAD subject: fix: stabilize frontend build dependencies
Relation to origin/main: one local commit ahead, no remote-only commit
```

### Runtime topology

```text
RAG unit: coursemate-rag.service — active/enabled
RAG user/workdir: admin / /home/admin/coursemate-ai/services/rag-api
RAG env file: /etc/coursemate/rag.env (640 root:admin)
RAG bind: 127.0.0.1:8000

Agent unit: coursemate-agent.service — active/enabled
Agent user/workdir: admin / /home/admin/coursemate-ai
Agent env file: /etc/coursemate/agent.env (640 root:admin)
Agent bind: *:8001; UFW blocks direct public access

Caddy unit/config: caddy.service / /etc/caddy/Caddyfile — active/enabled
rag.qqttai.com   -> 127.0.0.1:8000
agent.qqttai.com -> 127.0.0.1:8001
api.srszq.com    -> 127.0.0.1:9080 (unrelated unless the Owner proves otherwise)

UFW: active; inbound default deny; only 22, 80, and 443 allowed
```

### Authoritative paths on this host

For **this host**, the Agent DB path is no longer unknown. It is independently supported by the
allowlisted runtime environment, the active Agent process's open file descriptor, and SQLite checks:

```text
RAG_DATABASE_PATH=/srv/coursemate/rag/rag.sqlite3
AGENT_DATABASE_PATH=/srv/coursemate/agent/agent.sqlite3
RAG_UPLOAD_DIR=/srv/coursemate/rag/uploads
```

Aggregate-only health snapshot:

```text
RAG DB: 131072 bytes; WAL; integrity=ok; FK violations=0; migrations=1
RAG rows: courses=2, documents=1, chunks=0, ingestion_jobs=1,
          conversations=0, messages=0

Agent DB: 32768 bytes; WAL; integrity=ok; FK violations=0; migrations=1
Agent rows: tasks=0, rate_limit_windows=0

Uploads: 1 file, 229 bytes, symlinks=0, special files=0
```

The environment files report OpenAI-compatible mode with `gpt-5.6-luna` for chat and
`text-embedding-3-small` for embeddings. Secret-valued variables were excluded from output. These
provider/model facts apply only to `8.210.58.22`, not to the inaccessible current DNS backend.

## DESTINATION SERVER — new Alibaba ECS

### Verified host baseline

```text
SSH alias: coursemate-prod-new
Host: iZbp1f0vqhds2341pdqqiyZ
Public IP: 47.114.34.175
Private IP: 172.20.170.40
Region / zone: cn-hangzhou / cn-hangzhou-k (ECS metadata)
OS: Ubuntu 22.04.5 LTS
Kernel: 5.15.0-187-generic
Root disk: 40G total, 4.0G used, 34G available (11%)
Memory: 3.4GiB total; no swap
Time zone / sync: Asia/Shanghai; NTP synchronized
Restart required: YES
```

### Tooling and application state

```text
git: 2.34.1
python3: 3.10.12
node: 24.20.0
npm: 11.19.0
rsync: 3.2.7
caddy: MISSING
sqlite3 CLI: MISSING

/srv/coursemate: MISSING
/etc/coursemate: MISSING
/home/admin/coursemate-ai: MISSING
/root/coursemate-ai: MISSING
/opt/coursemate: MISSING
CourseMate RAG/Agent units: NOT INSTALLED
RAG DB / Agent DB / uploads: NOT TRANSFERRED
```

The destination is **not an empty machine** and must not be repurposed destructively. Existing,
enabled services currently own the standard web port and internal application ports:

```text
nginx 1.18.0: active/enabled, listening on :80
enabled site: srszq-api (default server)
upstreams: 127.0.0.1:8081 and 127.0.0.1:8080
pm2-root.service: active/enabled; Node process owns 127.0.0.1:8080 and :8081
UFW: inactive
```

No Caddy installation, firewall change, package installation, reboot, service stop, or file transfer
was performed. The Alibaba Security Group remains unknown from the guest OS and requires console
verification. A coexistence/protection plan for the existing `srszq-api` service is mandatory before
binding Caddy or another proxy to ports 80/443.

## Migration state

```text
SSH access: COMPLETE for old/current/destination aliases
Discovery: COMPLETE for 8.210.58.22, 47.237.179.69 and 47.114.34.175
Current public discovery: COMPLETE — host, runtime, proxy, release, DBs, uploads and safe provider config inventoried
Current public SSH: READY — strict public-key BatchMode PASS
Authoritative source selection: RESULT B — 47.237.179.69
Preparation: COMPLETE for the initial recovery slice
Initial sync: COMPLETE — verified recovery unit copied to destination isolation root
Consistent backup: INITIAL ONLINE SNAPSHOT PASS; FINAL DRAINED/CUTOVER SNAPSHOT NOT STARTED
Isolated restore: COMPLETE — checksums, DB binaries, integrity/FK/counts and uploads match
Schema migration: BLOCKED BEFORE EXECUTION — destination has Python 3.10; project requires >=3.11
Pre-cutover: NOT STARTED
Cutover: NOT STARTED — OWNER GATE
Post-cutover: NOT STARTED
Observation: NOT STARTED
Completed: NO
```

## Initial backup and isolated restore evidence

The source backup contract first exposed a production-only WAL edge case: the original script left
zero-byte `-wal` and `-shm` sidecars beside otherwise valid snapshots, outside `SHA256SUMS`. That first
pack remains preserved and is not used for migration. Commit `105ccda` adds a failing-then-passing WAL
regression test and converts only each destination snapshot to `journal_mode=DELETE`; the live source
databases remain WAL. Focused verification: 9 backup/restore tests, Ruff and mypy all pass.

The corrected initial recovery unit is:

```text
Source:
/home/admin/coursemate-migration-backups/initial-standalone-20260913T121500Z/
  coursemate-v2-20260913T121513.787049Z

Destination copy:
/srv/coursemate-migration/incoming/coursemate-v2-20260913T121513.787049Z

Isolated restore:
/srv/coursemate-migration/restores/initial-20260913T121513Z
```

The pack contains exactly six top-level files, has no SQLite sidecars, and all five manifest-covered
artifact checksums pass. Restored RAG/Agent database SHA-256 values exactly match the backup files;
both report integrity `ok` and FK 0. RAG remains migration 10 with 1,936 chunks, 66 documents,
39 conversations and 86 messages. Agent remains migration 1 with one task. Restored uploads are
67 files / 124,209,790 bytes with normalized manifest digest
`c5fb27c39fd06ff48972d3df1bb495345adfffffb4324b7d4dc579ad454c0a2d`.

Tracked source at `105ccdaeec3b45c208a8e039d7943a5e22e277ce` was packaged as a complete Git
bundle, SHA-256 `93e00cd8e1230d45a3aeb6cbae72e817fc8985248082d7695c2d6c99b55315df`, then
cloned to `/srv/coursemate-migration/releases/105ccda` and checked out detached. The clone has zero
tracked or untracked changes. This is an isolated migration release, not a running deployment.

## Current blockers and risks

1. **Runtime-installation gate:** an exhaustive read-only scan found only Python 3.10.12. There is no
   Python 3.11/3.12/3.13 executable, compatible virtual environment, `uv`, `pyenv`, Conda, Docker,
   Podman or other ready runtime. The apt mirror exposes only a Python 3.11.0 release-candidate package,
   which is not an acceptable production foundation. LXD is installed but has no instance, local image
   or storage pool, so using it would require mutating host initialization. The release also lacks its
   required `pydantic`, `pydantic-settings` and FastAPI dependencies. Do not install packages or
   initialize a runtime until the Owner verifies the Security Group and creates/approves a new-ECS
   rollback snapshot; snapshot storage may incur cloud cost.
2. **Destination service collision:** new ECS ports 80, 8080, and 8081 already support `srszq-api`.
   Replacing nginx or stopping PM2 could break an unrelated live service.
3. **Destination hardening:** the machine requires a reboot, UFW is inactive, Caddy and SQLite CLI
   are absent, and the Alibaba Security Group is unverified.
4. **Release publication:** exact tracked commit `105ccda` is frozen and cloned from a verified Git
   bundle for isolated rehearsal, but the V3 branch is still absent on origin. Publish/review the exact
   release before production service deployment; never copy a dirty working tree.
5. **Final recovery gate:** the initial online recovery unit and isolated restore pass, but no new-ECS
   snapshot, final source write drain/delta backup, rollback smoke, or cutover snapshot exists.
6. **Credential hygiene:** rotate previously exposed server passwords after a separate approved
   maintenance window. Do not disable public-key access until replacement credentials are verified.

## First safe next actions

1. Owner verifies the new ECS Security Group and explicitly approves/creates a rollback snapshot
   before runtime installation. Record only snapshot ID/time/status and non-secret network facts.
2. Install a project-isolated Python >=3.11 runtime and pinned RAG dependencies without replacing the
   system Python or changing SRSZQ. Record package hashes/versions and recheck nginx/PM2 afterward.
3. Rehearse the reviewed 10 -> 21 RAG migration twice only on a fresh copy under the cloned release's
   ignored `work/`; never point migration or tests at either live source path or the pristine restore.
4. Re-verify old-row fingerprints/counts, 1..21 continuity, 019/020/021 objects, integrity/FK and all
   V3 invariants. Preserve only content-free evidence.
5. Establish a coexistence plan for destination nginx/PM2 `srszq-api`. Preserve its files, process
   definitions, domains, ports, and rollback path; do not overwrite it with CourseMate config.
6. Publish or otherwise freeze the exact reviewed V3 release SHA before deployment.
7. Prepare a final maintenance/drain + delta backup plan after the initial restore rehearsal passes;
   do not perform the final drain until its availability window and rollback conditions are approved.
8. Keep DNS unchanged until the restored release passes private/local smoke tests, authentication,
   data invariants, monitoring, and rollback rehearsal.

## Safety record for this run

- No production database, upload, repository, environment file, systemd service, proxy, firewall,
  package set, provider configuration, or DNS record was modified.
- The 2026-09-13 18:02 CST Phase A1 slice performed DNS and pinned-IP HTTPS/TLS/OpenAPI reads only.
  The local Alibaba CLI remains unavailable.
- Owner-console evidence and strict known_hosts verification established current-host identity. The
  dedicated `coursemate-prod-current` alias and key were created, loaded and accepted in BatchMode.
- Current/old runtime, proxy, release, safe environment names/allowlisted values, aggregate database
  health/counts and upload digests were read without exposing secrets, rows or private filenames.
- Before source selection, the only remote writes were the explicitly requested SSH public-key append
  operations. Each original `authorized_keys` file received a timestamped backup first.
- After Result B, migration writes were confined to dedicated source backup/tool directories and
  `/srv/coursemate-migration` on the destination. A corrected initial backup was copied and restored
  there; `/srv/coursemate`, `/etc/coursemate`, systemd, nginx, PM2 and all SRSZQ paths were untouched.
- A final read-only destination runtime scan found no ready Python >=3.11 or initialized container
  alternative. Nginx remained active, both SRSZQ PM2 applications remained online, and listeners on
  ports 80/8080/8081 remained unchanged after the checks.
- No Schema migration, package installation, model call, service reload/restart, running deployment,
  DNS change or cutover has run. Source RAG/Agent/Caddy and destination nginx/PM2 remained active;
  source health stayed HTTP 200 and destination ports 80/8080/8081 were unchanged.
- Secret values and private keys were never printed, copied to the repository, or placed in command
  arguments. Owner passphrase entry occurred only in a local interactive PowerShell prompt.
