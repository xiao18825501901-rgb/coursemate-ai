# CourseMate V3 — New Alibaba ECS Migration State

Last updated: 2026-09-13 03:41 CST / 2026-09-12 19:41 UTC

Current phase: `SSH access ready; read-only inventory complete; data migration paused`

Production data copied: `NO`

Production writes changed: `NO`

DNS changed: `NO`

Rollback-ready application backup: `NO`

This is the non-secret migration control record. It separates live evidence, repository facts,
Owner-designated roles, and unresolved production authority. It must never contain credentials,
private key material, private course content, database rows, upload names, prompt bodies, or raw
provider responses.

## Executive gate

Both requested Windows SSH aliases now pass strict, public-key-only BatchMode authentication:

```text
coursemate-prod-old -> root@8.210.58.22     READY
coursemate-prod-new -> root@47.114.34.175   READY
```

This closes the SSH access gate and permits read-only migration preparation. It does **not** yet
authorize or make production data transfer safe: the current public backend still resolves to
`47.237.179.69`, not the Owner-designated old server `8.210.58.22`. Source authority must be
reconciled before any backup is treated as the production recovery unit.

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

Password included in scripts/files: NO
Private key exposed: NO
Ready for read-only migration preparation: YES
Ready for production data transfer/cutover: NO — SOURCE AUTHORITY UNRESOLVED
```

### Local SSH state and rollback

- The four dedicated CourseMate key files were already in `C:\Users\Hp\.ssh` when this run began.
  Their private/public fingerprints match. The mistaken `C:\Users\Hp.ssh` directory no longer
  exists, so no duplicate private-key deletion was required.
- Windows `ssh-agent` is `Running` with startup type `Automatic`. Both dedicated identities were
  loaded for the acceptance test. Re-run BatchMode validation after a Windows reboot or agent reset.
- The final two alias blocks specify the exact host, `root`, port 22, the dedicated identity,
  `IdentitiesOnly yes`, `PreferredAuthentications publickey`, and `BatchMode yes`.
- Both private key ACLs are limited to the current user, `SYSTEM`, and local Administrators; no
  `Everyone` or ordinary `Users` grant was observed.
- Before appending each dedicated public key, the existing remote `authorized_keys` was backed up as
  `/root/.ssh/authorized_keys.pre-coursemate-20260912T193152Z`. Both remote files remain mode 600
  under root-owned mode-700 `.ssh` directories.
- Rollback of the key append is possible through the corresponding backup, but only while retaining
  another verified management path. No rollback was needed.
- `PASSWORD ROTATION REQUIRED`: the Owner reported that server passwords had appeared in an external
  chat context. Rotation is recommended after access stabilization, but no password was requested,
  collected, changed, logged, or stored in this run.

## Production reality reconciliation

### Current public runtime evidence

As rechecked after the alias repair, two independent public resolvers agree:

```text
rag.qqttai.com   A 47.237.179.69
agent.qqttai.com A 47.237.179.69
```

Both public health endpoints return HTTP 200. The public RAG OpenAPI currently has 18 paths and
SHA-256:

```text
3c7c74ef0b98c114403c46f798d10720198a4452860e226df1530ae7a2b30572
```

The previously observed SSH endpoint at `47.237.179.69:22` has ED25519 host-key fingerprint
`SHA256:xrg8yao3PqVrTPP5Qx0st1pxeHt4jVR13L7CY38D8iw`, but that remains TOFU-only evidence and no
trusted login identity is available. Its release, systemd configuration, databases, uploads,
environment files, provider, and cloud region therefore remain:

```text
UNKNOWN — REQUIRES MANUAL VERIFICATION OR TRUSTED SSH ACCESS
```

### Owner-designated old server evidence

The repaired `coursemate-prod-old` alias authenticates to `8.210.58.22`. Its local RAG OpenAPI has
only 6 paths and a different SHA-256:

```text
767cc1c7a37a7ae6b7edc8cda76fed06d98e1de7e9d91369fc8800a8acec5a06
```

This proves that `8.210.58.22` and the current DNS backend do not expose the same RAG release. The
Owner may intentionally designate `8.210.58.22` as the migration source, but that role is a product/
operations decision; it is not established by current public-runtime evidence.

## Local release candidate

```text
Repository root:
C:\Users\Hp\Documents\Codex\2026-08-11\files-mentioned-by-the-user-coursemate\outputs\coursemate-ai

