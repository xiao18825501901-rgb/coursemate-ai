# CourseMate V3 — Final Production Deployment Report

Report time: 2026-09-14 02:05 CST / 2026-09-13 18:05 UTC

Last resume verification: 2026-09-14 02:43 CST / 2026-09-13 18:43 UTC

Outcome: `HARD EXTERNAL BLOCKER — PRODUCTION CUTOVER NOT PERFORMED`

This report records the authorized unattended cutover attempt. It is deliberately not a success
certificate. The attempt completed every independent safe preparation available with the configured
accounts, then stopped because the authoritative source became unreachable and the installed
Singapore Model Studio key was rejected. No stale backup was promoted as current production.

## Release identity

```text
Repository branch: feature/coursemate-v3-persistent-learning
Validated application SHA: 9806a553a30c0531f727ba1538543fe6225e4c44
Repository HEAD before this report: c85a1e9821f9c2fa52ab15d623866b964c031f0f
Destination release: /srv/coursemate/releases/9806a55
Destination current symlink: /srv/coursemate/current -> validated release
Destination: 47.114.34.175 / iZbp1f0vqhds2341pdqqiyZ
Authoritative source: 47.237.179.69 / iZt4n0k005125h6vlxoiloZ
Legacy preserved host: 8.210.58.22
```

The Git commit containing this report is recorded in the final handoff response. A commit cannot
truthfully embed its own not-yet-created hash in its contents.

## Acceptance classification

### SOURCE IMPLEMENTED

- V3 Shared Learning Orchestrator, Teaching/Problem workflows, LearningBridge, persistence,
  assessment, knowledge-tree and private-resource controls are in the validated release.
- Production provider variables independently select `qwen3.8-max` generation while retaining
  `text-embedding-v4` for existing embeddings.
- Database migrations 1 through 21, backup/restore safety, bounded live canary, monitoring and
  rollback tooling exist in source.

### LOCAL VERIFIED

- Historical exact-release gates: Python 328 passed locally; destination exact-release Python 322
  passed with 6 opt-in corpus skips; Ruff, mypy, Web 49/49, Agent 66/66, typecheck and production
  builds passed.
- This attempt reran the affected focused gates: Python 27 passed; Agent configuration 20 passed;
  Web typecheck and 49 tests passed.
- Netlify production-flag build passed before the draft deploy.
- Production-env rewriter tests, nginx static guardrails, shell syntax and Python compilation passed.

### DESTINATION PRIVATE VERIFIED

- Initial recovery unit was previously checksum-verified, isolated-restored and migrated on copies
  from RAG Schema 10 to 21. Migration versions are contiguous; integrity is `ok`; FK violations are
  zero; old row fingerprints are preserved; V3 invariants pass.
- Private deterministic RAG/Agent/proxy/monitor smoke and private TLS smoke passed and cleaned up.
- Production-shaped env loads through the actual RAG and Agent configuration code. Safe values are:
  `qwen3.8-max`, exact Singapore workspace endpoint, `text-embedding-v4`, loopback ports 28000/28001,
  final data paths, production Clerk configuration present, and `V3_ENABLED=false`.
- The final HTTPS nginx candidate passes `nginx -t` but remains disabled and has never been reloaded.
- Trusted production certificate and automated renewal are verified as described below.

### REAL PROVIDER VERIFIED

- Historical Owner evidence reported a successful Windows canary against the exact Singapore
  workspace and `qwen3.8-max` (112 total tokens). That is historical provider evidence only.
- The required destination-backend canary is **not verified**. Both the exact workspace endpoint and
  shared Singapore endpoint returned `401 invalid_api_key` for the protected destination key.
- The canary had a maximum of three calls and zero retries. It stopped on the first Planner request,
  recorded zero input/output tokens and no provider response ID, and estimated CNY 0 cost.

### PRODUCTION VERIFIED

Only these production-surface facts are verified:

- `https://qqttai.com` still returns HTTP 200 from the unchanged Netlify production deploy.
- Cloudflare remains authoritative. Both backend A records remain DNS-only at `47.237.179.69` with
  automatic TTL. API read and DNS-01 writes are accepted by the scoped token.
- The destination certificate is publicly trusted and covers only the intended backend names.
- Destination nginx and both existing SRSZQ PM2 applications stayed active with unchanged process
  identities throughout the attempt.

This does not mean CourseMate V3 production is accepted. The currently routed backend address is
unreachable, while the new backend was intentionally not activated from stale data.

### NOT VERIFIED

- final source drain and consistent final recovery unit;
- final data transfer and live destination Schema 21 migration;
- destination production RAG/Agent/V3 activation;
- trusted pinned-IP authenticated application acceptance;
- successful destination `qwen3.8-max` Teaching/Problem structured canary;
- Netlify V3 production promotion;
- Cloudflare backend DNS cutover and convergence;
- public V2/V3 smoke, streaming, citations and persistence;
- production multi-user/private-resource isolation smoke;
- production monitor activation and destination post-cutover backup;
- post-cutover observation window.

## Trusted TLS and renewal

```text
Lineage: /etc/letsencrypt/live/coursemate-backend
Issuer: Let's Encrypt YR2
Subject: CN=rag.qqttai.com
SANs: agent.qqttai.com, rag.qqttai.com
Valid from: 2026-09-13 16:17:47 UTC
Expires: 2026-12-12 16:17:46 UTC
SHA-256 fingerprint: 38:C6:92:08:8E:1C:7A:9B:59:B3:C0:F2:E3:88:85:F2:04:D0:2A:10:BA:D7:BD:85:CB:0C:C6:50:3D:AD:80:ED
Chain verification: PASS
Private-key permissions: 0600 root:root
Renewal dry-run: PASS
Custom renewal timer: enabled and active
Default direct certbot timer: disabled
```

The Hangzhou destination cannot directly reach Cloudflare API. Renewal therefore uses a dedicated
destination-held SSH identity through the legacy Hong Kong host. The legacy account has no shell and
permits forwarding only to `api.cloudflare.com:443`; neither the Cloudflare token nor TLS private key
was copied there. This is a documented dependency: do not retire `8.210.58.22` until another renewal
egress is installed and a dry-run passes.

The CourseMate nginx site redirects HTTP to HTTPS, terminates this certificate and proxies only
`rag.qqttai.com` to 127.0.0.1:28000 and `agent.qqttai.com` to 127.0.0.1:28001. HSTS,
`nosniff`, frame denial, referrer and permissions headers are configured. The site is not enabled;
public port 443 is not listening on the destination.

## Data and migration evidence

The last verified initial online recovery unit remains:

```text
Source path: /home/admin/coursemate-migration-backups/initial-standalone-20260913T121500Z/
Destination backup: /srv/coursemate/backups/coursemate-v2-20260913T121513.787049Z
RAG source schema: 10
Agent schema: 1
Courses / documents / chunks: 2 / 66 / 1,936
Conversations / messages: 39 / 86
Agent tasks: 1
Uploads: 67 files / 124,209,790 bytes
Normalized upload digest: c5fb27c39fd06ff48972d3df1bb495345adfffffb432b7d4dc579ad454c0a2d
Isolated RAG migration: Schema 10 -> 21 PASS
Isolated migration evidence SHA-256: a9a7bb9b1751317be2ebae4fddb58bdb1470409875457e84275c18a7557f2a7f
```

These aggregates and hashes describe the initial recovery slice, not final current data. The
destination final data root deliberately contains zero files and one empty uploads-directory
skeleton. No live database migration was attempted.

## Netlify evidence

```text
Site: coursemate-ai-qqtt
Site ID: 166afb5a-4103-4236-9f13-4be34dc68cd2
Production domains: qqttai.com, www.qqttai.com
Unchanged production deploy: 6a83d079cd1da1000859b96c
V3 draft deploy: 6aa6dd8531deb2ee7072f3ec
Configured backend origins: https://rag.qqttai.com, https://agent.qqttai.com
V3 draft document status: 200
Desktop Chromium: rendered
Mobile Chromium: rendered; no horizontal overflow
Page exceptions / failed requests: 0 / 0
Production promotion: NOT PERFORMED
```

