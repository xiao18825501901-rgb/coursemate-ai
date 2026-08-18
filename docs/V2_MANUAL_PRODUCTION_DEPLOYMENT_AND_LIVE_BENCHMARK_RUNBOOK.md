# CourseMate AI V2 Manual Production Deployment and Live Benchmark Runbook

> 文档用途：项目 Owner 从 Local Release Candidate 推进到 Production Acceptance 的人工执行总手册<br>
> 生成日期：2026-08-14（Asia/Shanghai）<br>
> 适用分支：`feature/coursemate-v2-ai-tutor`<br>
> 当前结论：**SOURCE / LOCAL RELEASE READY；不是 PRODUCTION ACCEPTED**

这份手册面向实际持有 GitHub、Netlify、Clerk、云主机和模型 Provider 权限的项目 Owner，也可直接交给另一个 ChatGPT 逐步陪同执行。它独立于 [V2_PRODUCTION_DEPLOYMENT.md](V2_PRODUCTION_DEPLOYMENT.md)，但以当前源码、数据库初始化器、运维脚本和测试证据为准。

任何页面、主机、环境变量或模型状态，只要未由 Owner 在真实控制台或运行时核验，统一标记为：

> **UNKNOWN — REQUIRES MANUAL VERIFICATION**

不要把目标架构、Git 配置、旧交接说明或模型选择意图写成线上事实。不要把密钥、Bearer token、私有课程内容、完整环境文件或未脱敏日志发给 ChatGPT。

---

## 1. V2 Release Candidate

以下是生成本手册时可由本地仓库证明的快照；执行部署时必须重新运行第 4 节并记录新快照。

```text
V2 Release Candidate

Branch: feature/coursemate-v2-ai-tutor
Commit: 9951d5b58e993f4a41b0d5de72177fa62ea59ae1
Git status: DIRTY — two pre-existing untracked files: ACTUAL_IMPLEMENTED_CHANGES_AUDIT.md and curl
RAG tests: PASS — 194 passed; 2 non-failing warnings
Web tests: PASS — 29 passed across 6 files
Agent tests: PASS — 51 passed across 9 files
Playwright: PASS — Chrome 4/4
Migration version: RAG 1-10; Agent 1; verified only on local copies
Benchmark status: NOT PASS — live paid 50-case comparison not run
Production status: NOT PASS — live runtime/deployment/smoke not verified
```

The untracked files above are not part of the release commit. Do not delete or add them merely to obtain a clean status. For release work, use an immutable clean checkout of the approved commit.

---

# PRODUCTION REALITY RECONCILIATION

## 2.1 Last Verified Production State

No available tracked evidence proves the current live provider, live commit, backend platform, database version, service configuration, Netlify deploy, Clerk instance, domain routing, backup status, or smoke-test result.

The old handoff describes a GitHub → Render → Netlify deployment plan and explicitly says production OpenAI was **not verified**. The current production report says `qqttai.com` and documented API hosts were unreachable from the verification environment and no SSH/control-plane evidence was available. Therefore:

- Live frontend/deploy ID: **UNKNOWN — REQUIRES MANUAL VERIFICATION**
- Live backend platform (Alibaba ECS, Render, or other): **UNKNOWN — REQUIRES MANUAL VERIFICATION**
- Live backend commit: **UNKNOWN — REQUIRES MANUAL VERIFICATION**
- Live chat/Agent/embedding provider and model: **UNKNOWN — REQUIRES MANUAL VERIFICATION**
- Live RAG/Agent schema and data counts: **UNKNOWN — REQUIRES MANUAL VERIFICATION**
- Live health, backups, monitoring and alerts: **UNKNOWN — REQUIRES MANUAL VERIFICATION**

There is no defensible basis to label the last verified production state “OpenAI” or “Qwen.” OpenAI is a source default/legacy fallback; Qwen is a deployment-template intent. Neither is a verified live fact.

## 2.2 Current V2 Source Intent

Current source supports independent OpenAI-SDK-compatible endpoints:

- RAG chat: `RAG_CHAT_API_KEY`, `RAG_CHAT_BASE_URL`, `RAG_CHAT_MODEL`
- RAG embeddings: `RAG_EMBEDDING_API_KEY`, `RAG_EMBEDDING_BASE_URL`, `RAG_EMBEDDING_MODEL`
- Agent: `AGENT_MODEL_API_KEY`, `AGENT_MODEL_BASE_URL`, `AGENT_MODEL_NAME`
- Legacy fallback: corresponding `OPENAI_*` variables
- Provider modes: production-compatible mode is named `openai`; deterministic mode is test-only

The literal mode name `openai` means “use the OpenAI SDK/protocol path,” not “the vendor is definitely OpenAI.” Source defaults still name `gpt-5.6-luna` and `text-embedding-3-small`, but production must use explicit role-specific variables.

## 2.3 Current Deploy Template Intent

Tracked [render.yaml](../render.yaml) describes two **Render Starter** services with persistent 1 GB disks. It configures Alibaba Cloud Model Studio compatible endpoints in Singapore, `qwen3.7-plus` for RAG chat/Agent, and `text-embedding-v4` for embeddings. This proves only the Git template intent.

Tracked [netlify.toml](../netlify.toml) describes a Netlify React/Vite build and requires these UI-managed values:

- `VITE_CLERK_PUBLISHABLE_KEY`
- `VITE_RAG_API_URL`
- `VITE_AGENT_API_URL`

The V2 deployment document instead records a requested target topology of Netlify plus Alibaba Cloud Hong Kong, Caddy, systemd, SQLite and uploads. The repository contains no Dockerfile, Caddyfile, systemd unit, UFW provisioning or ECS deployment script. Do not overwrite a working live topology from `render.yaml`, and do not claim Alibaba ECS is live merely because it is the target architecture.

