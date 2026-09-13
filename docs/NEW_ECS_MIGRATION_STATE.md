# CourseMate V3 — New Alibaba ECS Migration State

Last updated: 2026-09-13 23:13:06 CST / 2026-09-13 15:13:06 UTC

Current phase: `SECURITY GROUP VERIFIED + PRIVATE TLS PATH PASS; PRODUCTION CERT/REBOOT/FINAL-DRAIN/LIVE-MODEL/DNS OWNER GATES REMAIN`

Production data copied: `YES — INITIAL ONLINE BACKUP ONLY; FINAL DELTA NOT STARTED`

Production writes changed: `NO`

DNS changed: `NO`

Rollback-ready application backup: `INITIAL RESTORE + LOCAL COPY VERIFIED; DESTINATION PRE-RUNTIME DISK SNAPSHOT RECORDED; FINAL CUTOVER SNAPSHOT NOT CREATED`

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
**Result B**. The initial backup/off-host copy/isolated restore, destination rollback snapshot,
isolated runtime installation, Schema 10 -> 21 rehearsal and destination source validation have
completed. The exact release/runtime, non-started service files, disabled monitor timer and a
non-enabled nginx candidate are now prepared; private V2/V3/proxy/monitor and synthetic-certificate TLS smoke
tests pass. The destination Security Group permits public 80/443, but no public CourseMate listener
or production certificate exists. Final drain, production activation/cutover, certificate issuance,
DNS, paid model calls, destructive actions and destination reboot remain gated. The full
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
Ready for isolated destination runtime/rehearsal: YES — COMPLETED
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
Validated application commit: 9806a553a30c0531f727ba1538543fe6225e4c44
Documentation HEAD before this state update: cebe9b4 (docs(ops): record isolated runtime validation)
Working tree at this state update: this tracked migration-state edit plus two preserved Owner untracked files; nothing staged
Owner files preserved: ACTUAL_IMPLEMENTED_CHANGES_AUDIT.md, curl
Origin main last observed: 73e7595dc8fc7179e4cd9693dd024e7a983792c2
V3 branch on origin: PUBLISHED — non-force push; exact application commit 9806a55 is reachable
Schema source: migrations 1-21
```

The Stage 8 report records 327 Python, 49 Web, 66 Agent, 3 V3 Playwright and 4 V2 Playwright tests at
its recorded code state. Exact commit `9806a55` was subsequently revalidated locally and on the
destination as recorded below. All such evidence remains local/fake-provider, not live-model or
production acceptance.

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
ECS instance ID: i-bp1f0vqhds2341pdqqiy
Host: iZbp1f0vqhds2341pdqqiyZ
Public IP: 47.114.34.175
Private IP: 172.20.170.40
Region / zone: cn-hangzhou / cn-hangzhou-k (ECS metadata)
OS: Ubuntu 22.04.5 LTS
Kernel: 5.15.0-187-generic
Root disk: d-bp1f0vqhds2341pces7h; system disk; ESSD PL0; 40 GiB; unencrypted
Filesystem after isolated runtime/dependency installation: 40G total, 5.4G used, 32G available (15%)
Memory: 3.4GiB total; no swap
Time zone / sync: Asia/Shanghai; NTP synchronized
Restart required: YES
```

### Tooling and application state

