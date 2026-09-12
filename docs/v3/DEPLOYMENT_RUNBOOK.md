# CourseMate V3 — Deployment Runbook

Version: Stage 8 gated handoff, 2026-09-12.

This runbook prepares a reversible V3 release; it is not proof that a deployment occurred. Current production release, provider, region, database versions, backup health, Netlify/Clerk configuration and smoke status are **UNKNOWN — REQUIRES OWNER VERIFICATION**. No production write or paid model call was executed during Stages 0–8.

## 1. Current release evidence

```text
Branch: feature/coursemate-v3-persistent-learning
Stage 8 implementation SHAs: 2bec11d, 7c6c54c
Source scope: Stages 1–8 implemented for their recorded slices; listed product gaps remain
V3 Schema in source: 1–21
Local real RAG DB: 1–18 after documented E2E isolation incident/recovery; 019–021 not executed there
Real-RAG-copy migration: 1–18 to isolated 1–21 PASS; active source unchanged
Complete current two-DB/uploads restore: BLOCKED / NOT VERIFIED — authoritative Agent DB absent/unknown
Local tests: Python 327; Web 49; Task Agent 66; V3 Playwright 3; independent V2 Playwright 4; npm audit 0
Live qwen3.8-max: NOT VERIFIED
Production: NOT VERIFIED
```

Do not label this branch production-accepted while the complete current restore gate, live model review and production smoke remain incomplete. It may be deployed only to an explicitly isolated preview/staging environment after the gates below pass.

## 2. Hard stop conditions

Stop before any production mutation if any item is unknown or failed:

- exact backend and frontend release SHA;
- resolved RAG DB, Task Agent DB, upload root and backup destination paths;
- current Schema, SQLite integrity/FK result and active writer inventory;
- a complete, recent backup restored successfully into new isolated paths;
- Clerk issuer/audience and exact allowed Web/API origins;
- provider endpoint, workspace/region, model entitlement, budget and owner approval;
- error/latency/disk/backup-age monitoring and an operator able to disable both V3 flags;
- zero unresolved critical/high reachable dependency vulnerabilities;
- two-user/Admin authorization and accessibility acceptance for the release candidate.

Never use `git pull` in an unknown live directory, copy only a live SQLite main file while ignoring WAL, point a test runner at production, rebuild/drop the database, or expose private evidence in logs/screenshots.

## 3. Evidence Owner must collect

Store redacted evidence outside the repository and never include keys, tokens, database files, uploads, prompt bodies or user records:

```text
timestamp and operator
GitHub release/commit SHA
backend host/service/release SHA
Netlify site/deploy SHA and API origin
Clerk instance domain, authorized origins and test-user roles
provider model ID, protocol, endpoint host and region/workspace label
database versions, integrity/FK and aggregate row counts
upload file count/bytes and manifest digest
backup ID/time plus isolated restore result
health/error-rate/p50/p95/disk/backup-age baseline
feature-flag values and rollback owner
```

Historical V2 reports and `render.yaml`/`netlify.toml` are configuration intent, not current runtime evidence.

## 4. Local release gate

Run from a clean, reviewed checkout while preserving Owner files. Do not use `git add .`.

```powershell
git status --short --branch
git rev-parse HEAD

Set-Location services/rag-api
.venv/Scripts/python.exe -m pytest -q -o cache_dir=../../work/pytest-cache
.venv/Scripts/python.exe -m ruff check app tests ../../scripts
.venv/Scripts/python.exe -m mypy app ../../scripts/run_model_benchmark.py ../../scripts/run_v3_model_canary.py
Set-Location ../..

npm --workspace @coursemate/web test
npm --workspace @coursemate/agent-api test
npm run typecheck
npm run build
npm audit --json
npm audit --omit=dev --json
npm run test:e2e
npm exec playwright test -- --config=playwright.v3.config.ts
```

The default Playwright config must print a database under `work/e2e-rag-*` and run only `coursemate.spec.ts`. The V3 config must run only `learning.spec.ts` and start owner, second-user and Admin identities against one synthetic database. Abort if a server environment lacks explicit `RAG_DATABASE_PATH` and `RAG_UPLOAD_DIR`. Record the active local DB/upload hashes before and after; they must match.

Also run a fresh migration rehearsal target and keep only content-free aggregate evidence:

```powershell
services/rag-api/.venv/Scripts/python.exe scripts/rehearse_v3_migration.py `
  --source data/rag.sqlite3 `
  --target work/v3-migration-rehearsal-stage8-<unique-id>
```

