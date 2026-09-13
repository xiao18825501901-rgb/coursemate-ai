# CourseMate V3 — Final Production Deployment Report

Report time: 2026-09-14 05:11 CST / 2026-09-13 21:11 UTC

Outcome: `PRODUCTION ONLINE — ACCEPTANCE WITH LIMITATIONS`

CourseMate V3 is publicly online at <https://qqttai.com>. The production frontend is the V3
Netlify build, and both public backend names continue to terminate on the already-authoritative
Alibaba Cloud Singapore-region ECS, now running the V3 release. No ICP control was bypassed. The
Hangzhou ECS remains a non-authoritative recovery candidate and its mainland public-ingress block
does not sit in the active request path.

This report is not an unconditional production-acceptance certificate. Public availability,
deployment identity, data preservation, migration, unauthenticated security behavior, browser
rendering, backups and monitoring are verified. Authenticated multi-user isolation and the complete
paid Qwen Teaching/Problem/image canary remain explicitly not accepted.

## Production reality reconciliation

| Surface | Last verified production fact |
|---|---|
| Public application | `https://qqttai.com` returns HTTP 200 and renders the V3 protected learning route |
| Frontend | Netlify production deploy `6aa70f2b5a330d5a8ae4be56` |
| Backend DNS | `rag.qqttai.com` and `agent.qqttai.com` both resolve to `47.237.179.69` |
| Backend region | Alibaba Cloud ECS metadata reports `ap-southeast-1` |
| Backend release | `cd8c1218b56f04c3947abda33cf1b2638bafbf16` |
| Backend runtime | RAG and Agent active/enabled on loopback 8000/8001 behind unchanged Caddy |
| Database | RAG Schema 21; Agent Schema 1; integrity `ok`; zero FK violations |
| Model intent | `qwen3.8-max` generation through the exact Singapore workspace; independent `text-embedding-v4` embedding |
| Live model fact | Key/workspace/model visibility and structured Planner calls verified previously; full canary not accepted |
| Hangzhou ECS | `47.114.34.175`, non-authoritative, no CourseMate DNS points to it |

## Release identity

```text
Repository branch: feature/coursemate-v3-persistent-learning
Pre-deployment documentation HEAD: 9a1b5f0c250c50a41e2c19ef2e2e8fb3c8fa7df1
Application release SHA: cd8c1218b56f04c3947abda33cf1b2638bafbf16
Production release root: /home/admin/coursemate-v3-releases/cd8c121
Production host: 47.237.179.69 / iZt4n0k005125h6vlxoiloZ / ap-southeast-1
Frontend deploy: 6aa70f2b5a330d5a8ae4be56
Previous frontend rollback deploy: 6a83d079cd1da1000859b96c
Documentation commit: the commit containing this report; verify with git log
```

The release archive was built from the exact application commit. Its SHA-256 was
`37d46d20fa529a49dc8d803eac58136ca66b382451ffbee2d552c85777cca58a`.

## Deployment performed

1. Reconfirmed that `47.237.179.69` was the complete authoritative application/data source and that
   both backend DNS records still selected it.
2. Installed the exact V3 release in a versioned directory with an isolated Python environment and
   lockfile-controlled Node dependencies.
3. Transferred production configuration only through protected files. No secret value was printed,
   committed or written into this report.
4. Created a preflight backup, restored it to an isolated directory, migrated the copy from Schema
   10 to 21, and ran private health/authentication checks before touching live services.
5. Drained the existing services, created and isolated-restored a new final recovery unit, installed
   reversible systemd drop-ins, migrated the live database in place, and restarted the public
   services.
6. Enabled the V3 frontend flag in the Netlify production context, built from the repository, and
   published deploy `6aa70f2b5a330d5a8ae4be56`.
7. Normalized the server environment files to LF after detecting PowerShell-origin CRLF bytes,
   restarted both services, and repeated health/config checks.
8. Copied the final recovery unit to the Hangzhou ECS as an off-host backup and enabled a hardened
   five-minute readiness monitor on the active production host.

No backend DNS record had to change because the safe rollout upgraded the already-authoritative
non-mainland host. No database was dropped or rebuilt, and no user upload was read or deleted.

## Data and migration evidence

```text
Final cutover operation: 20260913T205218Z
Preflight backup:
  /home/admin/coursemate-v3-preflight-backups/coursemate-v2-20260913T204112.073088Z
Preflight isolated restore:
  /home/admin/coursemate-v3-restores/preflight-20260913T204112Z
Final backup:
  /home/admin/coursemate-v3-final-backups/coursemate-v2-20260913T205218.863043Z
Final isolated restore:
  /home/admin/coursemate-v3-restores/final-20260913T205218Z
Off-host copy:
  /srv/coursemate/backups/source-active-v3-cutover-20260913T205218Z
Environment rollback copy:
  /etc/coursemate/env-backups/source-v3-20260913T205218Z
LF-normalization rollback copy:
  /etc/coursemate/env-backups/normalize-lf-20260913T210601Z

RAG schema: 10 -> 21
Agent schema: 1 -> 1
Courses: 2
Documents: 66
Chunks: 1,936
Ingestion jobs: 69
Conversations: 39
Messages: 86
Agent tasks: 1
Uploads: 67 files / 124,209,790 bytes
RAG integrity / FK: ok / 0
Agent integrity / FK: ok / 0
```

Legacy-row fingerprints and the normalized upload manifest matched before and after migration. The
final source backup and its off-host copy passed checksum verification. No production row content,
private filename or upload body was printed during verification.

## Verification evidence

### Exact release tests on the production host

