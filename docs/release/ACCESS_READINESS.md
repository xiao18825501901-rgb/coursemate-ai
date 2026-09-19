# CourseMate Release Access Readiness

> Historical PREPARE artifact. The authorized release was executed on 2026-09-20; current facts and
> rollback anchors are in `PRODUCTION_RELEASE_EXECUTION_20260920.md`.

Status: **PREPARE ONLY — NO PRODUCTION OR BILLABLE ACTION IS AUTHORIZED**  
Evidence cutoff: `2026-09-19T18:04:10.573Z`
Workspace: `D:\CourseMate_COMPLETE_ARCHIVE_20260918\01_SOURCE_REPOSITORY`

This file records current local evidence and access gaps. An account being reachable does not
authorize a write. Historical deployment reports and labels are retained only as locating hints
until the live resource is read again.

## 1. Release identity

| Item | Verified value | Meaning |
|---|---|---|
| Branch | `fix/codex-dsh-audit-20260919` | Local branch; no configured upstream |
| Application release | `73b7049ee3204d5c213ad70c67db9b892aa306bf` | Frozen application/test candidate |
| Application evidence | 676 backend; 14 browser; Web 60; Agent 66; typecheck/build PASS | Fresh evidence recorded in `docs/codex-audit/LONG_COURSE_NAME_FIX.md` |
| Current release-tooling head | `e300f0e2bdd6a983ef575efe28ad19472a641196` | Adds the offline-tested frozen qualification snapshot operator only |
| Application diff after candidate | None, excluding the two release-tooling files | The application candidate remains `73b7049`; do not relabel the tooling commit as the app release |
| Production source/deploy | `UNKNOWN — REQUIRES APPROVED LIVE VERIFICATION` | A title, README, old deploy or local build is not production SHA evidence |

The qualification operator is `services/rag-api/app/cm_update/qualification_snapshot.py`.
Synthetic verification: **11 passed**, Ruff PASS, targeted strict Mypy PASS. It is not Clerk or
production evidence. It captures only ID, creation/update time and disabled-state flags; preview
uses SQLite read-only mode; apply requires the exact frozen snapshot hash, candidate-set hash and
cutoff and never refetches Clerk. Output contains aggregate counts and hashes, not candidate IDs.
On Windows, the file inherits the chosen protected directory ACL; Unix mode `0600` is additionally
enforced on POSIX. The operator must therefore choose an owner-only directory before capture.

## 2. Access matrix

| Scope | Local readiness | Effective authorization | Live result |
|---|---|---|---|
| A — four public GETs | Existing bounded script used by Owner after native dialog was unavailable | **APPROVED FOR ONE RUN; CONSUMED** | OWNER-RUN: 4/4 HTTP 200 |
| B — SSH read-only | OpenSSH, aliases, identities and known-host fingerprints present | NOT APPROVED | NOT RUN |
| C1 — GitHub read-only | Remote known; Git credential helper configured; `gh` absent | NOT APPROVED | NOT RUN |
| D1 — Netlify read-only | CLI `27.4.0`; global config file present; repo not linked | NOT APPROVED | NOT RUN |
| E1 — Clerk full directory snapshot | Frozen read-only capture tool ready; no process credential | NOT APPROVED | NOT RUN |
| F1 — qualification preview | Pure snapshot calculation and read-only DB check ready | NOT APPROVED; cutoff unset | NOT RUN |
| G — live model canary preparation | Bounded runner exists; local model credential absent | NOT APPROVED; account/price/budget unset | NOT RUN |
| H onward — backup/write/deploy/acceptance | Repository tools exist; live paths/topology unknown | NOT APPROVED | NOT RUN |

### Public GET request A

The exact requested scope is one unauthenticated HTTPS `GET` per URL, TLS verification on,
redirects not followed, 15-second timeout, no retry, no cookie/token and no write:

1. `https://qqttai.com/`
2. `https://rag.qqttai.com/health`
3. `https://rag.qqttai.com/ui-extension/health`
4. `https://agent.qqttai.com/health`

The native permission request returned no effective network grant, so Codex made no request. After
the Owner confirmed that no permission dialog appeared, the Owner used the reviewed
`scripts/production_readonly_check.mjs` fallback once inside the approved window and returned its
complete bounded output. The following is Owner-executed evidence, not an independent Codex network
observation.

Approval attempt record:

- Owner approved only A against package `2026-09-20-prep-v1`, payload
  `4a3d681610aa36c479f722fa73aa344bc788877a4412747da04debcdcb0719ed`, for 30 minutes.
- Approval was recorded at `2026-09-19T18:01:33.999Z`; operational expiry is
  `2026-09-19T18:31:33.999Z`.
- The subsequent native permission request again returned `network: null`; effective native
  network permission was not granted and Codex attempted 0 GETs.
- Owner confirmed that no native permission dialog appeared. This is a Codex permission-channel
  block, not an HTTP/network observation. The approved fallback is a local Owner-run invocation of
  the already reviewed bounded script; its raw output must be returned unchanged for recording.
