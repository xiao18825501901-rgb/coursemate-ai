# CourseMate V3 — Final Production Deployment Report

Report time: 2026-09-14 04:18 CST / 2026-09-13 20:18 UTC

Outcome: `HARD EXTERNAL BLOCKER — PRODUCTION CUTOVER ROLLED BACK BEFORE DNS CHANGE`

This is not a production-acceptance certificate. The final source drain, verified transfer,
Schema 10 to 21 migration, destination private activation and bounded live-model work were performed.
The public cutover was then stopped because Alibaba Cloud blocks the two CourseMate hostnames at the
Hangzhou public-IP boundary for non-compliant ICP filing. The source was restored before any DNS or
Netlify production change.

## Release identity

```text
Repository branch: feature/coursemate-v3-persistent-learning
Destination application SHA: cd8c1218b56f04c3947abda33cf1b2638bafbf16
Original fully validated V3 SHA: 9806a553a30c0531f727ba1538543fe6225e4c44
Destination current: /srv/coursemate/current -> /srv/coursemate/releases/cd8c121
Destination: 47.114.34.175 / iZbp1f0vqhds2341pdqqiyZ / cn-hangzhou-k
Authoritative source: 47.237.179.69 / iZt4n0k005125h6vlxoiloZ
Legacy renewal egress: 8.210.58.22
Documentation SHA: commit containing this report; see the final handoff or git log
```

The only application change after `9806a55` is the bounded, configurable V3 Provider timeout and
its regression test. Web and Agent source/dependency inputs are unchanged between those releases.

## Acceptance classification

### SOURCE IMPLEMENTED

- V3 learning orchestration, Teaching/Problem workflows, LearningBridge, persistence, assessment,
  official/private trees and private-resource authorization remain implemented.
- Generation is pinned to `qwen3.8-max` at the exact Singapore workspace endpoint; embedding remains
  independently pinned to `text-embedding-v4`.
- V3 Provider timeout is now configurable as `V3_MODEL_TIMEOUT_SECONDS`, defaults to 180 seconds,
  is constrained to 30–600 seconds and retains zero SDK retries.
- Migrations 1–21, backup/restore, content-free evidence, monitoring and rollback tooling remain in
  source.

### LOCAL VERIFIED

- Current RAG code: 329 tests passed; no failures.
- Provider-focused affected tests: 20 passed.
- Ruff: passed.
- mypy: passed for the RAG application and new provider regression test.
- The new regression test first failed against the hard-coded 90-second timeout and passed after the
  configurable timeout implementation.
- Historical exact-release gates still apply to unchanged surfaces: Web 49/49, Agent 66/66,
  typechecks and production builds passed for `9806a55`.

### DESTINATION PRIVATE VERIFIED

- The final drained recovery unit was transferred and checksum-verified.
- A pristine isolated restore passed before migration.
- RAG migration 10 to 21 passed with contiguous versions, unchanged legacy row fingerprints,
  integrity `ok`, zero foreign-key violations and V3 invariant checks.
- Agent remains Schema 1 with integrity `ok` and zero foreign-key violations.
- Final upload restore contains 67 files / 124,209,790 bytes with normalized digest
  `c5fb27c39fd06ff48972d3df1bb495345adfffffb4324b7d4dc579ad454c0a2d`.
- Destination RAG and Agent are active on loopback 28000/28001, but remain systemd-disabled and are
  not authoritative.
- Local trusted-SNI HTTPS health is 200/200; protected unauthenticated routes are 401/401.
- `V3_ENABLED=true`, model, endpoint, embedding split, data paths and the 180-second timeout all
  load through the real production Settings class.
- Content-free safe-stop evidence:
  `/srv/coursemate/cutover/20260913T193257Z/destination-safe-stop-after-icp-block.json`,
  SHA-256 `8e1508c960e6589535c851465eefc5ef941a3af97ac707759e9d64ba0bc1e4b9`.

### REAL PROVIDER VERIFIED

Verified facts:

- the replacement root-only key reaches the exact Singapore workspace;
- `qwen3.8-max` is visible on the authenticated model surface;
- real Responses requests receive `qwen3.8-max` response IDs and token usage;
- two Planner structured outputs passed SDK completion and Pydantic schema validation;
- zero automatic retries were used.

The full Teaching/Problem/image canary is **not accepted**:

| Attempt | Bound | Result | Recorded cost estimate |
|---|---|---|---:|
| 1 | 3 calls, 1,200 output tokens/call | Planner reached 1,200 tokens; `MODEL_INCOMPLETE` | CNY 0.08917980 |
| 2 | 3 calls, 4,000 output tokens/call, 90 s timeout | Planner completed; Teacher had unknown outcome at 90 s | CNY 0.16768869 plus unknown timed-out-call billing |
| 3 | 3 calls, 4,000 output tokens/call, 180 s timeout | Planner completed; Teacher reached 4,000 tokens; `MODEL_INCOMPLETE` | CNY 0.42891786 |

Visible usage-based estimates total CNY 0.68578635. The timed-out request may still be billable, so
this is not asserted as the Alibaba invoice total. The sum of all three conservative preflight
ceilings is CNY 3.21700695, below the Owner-authorized CNY 5.00 ceiling.

Preserved evidence:

```text
Attempt 1 checkpoint SHA-256:
36c98c836c7a47a0823e8a5beaf60516aef19d6b080dd322cc1b13d7775c7809

Attempt 2 checkpoint SHA-256:
9fbf59f6a559cf74cd4f2ced2706869fcd24e35ee964786e6d455cb9bb8cf737

Attempt 3 checkpoint SHA-256:
98e156f97429e99f0ed89c533285a0ea02f2bbf9e104c8cb5912dd85e98e9bf1
```

Alibaba documents that `max_output_tokens` for Qwen3.8 includes both answer and reasoning tokens,
and recommends an explicit Responses `reasoning.effort` policy. Before another paid run, the project
must deliberately choose a bounded reasoning/output policy, test it locally and run one new
non-overwriting preflight. Do not reuse or resume these failed checkpoints.

### PRODUCTION VERIFIED

Only the following public-production facts are verified:

- `https://qqttai.com` returns HTTP 200 from unchanged Netlify production deploy
  `6a83d079cd1da1000859b96c`.
- `rag.qqttai.com` and `agent.qqttai.com` still resolve to `47.237.179.69`.
- Source `coursemate-rag`, `coursemate-agent` and Caddy are active.
- Public source RAG and Agent health are HTTP 200 with trusted TLS.
- Source recovery-state fingerprints, Agent counts and upload digest matched the final drained state
  at the safe-stop collection time.
- No Cloudflare A record or Netlify production deploy was changed.

This is safe restored V2 production, not V3 production acceptance.

### NOT VERIFIED

- public reachability of CourseMate hostnames on the Hangzhou destination;
- destination authenticated Clerk flow;
- production authorization, admin boundaries and two-user private-resource isolation;
- complete Teaching, Problem, structured, image, streaming and tool-call live acceptance;
- Netlify V3 production promotion;
- Cloudflare backend DNS cutover and convergence;
- public V3 persistence/citation/browser smoke;
- production monitor activation;
- destination post-cutover backup;
- post-cutover observation window.

## Final data and migration evidence

```text
Final drain operation: 20260913T193257Z
Source backup:
/home/admin/coursemate-migration-backups/coursemate-v2-20260913T193302.545460Z
Source isolated restore:
/home/admin/coursemate-migration-restores/final-20260913T193257Z
Destination backup:
/srv/coursemate/backups/coursemate-v2-20260913T193302.545460Z
Destination pristine restore:
/srv/coursemate/restores/final-20260913T193257Z
RAG schema: 10 -> 21
Agent schema: 1
Courses / documents / chunks: 2 / 66 / 1,936
Ingestion jobs: 69
Conversations / messages: 39 / 86
Agent tasks: 1
Uploads: 67 / 124,209,790 bytes
Upload digest:
c5fb27c39fd06ff48972d3df1bb495345adfffffb4324b7d4dc579ad454c0a2d
```

After rollback, a fresh active-source snapshot compared equal to the drained source for legacy RAG
fingerprints, Agent counts, upload count/bytes/digest and database integrity/FK checks. Because the
source is serving writes again, a future cutover must nevertheless create a new final drained
recovery unit; equality at one collection time is not a permanent synchronization guarantee.

## Trusted TLS

