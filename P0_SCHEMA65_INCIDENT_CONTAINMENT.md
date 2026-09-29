# P0 · Schema 65 incident containment and the recovery point (2026-09-30)

This document contains the accidental-migration incident, states what was kept and
why, and records the recovery point that now exists.  It does not erase the
incident: the process violation stands.

## 1. The incident, as previously reported

`work/hybrid-p0-20260929/remote_recover.sh` sourced the deployment environment
(whose `RAG_DATABASE_PATH` names the live database) and then called
`Database(...).initialize()` intending a restored copy.  The copy path had been
exported for the review script but not for the migration call, so migration **065**
ran against the live database.

Read-only verification at the time, and re-verified in this round:

| check | value |
|---|---|
| `PRAGMA integrity_check` | `ok` |
| foreign-key violations | 0 |
| `schema_migrations` rows / max version | 65 / 65 |
| new tables from 065 | 5, all empty |
| existing tables altered | none |
| question revisions / provenance | 58 / 58, 49 READY and 9 NEEDS_REVIEW |
| JEV receipts | 117, identity and decoding unchanged |
| hybrid receipts, calls, qualifications, cards | 0, 0, 0, 0 |

065 contains only `CREATE ... IF NOT EXISTS` and one `INSERT OR IGNORE`, and the
release in service (`916b76c`) selects `schema_migrations WHERE version <= 64`, so
the migration is inert for the running code.  That makes it containable; it does not
make it correct.

## 2. The decision, and what it rests on

**Keep schema 65.**  Nothing is dropped, the migration ledger entry is not deleted,
and no older database is restored to force the number back to 64.  The decision
rests on the read-only facts above, not on a claim that no data loss occurred: a
conflicting observation would have moved this into full incident response.

## 3. The second production write is now blocked by construction

The guard that followed the incident compared the environment path with the
`--database` argument and refused when the two disagreed.  That is necessary and
not sufficient, and `app/db_target.py` replaces it:

* **two production paths that agree are still refused** -- agreement is not
  authorisation, and this is the exact condition the old rule passed;
* identity is checked rather than spelling: `realpath`, `samefile`,
  `(st_dev, st_ino)`, symlink components, hard links, path traversal and case
  aliases;
* the target must live inside an explicitly authorised work root, must exist, must
  not be reached through a symbolic link for a writable purpose, and must not be
  the copy of its own source;
* a writable purpose must declare the production paths it is checked against --
  declaring none is itself a refusal;
* the expected schema is read read-only and compared;
* `ReadOnlyDatabase.initialize()` raises, and a read-only probe uses `mode=ro` with
  `query_only=ON` rather than `immutable=1`, because the live database is in WAL
  mode and `immutable=1` would read a stale, possibly torn, image.

### Measured on the production host, against the real production path

Run as root, with no deployment environment file sourced:

| case | result |
|---|---|
| the argument alone names production | `DATABASE_TARGET_IS_PRODUCTION` |
| environment and argument **both** name production | `DATABASE_TARGET_IS_PRODUCTION` |
| environment names production while the argument names a copy | `DATABASE_TARGET_ENVIRONMENT_MISMATCH` |
| environment names a different, non-production file | `DATABASE_TARGET_ENVIRONMENT_MISMATCH` |
| a traversal path reaches production | `DATABASE_TARGET_NOT_EXPLICIT` |
| a **symbolic link** to production | `DATABASE_TARGET_IS_PRODUCTION` |
| a **hard link** to production | `DATABASE_TARGET_IS_PRODUCTION` |
| a copy outside the authorised root | `DATABASE_TARGET_OUTSIDE_ALLOWED_ROOT` |
| a path that does not exist | `DATABASE_TARGET_MISSING` |
| a writable purpose that declares no production path | `DATABASE_TARGET_PRODUCTION_PATHS_REQUIRED` |
| the wrong expected schema | `DATABASE_TARGET_SCHEMA_MISMATCH` |
| the copy declared as its own source | `DATABASE_TARGET_IS_SOURCE` |
| a distinct copy inside the root, from a declared source | **ACCEPTED** |
| the read-only probe calling `initialize()` | `DATABASE_TARGET_READ_ONLY` |
| the read-only probe issuing a write | `OperationalError` |

