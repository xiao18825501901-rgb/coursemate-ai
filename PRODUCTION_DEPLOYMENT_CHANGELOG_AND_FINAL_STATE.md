# Production Deployment Changelog and Final State

## 2026-08-13 V2 release candidate

- Implemented durable multilingual tutor conversations, deterministic intent/routing/rewrite,
  exact-question retrieval, deeper teaching policy and reproducible evaluation.
- Added independent provider roles and a fail-closed 50-case benchmark harness; no paid benchmark or
  provider switch was performed.
- Added private user courses, secure ingestion/deletion, teaching-profile versions/prompt builder,
  dual-consent administrator publication and post-review mutation locking.
- Added schema versions 5-7, SQL record, migration-on-copy evidence and backup/isolated-restore tools.
- Passed the complete local source/build/browser gates recorded in `docs/V2_TEST_REPORT.md`.

## Final production truth

`qqttai.com` production was not changed or verified by this work session. Network probes failed and
no production control-plane/server access was supplied. The live commit, model/provider, database,
service units, Caddy rules, backups and observability therefore remain unknown. Use
`docs/V2_PRODUCTION_DEPLOYMENT.md` to collect that evidence and deploy safely. This file supersedes
no real server evidence; append verified deployment facts here only after a successful smoke test.