```text
git: 2.34.1
system python3: 3.10.12 (unchanged)
isolated rehearsal Python: 3.12.14 under /srv/coursemate-migration
final candidate Python: 3.12.14 at /srv/coursemate/runtime/cpython-3.12.14-linux-x86_64-gnu
isolated uv: 0.12.13 under /srv/coursemate-migration/tools
final candidate RAG venv: /srv/coursemate/runtime/rag (40 hash-locked distributions)
isolated test venv: /srv/coursemate-migration/venvs/test-105ccda-py312 (51 locked distributions)
node: 24.20.0
npm: 11.19.0
final candidate Node dependencies: lockfile-installed, build-verified and production-pruned under /srv/coursemate/releases/9806a55
rsync: 3.2.7
caddy: MISSING
sqlite3 CLI: MISSING

/srv/coursemate: PRESENT — independent candidate root, not serving production traffic
/srv/coursemate/current: symlink to releases/9806a55
/srv/coursemate/data: DIRECTORY SKELETON ONLY — 0 files; RAG/Agent DB absent
/srv/coursemate/backups: PRESENT — verified local copy of initial recovery unit
/etc/coursemate: PRESENT — root-owned, group-readable candidate env files
/home/admin/coursemate-ai: MISSING
/root/coursemate-ai: MISSING
/opt/coursemate: MISSING
CourseMate RAG/Agent units: INSTALLED/LOADED; inactive and disabled
CourseMate monitor service/timer: INSTALLED/LOADED; service static/inactive, timer disabled/inactive
CourseMate nginx site: INSTALLED in sites-available; not enabled; nginx not reloaded
Isolated initial RAG DB / Agent DB / uploads copy: PRESENT under /srv/coursemate-migration
Exact validated candidate release: /srv/coursemate/releases/9806a55
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

No Caddy installation, apt/system/global package replacement, firewall change, reboot, existing
service stop, or public proxy reload was performed. The isolated CourseMate identity, paths,
root-owned environment, systemd units and disabled nginx virtual hosts were prepared without touching
the enabled SRSZQ site. Owner-console evidence now shows all four inbound rules for the matching
Security Group: allow IPv4 TCP/80 and TCP/443 from `0.0.0.0/0` at priority 1, plus allow all ICMP-IPv4
and TCP/22 from `0.0.0.0/0` at priority 100. This proves the Security Group permits 443; the external
443 check still fails because the destination has no listener. No Security Group rule was changed.
The globally exposed SSH rule is a later hardening risk and must not be narrowed until the Owner's
stable management source and a tested fallback are known.

### Destination rollback snapshot and isolated runtime evidence

Before installation, Owner-console evidence recorded standard snapshot
`s-bp13r5gqocjif1jtieav` for the exact system disk `d-bp1f0vqhds2341pces7h`, with instant
availability enabled and the console rollback action present. The Owner then explicitly approved
isolated runtime installation. No snapshot delete, rollback, disk replacement or reboot was run.

The rehearsal runtime is confined to `/srv/coursemate-migration`; the final candidate runtime is
confined to `/srv/coursemate/runtime`. System Python remains 3.10.12 and no system-visible
`python3.12` shim remains. A shim created by `uv python install` was identified by its exact target and
moved recoverably to
`/srv/coursemate-migration/rollback/uv-python-shims-20260913T130418Z/python3.12`.

Content-free runtime evidence:

```text
uv binary SHA-256: b59310db262709ee92baf7954ef30820f1442ffa48b263f7001a236fe9004047
Python binary SHA-256: f7c6210eb40fadcd3c2889dddd24a15fc2c9f926aec5a03bf9da66e12d581526
production lock SHA-256: f77ad759770ef3c933826025d7f6fc4dcdd6eb5faa2de82d09ae116d112218ac
production freeze SHA-256: 4993b156fa204d7cc9ccceb4605c04d8f304bf7f703edc7bbf320782f6ecdf1f
test lock SHA-256: 060e8248afae89a66362aefa0fb1453ed6e2e40d743505d6cec7d25a331204ac
test freeze SHA-256: 0c85c2c48a69b90a7fa03f712ae7de8fe2d199024eae9c5a5517b712218e1f2a
Python dependency compatibility: PASS
```

The official npm registry repeatedly reset/timed out from this ECS. The stalled install left an
orphaned `npm ci` process after the SSH client was interrupted; its exact PID and migration-release
working directory were verified, TERM was attempted, and only that unresponsive process was then
killed. A clean reinstall used the same integrity-bearing `package-lock.json` through the fast
`registry.npmmirror.com` transport with lifecycle scripts disabled. The cache verified, `npm ls`
passed, and neither global npm state nor SRSZQ dependencies were changed. Cross-platform raw file
hashes differed only because Git checked out different line endings; the verified lockfile Git blob
is `d5db460680bde5542cdc80fead1e77e691dc0e6e5918d05f0c6dbc2722fca2af`.

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
Destination rollback snapshot: RECORDED — exact system disk, before runtime installation
Isolated runtime: COMPLETE — Python 3.12.14, locked production/test venvs and locked Node dependencies
Schema migration: REHEARSAL PASS — 10 -> 21 twice on fresh copies; live source/pristine restore untouched
Exact-release validation: PASS — Python, Web, Agent, typecheck and production build on 9806a55
Final candidate: PREPARED — exact release, independent runtime/user/paths, secret-safe env and non-started units/site
Private smoke: PASS — V2 compatibility, V3 migration/routes, auth/CORS, proxy and monitor; all transient services stopped
Release publication: COMPLETE — branch pushed non-force; 9806a55 reachable from origin branch history
Security Group inbound: VERIFIED — public TCP/80, TCP/443, TCP/22 and ICMP allowed from 0.0.0.0/0
Private TLS path: PASS — loopback-only synthetic certificate/SNI/proxy/security-header smoke; key removed
Production TLS readiness: BLOCKED — no trusted destination certificate or 443 listener; issuance method requires Owner decision
Reboot readiness: BLOCKED — SRSZQ staging is running but absent from the saved PM2 resurrection dump
Pre-cutover: COMPLETE FOR NON-ACTIVATING WORK — final data has 0 files and candidate remains inactive
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

Destination-local recovery copy:
/srv/coursemate/backups/coursemate-v2-20260913T121513.787049Z
```

