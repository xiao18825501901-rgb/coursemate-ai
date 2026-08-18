# CourseMate AI V2 Security Review

Reviewed: 2026-08-13. Scope: source branch and isolated local tests; not a production penetration
test.

## Controls verified

- Clerk bearer authentication is independently verified by both APIs; test identity is fail-closed
  to `APP_ENV=test` plus deterministic providers.
- Central course authorization hides foreign private resources and applies to course/document/job,
  QA/conversation, profile and publication operations.
- Conversations and Agent tasks are owner-scoped; list/detail/mutation paths are tested with two
  identities.
- Publication requires dual consent plus administrator approval; published owner mutations are
  locked until administrator unpublish.
- JSON bodies are strict and bounded; file extension/size/hash/path rules protect ingestion.
- Course/file/owner-byte quotas are configurable and checked atomically; user storage namespaces use
  opaque owner hashes and server-generated document names.
- SQL uses parameters. SQLite foreign keys, busy timeout, WAL and indexes are configured.
- CORS accepts one configured origin. RAG emits HSTS in production plus a deny-all API CSP,
  nosniff, frame-deny, no-referrer and restrictive Permissions Policy. Agent uses Helmet/HSTS,
  restrictive Permissions Policy and request limits. Netlify emits HSTS, nosniff, frame-deny,
  no-referrer and restrictive Permissions Policy for the static frontend.
- Model/provider secrets are backend-only `SecretStr`/environment values. Tracked-source scans found
  no credential-pattern match. API models exclude stored paths and sensitive owner/reviewer IDs.
- Course content, history, profile notes and model outputs are treated as untrusted at the prompt and
  typed boundary.
- QA and Agent model calls have per-owner minute limits; Agent tool rounds and body size are bounded.
- Health checks fail closed on missing schema migrations; the RAG database probe is read-only and
  cannot recreate a missing database. Backup/restore covers both databases and uploads with
  checksums, safe archive extraction, SQLite integrity/FK checks and non-overwrite semantics.

## Required production gates

1. Revoke/rotate any model credential that may have been exposed during local testing, then update
   only the backend secret store. Never paste the replacement into Git, logs or this report.
2. Confirm exact `WEB_ORIGIN`, Clerk production keys, administrator IDs, database/upload paths and
   provider region/model through redacted runtime inspection.
3. Verify Caddy TLS/header behavior does not weaken or duplicate application headers, configure
   request/body limits and log redaction, and verify UFW exposes only SSH, HTTP and HTTPS as intended.
4. Run dependency vulnerability checks in the deployment network and resolve critical/high findings.
5. Schedule `ops/monitor_v2.sh` for API health/latency, disk and completed-backup age, and alert on
   its nonzero exit. Configure error-rate, p95 latency, repeated-429 and ingestion-failure alerts in
   the production log/metrics platform; those require live runtime integration.
6. Do not expose the populated local course corpus unless rights are confirmed.
7. Add a frontend CSP only after the exact production Clerk, RAG and Agent origins are known; then
   smoke login, token refresh and both APIs. A guessed CSP can break authentication or create an
   unsafe wildcard policy.

## Accepted/known limitations

- RAG rate limiting is per authenticated owner but not a distributed global limiter; multiple API
  replicas need shared enforcement.
- SQLite is suitable for this deployment shape but needs one-writer-aware capacity monitoring.
- Publication audit data cascades on course deletion and is not an immutable legal ledger.
- Live model quality/security behavior is unknown until an approved benchmark and canary.

## Incident prevention lesson

Configuration tests must explicitly replace provider environment variables with inert placeholders.
Assertions must never render secret-bearing settings or client objects. A credential inherited from a
developer shell can otherwise appear in a failure report even when production code uses secret
types. This rule is now part of the handoff and global pitfall record.