## 2.4 Unknown Current Runtime Facts

All of the following are **UNKNOWN — REQUIRES MANUAL VERIFICATION**:

1. Which GitHub commit and branch are deployed.
2. Whether `qqttai.com` is attached to the correct Netlify site and deploy.
3. Actual RAG and Agent public origins and TLS certificates.
4. Alibaba ECS region/instance/security group/public IP, or whether ECS is used at all.
5. systemd unit names, Unix user, working directories, ports and restart policy.
6. Caddy sites, reverse-proxy targets, request limits, access-log redaction and headers.
7. Live database/upload paths, schema versions, trigger count, row/file counts and disk free space.
8. Clerk production instance, issuer, keys, authorized frontend origin and administrator IDs.
9. Provider account, region, compatible base URL, enabled models, prices, quotas and billing balance.
10. Backup location, last successful backup/restore test, off-host copy and monitor/alert status.

## 2.5 Facts Owner Must Personally Verify

Only the Owner or an explicitly authorized operator may perform these actions:

- Sign in to billing/control planes; view or rotate secrets; approve real model spend.
- Confirm legal/data-region permission for sending benchmark/course content to a provider.
- Change DNS, Netlify production deploy, Clerk production keys, ECS security groups, Caddy or systemd.
- Stop production writers, run final backup, migrate live data, restore or roll back.
- Use real test accounts to verify authentication, two-user isolation, administration and publication.
- Decide benchmark winners and approve a production model switch.

---

## 3. Operator Rules, Evidence and Stop Conditions

### 3.1 Prepare an evidence directory

Create an encrypted/local folder outside the repository, for example:

```text
CourseMate-V2-Acceptance-YYYYMMDD-HHMM/
  00-approval/
  01-release-candidate/
  02-production-inventory/
  03-backup-restore/
  04-backend-deploy/
  05-netlify-clerk/
  06-production-smoke/
  07-live-benchmark/
  08-final-verdict/
```

For every step save: timestamp/timezone, operator, command or console path, exit code, redacted output, screenshot filename and verdict. Use screenshots only after hiding secrets and private content.

Send another ChatGPT only:

- commit SHA, deploy ID, service names, regions, public URLs;
- redacted environment-variable **names**, never values;
- health/status/schema/count summaries;
- backup manifest/checksum verification result, not databases/uploads;
- benchmark JSON and human scores after confirming they contain no private text;
- screenshots with keys, tokens, email addresses, user IDs and private content masked.

### 3.2 Hard stop conditions

Stop immediately and do not continue if any of these occurs:

- exact live topology, database paths or unit names cannot be determined;
- no verified restorable backup exists;
- `integrity_check` is not `ok`, `foreign_key_check` returns rows, counts unexpectedly change;
- a private course, conversation or task is visible to another user;
- a secret appears in Git, terminal capture, URL, benchmark output or ChatGPT message;
- provider price/region/model name is not confirmed from its current official console/docs;
- projected benchmark cost exceeds the signed cap;
- health is not 200/`status=ok`, migration versions are incomplete, or smoke tests fail;
- a critical/high dependency issue is found without an approved disposition.

### 3.3 Risk labels

| Label | Meaning |
|---|---|
| READ-ONLY | Inspects state; should not change production. |
| CHANGE | Alters code/config/runtime but is normally reversible. |
| DATA-RISK | Stops writers, migrates or restores persistent data. |
| BILLABLE | Creates real Provider charges. |
| OWNER-ONLY | Requires the Owner's credentials, approval or legal decision. |

---

## 4. Re-verify the Release Candidate

**Labels:** READ-ONLY. Run on the trusted Windows development machine from a fresh clean checkout.

### 4.1 Open GitHub and reconcile Git

1. Open GitHub → `xiao18825501901-rgb/coursemate-ai` → **Commits** and **Branches**.
2. Confirm the candidate SHA exists remotely. At document generation time, `origin/main` was only `e1ef57a`; the V2 branch had no verified upstream tracking record.
3. If the candidate is not remote, do not deploy from an unreviewed local directory. Review the diff, intentionally push the branch, open/merge the approved PR, then record the immutable SHA.