The pack contains exactly six top-level files, has no SQLite sidecars, and all five manifest-covered
artifact checksums pass. Restored RAG/Agent database SHA-256 values exactly match the backup files;
both report integrity `ok` and FK 0. RAG remains migration 10 with 1,936 chunks, 66 documents,
39 conversations and 86 messages. Agent remains migration 1 with one task. Restored uploads are
67 files / 124,209,790 bytes with normalized manifest digest
`c5fb27c39fd06ff48972d3df1bb495345adfffffb432b7d4dc579ad454c0a2d`.

Tracked source at `105ccdaeec3b45c208a8e039d7943a5e22e277ce` was packaged as a complete Git
bundle, SHA-256 `93e00cd8e1230d45a3aeb6cbae72e817fc8985248082d7695c2d6c99b55315df`, then
cloned to `/srv/coursemate-migration/releases/105ccda` and checked out detached for the first
rehearsals. It remains preserved.

Clean-clone validation exposed two benchmark safety tests that accidentally depended on an ignored
local corpus database. Commit `9806a553a30c0531f727ba1538543fe6225e4c44` makes static provider URL
and conservative query-cost gates run before corpus/database access, and makes the two tests prove
that ordering with an explicitly missing database. Local evidence for the exact commit is 328 Python
tests passed, Ruff passed, mypy passed for 62 source files, Web 49/49, Agent 66/66, typecheck passed,
and the production build passed.

The exact corrected release was transferred as a complete Git bundle with SHA-256
`9c6437726341ff8008d859a93d96674b8e64a82ac1e546401e6ea4db4db10f34`, cloned detached to
`/srv/coursemate-migration/releases/9806a55`, and verified with zero tracked changes. This is an
isolated migration release, not a running deployment.

## Schema rehearsal and exact-release validation evidence

Two independent Schema 10 -> 21 rehearsals on fresh copies under release `105ccda` and one confirming
rehearsal under exact release `9806a55` all passed. Each calls database initialization twice to test
idempotency and produced the same content-free evidence digest:
`a9a7bb9b1751317be2ebae4fddb58bdb1470409875457e84275c18a7557f2a7f`.

```text
Migration versions: 1..21 contiguous
Pre-existing row fingerprints/counts unchanged: PASS
SQLite integrity: ok
Foreign-key violations: 0
documents / chunks: 66 / 1,936
conversations / messages: 39 / 86
document_versions: 66
unbound chunks: 0
grade-policy seed: 1
missing governance objects: 0
all checked V3 invariants: PASS
source restore hashes/sidecars changed: NO
```

