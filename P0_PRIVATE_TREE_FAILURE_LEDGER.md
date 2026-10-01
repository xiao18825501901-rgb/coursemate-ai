# P0 Private Tree Failure Ledger

Date: 2026-10-02

| Surface | Observed failure | Root cause | Fix | Regression evidence |
|---|---|---|---|---|
| New upload promptness | Upload and batch seal reached QUEUED but did not become READY within the browser journey. | New source events were reconciled only on the 300-second full-reconcile interval. | Every normal worker poll now drains only new events; full target recovery remains periodic and legacy backfill remains off. | Auto-map unit suite and private-course Chrome journey. |
| Status after batch seal | Target/job were READY while the user projection still said QUEUED. | An older future-dated document event was counted even after a newer consumed reconciliation release fence. | Reconcile and status now apply the same release-fence ordering. | Focused unit assertion: one queued event, one consumed event, READY, zero effective pending events. |
| Browser harness | The isolated E2E initially stayed QUEUED. | Its background worker was disabled. | Enable only the credential-free deterministic test worker while keeping legacy backfill disabled. | End-to-end upload to READY/tree/reload/relogin test. |

The production generator, authorization model, Map50 validator and atomic activation were reused; no second tree store or historical compaction job was introduced.