In PowerShell:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git status --short
git remote -v
git log -8 --oneline --decorate
```

Expected for this snapshot: branch and SHA from section 1; only the two documented untracked files. Save output to `01-release-candidate/git.txt`. Any different tracked modification requires review before proceeding.

### 4.2 Run the full local gate

Use the repository's existing RAG virtual environment and Node 24.14+ environment. Do not inherit real provider keys; use an inert clean shell. Commands below are read-only except for normal test/build artifacts and temporary test databases.

```powershell
$env:OPENAI_API_KEY = "test-only-inert"
$env:RAG_CHAT_API_KEY = "test-only-inert"
$env:RAG_EMBEDDING_API_KEY = "test-only-inert"
$env:AGENT_MODEL_API_KEY = "test-only-inert"
Set-Location services\rag-api
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check app tests ..\..\ops\backup_v2.py ..\..\ops\restore_v2.py ..\..\ops\monitor_v2.py ..\..\scripts\run_model_benchmark.py ..\..\scripts\run_embedding_benchmark.py
.\.venv\Scripts\mypy.exe app tests ..\..\ops\backup_v2.py ..\..\ops\restore_v2.py ..\..\ops\monitor_v2.py ..\..\scripts\run_model_benchmark.py ..\..\scripts\run_embedding_benchmark.py
Set-Location ..\..
npm test
npm run typecheck
npm run build
npm run test:e2e
npm audit --omit=dev
Remove-Item Env:OPENAI_API_KEY,Env:RAG_CHAT_API_KEY,Env:RAG_EMBEDDING_API_KEY,Env:AGENT_MODEL_API_KEY
```

Expected evidence baseline:

- pytest: 194 passed, only the two documented non-failing warnings;
- Web: 29 tests / 6 files; Agent: 51 tests / 9 files;
- Ruff, strict Mypy, TypeScript and both builds: exit 0;
- Playwright Chrome: 4/4;
- production dependency audit: 0 vulnerabilities.

The tracked Playwright config contains machine-specific Chrome, Node and Python paths. If the operator machine differs, do not silently skip E2E; update/override the runner deliberately and record the exact environment. A changed test count is not automatically a failure, but must be explained against the new commit.

### 4.3 Freeze the release identity

Record:

```text
RELEASE_SHA=<40-character reviewed commit>
PR=<GitHub PR URL or N/A with explanation>
LOCAL_GATE_TIME=<ISO-8601 with timezone>
LOCAL_GATE_RESULT=PASS/FAIL
```

Do not use a branch name as the production artifact identity; branches move.

---

## 5. Discover the Real Production Runtime Before Changing It

**Labels:** READ-ONLY, OWNER-ONLY.

### 5.1 Netlify inventory

Open Netlify → **Sites** → find the site serving `qqttai.com` → collect:

- site name and site ID;
- Production deploy ID, timestamp, Git repository, production branch and commit SHA;
- Domain management: primary domain, DNS status and TLS status;
- Build settings and current `VITE_*` variable **names**;
- latest successful and failed deploy logs, with values redacted.

Expected: one unambiguous site owns `qqttai.com`, TLS is valid, and the production deploy shows an exact Git SHA. Save screenshots and copy only non-secret metadata. If the site is absent or owned by an unknown team, stop.

### 5.2 Determine whether backend is Alibaba ECS, Render or something else

First inspect Netlify's current `VITE_RAG_API_URL` and `VITE_AGENT_API_URL` values in the protected UI. Record only their origins. Then inspect DNS:

```powershell
Resolve-DnsName qqttai.com
Resolve-DnsName <rag-host>
Resolve-DnsName <agent-host>
```

Do not infer the platform solely from an IP. Match the origins against Alibaba Cloud ECS/SLB, Render services, or the actual platform control plane.

#### If Alibaba Cloud is actually in use

Open Alibaba Cloud Console → **Elastic Compute Service (ECS)** → **Instances & Images** → **Instances** → select the confirmed region (the target document says Hong Kong, but verify it) → select the instance → **Workbench/Connect**.

Also open **Network & Security → Security Groups**. Read-only expectations:

- SSH/22 restricted to an approved operator source, not the whole Internet;
- HTTP/80 and HTTPS/443 public if Caddy terminates TLS;
- backend ports such as 8000/8001 are not publicly open;
- no unexpected database/admin port is public.

After SSH, run these read-only commands and save redacted output:

```bash
date --iso-8601=seconds
hostnamectl
uname -a
df -h
free -h
sudo systemctl list-units --type=service --all | grep -Ei 'coursemate|rag|agent|caddy'
sudo systemctl show <rag-unit> <agent-unit> -p Id -p ActiveState -p SubState -p User -p Group -p WorkingDirectory -p ExecStart
sudo systemctl status <rag-unit> <agent-unit> caddy --no-pager
sudo ss -ltnp
sudo ufw status verbose
sudo caddy validate --config <actual-caddy-config-path>
sudo caddy adapt --config <actual-caddy-config-path> --pretty
```

Discover paths from `systemctl show`; do not guess `/srv`, `/var/lib` or unit names. If an environment file is referenced, list keys without values:

```bash
sudo awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/{print $1}' <actual-rag-env-file> | sort
sudo awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/{print $1}' <actual-agent-env-file> | sort
```

For the running release, use the discovered working directory:

```bash
sudo -u <service-user> git -C <actual-working-directory> rev-parse HEAD
sudo -u <service-user> git -C <actual-working-directory> status --short
```

If it is not a Git checkout, identify the artifact/release manifest instead. Never print `/proc/<pid>/environ`, `systemctl show Environment`, or the full env file.

#### If Render is actually in use

Open Render → **Dashboard** → the two confirmed services → collect service ID, region, runtime, deploy commit, start command, health path, persistent-disk mount/size and environment-variable names. Confirm the two databases live on distinct persistent disks. A Render deploy from [render.yaml](../render.yaml) is a separate architecture choice; it is not a harmless substitute for an existing ECS deployment.

#### If another platform is in use

Stop and produce an inventory equivalent to the fields above. Have ChatGPT rewrite only the platform-specific deployment portion after seeing redacted evidence. Do not improvise migration commands.

### 5.3 Live health and baseline

With the real origins:

```bash
curl --fail --silent --show-error https://<rag-host>/health
curl --fail --silent --show-error https://<agent-host>/health
```

Expected exact JSON semantics:

```json
{"status":"ok","service":"rag-api"}
{"status":"ok","service":"agent-api"}
```

A missing migration/state returns HTTP 503 with `status=unavailable`. HTTP 200 proves readiness checks, not model quality or full production correctness.

Capture 10–20 health timings for a pre-deploy latency baseline, current error logs, ingestion failures, 429s, disk free space and latest completed backup age. Do not capture prompts/private content.

---

## 6. Verify Clerk and Provider Control Planes

### 6.1 Clerk production instance

**Labels:** READ-ONLY initially; OWNER-ONLY; CHANGE if keys/origins are changed.

Open Clerk Dashboard → select the CourseMate application → confirm the **Production** instance, not Development. Record:

- application/instance name and issuer/domain;
- publishable-key prefix only;
- that a production secret key and signing/JWT verification material exist;
- allowed frontend origin/redirect URLs include the exact production HTTPS origin;
- two ordinary test users and one approved admin test user exist;
- the `ADMIN_USER_IDS` runtime configuration matches the intended admin, without exposing IDs in evidence.

Never put `CLERK_SECRET_KEY` or `CLERK_JWT_KEY` in Netlify. Netlify receives only the publishable key. Both APIs require real Clerk credentials in production and must fail startup if they are absent.

### 6.2 Provider account and secret rotation

**Labels:** OWNER-ONLY, CHANGE, potentially BILLABLE.

For each candidate/provider, open its official model console and billing page. Before any call, save redacted evidence of:

- account/project and exact region;
- compatible endpoint hostname and path;
- exact chat/Agent/embedding model aliases currently enabled;
- current input/output/cached price and currency;
- quota, rate limit, prepaid balance/billing status and budget alert;
- data retention/training/region terms approved for this corpus;
- key creation time and restricted scope if supported.

Current official links are listed in [MODEL_BENCHMARK_2026.md](MODEL_BENCHMARK_2026.md). Prices and aliases are time-sensitive: the document's old figures are not authorization to spend.

For Alibaba specifically, open Alibaba Cloud Console → **Model Studio / 百炼**. In the current localized UI, locate **API Key Management**, **Model Explorer/Model List**, **Usage/Monitoring** and **Billing Center**; verify the workspace and Singapore/other actual region before copying the compatible endpoint. Also open Alibaba Cloud → **Billing Management → Budget/Alerts** and create an account-side cap. UI labels may change, so preserve the page title/URL and screenshot used rather than guessing from this document.

If any key may have appeared during development, revoke it and create a replacement. Update only protected backend secrets. Never paste a key into GitHub Issues, ChatGPT, screenshots, command arguments or URLs.

### 6.3 Record actual production variables without values

Expected explicit backend key names are:

```text
RAG_PROVIDER_MODE
RAG_CHAT_API_KEY / RAG_CHAT_BASE_URL / RAG_CHAT_MODEL
RAG_EMBEDDING_API_KEY / RAG_EMBEDDING_BASE_URL / RAG_EMBEDDING_MODEL
AGENT_PROVIDER_MODE
AGENT_MODEL_API_KEY / AGENT_MODEL_BASE_URL / AGENT_MODEL_NAME
WEB_ORIGIN
CLERK_PUBLISHABLE_KEY (Agent only)
CLERK_SECRET_KEY
CLERK_JWT_KEY (optional verification path)
ADMIN_USER_IDS (RAG)
RAG_DATABASE_PATH / RAG_UPLOAD_DIR / AGENT_DATABASE_PATH
APP_ENV=production
```

Production should use role-specific variables rather than relying on `OPENAI_*` fallbacks. Keep fallback disabled operationally unless it has passed the same benchmark and has an approved double-charge control design.

---

## 7. Backup, Isolated Restore and Migration Rehearsal

**Labels:** OWNER-ONLY, DATA-RISK. Backup is reversible; restoring over live paths is forbidden in this phase.

### 7.1 Approve a maintenance checkpoint

Before stopping writers, record:

- maintenance start/end and user notice;
- actual RAG DB, Agent DB, uploads and dedicated backup-root paths;
- pre-deploy row counts and upload file/byte counts;
- the prior known-good release identity;
- rollback owner and maximum outage window.

SQLite uses WAL. Do not copy only the main `.sqlite3` file while a writer is active. Stop both writer services for the final maintenance checkpoint, or use the repository's online backup script for the first rehearsal.

### 7.2 Run repository backup

From the checked-out release repository on the backend host:

```bash
sudo -u <service-user> env \
  RAG_DATABASE_PATH=<actual-rag-db> \
  AGENT_DATABASE_PATH=<actual-agent-db> \
  RAG_UPLOAD_DIR=<actual-upload-dir> \
  BACKUP_ROOT=<dedicated-backup-root-outside-uploads> \
  PYTHON_BIN=<release-python> \
  ./ops/backup_v2.sh