Expected: the source is opened read-only, the isolated target initializes twice to continuous versions 1–21, old-row fingerprints/counts remain unchanged, `integrity=ok`, FK 0 and every V3 invariant is true. This is not the full two-database/uploads restore gate.

## 5. Live-model canary gate

This section is executable preparation, not authorization. The Owner must first verify in Alibaba Cloud that the exact account/workspace, region, endpoint, `qwen3.8-max` entitlement, image input, Responses API, streaming, tool calling, quota and current input/output prices apply to that endpoint. Never paste the API key, private image, raw provider body or student material into ChatGPT or Git.

Use a new, non-private synthetic PNG/JPEG that visibly contains a tiny question such as `2 + 3 = ?`. The V3 canary always includes the image call. The smallest selection is therefore 3 calls: one Planner, one Teacher and one Problem image call. Preflight reads no key, constructs no client and makes no call:

```powershell
services/rag-api/.venv/Scripts/python.exe scripts/run_v3_model_canary.py `
  --base-url "<owner-verified-model-studio-compatible-mode-endpoint>" `
  --api-key-env "COURSEMATE_V3_CANARY_KEY" `
  --image "<absolute-path-to-synthetic-png-or-jpeg>" `
  --output "work/benchmarks/v3-qwen38-small-<unique-id>.json" `
  --case-id "cs-case-a" `
  --input-price-per-million <verified-current-input-price> `
  --output-price-per-million <verified-current-output-price> `
  --max-cost <owner-approved-maximum> `
  --currency <ISO-4217-code> `
  --max-provider-calls 3 `
  --preflight-only
```

After the Owner checks the printed ceiling and separately authorizes that exact spend, set `COURSEMATE_V3_CANARY_KEY` only in the private shell, use a new output path, remove `--preflight-only`, and add both `--allow-billable` and `--confirm-synthetic-image`. There is no automatic retry or resume. Preserve any checkpoint after failure and ask before another paid attempt. The full four-major matrix omits `--case-id` and uses `--max-provider-calls 17`.

Test Responses streaming with exactly `zh-01` and multi-round tools with exactly `tool-03`; these use fixed synthetic prompts and content-free simulated tool results, so they do not mutate the Task database. First run each command with `--preflight-only`; only after separate approval replace it with `--allow-billable`:

```powershell
services/rag-api/.venv/Scripts/python.exe scripts/run_model_benchmark.py `
  --provider "alibaba-model-studio" --model "qwen3.8-max" `
  --base-url "<owner-verified-model-studio-compatible-mode-endpoint>" `
  --api-key-env "COURSEMATE_V3_CANARY_KEY" `
  --output "work/benchmarks/qwen38-stream-<unique-id>.json" `
  --case-id "zh-01" `
  --input-price-per-million <verified-current-input-price> `
  --output-price-per-million <verified-current-output-price> `
  --max-cost <owner-approved-maximum> --currency <ISO-4217-code> `
  --preflight-only

services/rag-api/.venv/Scripts/python.exe scripts/run_model_benchmark.py `
  --provider "alibaba-model-studio" --model "qwen3.8-max" `
  --base-url "<owner-verified-model-studio-compatible-mode-endpoint>" `
  --api-key-env "COURSEMATE_V3_CANARY_KEY" `
  --output "work/benchmarks/qwen38-tool-<unique-id>.json" `
  --case-id "tool-03" `
  --input-price-per-million <verified-current-input-price> `
  --output-price-per-million <verified-current-output-price> `
  --max-cost <owner-approved-maximum> --currency <ISO-4217-code> `
  --preflight-only