On destination release `9806a55`, the full Python suite passed with 322 tests and 6 skips in 64.84s;
the six skips are only opt-in local real-corpus/golden tests and are not failures. Ruff and mypy
passed. After the isolated Node dependency race was corrected, destination typecheck passed, Web
passed 49/49, Agent passed 66/66, and both workspace production builds completed. `npm ls` passed and
its content-free evidence SHA-256 is
`09940af3ad1abe327405c0c8f419c523a89a2f3804db9d7a6f5a05de57a99ed0`.

All tests used fake/local providers and isolated data. No live model call, paid call, source write,
production service start, or production migration was part of this validation.

## Final candidate and private-smoke evidence

The destination now has an inactive, production-shaped candidate owned by the unprivileged
`coursemate` identity. The exact clean release is `/srv/coursemate/releases/9806a55`, selected by the
`/srv/coursemate/current` symlink. Its dedicated Python runtime and RAG virtual environment are below
`/srv/coursemate/runtime`; the Web/Agent dependencies were installed from the lockfile, the production
build passed and development dependencies were pruned. File ownership and traversal were verified by
executing the actual entry points as the service user, not merely by inspecting execute bits.

Secret-bearing RAG and Agent configuration was copied directly from the authoritative source over the
trusted server channel, transformed through an explicit safe-field policy, and installed as
`/etc/coursemate/rag.env` and `/etc/coursemate/agent.env` with mode 0640 and `root:coursemate`
ownership. Secret values were never printed. Compatibility remains on the currently verified
DashScope/OpenAI-compatible configuration; `V3_MODEL=qwen3.8-max` is only an inactive intent and
`V3_ENABLED=false` remains the initial activation policy.

The loaded RAG and Agent units are inactive/disabled; the monitor service is static/inactive and its
timer is inactive/disabled. The
CourseMate nginx file is present only in `sites-available`; it is not linked into `sites-enabled`, and
the live nginx process was not reloaded. Static systemd verification and both the live configuration
test and a candidate-union nginx test pass. The existing nginx master and SRSZQ production/staging PM2
PIDs remained 897, 1182 and 48185 respectively.

Private smoke used only disposable copies below `/srv/coursemate/smoke/9806a55`, transient systemd
units, localhost ports 28000/28001 and a separate localhost-only nginx on 29080. The evidence is:

```text
V2 flag-off: health PASS; protected routes 401 without token; synthetic bearer compatibility PASS
V2 data: Schema 1..10; base counts/integrity/FK/upload digest unchanged
V3 flag-on: copied RAG Schema 10 -> 21; health/routes/auth/authorization/non-leak checks PASS
V3 external calls: model evidence rows=0; reservations=0; no live or paid provider call
Proxy: rag/agent Host routing, streaming headers, auth and exact CORS origin PASS
Monitor: status=ok; RAG 12 ms; Agent 2 ms; backup age 8,327 s; free space 33,468,669,952 bytes
Cleanup: localhost ports 28000, 28001 and 29080 closed; all candidate units inactive
Smoke evidence SHA-256: bde19f160d7957f63abf64154e54180c7a8d9b077ce9a200107c9431a338f4ba
Final Python freeze SHA-256: 8ddb0b7c056f403b16a62b4da10561cb0e4de5e95edbb413d00606a3436b476e
Production npm tree SHA-256: 6ff9dc368decc31e070d41a2bf5646a520f72a1f258fc6aa3af885c7da0b963c
RAG unit SHA-256: 2e373d7ce68eef50dbe3cd51d6935c53f06cb956b5cc34ee9ad09907e78339a9
Agent unit SHA-256: d5c5242ab38acd772c9c1ab56219a7329073736064c23aa5ca4b053df8f1fce8
Monitor service SHA-256: df6626c0c5efdc100065ffa1e7a71ca37a3bce4edc1dcd1987a4e47201e4a7b9
Monitor timer SHA-256: a04ca234f57608a099b95b8354b5bc1289f3b9963ef0dd4e1d662cfd0c921a42
Nginx candidate SHA-256: 73cd11192649a5612cf9fa7a978b83f00f495fa97a0ffd73cf587fd34a65519e
```

A final read-only pre-activation check found the authoritative source still at RAG Schema 10 and
Agent Schema 1, with the same aggregate row counts, database integrity/FK results, upload count/bytes
and normalized upload digest as the initial recovery slice. Equal aggregates do not prove unchanged
row content and do not replace the required final drained snapshot/delta.