Clerk returned two expected 400 responses on each draft-page load because its production custom
domain does not authorize the Netlify deploy-preview origin. This prevents the draft from being
claimed as authenticated evidence. Production remains on the authorized `qqttai.com` origin.

## Provider and cost evidence

The official Singapore `qwen3.8-max` list price used for the preflight was CNY 14.988 per million
input tokens and CNY 44.965 per million output tokens. Source:
<https://help.aliyun.com/en/model-studio/qwen3-8-max>.

Regional API-key handling and the provider error classification were checked against Alibaba Cloud's
official API-key and error-code documentation:
<https://help.aliyun.com/en/model-studio/get-api-key> and
<https://help.aliyun.com/en/model-studio/error-code>.

```text
Provider: Alibaba Cloud Model Studio, OpenAI-compatible
Region: Singapore / ap-southeast-1
Model: qwen3.8-max
Endpoint category: workspace
Maximum provider calls: 3
Maximum output per call: 1,200 tokens
Authorized maximum: CNY 5.00
Conservative preflight ceiling: CNY 0.79255405
Calls reaching a model response: 0
Input / output tokens: 0 / 0
Actual estimated cost: CNY 0
Failure: HTTP 401, invalid_api_key
Automatic retry: 0
```

Preserved checkpoint:
`/srv/coursemate/model-evidence/.qwen38-production-canary.json.checkpoint.json`, SHA-256
`b9cb250633cd3763d37505d300e3c8292a2def40fe2b8a9aab4c1bd85765d68f`.

The key file is a root-only regular file, uses the current long `sk-ws` format, has no embedded
whitespace, and exactly matches the value loaded by the inactive application env. Neither key value
nor partial key is recorded here.

## Hard external blockers

### 1. Authoritative source is unreachable

`47.237.179.69` was healthy and trusted earlier in the migration. Before any final drain in this
attempt, it stopped answering TCP 22, 80 and 443. The same timeout was reproduced from:

- the Owner workstation;
- destination ECS `47.114.34.175` in Hangzhou;
- legacy ECS `8.210.58.22` in Hong Kong.

ICMP also had 100% loss. DNS still points the public backends to this address, and direct public
health requests time out. No Alibaba ECS control-plane credential is available in the execution
environment, so the host cannot be safely started or repaired through an authenticated API. A final
backup cannot be created from an unreachable source.

### 2. Installed Singapore API key is rejected

Network and TLS reachability to the exact workspace are good (`/models` without credentials returns
401 in about 0.2 seconds). With the protected key, both the workspace and shared Singapore APIs
return `401 invalid_api_key`. This rules out application env parsing, endpoint DNS and basic transport
as causes. The remaining external causes include revoked/disabled key, wrong Singapore account or
workspace assignment, or an IP/model access restriction in Model Studio.

### Resume verification after Owner-reported remediation

The Owner subsequently reported that the source had been restored and the Singapore key replaced.
The workflow restarted from both non-mutating gates rather than trusting the prior result or
advancing directly to production writes. The reported remediation was not visible at the required
runtime surfaces:

- strict SSH to `47.237.179.69` still timed out;
- TCP 22, 80 and 443 still timed out from the Owner workstation, destination ECS and legacy ECS;
- a second local check after a 30-second startup window still timed out on all three ports;
- `/etc/coursemate/secrets/qwen-singapore.key` was still a 117-byte root-owned mode-0600 file with
  modification time `2026-09-14 00:47:38 +0800`;
- the actual destination RAG configuration loaded that file, but both the exact workspace and shared
  Singapore `/models` probes still returned `401 invalid_api_key`.

No inference request, token use, source mutation, service activation, DNS update or Netlify
production promotion occurred during this resume verification. The two external blockers therefore
remain active; the cutover must not resume until the source is reachable and the non-billable key
probe passes from the destination.

