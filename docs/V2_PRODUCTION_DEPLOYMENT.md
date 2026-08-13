# CourseMate AI V2 Production Deployment Runbook

## Current verified state

As of 2026-08-13, production deployment was **not executed**. Attempts to reach `qqttai.com`, its
about page and the documented API health hosts failed from this environment (connection/DNS). No
SSH credential, Netlify connector, server inventory, systemd/Caddy configuration or redacted
production environment was available. Tracked `netlify.toml` and `render.yaml` are configuration
artifacts only; they do not establish the live runtime.

The requested actual topology is:

```text
qqttai.com -> Netlify static React build
api/rag hosts -> Alibaba Cloud Hong Kong -> Caddy TLS/reverse proxy
                                      -> systemd RAG and Agent services
                                      -> persistent SQLite databases/uploads
```

An operator must reconcile this with the live server before using commands below. Do not replace a
working Alibaba topology with the stale Render blueprint merely because it exists in Git.

## Pre-deploy evidence gate

- Record current production commit, service/unit names, bind ports, Caddy sites, UFW rules, disk
  paths and redacted environment-variable **names**.
- Rotate the previously at-risk model credential and place only the replacement in backend secrets.
- Verify Clerk production issuer/keys and `ADMIN_USER_IDS` without printing values.
- Confirm provider account region, endpoint, chat/embedding/tool models and data-governance approval.
- Capture baseline health, p50/p95, errors, disk/free space, row/file counts and current backup age.
- Create and restore-test a consistent RAG DB/Agent DB/uploads snapshot using `ops/backup_v2.sh` and
  `ops/restore_v2.sh`.
- Run dependency audit and the complete commands in `V2_TEST_REPORT.md` on the release commit.

## Staged deployment

1. Build immutable frontend/backend artifacts from the reviewed commit.
2. Deploy backend code with public course creation/publication access operationally restricted to an
   internal test account if no feature-flag service exists.
3. Stop both writers, take a final backup, start one RAG and one Agent instance, and let their
   idempotent initializers run.
4. Verify both `/health` endpoints return 200, RAG schema versions 1-10, Agent schema version 1,
   eight activity triggers, integrity/FK checks and
   pre/post row/file counts.
5. Smoke one official course, Chinese general greeting, exact locator, history reload, Agent task,
   private A/B isolation, private upload/profile and publication reject/approve/unpublish.
6. Deploy Netlify with production `VITE_*` endpoints and Clerk publishable key; never backend keys.
7. Observe an internal account for 24 hours, then expand gradually only if error rate is within 10%
   and p95 latency within 20% of baseline with no new security/data-integrity issue.

## Health and smoke commands

Use the actual hostnames discovered in the evidence gate:

```bash
curl --fail --silent --show-error https://<rag-host>/health
curl --fail --silent --show-error https://<agent-host>/health
systemctl status <rag-unit> <agent-unit> --no-pager
journalctl -u <rag-unit> -u <agent-unit> --since '-15 min' --no-pager
sqlite3 <rag-db> 'PRAGMA integrity_check; PRAGMA foreign_key_check; SELECT version,name FROM schema_migrations ORDER BY version;'
sqlite3 <agent-db> 'PRAGMA integrity_check; PRAGMA foreign_key_check; SELECT version,name FROM schema_migrations ORDER BY version;'
```

Both health endpoints return 503 with a generic `unavailable` body when their persistent state is
not ready. A 200 therefore proves required migrations are queryable; RAG additionally requires its
upload directory. It does not prove provider quality or every downstream dependency.

Run backup and isolated restore from a protected operator shell while both writers remain stopped:

```bash
RAG_DATABASE_PATH=<rag-db> AGENT_DATABASE_PATH=<agent-db> \
RAG_UPLOAD_DIR=<upload-dir> BACKUP_ROOT=<dedicated-backup-root> ./ops/backup_v2.sh
RESTORE_SOURCE=<completed-backup-dir> RESTORE_TARGET=<new-empty-path> ./ops/restore_v2.sh
```

Keep values out of tickets and logs when paths disclose tenancy or infrastructure details. Never
use a `.partial` directory as a restore source.

Run the secret-free monitoring probe from a systemd timer/cron job and alert on exit code 2:

```bash
RAG_HEALTH_URL=https://<rag-host>/health AGENT_HEALTH_URL=https://<agent-host>/health \
BACKUP_ROOT=<dedicated-backup-root> RAG_UPLOAD_DIR=<upload-dir> ./ops/monitor_v2.sh
```

It emits one JSON record with generic health results/latencies, completed-backup age and free bytes.
Defaults are a 5-second request timeout, 26-hour maximum backup age and 1 GiB minimum free space;
override `HEALTH_TIMEOUT_SECONDS`, `MAX_BACKUP_AGE_SECONDS` and `MIN_FREE_BYTES` to match the approved
SLO/capacity plan. HTTP is rejected unless `ALLOW_INSECURE_HEALTH_URLS=1` is set for local testing.
Do not expose this output publicly. Separately alert on service error rate, p95 latency, ingestion
failure rate and repeated 429 responses from the production log/metrics platform.

Do not put tokens or secrets on shell command lines/history. Authenticated smoke requests should use
a short-lived token supplied by a protected environment/secret mechanism and redact response logs.

## Rollback triggers and procedure

Rollback immediately for integrity/FK failure, private data exposure, citation/source corruption,
new critical/high vulnerability, error rate above 2x baseline or p95 latency above 50% baseline.

1. Remove traffic/stop the new writer.
2. Redeploy the prior known-good commit/artifact.
3. If V2 writes occurred or counts changed unexpectedly, restore both pre-release DBs and uploads as
   one verified unit; otherwise retain additive columns and verify the prior binary tolerates them.
4. Re-run health, integrity, owner isolation and official QA smoke tests before reopening traffic.
5. Preserve logs/evidence and write an incident review; never “repair” private ownership rows by hand.

## Release verdict

Local source gate: **PASS**. Migration rehearsal: **PASS on local copy**. Production deploy/smoke:
**BLOCKED by missing access and unreachable endpoints**. Acceptance N remains not passed.