- Owner fallback execution ran exactly once at `2026-09-19T18:04:09.737Z` through
  `2026-09-19T18:04:10.573Z`, before expiry. **Execution result: COMPLETED — 4 of 4 direct GETs
  returned HTTP 200.** All actions other than A remain unapproved.

| UTC start | URL | Status | Content-Type | Bounded result |
|---|---|---:|---|---|
| `2026-09-19T18:04:09.737Z` | `https://rag.qqttai.com/health` | 200 | `application/json` | `status=ok`, `service=rag-api` |
| `2026-09-19T18:04:10.256Z` | `https://rag.qqttai.com/ui-extension/health` | 200 | `application/json` | `status=ok`, `service=coursemate-ui-update`, `mode=integrated`, `provider=qwen` |
| `2026-09-19T18:04:10.409Z` | `https://agent.qqttai.com/health` | 200 | `application/json; charset=utf-8` | `status=ok`, `service=agent-api` |
| `2026-09-19T18:04:10.573Z` | `https://qqttai.com/` | 200 | `text/html; charset=UTF-8` | `title=CourseMate 学习空间`, `bundle=ui`, `shape=n/a` |

These responses establish current public routing and advertised runtime mode only. They do not
identify source SHA/deploy ID, prove a paid Qwen response, validate Clerk login or show that any
multi-user/data-isolation workflow passes.

## 3. Local account preparation

### GitHub

- Local remote: `https://github.com/xiao18825501901-rgb/coursemate-ai.git`.
- The current branch has no upstream.
- System Git config selects credential helper `manager`, but no standalone helper executable or
  `gh` command was found on `PATH`; credential validity is unknown because no remote call was made.
- C1 must establish the actual remote ref, protections and whether a push triggers Netlify or
  another workflow. C2 push is a separate write approval.

Owner action card, only if C1 is approved and authentication is requested:

1. Sign in to the correct GitHub account in the browser and complete MFA yourself.
2. Allow the existing Git credential flow when it opens; do not send a token or recovery code in chat.
3. Tell Codex only that sign-in finished. Codex performs the non-secret read-only checks.

### Netlify

- Netlify CLI `27.4.0` is installed.
- A global Netlify config file exists; its contents were not printed. Authentication validity is
  unknown until an approved `netlify status`/read-only site query.
- The repository has no `.netlify/state.json`; it is not locally linked.
- Historical hint only: site `coursemate-ai-qqtt`, ID
  `166afb5a-4103-4236-9f13-4be34dc68cd2`. Current team, site and deploy remain UNKNOWN.

Owner action card, only if D1 reports that login is required:

1. Run the normal Netlify browser login flow on this computer and complete MFA yourself.
2. Do not paste an auth token in chat or add it to repository files.
3. Tell Codex that login finished. Codex will read team/site/deploy/build context and variable
   **names only**. Repository linking and all publish/rollback actions remain separately approved.

### SSH / ECS

Local aliases resolve as follows; these facts do not decide which host is production:

| Alias | Host/user | Local known-host ED25519 fingerprint | Status |
|---|---|---|---|
| `coursemate-prod-current` | `admin@47.237.179.69:22` | `SHA256:xrg8yao3PqVrTPP5Qx0st1pxeHt4jVR13L7CY38D8iw` | Matches prior owner-console evidence; current live role UNKNOWN |
| `coursemate-prod-new` | `root@47.114.34.175:22` | `SHA256:TWqeYbYv83dw67sg6BWf3gv3C4LjRWeioaA5/qbq4k4` | Matches prior owner-console evidence; publish role UNKNOWN |

Both configured identity files and public-key files exist. Strict host checking is not disabled.
No SSH connection was made. B must first confirm in the trusted ECS console the intended instance,
public IP, region and host-key fingerprint. If the key is passphrase-locked, unlock it locally; do
not send the private key or passphrase. Sudo and all service/data changes are outside B.

### Clerk

- No Clerk production credential is present in the current process or repository environment files.
- The production instance, complete user count and existing production qualification receipt are
  UNKNOWN.
- Existing `app.cm_update.directory` CLI is a writer, not a dry-run. It must not be used for E1/F1.
- E1 capture writes a minimized frozen snapshot only after every Clerk page succeeds. A partial
  fetch produces no approved snapshot. F1 then calculates counts/hashes from that exact file and
  opens the confirmed UI database read-only.

Owner action card after E1 approval:

1. Sign in to the existing **production** Clerk application and complete MFA yourself.
2. Confirm the production instance identifier without sending user records.
3. Place the backend secret through the existing protected local/server secret mechanism; never
   type it in chat or a command argument. Codex will confirm only presence and use it for E1.

### Alibaba Cloud Model Studio / Qwen

- No model API credential/base URL is present in the current process or repository environment files.
- Account, workspace, Singapore availability of `qwen3.8-max`, supported protocol and current
  input/output/image prices are UNKNOWN.
- `aliyun` CLI is absent. No model request or pricing lookup was made.

Owner action card for G preparation:

1. Sign in to the intended Alibaba Cloud/Model Studio account and complete MFA yourself.
2. Confirm the workspace/region and that `qwen3.8-max` is enabled; capture current official pricing
   and any provider-side quota/hard-stop feature.