```

Expected output is one completed directory such as:

```text
<backup-root>/coursemate-v2-YYYYMMDDTHHMMSS.ffffffZ
```

That directory must contain `rag.sqlite3`, `agent.sqlite3`, `uploads.tar.gz`, `manifest.json`, `sqlite-check.txt` and `SHA256SUMS`. A hidden `.partial` directory means failure and is not a usable backup. Save `manifest.json`, `sqlite-check.txt`, directory listing and checksum-verification output; do not copy data files into the evidence package.

Copy the completed backup to an access-controlled, immutable off-host location. Checksums detect corruption but are not signatures and do not protect a writable backup store from malicious replacement.

### 7.3 Restore into a new isolated directory

```bash
sudo -u <service-user> env \
  RESTORE_SOURCE=<completed-backup-directory> \
  RESTORE_TARGET=<new-nonexistent-rehearsal-directory> \
  PYTHON_BIN=<release-python> \
  ./ops/restore_v2.sh
```

Expected:

```text
Isolated restore ready at <rehearsal-directory>
```

The target must not exist and must not be inside the backup. Restored layout is:

```text
<rehearsal-directory>/rag.sqlite3
<rehearsal-directory>/agent.sqlite3
<rehearsal-directory>/uploads/
```

### 7.4 Initialize the isolated copies twice

Use the release's own executable initializers; do not run the SQL migration files blindly.

RAG, from `services/rag-api`:

```bash
RAG_DATABASE_PATH=<rehearsal>/rag.sqlite3 \
RAG_UPLOAD_DIR=<rehearsal>/uploads \
<release-python> -c 'from app.config import Settings; from app.db import Database; db=Database(Settings()); db.initialize()'
RAG_DATABASE_PATH=<rehearsal>/rag.sqlite3 \
RAG_UPLOAD_DIR=<rehearsal>/uploads \
<release-python> -c 'from app.config import Settings; from app.db import Database; db=Database(Settings()); db.initialize()'
```

Agent, after building the release, from repository root:

```bash
node --input-type=module -e "import {AgentDatabase} from './services/agent-api/dist/src/db.js'; const db=new AgentDatabase('<rehearsal>/agent.sqlite3'); db.initialize(); db.close();"
node --input-type=module -e "import {AgentDatabase} from './services/agent-api/dist/src/db.js'; const db=new AgentDatabase('<rehearsal>/agent.sqlite3'); db.initialize(); db.close();"
```

Paths are literal operator-supplied paths; do not interpolate untrusted text into the Node command.

### 7.5 Verify schema, integrity and counts

```bash
sqlite3 <rehearsal>/rag.sqlite3 "PRAGMA integrity_check; PRAGMA foreign_key_check; SELECT version,name FROM schema_migrations ORDER BY version; SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'course_activity_%';"
sqlite3 <rehearsal>/agent.sqlite3 "PRAGMA integrity_check; PRAGMA foreign_key_check; SELECT version,name FROM schema_migrations ORDER BY version;"
```

Expected: `integrity_check=ok`, no foreign-key rows, RAG versions 1–10, Agent version 1 and eight RAG activity triggers. Compare pre/post counts for courses, documents, chunks, conversations, messages, tasks and uploads. Also compare document/upload hashes and any FTS table count used by the live database. Local historical counts (3/67/1,937 and 68 uploads) are not production expectations.

If the second initialization changes counts or fails, stop. Do not repair ownership rows manually.

---

## 8. Build and Deploy the Backend

**Labels:** OWNER-ONLY, CHANGE, DATA-RISK during live switch. This section assumes section 5 proved Alibaba ECS/systemd/Caddy. Otherwise use the actual platform's equivalent workflow and preserve the same gates.

### 8.1 Build an immutable release beside the current one

Discover and follow the current release layout. A safe pattern, only if compatible with that layout, is one directory per SHA plus a `current` symlink. Do not introduce this pattern during the release if the existing units use something else.

In a new release directory checked out at `RELEASE_SHA`:

```bash
git rev-parse HEAD
git status --short
python3 --version
node --version
npm --version
python3 -m venv services/rag-api/.venv
services/rag-api/.venv/bin/python -m pip install -r services/rag-api/requirements.txt
npm ci
npm run build
```

Expected: exact approved SHA, clean tracked status, Python ≥3.11, Node ≥24.14, lockfile-resolved installs and both builds exit 0. Run dependency audit in the deployment network. Save version/build/audit output.

### 8.2 Prepare protected environment configuration

Use the existing secret manager or root-owned env files, permissions 600, service-readable only. Set exact production origins and persistent paths. Never create env files by pasting secrets into shell history or committing `.env`.

Confirm:

- RAG and Agent DB paths are different files;
- backup root is outside uploads;
- `WEB_ORIGIN=https://qqttai.com` (or the actual canonical origin, with no guessed wildcard);
- `APP_ENV=production` on RAG;
- provider base URLs are HTTPS with no userinfo, query or fragment;
- the production model aliases match the approved canary/benchmark decision;
- `AUTH_TEST_USER_ID` and deterministic provider modes are absent.

