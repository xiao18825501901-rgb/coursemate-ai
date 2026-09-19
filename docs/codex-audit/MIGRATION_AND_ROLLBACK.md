# Migration and rollback — local audit candidate

## 2026-09-20 long-name fix

Candidate `73b7049` adds no Schema migration. New private IDs are39-character ASCII UUIDs satisfying the old domain constraint; existing IDs and share-derived IDs are not rewritten. Code rollback preserves already-created courses/references and reintroduces the creation defect; do not regenerate IDs or delete data. This says nothing about migration requirements from the actual production version: RAG initialization happens before the UI feature flag check, so a disabled UI does not make startup read-only. Production inventory, consistent backup, isolated migration and exact rollback approval remain mandatory. See cards H/I in [PRE_DEPLOYMENT_ACCESS_AND_APPROVALS.md](PRE_DEPLOYMENT_ACCESS_AND_APPROVALS.md).

## 2026-09-20 continuation (supersedes historical recovery limits below)

Implementation `dcfd322`: no new RAG/UI schema migration. New share manifests add frozen `send_recovery.version=1` recipient intent; a data-directory process-owned lock excludes sends/recovery. The CLI in `app.cm_update.share_recovery` defaults to inspect and accepts `--apply` only for explicitly chosen recovery data. Complete verified archives can finish; incomplete ones remain unannounced/failed. Old PREPARING without frozen intent is refused, not guessed. Upgrade all send workers before using the recovery CLI; an old binary does not participate in the lock. Cancellation waits for actual file I/O, not merely a cancelled task wrapper.

Windows final restore publication now allows at most 5 attempts/1.5 seconds total waiting only for WinError5/32, logging each denial. Safe staging preservation, all byte/tree/DB checks and atomic no-overwrite remain. New first-command and explicit resume tests pass. Original denial source is still UNKNOWN. Real Linux WSL ext4 tests pass; DrvFS returned EINVAL and is not a valid rehearsal filesystem. This is not production validation.

Keep the complete pre-change recovery unit before real deployment. Code rollback does not revoke already committed notices, undo joined courses or erase later writes. Stop/quiesce the whole send-worker set before changing lock protocol versions; never delete an active lock file. No real database, uploads or production migration was changed in this continuation. Details and exact evidence: [RECOVERY_GATE_AND_REMAINING_STATUS.md](RECOVERY_GATE_AND_REMAINING_STATUS.md).

## Historical audit state

Date: 2026-09-19. No production database or unique real database was migrated.
All executions used newly created synthetic databases under `work/codex-audit`.
The owner confirmed DSH stopped; existing DSH commits were retained.

## Changes and evidence boundary

RAG migrations through `025_campus_display_and_verification.sql` are unchanged.
Node/file copies use existing V3 structures, upload policy and version triggers.
UI schema advances from 6 to 11 in `app/cm_update/db.py`:

| Version | Change | Data preservation |
|---|---|---|
| 7 | Verification HMAC + opaque code ID | Retains used/disabled code records and redeemed-owner tombstones; plaintext logical columns/attempts removed or redacted |
| 8 | Share import receipts | Durable per-share/recipient course ID, status and document/version/chunk mapping |
| 9 | Registered directory projection | Opaque public IDs; local privacy/block/qualification choices retained |
| 10 | First-node start receipts | One initial teaching claim per owner/course/node |
| 11 | Frozen message attachments | Recipient-owned remapped attachments persist independently of provider/run rows |

The schema-6 synthetic migration regression verifies repeated initialization,
leading zeros, HMAC lookup, retained tombstones and refusal without a configured
key. Table replacement is transactional, but bootstrap CREATE IF NOT EXISTS may
have already added empty tables before a migration error. Do not describe the
entire initialize operation as one cross-schema atomic transaction.
Logical redaction does not erase old SQLite free pages, WAL files or backups.
Treat all legacy copies as sensitive. Never log the verification secret.

Directory/grandfather/action/classification receipts use the existing meta table.
No directory sync or real eligibility change was executed. Production startup
must not pretend a completed protected registration snapshot exists.

## Required future release procedure (not authorized/executed here)

1. Identify actual deployment commit, processes and all authoritative data paths.
   Quiesce writers for a consistent multi-database/file recovery unit. A SQLite
   backup per database alone is not an atomic distributed snapshot.
2. Back up RAG DB, Agent DB, originals, UI DB, UI uploads **and UI shares**. The
   backup script includes `ui-shares.tar.gz` only when that directory exists;
   restore remains compatible with old units without it.
3. Keep the old runtime/configuration and protected verification HMAC secret.
   Record checksums and storage locations privately, not in Git.
4. Restore into a new isolated directory, never over an existing target. Verify
   integrity/foreign keys, file counts/bytes/hashes, owner isolation and all
   forward migrations. Disable real model, Clerk and outbound message effects.
5. Rehearse the upgrade using that copy; retain pre-upgrade counts and ownership
   invariants. Do not edit migration numbers or rebuild the real database.
6. Only with separate approval switch code and all data paths together. Run
   production smoke checks with an explicit budget and synthetic accounts.

## Restore publication failure and resume

Windows may reject directory publication while a descendant is open. Regressions
reproduce WinError 5 with a real handle; a separate intermittent denial can remain
after that handle closes. The original locking process is **unknown**. No global
antivirus/security setting was changed and no sleep/retry hides failures.

`ops/restore_v2.py` preserves `.TARGET.<uuid>.partial` on failure. Resolve the
lock/permissions without modifying contents. Keep RESTORE_SOURCE and
RESTORE_TARGET unchanged; explicitly set RESTORE_RESUME_PARTIAL to that exact
reported sibling. Resume rechecks source checksums, staged DB hashes/integrity,
every archive-derived tree and byte hash, rejecting extra/missing/modified files,
symlinks/reparse points/hardlinks and existing targets. It attempts publication
once and never overwrites a racing destination. Linux renameat2 has mock-contract
coverage only in this Windows run; Linux runtime rehearsal remains required.

The original backup publication can also encounter WinError 5. A backup left
`.partial` is not accepted as a completed recovery unit. Preserve it for diagnosis;
resolve the cause and create a new verified backup before any production action.

## Rollback boundary

The old UI binary refuses a newer schema. **Do not merely downgrade the version
marker, delete new tables, or run old code over the migrated database.** Before
accepting new writes, roll back by restoring the complete verified pre-upgrade
recovery unit to a new directory and switching to the matching old binary/config.
If post-upgrade writes exist, stop and reconcile those records explicitly first;
blind restoration would lose them. Keep both sets private and recoverable.

Snapshot import is a resumable saga, not a cross-database transaction: course and
some files can exist while receipt is IMPORTING/FAILED_RETRYABLE. Only all files,
knowledge/history remapping and receipt completion mark the recipient joined.
A caught send failure can resume the frozen manifest with the same request ID.
A process killed while send status is PREPARING requires a controlled stuck-build
recovery decision; do not re-create a live manifest or publish incomplete files.