The live database was read-only throughout and unchanged afterwards.  Artifact:
`/srv/coursemate/validation/p0-diag/guard-check-20260929T205901Z.txt`.

## 4. The recovery point that did not exist

Before this round the newest complete backup was `coursemate-v2-20260928T200126.170700Z`,
taken 2026-09-29 04:01 -- **before** the accidental migration.  There was no
post-incident recovery point at all.

There is one now:

```
VERIFIED_BACKUP=/srv/coursemate/backups/coursemate-v2-20260929T211151.109907Z
```

Produced by the project's own `ops/production_backup_window.sh` in one writer
pause, `SHA256SUMS` verified, four SQLite snapshots at `integrity_check=ok` with
zero foreign-key violations, 850 upload files at 1 191 756 901 bytes and 16 UI
shares.  It records `releaseConfigIncluded: false`, because no release manifest was
supplied -- recorded rather than carried forward stale.

**And it was restored once**, which is what makes it a backup rather than an
archive.  `ops/restore_v2.py` published an isolated restore whose database is
identical to live on every measured fact: integrity, foreign keys, 151 tables,
schema 65, 49 READY / 9 NEEDS_REVIEW, 87 courses, 850 documents, 22 909 chunks, 117
JEV receipts, 58 provenance rows, and the uploads extract matched the manifest
exactly.  The rehearsal target was removed afterwards and the live services stayed
healthy throughout.

### What that proved about file copies

A plain `scp` of the live database, taken at the same time for an off-box copy,
**does not open**:

```
PRAGMA integrity_check -> sqlite3.DatabaseError:
  malformed database schema (akm-job-d8f8959c079a3a68e6d20bec9b2bdb6d)
```

The live file grew during the transfer, so the copy is torn.  It was deleted and
never used as a backup.  This is why the tool uses SQLite's own backup API under a
writer pause.

## 5. Three deployment defects this round found while taking that backup

All three were pre-existing and all three would have broken the deployment this
round is building toward.  They are recorded here because the backup window is what
exposed them.

1. **Release `916b76c` was deployed without the `agent-api` Node dependencies.**
   `/srv/coursemate/current/services/agent-api` had no `node_modules` and no release
   on the host had one.  The running agent process predated the cutover, so it kept
   serving until the backup window stopped it; the restart then crash-looped with
   `ERR_MODULE_NOT_FOUND: cors`.  Repaired by installing exactly what the release's
   own `package-lock.json` pins (`npm ci --omit=dev --workspace @coursemate/agent-api`),
   with the release directory restored to mode 555; verified healthy afterwards.
2. **Every ops shell script shipped with CRLF endings**, so
   `production_backup_window.sh`, `backup_v2.sh`, `restore_v2.sh`, `monitor_v2.sh`
   and `production_switch_four_changes.sh` could not run at all: bash reads
   `set -euo pipefail` as an option named `pipefail\r`.  A wrapper that silently
   cannot run is worse than a missing one.  `.gitattributes` now forces `eol=lf`.
3. **The backup tool needed Python 3.11** (`datetime.UTC`) while its wrapper uses
   the host's 3.10.  It now uses `timezone.utc`, and this round's backup was taken
   through the documented wrapper with the host interpreter, which is the proof.

## 6. Still unverified

* No restore of the **failing** disk or a corrupt database has been rehearsed; what
  is proved is that the unit restores to an identical database.
* The pre-incident backup was not re-verified row by row against today's live data,
  so no statement is made about what an incident-time rollback would have lost.
* Production still runs `916b76c` at schema 65.  No cutover has happened, and
  migration 066 has not been applied there.
