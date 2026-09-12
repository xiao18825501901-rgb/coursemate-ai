# CourseMate V3 — New Alibaba ECS Migration State

Last updated: 2026-09-13 00:38 CST / 2026-09-12 16:38 UTC

Current phase: `Discovery`

Production data copied: `NO`

Production writes changed: `NO`

DNS changed: `NO`

Rollback ready: `NO`

This file is the non-secret migration control record. It distinguishes live evidence, repository
facts, Owner-reported destination facts, and unknowns. It must never contain credentials, private
course content, database rows, upload names, prompt bodies, or raw provider responses.

## Reality reconciliation

### Current public production endpoint evidence

The public backend DNS does **not** point at the only SSH alias currently available on the operator
machine.

```text
rag.qqttai.com   A 47.237.179.69  TTL 300 (1.1.1.1 and 8.8.8.8 agree)
agent.qqttai.com A 47.237.179.69  TTL 300 (1.1.1.1 and 8.8.8.8 agree)
qqttai.com       A 75.2.60.5 / 99.83.231.61; HTTP Server=Netlify
DNS authority    Cloudflare: walk.ns.cloudflare.com / nile.ns.cloudflare.com
```

Live probes on 2026-09-13 CST:

```text
https://rag.qqttai.com/health   HTTP 200, {status: ok, service: rag-api}
https://agent.qqttai.com/health HTTP 200, {status: ok, service: agent-api}
RAG public OpenAPI paths        18
RAG public OpenAPI SHA-256      3c7c74ef0b98c114403c46f798d10720198a4452860e226df1530ae7a2b30572
Reachable public ports          22, 80, 443
Ports 8000/8001                 not reachable from the operator machine
```

The SSH endpoint at `47.237.179.69:22` advertises
`OpenSSH_9.6p1 Ubuntu-3ubuntu13.19` and host-key fingerprint
`SHA256:xrg8yao3PqVrTPP5Qx0st1pxeHt4jVR13L7CY38D8iw`. The fingerprint was observed by an
authentication-disabled probe and is **TOFU evidence only** until checked in the Alibaba console or
another trusted channel. Existing local keys were rejected for `root`, `admin`, and `ubuntu`.

Because the DNS target cannot yet be authenticated over SSH, every host/runtime/database fact below
for the current public production server remains unknown unless it came from the public probes.

### Separate SSH-accessible legacy candidate

The existing local SSH alias `srszq-hk` resolves to a different host, `8.210.58.22`, with a different
SSH host key. It runs CourseMate services, but direct TLS/OpenAPI fingerprinting proves that it is
not the current DNS backend:

```text
candidate local/direct RAG OpenAPI SHA-256:
767cc1c7a37a7ae6b7edc8cda76fed06d98e1de7e9d91369fc8800a8acec5a06

current DNS RAG OpenAPI SHA-256:
3c7c74ef0b98c114403c46f798d10720198a4452860e226df1530ae7a2b30572

candidate paths: 6
current DNS paths: 18
```

Do not use the candidate's data as the authoritative production recovery unit unless the Owner
proves that it is an intended production member/source.

## Local release candidate

```text
Repository root:
C:\Users\Hp\Documents\Codex\2026-08-11\files-mentioned-by-the-user-coursemate\outputs\coursemate-ai

Branch: feature/coursemate-v3-persistent-learning
HEAD: c81c766d9c9aab66072c61394172e1b08aef70f3
HEAD subject: docs(v3): record stage 8 acceptance and handoff
Working tree: two preserved Owner untracked files; no tracked or staged changes before this file
Owner files: ACTUAL_IMPLEMENTED_CHANGES_AUDIT.md, curl
Origin main after read-only fetch: 73e7595dc8fc7179e4cd9693dd024e7a983792c2
V3 branch on origin: absent at discovery time
Schema source: migrations 1–21
```

The Stage 8 report records 327 Python, 49 Web, 66 Agent, 3 V3 Playwright, and 4 V2 Playwright tests
passing at the recorded code state. Those tests were not re-run during this discovery slice and are
not production evidence.

## SOURCE SERVER

### A. Current DNS production — authoritative target for discovery