Branch: feature/coursemate-v3-persistent-learning
Baseline HEAD before this state update: 07f3876c46bff0be9e28405dd703be71d18dead3
Baseline subject: docs(ops): record new ECS migration discovery state
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
SSH access: COMPLETE for Owner-designated old/new aliases
Discovery: COMPLETE for 8.210.58.22 and 47.114.34.175
Public-production source authority: BLOCKED / UNRESOLVED
Preparation: NOT STARTED
Initial sync: NOT STARTED
Consistent backup: NOT STARTED
Isolated restore: NOT STARTED
Schema migration: NOT STARTED
Pre-cutover: NOT STARTED
Cutover: NOT STARTED — OWNER GATE
Post-cutover: NOT STARTED
Observation: NOT STARTED
Completed: NO
```

## Current blockers and risks

1. **Source authority mismatch:** public DNS and health traffic use `47.237.179.69`, while the
   Owner-designated old/source alias is `8.210.58.22`; their RAG OpenAPI artifacts differ. Migrating
   the latter without an explicit authority decision can omit current production data.
2. **Current DNS backend access:** the trusted SSH user/key and out-of-band-verified host fingerprint
   for `47.237.179.69` remain unavailable.
3. **Destination service collision:** new ECS ports 80, 8080, and 8081 already support `srszq-api`.
   Replacing nginx or stopping PM2 could break an unrelated live service.
4. **Destination hardening:** the machine requires a reboot, UFW is inactive, Caddy and SQLite CLI
   are absent, and the Alibaba Security Group is unverified.
5. **Release immutability:** the reviewed V3 branch is still absent on origin. Do not deploy by
   copying an old working tree or by an unfrozen branch name.
6. **Recovery gate:** no source-authoritative coordinated RAG DB + Agent DB + uploads backup,
   off-host copy, ECS snapshot, isolated restore, write-drain plan, or rollback smoke proof exists.
7. **Credential hygiene:** rotate previously exposed server passwords after a separate approved
   maintenance window. Do not disable public-key access until replacement credentials are verified.

## First safe next actions

1. Owner must decide, with operational evidence, whether the migration source is intentionally
   `8.210.58.22` despite public DNS, or provide trusted SSH/console access to `47.237.179.69`. Do not
   create a production backup from the wrong host.
2. In Alibaba Cloud, verify the new ECS Security Group and take a rollback snapshot before any
   package installation, reboot, proxy change, or application write.
3. Establish a coexistence plan for destination nginx/PM2 `srszq-api`. Preserve its files, process
   definitions, domains, ports, and rollback path; do not overwrite it with CourseMate config.
4. Publish or otherwise freeze the exact reviewed V3 release SHA before deployment.
5. Only after source authority is resolved: create a consistent two-database/uploads backup, copy it
   off-host, verify checksums, restore to an isolated destination path, and rehearse migrations 1-21.
6. Keep DNS unchanged until the restored release passes private/local smoke tests, authentication,
   data invariants, monitoring, and rollback rehearsal.

## Safety record for this run

- No production database, upload, repository, environment file, systemd service, proxy, firewall,
  package set, provider configuration, or DNS record was modified.
- The only remote writes were the explicitly requested SSH public-key append operations. Each
  original `authorized_keys` file received a timestamped backup first.
- No application backup/restore, schema migration, model call, restart, deployment, or cutover ran.
- Secret values and private keys were never printed, copied to the repository, or placed in command
  arguments. Owner passphrase entry occurred only in a local interactive PowerShell prompt.