### 8.3 Pre-switch internal start

Before touching public units, start the new binaries on loopback-only alternate ports against the **isolated restored copies**, using the same non-secret configuration and test/approved credentials. Verify `/health`, schema and a controlled smoke. Do not point both old and new processes at the same SQLite files.

### 8.4 Final live switch

1. Put the product in maintenance/read-only mode.
2. Stop both actual writer units.
3. Confirm no process still owns the live SQLite files.
4. Take a new final backup using section 7 and restore-test it.
5. Record the completed backup directory as `ROLLBACK_SNAPSHOT`.
6. Switch the actual units/artifact reference to the approved SHA without changing persistent paths.
7. Start **one** RAG instance and let `Database.initialize()` finish.
8. Start **one** Agent instance and let `AgentDatabase.initialize()` finish.
9. Verify section 7.5 against live paths and compare baseline counts.
10. Run local-loopback health, then public HTTPS health.

Use the actual discovered unit names:

```bash
sudo systemctl daemon-reload
sudo systemctl restart <rag-unit>
sudo systemctl status <rag-unit> --no-pager
sudo journalctl -u <rag-unit> --since '-15 min' --no-pager
sudo systemctl restart <agent-unit>
sudo systemctl status <agent-unit> --no-pager
sudo journalctl -u <agent-unit> --since '-15 min' --no-pager
```

Logs must show successful startup without secret values, repeated crashes or migration errors. Do not open public traffic until counts and health match.

### 8.5 Verify Caddy and network boundaries

```bash
sudo caddy validate --config <actual-caddy-config-path>
curl -sS -D - -o /dev/null https://<rag-host>/health
curl -sS -D - -o /dev/null https://<agent-host>/health
sudo ss -ltnp
sudo ufw status verbose
```

Expected: valid TLS, API HSTS/security headers retained, CORS only for the canonical web origin, 8000/8001 loopback/internal only, and public exposure limited to intended 22/80/443 rules. Ensure Caddy request limits and logs do not retain Authorization headers, prompts or private uploads.