```text
Host: UNKNOWN — SSH authentication required
Public IP: 47.237.179.69 — verified by two public resolvers
Private IP: UNKNOWN — REQUIRES SSH/METADATA VERIFICATION
Region: UNKNOWN — REQUIRES SSH/ALIBABA CONSOLE VERIFICATION
OS: SSH banner indicates an Ubuntu OpenSSH 9.6 package; full OS UNKNOWN
Current production SHA: UNKNOWN
RAG unit: UNKNOWN
Agent unit: UNKNOWN
Caddy: public responses show Via: Caddy; exact config/path UNKNOWN
RAG DB: UNKNOWN
Agent DB: UNKNOWN
Uploads: UNKNOWN
Environment files: UNKNOWN
Domains: rag.qqttai.com, agent.qqttai.com
Frontend: qqttai.com on Netlify
DNS provider: Cloudflare
Provider/model: UNKNOWN — public health/OpenAPI do not prove provider or model
V3 enabled: UNKNOWN
```

### B. SSH-accessible legacy candidate — not authoritative

```text
SSH alias: srszq-hk
Host: iZj6chenajfmlqwq8i5x9pZ
Public IP: 8.210.58.22
Private IP: 172.19.63.160
Region / zone: cn-hongkong / cn-hongkong-b (ECS metadata)
OS: Ubuntu 24.04.4 LTS
Kernel: 6.8.0-63-generic
Disk: 40G root, 6.2G used, 32G available (17%)
Memory: 1.6GiB total; 2.0GiB swap
Restart required: YES
Git directory: /home/admin/coursemate-ai
Git branch: main, clean, ahead of origin/main by one local commit
Git HEAD: ef7795b1e41aefbfdf9738e88a7eca053ea621db
RAG unit: coursemate-rag.service
Agent unit: coursemate-agent.service
Caddy unit/config: caddy.service / /etc/caddy/Caddyfile
RAG workdir: /home/admin/coursemate-ai/services/rag-api
Agent workdir: /home/admin/coursemate-ai
RAG env file: /etc/coursemate/rag.env
Agent env file: /etc/coursemate/agent.env
RAG DB: /srv/coursemate/rag/rag.sqlite3
Agent DB: /srv/coursemate/agent/agent.sqlite3
Uploads: /srv/coursemate/rag/uploads
RAG internal bind: 127.0.0.1:8000
Agent process bind: *:8001; external probes are blocked by firewall/security controls
Caddy routes: rag.qqttai.com -> 127.0.0.1:8000
              agent.qqttai.com -> 127.0.0.1:8001
              api.srszq.com -> 127.0.0.1:9080 (unrelated until proven otherwise)
UFW: active; inbound default deny; only 22/80/443 allowed for IPv4/IPv6
```

Candidate data health, aggregate-only discovery snapshot:

```text
RAG DB: 131072 bytes; WAL mode; integrity=ok; FK violations=0
RAG Schema: only migration 1 (conversation ownership and per-user limits)
RAG counts: courses=2, documents=1, chunks=0, ingestion_jobs=1,
            conversations=0, messages=0

Agent DB: 32768 bytes; WAL mode; integrity=ok; FK violations=0
Agent Schema: migration 1 (task ownership and per-user limits)
Agent counts: tasks=0, rate_limit_windows=0

Uploads: 1 file, 229 bytes, symlinks=0, special files=0
Manifest SHA-256: 672a2a76ea75d8ad7da3eaf569cf184757061a1e30d29f23286180ac0519e170
Manifest algorithm: sorted relative POSIX path|size|sha256lower rows,
                    LF joined without final LF, then SHA-256
```

Candidate configuration is OpenAI-compatible mode with `gpt-5.6-luna` for chat and
`text-embedding-3-small` for embeddings. Secrets are present in root-owned environment files and
were not read into this document. This provider fact applies only to the candidate; it is not a
claim about current public production.

The CourseMate units and Caddy are active/enabled with zero systemd restarts and zero warning-or-
higher journal lines in the sampled prior 24 hours. Local health probes returned HTTP 200. Caddy
configuration validation passed. Runtime versions are Python 3.12.3, Node 24.14.0, npm 11.9.0,
Caddy 2.11.4, SQLite 3.45.1, Git 2.43.0, and rsync 3.2.7.

