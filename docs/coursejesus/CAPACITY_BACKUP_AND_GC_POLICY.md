# Capacity, backup, and garbage-collection policy

Policy date: 2026-09-28

## Admission formula

For every filesystem used by upload, extraction, database rehearsal, restore,
cache hydration, build, or deployment:

```text
reserve = max(10 GiB, 20% of filesystem capacity)
admit only when free - outstanding reservations - task peak >= reserve
```

`task peak` includes the compressed source, extracted bytes, temporary parser
output, database/WAL growth, index growth, build output, and recovery copy that
coexist at the high-water mark. Unknown peak means the task is not admitted.
Reservations cannot be negative and must be released on success or failure.

The storage cache has a 10 GiB default ceiling but never overrides the reserve
formula. Range preview bypasses full-object cache hydration. A parser may
hydrate a full object only after reserving its expected peak.

## Verified production capacity

Read-only sample at `2026-09-27T19:31:05Z`:

| Item | Bytes |
|---|---:|
| Root filesystem total | 41,882,943,488 |
| Root filesystem used | 38,975,713,280 |
| Root filesystem available | 971,333,632 |
| Required reserve | 10,737,418,240 |
| Shortfall before task peak | 9,766,084,608 |
| `/srv/coursemate/backups` | 11,703,298,001 |
| `/srv/coursemate/releases` | 3,161,323,842 |
| `/srv/coursemate/data` | 2,009,266,530 |
| `/srv/coursemate/staging` | 1,188,060,982 |
| `/var/lib` | 1,178,750,727 |
| `/srv/coursemate/logs` | 172,143,718 |
| `/srv/coursemate/cache` | 228,909,109 |

Therefore backup creation, schema rehearsal, bulk extraction, cache warming,
large copy, deployment, and production compaction are rejected. The figures do
not authorize deleting any of the listed directories.

## Recovery unit requirements

A recoverable backup unit contains a consistent SQLite database (including any
required WAL checkpoint procedure), immutable file/object manifest, application
and schema identities, `manifest.json`, and `SHA256SUMS`. Every regular file in
the unit must appear exactly once in `SHA256SUMS`; extra files, symlinks,
directories, unsafe names, missing hashes, or mismatches fail archival.

OSS archival writes each artifact to an immutable content-addressed object and
writes a separate receipt. Acceptance requires an isolated restore that reads
every byte, recomputes every SHA-256, and remains above the restore filesystem's
reserve. An upload success or HTTP 200 alone is not recovery evidence.

Maintain at least:

- one pre-migration local recovery unit;
- one verified OSS archive of that unit;
- one post-migration recovery unit after reconciliation;
- the immutable receipts and application/schema versions for each.

## Garbage-collection eligibility

| Class | Automatic deletion allowed? | Required evidence |
|---|---|---|
| Canonical original | No | Per-object OSS verification, references, isolated restore, separate backup, fallback, retention approval |
| SQLite database/WAL | No | Controlled database backup/restore and an explicit retired-generation decision |
| Only known backup | No | A second independently restored recovery point |
| Active release | No | New release accepted and rollback window elapsed |
| Old release | Manual only | Not active, no rollback reference, artifact digest retained |
| Quarantine upload | Lifecycle/manual | Terminal receipt, no document/version reference, retention elapsed |
| Incomplete multipart parts | Lifecycle | Upload is not active and provider abort-age rule elapsed |
| Parse cache | Bounded LRU/manual | No active lease; reserve and recovery source remain valid |
| Model artifact/UNKNOWN receipt | No | Immutable billing/reconciliation retention policy |
| `D:\Canvas` or `D:\Canvas-DG` | Never in this workflow | Owner originals are expressly out of scope |

Garbage collection is mark-and-sweep over immutable identities. The mark set
includes document versions, citation refs, share snapshots, problem/assessment
attachments, backup manifests, active/retained releases, model ledgers, and any
open lease. A sweep is dry-run first, stores the candidate list and hash, then
requires a separate explicit execution. `ossutil sync --delete` is prohibited.

## Failure behavior

- Capacity rejection occurs before extraction, model work, or a large copy.
- A failed upload preserves its scoped receipt and does not enqueue ingestion.
- A failed migration keeps local storage authoritative and records the error.
- A failed restore invalidates that recovery unit; it is never used to justify
  local deletion.
- A failed compaction keeps the old effective tree active and preserves paid
  and `UNKNOWN` model evidence.