The candidate TLS path was then tested with a one-day synthetic certificate containing only the two
CourseMate SANs. A separate nginx bound only to `127.0.0.1:29443` and proxied to transient RAG/Agent
units. Both HTTPS health checks returned 200; both unauthenticated protected routes returned 401;
certificate verification, SNI hostname rejection, configured TLS 1.2/1.3 policy, HSTS, security
headers and exact CORS passed. Cleanup removed the temporary private key and closed
28000/28001/29443. Final data files remained 0, both model-run evidence and call-reservation counts
remained 0, live nginx PID remained 897, and SRSZQ PIDs remained 1182/48185.

```text
TLS smoke script SHA-256: 59497976d1b295f1afbeea3e359e33d78b0abeef9a4b519261d62a4e4c6a0edd
TLS nginx config SHA-256: a4991f0829965c64c7271b4616ac1008895c0fe035274b1e9780e801b438277f
TLS smoke evidence SHA-256: f1b0fd8e63c33b9a02768ad6f080a5cf01fc907cfbc3d982ddbb84db77429ffe
Synthetic private key after cleanup: ABSENT
```

The cleanup path was separately failure-injected immediately after the private nginx became ready.
The expected exit code was 97; independent post-failure checks found zero test listeners, no test key,
all persistent CourseMate units inactive, final data files still 0, live nginx PID still 897, and both
existing nginx/PM2 services active. The repaired script then passed the normal path above.

Production TLS is not ready: nginx supports TLS and Certbot/timer exist, but the destination has no
trusted certificate material and no public 443 listener. The current source uses separate valid Let's
Encrypt certificates for the two CourseMate hostnames through 2026-11-10 UTC. The destination Certbot
has no DNS plugin, so a zero-downtime certificate issuance or explicitly authorized secure certificate
bootstrap method must be selected before activation. The synthetic smoke certificate is not a
production credential and cannot be used for public traffic.

Public DNS checks found no CAA record at `qqttai.com` and no current TXT record at either
`_acme-challenge.rag.qqttai.com` or `_acme-challenge.agent.qqttai.com`. That removes an observed DNS
conflict for a manual DNS-01 bootstrap, but does not authorize creating records or requesting a
certificate.

The destination also reports a pending `libc6` reboot. Production SRSZQ is present in the saved PM2
resurrection dump, but running `srszq-staging` is not. The reboot therefore remains prohibited until
the Owner decides whether staging must survive and its recovery path is tested or approved.

## Current blockers and risks

1. **Production certificate gate:** the Security Group permits TCP/443 and the loopback TLS path
   passes, but the destination has no publicly trusted certificate or 443 listener. The Owner must
   choose the issuance/key path before public HTTPS activation.
2. **Destination coexistence:** ports 80, 8080 and 8081 support `srszq-api`. The prepared CourseMate
   ports and virtual hosts avoid collision, but enabling/reloading nginx or replacing/stopping PM2
   remains prohibited until the cutover gate.
3. **Reboot recovery:** `libc6` requires a reboot, while the running `srszq-staging` process is absent
   from `/root/.pm2/dump.pm2`. Do not reboot or run an indiscriminate `pm2 save`; the Owner must decide
   the intended staging persistence first.
4. **Final recovery gate:** the initial online recovery unit, destination-local copy and isolated
   restore pass, but no new-ECS
   application backup after activation, final source write drain/delta backup, rollback smoke, or
   cutover snapshot exists. The pre-runtime disk snapshot is not a substitute for the final data pack.
5. **Credential hygiene:** rotate previously exposed server passwords after a separate approved
   maintenance window. Do not disable public-key access until replacement credentials are verified.
6. **Live-provider acceptance:** all current V3 test evidence is local/fake-provider. A live
   `qwen3.8-max` capability check and benchmark remain unverified and potentially billable; do not run
   them without the applicable budget/credential gate.
7. **Public SSH exposure:** TCP/22 currently allows `0.0.0.0/0`. Narrowing it can improve security but
   can also lock out administration; do not change it until a stable Owner source range and fallback
   access path are verified.