| Gate | Result |
|---|---|
| RAG pytest | 323 passed, 6 skipped because the read-only local corpus was not present; 329 discovered |
| Ruff | passed |
| mypy | no issues in 63 files |
| Web tests | 49 passed |
| Agent tests | 66 passed |
| Web/Agent typecheck | passed |
| Production dependency audit | 0 vulnerabilities |

The six RAG skips are environment/corpus-only. The same exact release line previously passed all
329 RAG tests in the complete local release workspace. Tests did not invoke the paid provider.

### Public production checks

| Check | Result |
|---|---|
| `https://qqttai.com/learn/cs3481` | HTTP 200 |
| `https://rag.qqttai.com/health` | HTTP 200 |
| `https://agent.qqttai.com/health` | HTTP 200 |
| Unauthenticated V3 workspace creation | HTTP 401 |
| Unauthenticated Agent tasks | HTTP 401 |
| Exact-origin RAG/Agent CORS preflight | HTTP 200 / 204 |
| Production OpenAPI V3 route subset | 40 learning/bridge/assessment/knowledge paths |
| RAG/Agent service restart count | 0 / 0 |
| Candidate ports 18000/18001 | closed |
| Service warnings since activation | none observed |

An isolated headless Chromium smoke of the production domain confirmed that `/learn/cs3481` is a
real V3 protected route rather than a 404, displays the expected sign-in boundary, produces no
console errors, request failures or 5xx responses, and has no mobile horizontal overflow.

Evidence screenshots:

- `work/source-v3-deploy-20260914T0438CST/production-v3-desktop.png`
- `work/source-v3-deploy-20260914T0438CST/production-v3-mobile.png`

### Monitoring

`coursemate-monitor.timer` is active, waiting and enabled. It runs every five minutes under the
unprivileged application account with systemd hardening. The latest observed checks reported:

```text
RAG: healthy
Agent: healthy
Latest final backup: fresh
Free disk: about 29.85 GB
Overall status: ok
```

## Controlled failure and recovery evidence

The first final-drain attempt at `20260913T205051Z` stopped before backup creation because the backup
root was owned by `root` with mode 0700 while the backup tool ran as `admin`. The rollback handler
restarted the unchanged V2 services. Public and local health returned 200/200; Schema remained 10,
the V3 drop-ins were absent, and no data/config migration had started.

The backup/restore roots were then assigned to the actual backup user and the cutover was rerun with
a single exit rollback trap. The successful operation at `20260913T205218Z` passed backup, isolated
restore, migration, activation and public smoke. This failed attempt caused no production data loss.

## Security state

- Clerk authentication remains mandatory for protected RAG and Agent routes.
- The browser-facing API origins remain restricted to `https://qqttai.com`.
- Production UI responses retain HSTS, MIME-sniff protection, frame denial, strict referrer policy,
  and camera/microphone/location denial.
- API services bind only to loopback; Caddy is the public TLS boundary.
- Environment files are root-owned and group-readable only where the service requires them.
- The final backup, private uploads and database are not web-served.
- No workaround proxy, alternate public port, forged Host header or TLS downgrade was introduced.

## Model acceptance status

The active settings load `V3_ENABLED=true`, `V3_MODEL=qwen3.8-max`, the exact Singapore workspace
endpoint, `text-embedding-v4`, a 180-second model timeout and zero SDK retries. A non-billable model
listing from the production host confirmed that `qwen3.8-max` is visible.

No paid request was made during this deployment. Earlier bounded live-provider work verified the
key/workspace/model and two structured Planner outputs, but the complete Teaching/Problem/image
canary is still **not accepted**: Teacher generation either timed out under the former 90-second
bound or exhausted the 4,000-token combined reasoning/answer cap. Visible prior estimates total CNY
0.68578635, plus potentially billable unknown usage from the timed-out request. A new paid run must
wait for an explicit bounded reasoning/output policy and a new cost authorization decision.

## Not yet verified

- A real Owner sign-in on the new production frontend.
- Production two-user private-resource isolation and administrator-boundary acceptance.
- Authenticated persistence across refresh/re-login for the complete Problem -> Step ->
  LearningBridge -> Teaching coverage -> return-to-Step journey.
- The complete real-model Teaching, Problem, structured, image, streaming and tool-call canary.
- A longer production observation window under normal user traffic.

These gaps do not negate current public availability, but they prevent the label `PRODUCTION
ACCEPTED`.

## Rollback boundary

Backend rollback remains recoverable without DNS change:

1. stop RAG and Agent;
2. remove or disable the V3 release drop-ins;
3. restore the protected environment copy from
   `/etc/coursemate/env-backups/source-v3-20260913T205218Z`;
4. restore both databases and uploads from
   `/home/admin/coursemate-v3-final-backups/coursemate-v2-20260913T205218.863043Z`;
5. reload systemd, start the previous V2 units, and repeat local/public integrity and health checks.

Frontend rollback is the prior known-good Netlify deploy `6a83d079cd1da1000859b96c`. Backend DNS
did not change, so rollback does not depend on DNS propagation. Do not execute rollback merely for a
cosmetic issue; capture state first and preserve any writes received after cutover.

## Final classification

```text
SOURCE IMPLEMENTED: PASS
LOCAL / FAKE-PROVIDER VERIFIED: PASS, with 6 production-host corpus-only skips
PRODUCTION DEPLOYED: PASS
PUBLIC UNAUTHENTICATED SMOKE: PASS
BACKUP / RESTORE / MIGRATION: PASS
MONITORING: ACTIVE
AUTHENTICATED PRODUCTION ACCEPTANCE: NOT VERIFIED
FULL LIVE MODEL CANARY: NOT ACCEPTED
OVERALL: PRODUCTION ONLINE — ACCEPTANCE WITH LIMITATIONS
```
