# CourseMate Release Approval Package

> Historical approval package. The Owner subsequently authorized the bounded and then full release;
> actual execution evidence is in `PRODUCTION_RELEASE_EXECUTION_20260920.md`.

Package version: **`2026-09-20-prep-v2`**
Mode: **PREPARE**  
Approval payload SHA-256: **`637d36cf6015400fecd7231871a19f24e01e0c4c16f85e4418ede202fb12abb7`**
Application release: **`73b7049ee3204d5c213ad70c67db9b892aa306bf`**  
Release tooling: **`e300f0e2bdd6a983ef575efe28ad19472a641196`**

This package centralizes Owner decisions. It is not permission by itself. Blank/UNKNOWN fields,
historic approvals, prior budgets and account login state mean **not approved**. Never put a
password, MFA code, private key, API key, token, real user list or private course text in this file
or chat.

## 1. Current release evidence

| Layer | Status | Evidence |
|---|---|---|
| Source implementation | VERIFIED at application SHA | Long legal course names, UI and audited functionality are in the frozen candidate |
| Offline qualification operator | VERIFIED at tooling SHA | 11 synthetic tests; Ruff PASS; targeted strict Mypy PASS |
| Full backend regression | VERIFIED at application SHA | 676 passed; 0 failure/error/skip; 755.03s |
| Browser regression | VERIFIED at application SHA | 14 passed; no skip/failure/flaky; 48.2s |
| Web / Agent / types / local build | VERIFIED at application SHA | 60 / 66 / PASS / PASS |
| Real Clerk/model/account integration | NOT VERIFIED | No approved access or billable call |
| Public routing/runtime advertisement | OWNER-RUN VERIFIED | Four bounded direct GETs returned 200; UI extension advertises integrated/Qwen and root serves the `ui` bundle |
| Production version/deployment | NOT VERIFIED | Public GETs do not identify source SHA or deploy ID; no publish was run |

Candidate source schemas are RAG migration **25**, UI schema **11**, Agent schema **1**. Actual
production schemas are UNKNOWN. The local optimized build is not a production-configured artifact.
Netlify production must run:

```text
node scripts/preflight_release_build.mjs
npm run build --workspace @coursemate/web
node scripts/verify_release_build.mjs
```

The generated `build-info.json`, its artifact hash, actual deploy ID and production application SHA
will be separate evidence; none is inferred from a page title.

## 2. Resource register

| Resource | Proposed/known locator | Approval-ready fact |
|---|---|---|
| Public site/API | Four exact A URLs below | Owner bounded run at `2026-09-19T18:04Z`: all HTTP 200; A consumed |
| Git | `https://github.com/xiao18825501901-rgb/coursemate-ai.git` | Local remote only; target ref/protection/automation UNKNOWN |
| ECS candidate 1 | `admin@47.237.179.69`; fingerprint `SHA256:xrg8yao3PqVrTPP5Qx0st1pxeHt4jVR13L7CY38D8iw` | Local config/prior console match; live role UNKNOWN |
| ECS candidate 2 | `root@47.114.34.175`; fingerprint `SHA256:TWqeYbYv83dw67sg6BWf3gv3C4LjRWeioaA5/qbq4k4` | Local config/prior console match; live role UNKNOWN |
| Netlify | Historical `coursemate-ai-qqtt`, site ID `166afb5a-4103-4236-9f13-4be34dc68cd2` | Current team/site/deploy/rollback deploy UNKNOWN |
| Clerk | Existing production application required | Instance and full snapshot UNKNOWN |
| Model Studio | Intended Singapore workspace, `qwen3.8-max` | Account/region/protocol/price/quota UNKNOWN |
| Production data | RAG, Agent, UI databases; RAG/UI uploads; share snapshots; protected config | Exact paths/writers/counts UNKNOWN |

## 3. Owner decisions still required

Do not fill sensitive values. Use non-sensitive identifiers or `UNKNOWN`.