## First safe next actions

1. Owner selects a zero-downtime production certificate method. The preferred path is a fresh
   Let's Encrypt DNS-01 bootstrap certificate; no existing private key is copied without explicit
   authorization.
2. Owner states whether `srszq-staging` must survive a reboot; then prepare and test only the approved
   persistence/recovery change before any maintenance reboot.
3. Agree an exact paid-call ceiling and credential scope for the `qwen3.8-max` capability probe and
   live benchmark. Until then the provider remains local/fake-only and V3 remains disabled.
4. Freeze the final write window, revalidate authoritative source aggregates, drain writes, create and
   verify the final standalone snapshot/delta, and copy it to the destination. This is an Owner gate.
5. Only after TLS, rollback, final data, private acceptance and monitoring pass: enable CourseMate
   units/site, execute pinned-IP HTTPS smoke, and request the separate DNS cutover approval.

## Safety record for this run

- No authoritative-source production database, upload, environment, service, proxy, firewall,
  provider configuration or DNS record was modified.
- The 2026-09-13 18:02 CST Phase A1 slice performed DNS and pinned-IP HTTPS/TLS/OpenAPI reads only.
  The local Alibaba CLI remains unavailable.
- Owner-console evidence and strict known_hosts verification established current-host identity. The
  dedicated `coursemate-prod-current` alias and key were created, loaded and accepted in BatchMode.
- Owner-console screenshots revalidated the destination as running instance
  `i-bp1f0vqhds2341pdqqiy` in `cn-hangzhou-k` with one attached 40 GiB ESSD PL0 system disk,
  `d-bp1f0vqhds2341pces7h`; later evidence recorded its pre-runtime snapshot
  `s-bp13r5gqocjif1jtieav`. A later Owner screenshot verified all four inbound allow rules: public
  IPv4 TCP/80, TCP/443, TCP/22 and all ICMP-IPv4. No rule was modified.
- Current/old runtime, proxy, release, safe environment names/allowlisted values, aggregate database
  health/counts and upload digests were read without exposing secrets, rows or private filenames.
- Before source selection, the only remote writes were the explicitly requested SSH public-key append
  operations. Each original `authorized_keys` file received a timestamped backup first.
- After Result B, source-side writes were confined to dedicated backup/tool directories. Destination
  writes were confined to `/srv/coursemate-migration`, the independent `/srv/coursemate` candidate,
  `/etc/coursemate`, four CourseMate systemd unit files and a disabled nginx `sites-available` file.
  No SRSZQ application, PM2 definition or enabled nginx site was modified.
- Following explicit Owner approval, isolated Python/uv/venv and release-local Node dependencies were
  installed under the migration and candidate roots. System Python and global npm were unchanged. A
  transient orphaned migration npm process was removed after exact PID/cwd verification; no SRSZQ
  process was signalled.
- Secret configuration moved server-to-server through protected files and an allowlisted transform;
  values were not printed. CourseMate systemd and nginx candidates were statically validated but not
  activated; RAG/Agent/timer remain disabled, monitor remains static, and nginx was not reloaded.
  Transient private smoke services were stopped and their localhost test ports were confirmed closed.
- A separate TLS smoke used a generated one-day synthetic certificate on loopback 29443. It verified
  HTTPS/SNI/auth/CORS/security headers, then stopped both transient apps and nginx, removed the private
  key and independently confirmed all listeners closed. It did not bind public 443 or reload nginx.
- Schema 10 -> 21 ran only on fresh copied databases. The pristine restore and authoritative source
  hashes remained unchanged. Destination tests, typecheck and builds passed for exact release
  `9806a55`.
- The V3 branch was published by non-force push; the two Owner untracked local files remain unstaged.
- No live-source Schema migration, live/paid model call, public CourseMate activation, nginx reload,
  DNS change, reboot or cutover has run. Source RAG/Agent/Caddy remain active with public health HTTP
  200; destination nginx and SRSZQ PM2 processes remain active with the same PIDs (1182 and 48185).
- Secret values and private keys were never printed, copied to the repository, or placed in command
  arguments. Owner passphrase entry occurred only in a local interactive PowerShell prompt.