---

## 9. Deploy the Frontend on Netlify

**Labels:** OWNER-ONLY, CHANGE, reversible by Netlify deploy rollback.

1. Open Netlify → confirmed CourseMate site → **Site configuration → Build & deploy**.
2. Confirm GitHub repository and approved production branch/commit policy.
3. Confirm `netlify.toml` is detected: build command `npm run build --workspace @coursemate/web`, publish directory `apps/web/dist`, Node `24.14.0`.
4. Open **Environment variables** and set only:
   - `VITE_CLERK_PUBLISHABLE_KEY`
   - `VITE_RAG_API_URL=https://<verified-rag-host>`
   - `VITE_AGENT_API_URL=https://<verified-agent-host>`
5. Create a Deploy Preview from the approved SHA. Test login, token refresh and both APIs.
6. If preview passes, promote/deploy that exact SHA to production.
7. Open **Domain management** and verify `qqttai.com`, TLS and redirects. Do not change DNS if the existing domain is healthy unless an explicit migration plan requires it.

Expected production evidence: Netlify deploy ID, exact Git SHA, successful build log, valid HTTPS, no browser console errors and no backend secret in environment/build output.

The static config has HSTS, nosniff, frame deny, referrer and permissions headers. Add a frontend CSP only after exact Clerk and API origins are known; smoke authentication again after any CSP change.

Rollback: Netlify → **Deploys** → select the prior known-good deploy → **Publish deploy**. This rolls back frontend code only; it does not revert backend/database changes.

---

## 10. Production Smoke Test

**Labels:** OWNER-ONLY. Normal smoke creates test data and may make small BILLABLE model calls. Approve a smoke budget and use dedicated accounts/courses.

### 10.1 Unauthenticated/platform checks

- `https://qqttai.com` loads with valid TLS and no mixed content.
- Both public health endpoints return 200 and exact service names.
- Browser DevTools Console has no uncaught errors; Network shows no CORS, 401 loop or leaking secrets.
- Sign-in, token refresh, sign-out and sign-in again work in the Clerk production instance.

### 10.2 Authenticated functional matrix

Use ordinary test users A and B plus an admin test user. Save redacted screenshots and IDs of synthetic test objects only.

1. **Official grounded QA:** ask a Chinese course question; require a streamed answer and valid source citations.
2. **General chat:** ask a greeting; it must not incorrectly return a no-evidence refusal.
3. **Exact locator:** ask an exact filename/question/subpart query; citation must point to the correct material.
4. **History:** ask three turns, refresh, sign out/in, reopen; all turns and course scope persist.
5. **Course switching:** switch official courses; answers/citations must not leak across courses.
6. **Agent:** create a task through natural language, search/list it, edit it, complete it and delete a separate synthetic task. Restart the Agent service in a planned window and prove persistence.
7. **Private course:** A creates a private course, uploads a safe synthetic document, waits for indexing, asks a question and sees a citation.
8. **Teaching profile:** A previews, saves, versions and restores a profile; a conversation remains pinned to its recorded version.
9. **Isolation:** B cannot list/read/chat/update/delete A's course, conversation, profile, document or Agent task. A 404-style hiding response is acceptable; any data exposure is an immediate rollback.
10. **Publication:** A gives both consents; status becomes pending. Admin rejects one synthetic request, then approve/publish another; verify owner lock, admin unpublish and withdrawal behavior.
11. **Deletion:** delete only designated synthetic objects and verify their files/data are gone without affecting other users.

For each test record input category, object ID, HTTP/browser result, citation IDs, latency and PASS/FAIL. Do not record private course text or bearer tokens.

### 10.3 Monitoring probe

```bash
RAG_HEALTH_URL=https://<rag-host>/health \
AGENT_HEALTH_URL=https://<agent-host>/health \
BACKUP_ROOT=<dedicated-backup-root> \
RAG_UPLOAD_DIR=<actual-upload-dir> \
PYTHON_BIN=<release-python> \
./ops/monitor_v2.sh
echo $?
```

Expected: one secret-free JSON object with top-level `status: "ok"`, four passing checks and exit code 0. Defaults are 5-second health timeout, 26-hour maximum backup age and 1 GiB minimum free space. Exit 2 must alert. Separately configure live error-rate, p95 latency, repeated-429 and ingestion-failure alerts; the script does not cover them.

### 10.4 Observation gate

Restrict initial use to internal accounts for 24 hours. Continue only when:

- no integrity, privacy, citation or authentication incident occurs;
- error rate stays within 10% of baseline;
- p95 latency stays within 20% of baseline;
- backups/monitoring remain current;
- model/token cost stays inside the approved operational budget.

---

## 11. Live Model Benchmark — Paid Human Execution

**Labels:** OWNER-ONLY, BILLABLE. This is acceptance criterion G. It is separate from production smoke and must not use private production content.

### 11.1 Inputs and authorization

Use:

- 50-case dataset: `benchmarks/tutor-model-cases.json`
- candidate template: `benchmarks/model-candidates.example.json`
- generation runner: `scripts/run_model_benchmark.py`
- 8-judgment embedding dataset: `benchmarks/embedding-retrieval-cases.json`
- embedding runner: `scripts/run_embedding_benchmark.py`
- official/public local RAG database copy only

Before adding `--allow-billable`, create a signed table:

| Candidate | Exact model | Region/base URL | Input price/M | Output price/M | Currency | Per-run cap | Repeats | Total approved cap |
|---|---|---|---:|---:|---|---:|---:|---:|