## DESTINATION SERVER

The following values are Owner-reported input from the migration specification. No SSH alias,
authenticated shell, Alibaba control-plane connector, or console evidence for this destination is
available to the current task.

```text
Host: UNKNOWN — REQUIRES SSH ALIAS/PUBLIC IP
Public IP: UNKNOWN — DO NOT USE 172.20.170.40 AS PUBLIC
Private IP: 172.20.170.40 — OWNER-REPORTED, NOT INDEPENDENTLY VERIFIED
Region: UNKNOWN
Zone: UNKNOWN
VPC: UNKNOWN
Security Group: UNKNOWN
OS: Ubuntu 22.04.5 LTS — OWNER-REPORTED
Kernel: 5.15.0-187-generic x86_64 — OWNER-REPORTED
Disk: 39.01GB root, approximately 10% used — OWNER-REPORTED
Memory: approximately 13% used — OWNER-REPORTED
Restart required: YES — OWNER-REPORTED
Release SHA: NOT DEPLOYED / NOT VERIFIED
RAG DB: NOT TRANSFERRED
Agent DB: NOT TRANSFERRED
Uploads: NOT TRANSFERRED
```

## Migration State

```text
Discovery: IN PROGRESS / BLOCKED ON TWO SSH IDENTITIES
Preparation: NOT STARTED
Initial Sync: NOT STARTED
Restore: NOT STARTED
Migration: NOT STARTED
Pre-cutover: NOT STARTED
Cutover: NOT STARTED — OWNER GATE
Post-cutover: NOT STARTED
Observation: NOT STARTED
Completed: NO
```

## Migration blockers

1. `47.237.179.69` is the current public backend target, but its trusted SSH user/key and console-
   verified host fingerprint are unavailable. Exact release, systemd, DB, uploads, environment,
   region and writer inventory cannot yet be established.
2. The destination's `NEW_SERVER_PUBLIC_IP`, SSH user/key, host fingerprint, region/zone/VPC and
   Security Group are unavailable. `172.20.170.40` is private-only evidence.
3. The Agent DB found on `8.210.58.22` cannot resolve the authoritative production Agent DB blocker,
   because that host is not the current DNS backend.
4. The reviewed V3 SHA `c81c766` is not present on `origin` at discovery time. Do not deploy a branch
   name or copy an old working tree; publish/freeze the exact reviewed SHA only after source discovery
   closes.
5. No current-production complete recovery unit, off-host copy, ECS disk snapshot, write-drain plan,
   or isolated restore evidence exists for this migration.
6. Current-production Clerk, model provider, V3 flags, Netlify deploy SHA, monitoring baseline and
   backup schedule remain unverified.

## First safe next action

Owner/manual login action is required before any server preparation or data movement:

1. Verify the SSH host fingerprint for `47.237.179.69` in Alibaba Cloud and configure a local alias
   such as `coursemate-prod-old` using the correct user and an existing private-key path. Do not paste
   a password or private key into chat.
2. Obtain the destination ECS public IP from the Alibaba console, verify its SSH host fingerprint,
   and configure a local alias such as `coursemate-prod-new`. Confirm that the authenticated host
   reports private IP `172.20.170.40`, Ubuntu 22.04.5, and the expected disk.
3. After both aliases pass `ssh -o BatchMode=yes <alias> true`, resume read-only inventory on the
   actual DNS production host and destination. Do not copy databases or change DNS yet.

Only after those facts close may the migration advance to destination update/reboot, exact-SHA
deployment, initial uploads dry-run, consistent two-database backup, isolated restore and migration
rehearsal.

## Safety note for this discovery slice

No service was stopped/restarted, no environment file was modified, no database or upload was copied,
no migration ran, no provider call ran, and no DNS/control-plane change was made. One health-capture
command briefly created and removed two uniquely named files under `/tmp` on the non-authoritative
`8.210.58.22` candidate; it did not touch application data. Later probes used streaming output only.