```

The specialized artifact records the fixed dataset hash, endpoint category, image hash/size, Owner-supplied price basis, preflight ceiling, usage, structured outputs and manual rubric. Automated success remains `PENDING_HUMAN_QUALITY_REVIEW`. The Owner must review every selected result for domain accuracy, teaching depth, grounding, language/preference adherence, visual transcription/signs and uncertainty. Only a completed, dated human record may support `LIVE_MODEL_VERIFIED`; it still does not prove production.

## 6. Complete backup and isolated restore gate

First discover actual production paths; do not copy examples as facts. Drain public writes and confirm ingestion/model finalization is idle. Then run the repository backup with explicit environment values on the production host:

```text
RAG_DATABASE_PATH=<verified-rag-db>
AGENT_DATABASE_PATH=<verified-agent-db>
RAG_UPLOAD_DIR=<verified-upload-root>
BACKUP_ROOT=<verified-dedicated-backup-root>
```

Use `ops/backup_v2.py`/platform wrapper, verify the completed manifest/checksums, and copy the recovery unit to protected off-host storage. Restore with `ops/restore_v2.py` into a new empty isolated directory. Boot the candidate only against restored paths, initialize twice, and verify:

- both DBs: integrity `ok`, FK 0 and expected migration versions;
- protected aggregate counts and deterministic fingerprints unchanged;
- every referenced original/artifact exists and matches its recorded size/hash;
- V2 flag-off smoke and V3 owner-only smoke both pass;
- the restore target can be discarded without touching live paths.

If the Task Agent DB is not deployed, prove that fact from current runtime configuration; do not invent a dummy DB and call the backup complete.

Current local checkpoint: `data/agent.sqlite3` is absent and no repository/runtime evidence accessible to this task identifies another authoritative Agent runtime DB. Disposable `work/agent-smoke.sqlite3` and `work/e2e-agent-*` files are not admissible substitutes. The backup preflight failed safely with exit 2 before creating its destination. Therefore stop here until the Owner/runtime identifies the actual path or proves that this release has no persistent Agent DB. This blocker does not invalidate the successful RAG-only 1–18 → 1–21 copy rehearsal, but it prevents complete restore acceptance.

## 7. Staged rollout

1. Deploy reviewed backend code with `V3_ENABLED=false`; keep the current Web V3 navigation off.
2. Verify `/health`, V2 QA/citation/history/private-course and Task Agent flows with real Clerk identities.
3. Drain writes, take the final verified backup, apply 011–021 once from one backend instance, then re-run Schema/integrity/count/publication/budget-reservation checks.
4. Enable backend V3 only for an Owner/internal canary. Confirm generic Admin cannot access private workspace/Assessment data.
5. With explicit budget, run the smallest live `qwen3.8-max` text/structured/image/stream canaries and record exact model/protocol/region/usage. Do not retry unknown paid outcomes automatically.
6. Deploy Web with `VITE_V3_ENABLED=true` to preview/canary users only.
7. Run authenticated A/B/Admin smoke: join course, private source isolation, tree state, Problem full solution, Bridge/Teaching/return, five-question Assessment, practice downgrade, reload/relogin and Task Agent regression.
8. Hold and monitor before widening. Keep the flag owner and rollback procedure active until Stage 8 acceptance.

## 8. Monitoring and decision thresholds

Capture baseline and canary values for endpoint error rate, p50/p95 latency, provider failures/unknown outcomes, token/cost rate, 401/403/404 anomalies, SQLite lock time, disk free space, ingestion failures, client JS errors and backup age.

Advance only when error rate is within 10% and p95 within 20% of baseline with no new security/data-integrity issue. Hold at 10–100% error increase or 20–50% p95 increase. Disable V3 immediately for any authorization leak, integrity/FK failure, repeated duplicate charge risk, more than 2× baseline error rate or more than 50% p95 regression. Product thresholds may be stricter; current production baselines are unknown.

## 9. Rollback

| Failure | First reversible action | Data rule |
|---|---|---|
| UI/quality issue | disable `VITE_V3_ENABLED` | keep additive data/history |
| backend/provider/cost issue | disable `V3_ENABLED` or generation canary | preserve safe operation evidence; no hidden retry |
| authorization leak | disable affected routes/V3 and preserve security evidence | revoke access before cleanup; do not erase incident history |
| migration gate fails before exposure | keep writers drained and abort rollout | validate restore in isolation before any cutover |
| post-exposure corruption | stop writers; preserve DB/WAL/uploads | Owner-authorized complete snapshot restore; preserve post-backup deltas separately |

Do not drop 011–021 tables to “roll back.” Older code should ignore additive tables with V3 disabled. A database restore is a last-resort data operation requiring the exact target, verified recovery unit and Owner-controlled maintenance window.

## 10. Acceptance record

Record each layer separately:

```text
SOURCE_IMPLEMENTED: <SHA and scope>
LOCAL_CONTRACT_VERIFIED: <commands/results>
LOCAL_FAKE_PROVIDER_VERIFIED: <browser/test evidence>
LIVE_MODEL_VERIFIED: <approved canary evidence or NOT VERIFIED>
PRODUCTION_VERIFIED: <release/auth/data/monitoring smoke or NOT VERIFIED>
```

At this Stage 8 checkpoint, `LIVE_MODEL_VERIFIED` and `PRODUCTION_VERIFIED` remain `NOT VERIFIED`; the complete current restore line is also blocked as stated above. A healthy local build, fake-provider flow or migration rehearsal must never be upgraded to live-model or production acceptance.