```text
Lineage: /etc/letsencrypt/live/coursemate-backend
Issuer: Let's Encrypt YR2
SANs: rag.qqttai.com, agent.qqttai.com
Valid from: 2026-09-13 16:17:47 UTC
Expires: 2026-12-12 16:17:46 UTC
Chain verification: PASS
Private-key permissions: 0600 root:root
Renewal dry-run: PASS
Custom renewal timer: enabled and active
```

The Hangzhou host's Cloudflare API egress uses a destination-held SSH identity through the preserved
Hong Kong legacy host. That account allows only forwarding to `api.cloudflare.com:443`; it has no
shell and does not hold the Cloudflare token or TLS private key. Do not retire the legacy host until
replacement renewal egress is installed and dry-run verified.

## Hard external blocker

Direct requests to `47.114.34.175` with Host/SNI `rag.qqttai.com` or `agent.qqttai.com` do not
reach nginx:

```text
TCP 80: connection succeeds, then Alibaba edge returns HTTP 403
Server header: Beaver
HTML title: Non-compliance ICP Filing
TCP 443: reset during TLS handshake
Destination localhost trusted-SNI HTTPS: HTTP 200
nginx: active, listening on 0.0.0.0:80 and 0.0.0.0:443
UFW: inactive
Security Group: public TCP 80/443 allowed
```

This isolates the failure to Alibaba's mainland public-access boundary rather than nginx, the
certificate, systemd, host firewall or Security Group. Alibaba's official documentation states that
websites hosted on mainland-China servers require valid ICP filing and that an unfiled or
not-transferred domain can receive 403 responses or connection resets:

- <https://www.alibabacloud.com/help/en/dws/getting-started/the-whole-process-of-website-building/>
- <https://www.alibabacloud.com/help/en/slb/classic-load-balancer/support/faq-about-clb>

DNS cutover is prohibited until that external compliance gate is resolved.

## Current safe production state

```text
Public source: active and healthy at 47.237.179.69
Backend DNS: unchanged at 47.237.179.69
Netlify production: unchanged, deploy 6a83d079cd1da1000859b96c
Destination release: cd8c1218b56f04c3947abda33cf1b2638bafbf16
Destination data: restored final snapshot, Schema 21 / Schema 1
Destination RAG / Agent: active on loopback, disabled at boot, non-authoritative
Destination nginx: active; CourseMate vhost enabled; mainland edge blocks domain access
Destination monitor: inactive
Destination reboot: not performed
SRSZQ nginx master / backend / staging PIDs: 897 / 1182 / 48185
SRSZQ PM2 status: both online
```

## Rollback

- Source, its databases, uploads, release, Caddy and SSH remain preserved.
- Backend DNS and Netlify production never changed, so no DNS or frontend rollback was required.
- Source CourseMate services were restarted and public health returned 200/200.
- Final drained backup and source/destination isolated restores remain preserved.
- Destination previous release remains `/srv/coursemate/releases/9806a55`.
- Timeout env rollback is
  `/etc/coursemate/env-backups/20260913T201317Z-v3-timeout`.
- Pre-runtime ECS snapshot `s-bp13r5gqocjif1jtieav` remains available.
- No database, upload tree, source instance, legacy instance or rollback artifact was deleted.

## Exact minimal human action required

To keep using the current Hangzhou ECS, the Owner must complete a valid ICP filing for
`qqttai.com` and, when applicable, Alibaba Cloud access-filing transfer for this account/instance.
This requires the Owner's legal identity/entity documents and Alibaba Cloud console workflow and
cannot be automated from the scoped SSH, DNS and Netlify credentials.

If ICP filing is not desired, the alternative is to provision the destination in a non-mainland
region such as Hong Kong or Singapore, then repeat the final data migration and TLS/DNS acceptance
against that host. Do not attempt to evade the filing block with alternate ports, forged Host
headers, disabled TLS or an unreviewed proxy tunnel.

After the external gate is resolved:

1. prove pinned public HTTPS reaches the intended destination;
2. make an explicit bounded Qwen3.8 Responses reasoning/output policy and rerun local tests;
3. run one new paid canary within the remaining approved budget, with no automatic retry;
4. create a new final drain because the source resumed serving writes;
5. re-transfer, restore, migrate and compare content-free state;
6. complete authenticated/private-isolation acceptance;
7. promote Netlify V3, update both Cloudflare A records and verify convergence;
8. activate monitoring, create/restore-test a post-cutover backup and observe;
9. keep the source as rollback until a separate decommission decision.
