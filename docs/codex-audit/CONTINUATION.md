# Continuation — 2026-09-19

Baseline: `fix/codex-dsh-audit-20260919`, HEAD
`9104b5ae5cc767a57d804131b01b925728552cb5`; existing audit edits retained.
Owner confirmed DSH stopped. No production, live models, Clerk sync or push.

Reproduced before edits: `test_codex_sharing.py::test_integrated_share_imports_real_file_without_embedding_call`.
Traceback: line 40, `assert sent.json()['files_copied']==1`; actual 0,
expected 1. Result: 1 failed in 5.46 seconds; isolated V3 and fake provider.

## Ordered implementation gates

1. Freeze authorized V3 versions, bytes and parsed index; verify hashes. Route
   creation must not mark snapshots ready until every file is archived.
2. Import through an explicit IngestionService snapshot method, retaining its
   upload validation, quotas, ownership and document-version triggers. Reuse
   compatible frozen index without billing. Add durable per-recipient receipt,
   file/version/chunk mapping and retry-safe history import. Do not mark joined
   until all files and history are ready.
3. Prove three-file list/content/download/retrieval, immutable copies, source
   deletion, retry, repeated join, outsider isolation and campus gate.
4. Close remaining original R01–R18 gaps with regression-first changes; preserve
   template bodies and UI design. Offline directory upstream contracts first.
5. Full isolated API/web/agent/browser verification, review, migration/rollback
   documentation and final layered completion report.

No true-model or production PASS may be inferred from local results.