Prices must come from the provider's current official page/console on the execution date. Also set account-side budget alerts/quotas. The CLI's conservative ceiling is a second guard, not a replacement for account controls.

### 11.2 Load API keys without shell history

On PowerShell, use a process-only environment variable. Example for `CANDIDATE_API_KEY`:

```powershell
$secret = Read-Host "Candidate API key" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try { $env:CANDIDATE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
```

The key remains available to child processes in that terminal. Close the shell or run `Remove-Item Env:CANDIDATE_API_KEY` immediately after the benchmark. Do not capture the terminal while entering it.

### 11.3 Generation compatibility canaries

From repository root, using the trusted RAG venv Python:

```powershell
services\rag-api\.venv\Scripts\python.exe scripts\run_model_benchmark.py `
  --provider "<candidate>" --model "<exact-model>" `
  --base-url "https://<verified-provider-endpoint>/v1" `
  --api-key-env "CANDIDATE_API_KEY" `
  --output "<evidence>\07-live-benchmark\<candidate>-canary-general.json" `
  --limit 2 `
  --input-price-per-million <verified-price> `
  --output-price-per-million <verified-price> `
  --max-cost <approved-canary-cap> --currency <ISO-4217> `
  --allow-billable
```

Then explicitly canary one Agent case:

```powershell
services\rag-api\.venv\Scripts\python.exe scripts\run_model_benchmark.py `
  --provider "<candidate>" --model "<exact-model>" `
  --base-url "https://<verified-provider-endpoint>/v1" `
  --api-key-env "CANDIDATE_API_KEY" `
  --output "<evidence>\07-live-benchmark\<candidate>-canary-agent.json" `
  --category "agent_tools" --limit 1 `
  --input-price-per-million <verified-price> `
  --output-price-per-million <verified-price> `
  --max-cost <approved-canary-cap> --currency <ISO-4217> `
  --allow-billable
```

Expected: the endpoint supports the Responses streaming contract; the Agent case returns valid strict JSON arguments, exact tool sequence/call IDs and a final natural-language response. Failure preserves a checkpoint file named like `.<output-name>.checkpoint.json`; do not automatically retry or resume, because that can double charge. Diagnose, approve a new attempt and use a new output path.

Custom base URLs must be HTTPS and contain no credentials, query, fragment or control characters. Never use `--allow-insecure-loopback` for an external provider.

### 11.4 Full 50-case runs

After both canaries pass, run all 50 cases at least three times per candidate. Omit `--limit` and `--category`; use a fresh output path for every repetition:

```powershell
services\rag-api\.venv\Scripts\python.exe scripts\run_model_benchmark.py `
  --provider "<candidate>" --model "<exact-model>" `
  --base-url "https://<verified-provider-endpoint>/v1" `
  --api-key-env "CANDIDATE_API_KEY" `
  --output "<evidence>\07-live-benchmark\<candidate>-run-01.json" `
  --input-price-per-million <verified-price> `
  --output-price-per-million <verified-price> `
  --max-cost <approved-full-run-cap> --currency <ISO-4217> `
  --allow-billable
```

The runner uses 60-second timeout, zero SDK retries, non-overwriting outputs and per-case atomic checkpoints. Save:

- all JSON outputs and any checkpoint/failure evidence;
- terminal exit codes and redacted error messages;
- provider usage/billing screenshots immediately before and after each run;
- exact model alias, region/base URL, price source timestamp and approved cap;
- measured token usage/cost, TTFT, total latency, p50/p95 and streaming/tool results.

### 11.5 Human scoring

Automatic contract checks are insufficient. Have one consistent evaluator score every completed case using the rubric in [MODEL_BENCHMARK_2026.md](MODEL_BENCHMARK_2026.md): retrieval relevance, source/citation correctness, teaching depth, step-by-step quality, Chinese quality, follow-up coherence, hallucination and instruction adherence.

Blind model labels where practical. Record both per-case scores and aggregated category results. Reject a candidate regardless of average score if it leaks course scope, fabricates citations, fails private authorization scenarios, breaks any Agent tool schema/sequence, or cannot complete multi-round call-id replay.

### 11.6 Embedding benchmark

**Privacy gate:** this sends selected official/public course chunks to the provider. Confirm the database copy contains no private/user course and that rights/region terms allow transfer. Never point the runner at the production DB.

Run at least three times per embedding candidate:

```powershell
services\rag-api\.venv\Scripts\python.exe scripts\run_embedding_benchmark.py `
  --provider "<candidate>" --model "<exact-embedding-model>" `
  --base-url "https://<verified-provider-endpoint>/v1" `
  --api-key-env "CANDIDATE_API_KEY" `
  --database "<read-only-public-corpus-copy>" `
  --output "<evidence>\07-live-benchmark\<candidate>-embedding-run-01.json" `
  --top-k 3 --batch-size 10 `
  --input-price-per-million <verified-price> `
  --max-total-cost <approved-run-cap> --currency <ISO-4217> `
  --allow-billable