## Completed work before the stop

- revalidated repository, destination release, inactive units, final-data emptiness and SRSZQ PIDs;
- installed only the Ubuntu Certbot Cloudflare plugin dependencies; no running service restarted;
- issued and verified the trusted two-name certificate;
- built, failure-tested and activated restricted automatic renewal;
- prepared and validated the disabled production HTTPS nginx site;
- atomically updated inactive provider env with automatic rollback on validation failure;
- preserved existing embedding configuration and validated both runtime loaders;
- captured Cloudflare pre-cutover DNS state without changing either A record;
- built and browser-tested a V3 Netlify draft without changing production;
- ran the bounded provider preflight and one zero-token, zero-retry authentication attempt;
- reran focused local regression tests;
- preserved all backups, source/legacy hosts, Owner files and rollback artifacts.

## Current safe production state

```text
Source mutation by this attempt: none
Source services stopped by this attempt: none
Backend DNS: unchanged at 47.237.179.69
Netlify production: unchanged
Destination final data files: 0
Destination RAG: inactive / disabled
Destination Agent: inactive / disabled
Destination monitor: inactive / disabled
Destination CourseMate nginx site: disabled
Destination public 443: absent
Destination V3 flag: false
Destination reboot: not performed
SRSZQ nginx / production / staging PIDs: 897 / 1182 / 48185
```

This state is safe from split-brain and stale-data promotion, but the public CourseMate backend is
not healthy because its unchanged authoritative source is externally unreachable.

## Rollback state

- Source, source databases and source uploads were not modified or deleted.
- Legacy host was not decommissioned.
- Initial recovery unit and isolated restore remain preserved.
- Destination pre-runtime ECS snapshot `s-bp13r5gqocjif1jtieav` remains the machine-level rollback.
- Provider env rollback is `/etc/coursemate/env-backups/20260913T174047Z`.
- Prior HTTP-only nginx candidate backups remain beside `/etc/nginx/sites-available/coursemate`.
- Backend DNS never changed, so no DNS rollback was required.
- Netlify production never changed, so no frontend rollback was required.

## Exact minimal human actions required

1. In Alibaba Cloud ECS Console, switch to the region/account containing public IP
   `47.237.179.69` and locate hostname `iZt4n0k005125h6vlxoiloZ`. Preserve its system disk. If the
   instance is stopped, **start it**; do not reinitialize, replace or reinstall it. If it is already
   running, use ECS diagnostics/VNC to restore its public network and inbound TCP 22/80/443. Confirm
   that the ED25519 host fingerprint is still
   `SHA256:xrg8yao3PqVrTPP5Qx0st1pxeHt4jVR13L7CY38D8iw` before accepting SSH again.
2. In Alibaba Cloud Model Studio, switch to **Singapore**, open API Key management for the business
   workspace whose API host is
   `ws-nfiuupw9zjickulc.ap-southeast-1.maas.aliyuncs.com`, and check the deployed key is enabled and
   assigned to that workspace/model. If it has an IP allowlist, include destination egress
   `47.114.34.175`. If the key is revoked or cannot be recovered, create/reset a pay-as-you-go
   Singapore `sk-ws` key. Install the full value directly into
   `/etc/coursemate/secrets/qwen-singapore.key` on the destination with owner `root:root` and mode
   `0600`; never send it through chat or commit it.

After those two actions, resume this same cutover workflow. No design choice is needed. The next
automation must first rerun source identity/health and the non-billable key probe, then execute:

```text
drain source writes
-> new final verified backup
-> transfer and isolated restore
-> live Schema 10 -> 21 migration
-> destination private start and pinned HTTPS acceptance
-> one new bounded qwen canary (do not reuse the failed checkpoint)
-> Netlify V3 production deploy
-> Cloudflare two-record cutover
-> public/auth/multi-user smoke
-> monitoring
-> post-cutover backup and restore verification
-> observation
```

Do not start from the initial backup merely to bypass the source outage, and do not rerun a billable
canary until the non-billable credential probe passes.