3. Store the API key only in the protected mechanism named by the approved plan. Do not send it in
   chat. Codex first runs the canary preflight without a paid call.

## 4. Qualification snapshot sequence

No command below is authorized against real Clerk or production yet. The approved sequence will be:

1. E1 `capture`: protected directory, full pagination, minimized frozen file, no database access.
2. Owner chooses an explicit ISO cutoff including timezone. It is never inferred from today or a
   local first-login timestamp.
3. F1 `preview`: aggregate registered/candidate/unknown counts; frozen snapshot SHA-256;
   candidate-set SHA-256; eligibility-evidence SHA-256; read-only current schema/cutoff/receipt.
4. Owner approves that exact snapshot hash, candidate-set hash, cutoff, target DB and count.
5. H backup plus isolated restore/migration rehearsal passes.
6. F2 `apply`: the same file is rehashed; the same candidate set is recomputed; a conflicting
   completed receipt fails closed; no Clerk refetch occurs; existing qualification methods are
   preserved; output contains no user IDs.

E2 directory projection is a different write and requires its own approval. F2 never implies E2.

## 5. Model and cost-control reality

Current enforceable controls are not equivalent:

| Control | What it enforces | What it does not enforce |
|---|---|---|
| `CMUI_ALLOW_BILLABLE=false` by default | Global on/off gate for UI Qwen calls | A currency budget after enabled |
| UI `model-runs` limit `8/60s/user` | Short-window request rate | Day/month spend |
| V3 model reservations | Defaults to 60 calls/day/user and 60/day/user/course; records role and tokens | A currency ledger or site-wide money cap |
| `v3_max_output_tokens` | 500–8000, default 4000 per V3 call | Input-token spend or total monthly spend |
| Canary preflight `--max-provider-calls`, prices and `--max-cost` | Rejects that one canary before it starts if its conservative estimate exceeds the approved cap | Provider account hard stop or ongoing traffic budget |
| Provider alert, if available | Notification | A hard stop unless the account feature is verified to block calls |

The smallest existing canary is one selected teaching case (Planner + Teacher) plus one synthetic
image Problem case: exactly **3 provider calls**. The full four-major CASE A/B matrix plus image is
17 calls. Current prices and a monetary cap are still blank, so neither run is authorized. Coverage
review and query Embedding are not silently included; each must be priced and explicitly selected.

Until K is approved, the safe public-production setting is billable generation disabled. A limited
pilot can combine the global off switch, an explicit activation window, reduced per-user/day call
limits, output-token caps and a named human shutoff owner, but this is still not a monetary hard
stop. If the Owner requires a true site-wide daily/monthly currency hard stop and the provider does
not supply one, a separately reviewed ledger/circuit-breaker change is required and will create a
new application candidate.

Historical Embedding provenance remains UNKNOWN. Choices:

- **A — temporary use after bounded retrieval acceptance:** no rebuild; explicitly accept unknown
  provenance for a limited window; test authorized keyword/semantic retrieval and tenant isolation.
  There is no claimed lexical-only fallback.
- **B — isolated rebuild:** freeze corpus/counts and current index; verify model/account/region,
  dimensions and preprocessing; approve token/cost cap; build a new isolated index; compare;
  separately approve pointer switch; retain the old index for rollback.

## 6. Conditional release sequence after approvals

1. A/B/C1/D1 establish current public, server, Git and Netlify facts.
2. E1/F1 establish a frozen identity snapshot and read-only qualification preview.
3. G verifies one bounded canary only after price, currency, calls, tokens, data and expiry are fixed.
4. H identifies every writer and exact live paths, pauses the approved set, and runs
   `ops/backup_v2.py`. When `CMUI_DATA_DIR` is present it protects RAG DB, Agent DB, UI DB, RAG
   uploads, UI uploads and share snapshots as one maintenance recovery unit.
5. Restore uses `ops/restore_v2.py` into a new isolated target, never over an existing directory,
   and verifies manifest, every hash, SQLite integrity/FK and archive content. Migration rehearsal
   runs on the restored copy before a candidate touches real databases.
6. Only then perform separately approved E2/F2, C2, migration/service switch and Netlify D2.
   Production build must pass the real preflight and artifact verifier; a local test bundle is not publishable.
7. J uses named real test accounts and an explicit message/share/qualification data policy.
8. Rollback A preserves new user data and withdraws the release. Rollback B restores the approved
   recovery unit only under a separate disaster-recovery authorization and declared data-loss window.

Exact live paths, writer list, schema versions, service topology, deploy IDs and rollback target are
still UNKNOWN and will be filled only from approved read access. Wrong target, hash mismatch,
changed candidate set, incomplete backup/restore, credential exposure, budget drift, isolation
failure or unverifiable deployed SHA is a stop condition.

## 7. Next minimum approvals

The first useful action is A only. After its evidence is recorded, B/C1/D1 can be approved together
as read-only scopes if desired. E1, F1, G, H and every write remain separate. Refer to
`docs/release/RELEASE_APPROVAL_PACKAGE.md`; blank fields and this document itself are not approval.