```

Add `--dimensions <approved-dimension>` only when the provider/model supports and the comparison intentionally fixes it. Compare course-scoped Recall@K and MRR first, then latency, dimension/storage, cost, region and stability. Output intentionally contains identifiers/metrics, not chunk text or vectors.

Changing embedding model or dimension requires a complete corpus re-embedding and retrieval regression. Never mix vector contracts in one index and never switch production embeddings solely by changing an environment variable during this runbook.

### 11.7 Select and document winners

Create a decision table covering Tutor, Agent and Embedding separately. A candidate is eligible only when:

- all required repeats completed within budget;
- human quality/citation/safety thresholds pass;
- exact Agent tool/Responses contract passes if used for Agent;
- region/governance and operational quotas are approved;
- price/latency are acceptable;
- deployment and rollback steps are defined.

Do not call Qwen, OpenAI, Doubao or another model a “winner” before this evidence exists. Fallback remains disabled unless both primary and fallback pass the same benchmark and one bounded cross-provider attempt is designed with idempotency and circuit/cost controls.

---

## 12. Rollback Matrix

| Failure | Immediate action | Rollback | Evidence to preserve |
|---|---|---|---|
| Frontend deploy/login/CORS | Stop promotion | Publish prior Netlify deploy | deploy IDs, console/network errors |
| Backend startup/health | Remove traffic; stop new unit | Point units/artifact to prior SHA; restart | status/journal, SHA, health output |
| Integrity/FK/count mismatch | Stop all writers | Restore RAG DB + Agent DB + uploads from one `ROLLBACK_SNAPSHOT` | manifests, checksums, before/after counts |
| Private data exposure | Disable access immediately | Prior code and, if required, consistent snapshot; start incident response | minimal redacted request/object IDs |
| Citation/source corruption | Restrict traffic | Prior code/model/config; restore only if data changed | test case, citation IDs, model config names |
| Model incompatibility/cost spike | Disable affected model path | Restore prior explicit model variables; no silent fallback | provider request IDs, usage/cost, redacted error |
| Critical/high vulnerability | Hold launch | Prior known-good artifact or keep maintenance | scanner report and disposition |

Immediate rollback triggers include integrity/FK failure, private exposure, citation corruption, new unresolved critical/high vulnerability, error rate above 2× baseline or p95 latency above 50% over baseline.

Do not drop additive V2 columns in place. If no V2 writes occurred, the prior binary may tolerate additive schema after verification. If V2 writes occurred or counts changed unexpectedly, restore both databases and uploads as one consistent unit.

---

## 13. Final Acceptance and Handoff to ChatGPT

### 13.1 Criterion G — Live Model Benchmark

PASS only when the evidence package contains:

- current price/region/model verification and signed budget;
- canaries and at least three complete 50-case runs for each compared generation candidate;
- at least three complete public-corpus embedding runs for each compared embedding candidate;
- automatic metrics plus completed human rubric;
- separate approved Tutor/Agent/Embedding decisions;
- actual provider charges reconciled to estimates;
- no private content or secret exposure.

Otherwise: **G = NOT PASS**.

### 13.2 Criterion N — Production Deployment + Production Smoke

PASS only when the evidence package contains:

- exact production Git SHA, Netlify deploy ID and backend runtime inventory;
- verified Clerk/provider/region configuration names and secret rotation status;
- completed backup, isolated restore, migration-twice, integrity/FK/schema/count evidence;
- backend/frontend production deploy evidence and public HTTPS health;
- complete three-account smoke matrix including private isolation/publication;
- monitor/alerts and 24-hour observation gate;
- tested rollback identifiers and Owner sign-off.

Otherwise: **N = NOT PASS**.

### 13.3 Redacted handoff template

Send the guiding ChatGPT this structure:

```text
Release SHA:
GitHub PR/deploy source:
Netlify site/deploy ID:
Production web/RAG/Agent origins:
Backend platform/region/instance or service IDs:
Unit/service names and bind ports:
Environment key names present (no values):
Live provider/model names and regions:
Clerk production instance verified: yes/no
Backup directory ID + manifest/checksum result:
Restore/migration/integrity/schema/count result:
Health result:
Smoke matrix result and failed step IDs:
Monitor/24h observation result:
Benchmark approval/cap/actual cost:
Generation output filenames + human score sheet:
Embedding output filenames:
Tutor/Agent/Embedding decision:
Rollback SHA/Netlify deploy/snapshot ID:
G verdict:
N verdict:
Open risks:
```

Owner final attestation:

```text
I personally verified the named production control planes and runtime evidence.
No secret/private content is included in the handoff package.
Criterion G: PASS / NOT PASS
Criterion N: PASS / NOT PASS
Production Acceptance: ACCEPTED only if both G and N are PASS
Owner:
Timestamp/timezone:
```

---

## 14. Repository Sources Audited

This runbook was reconciled against current Git/status/history, source configuration, FastAPI/Express health and DB initialization code, [V2_TEST_REPORT.md](V2_TEST_REPORT.md), [V2_COMPLETION_AUDIT.md](V2_COMPLETION_AUDIT.md), [MODEL_BENCHMARK_2026.md](MODEL_BENCHMARK_2026.md), [V2_PRODUCTION_DEPLOYMENT.md](V2_PRODUCTION_DEPLOYMENT.md), [V2_DATABASE_MIGRATION.md](V2_DATABASE_MIGRATION.md), [V2_SECURITY.md](V2_SECURITY.md), [V2_ARCHITECTURE.md](V2_ARCHITECTURE.md), [V2_CURRENT_GAP_ANALYSIS.md](V2_CURRENT_GAP_ANALYSIS.md), `V2_HANDOFF_FOR_CHATGPT.md`, `PRODUCTION_DEPLOYMENT_CHANGELOG_AND_FINAL_STATE.md`, `DEPLOYMENT_HANDOFF_FOR_CHATGPT.md`, `docs/file-request-packs/`, benchmark datasets/runners, backup/restore/monitor scripts, migration records, package scripts, [render.yaml](../render.yaml), [netlify.toml](../netlify.toml) and `.env.example`.

If future evidence conflicts, use this order: current real production runtime → current source → current DB schema → Git history → live server/runtime configuration → V2 reports → production changelog → old handoff → README → assumptions. Record the conflict; never silently merge incompatible claims.