| Decision | Current value | Required before |
|---|---|---|
| Approval validity window | UNKNOWN | Any external action |
| Confirmed production ECS / region / fingerprint | UNKNOWN | B/H/I |
| Git target ref and whether push auto-publishes | UNKNOWN | C2 |
| Netlify team/site/current deploy/rollback deploy | UNKNOWN | D2 |
| Clerk production instance identifier | UNKNOWN | E1 |
| Qualification cutoff (ISO timestamp + timezone) | UNKNOWN | F1 |
| Frozen Clerk snapshot SHA / candidate-set SHA / count | UNKNOWN until E1/F1 | F2 |
| Canary case and synthetic image | Proposed: one teaching case + one synthetic image | G |
| Canary maximum provider calls | Proposed: **3** | G |
| Canary max output tokens per call | Proposed: **4000** | G |
| Canary prices, currency, total cap and expiry | UNKNOWN | G |
| Include coverage-review call | UNKNOWN; default-off implementation | G/K |
| Include query Embedding | UNKNOWN | G |
| Historical Embedding policy | Choose A temporary bounded acceptance / B isolated rebuild | Production retrieval acceptance |
| Rebuild corpus/model/region/dimensions/preprocessing/budget | UNKNOWN; required only for B | Rebuild |
| Ongoing model activation period and scope | UNKNOWN | K/public billable use |
| Per-user/day, per-course/day and output-token caps | UNKNOWN | K |
| Site-wide daily/monthly money policy and enforceable stop | UNKNOWN; current code has no currency hard stop | K |
| Alert/shutoff owner | UNKNOWN | K |
| Maintenance window and writers allowed to pause | UNKNOWN | H/I |
| Exact backup root and isolated restore root | UNKNOWN after B inventory | H |
| Two normal test accounts + admin aliases | UNKNOWN | J |
| Allowed message/share recipient/data scope | UNKNOWN | J |
| Acceptance test retention/cleanup policy | UNKNOWN | J |
| Rollback A trigger/authority | UNKNOWN | I/J |
| Disaster recovery RPO/data-loss window/authority | UNKNOWN | Separate rollback B approval |

### Historical Embedding selection

- **A — bounded temporary acceptance:** keep the current index without claiming known provenance;
  run approved real retrieval and tenant-isolation checks; set an expiry/review date. No automatic
  lexical-only fallback exists.
- **B — isolated rebuild:** freeze the approved corpus and current index; verify the new embedding
  model/account/region/dimensions/preprocessing; approve token and monetary caps; build separately;
  compare retrieval/isolation; approve pointer switch separately; retain the old index for rollback.

### Canary and continuing-cost selection

The prepared runner makes exactly three calls for the smallest proposed canary: Planner, Teacher
and one image Problem call. It refuses execution without explicit billable opt-in, provider-call
cap, current prices, currency, max-cost, bounded output tokens and confirmation that the image is
synthetic. It checkpoints each paid result and never retries automatically.

Three calls do **not** cover model-based coverage review or query Embedding. If selected, those are
additional priced calls and require an updated package. `CMUI_ALLOW_BILLABLE`, request rate limits,
daily call reservations and output-token caps are enforceable controls, but none is a site-wide
currency hard stop. If a verified provider hard stop is unavailable and Owner requires one, a new
reviewed application change is required before public billable use.

## 4. Approval ledger

Every row except completed action A is currently **NOT APPROVED**.

| ID | Exact scope | Current state | Preconditions / output |
|---|---|---|---|
| A | One unauthenticated GET each: `https://qqttai.com/`, `https://rag.qqttai.com/health`, `https://rag.qqttai.com/ui-extension/health`, `https://agent.qqttai.com/health`; TLS on, no redirect follow, one attempt, 15s, no token/write | **COMPLETED BY OWNER; APPROVAL CONSUMED** | 4/4 HTTP 200 at `2026-09-19T18:04Z`; public routing only, not business acceptance |
| B | SSH read-only inventory of Owner-confirmed host(s); keep host-key verification; no sudo/write/restart | NOT APPROVED | Owner confirms ECS identity/fingerprint; record services, process/ports, paths, schemas and writer topology without secrets |
| C1 | GitHub read-only remote/ref/protection/workflow/Netlify-link inspection | NOT APPROVED | Authentication may require Owner browser/MFA |
| D1 | Netlify read-only team/site/deploy/build context/variable-name inspection | NOT APPROVED | Authentication may require Owner browser/MFA; no variable values |
| E1 | Complete minimized Clerk production directory capture to protected, no-overwrite frozen file | NOT APPROVED | Correct production instance; all pages succeed; no DB write |
| F1 | Read-only qualification preview for Owner cutoff against exact E1 file and confirmed UI DB | NOT APPROVED | Explicit cutoff; aggregate count + hashes; no qualification write |
| G | Bounded real `qwen3.8-max` canary matching filled case/calls/tokens/prices/currency/cap/window | NOT APPROVED | Preflight ceiling <= approved cap; protected key; synthetic data only |
| Embedding-eval | Bounded real retrieval/isolation evaluation of current index | NOT APPROVED | Explicit queries/accounts/data scope; no rebuild/switch |
| Embedding-rebuild | Build an isolated new index for exact corpus/config/budget | NOT APPROVED | Separate token/currency cap; preserve old index |
| Embedding-switch | Change production index pointer | NOT APPROVED | Approved comparison and rollback pointer |
| H | Pause approved writers; consistent backup; isolated verified restore and migration rehearsal | NOT APPROVED | B confirms paths/topology; destination outside upload tree; manifest/hash/integrity/FK/files pass |
| E2 | Sync exact complete Clerk snapshot into confirmed UI directory projection | NOT APPROVED | H PASS; separate from qualification |
| F2 | Apply only approved frozen snapshot/cutoff/candidate-set hash to confirmed UI DB | NOT APPROVED | H PASS; operator rehashes same file and does not refetch |
| C2 | Push exact approved ref/application/tooling commits to approved remote | NOT APPROVED | C1 records protection and automatic deployment behavior; no force push |
| I/D2 | Migrate/switch backend group and publish verified Netlify production artifact | NOT APPROVED | H PASS; G/K as needed; exact maintenance window/deploy/rollback target |
| J | Full named multi-user production acceptance with explicitly allowed messages/shares/qualification/test data | NOT APPROVED | Two normal accounts/admin alias and retention policy fixed |
| K | Enable ongoing model traffic only for exact period/scope/limits/alerts/stop owner | NOT APPROVED | Cost policy is actually enforceable; otherwise controlled pilot only |
| DR-B | Destructive disaster recovery from approved backup | NOT APPROVED | Separate incident approval, exact target, RPO/data-loss window and post-restore validation |

Actions are dependency ordered, not bundled implicitly:

```text
A/B/C1/D1 -> live inventory
E1 + Owner cutoff -> F1 -> exact identity approval
account/pricing facts -> G
B live paths -> H backup + isolated restore/migration
H PASS -> E2/F2 and/or I/D2 as explicitly approved
verified deploy -> J
G evidence + enforceable policy -> K
```

## 5. Backup, migration, publish and rollback boundary

The exact execution commands cannot be finalized until B identifies live paths and writers. The
existing backup tool requires explicit `RAG_DATABASE_PATH`, `AGENT_DATABASE_PATH`, `RAG_UPLOAD_DIR`
and `BACKUP_ROOT`; deployed UI state is included only when confirmed `CMUI_DATA_DIR` is supplied.
Backup root must be outside the upload tree. The backup contains standalone SQLite snapshots,
uploads, optional UI attachments/share snapshots, manifest, integrity/FK results and SHA-256 sums.

Restore uses explicit `RESTORE_SOURCE` and a brand-new `RESTORE_TARGET`, refuses overwrite and
revalidates every artifact. Migration rehearsal is run only on that restored copy. Candidate startup
must not touch a production database before H passes because startup can initialize/migrate schemas.

Rollback A withdraws the application while preserving post-release data and must use a runtime
compatible with the resulting schemas. Rollback B restores the full recovery unit and can lose
post-backup data, so it is never implied by release approval.

## 6. Current canonical approval payload

The SHA at the top is calculated over the exact UTF-8 bytes of the single canonical JSON line below,
without the trailing newline. It identifies this package's present decision state; it does not
authorize anything.

<!-- APPROVAL_PAYLOAD_START -->
{"actions":{"A":"COMPLETED_OWNER_RUN","B":"NOT_APPROVED","C1":"NOT_APPROVED","C2":"NOT_APPROVED","D1":"NOT_APPROVED","DR_B":"NOT_APPROVED","E1":"NOT_APPROVED","E2":"NOT_APPROVED","EMBEDDING_EVAL":"NOT_APPROVED","EMBEDDING_REBUILD":"NOT_APPROVED","EMBEDDING_SWITCH":"NOT_APPROVED","F1":"NOT_APPROVED","F2":"NOT_APPROVED","G":"NOT_APPROVED","H":"NOT_APPROVED","I_D2":"NOT_APPROVED","J":"NOT_APPROVED","K":"NOT_APPROVED"},"application_release_sha":"73b7049ee3204d5c213ad70c67db9b892aa306bf","decisions":{"approval_window":null,"canary":{"currency":null,"include_coverage_review":null,"include_query_embedding":null,"max_cost":null,"max_output_tokens_per_call":4000,"max_provider_calls":3,"price_basis":null,"selected_case":null,"synthetic_image":null},"clerk_instance":null,"embedding_policy":null,"maintenance_window":null,"ongoing_cost_policy":null,"production_host":null,"qualification_candidate_set_sha256":null,"qualification_cutoff_iso":null,"qualification_snapshot_sha256":null,"test_accounts":null},"evidence":{"public_get":{"observed_at":"2026-09-19T18:04:10.573Z","source":"OWNER_RUN_BOUNDED_SCRIPT","statuses":[200,200,200,200]}},"package_version":"2026-09-20-prep-v2","release_tooling_sha":"e300f0e2bdd6a983ef575efe28ad19472a641196"}
<!-- APPROVAL_PAYLOAD_END -->

## 7. How the Owner approves

First, choose only scopes whose required fields are complete. A is complete and its one-run approval
is consumed. C1/D1 can be considered next as read-only account inventory; B additionally requires
the Owner to confirm which ECS instance(s) may be inspected. Refer to the current package version
and payload hash, enumerate approved action IDs, target resources and UTC window, and state that
every unlisted action remains prohibited.

Native permission must still authorize Codex network access where available. The A fallback is
recorded as Owner-executed because the native dialog did not appear; it grants no reusable access.
After further read-only evidence is collected, this package will be updated to a new version/hash
with exact live resources and remaining choices. EXECUTE begins only
for action IDs the Owner then explicitly approves. Scope, target, candidate set, budget or automatic
publish behavior changes invalidate that approval and require a new package version.
