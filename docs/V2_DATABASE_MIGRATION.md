# V2 Database Migration and Recovery

## Migration model

`app.db.Database.initialize()` is the executable source of truth. It inspects `PRAGMA table_info`,
adds missing fields, creates tables/indexes, repairs null legacy timestamps and records versions.
`services/rag-api/migrations/005_007_v2_course_platform.sql`, `008_user_course_storage_quotas.sql`,
`009_course_language_preference.sql`, and `010_course_activity_timestamps.sql` are the
operations-readable SQL records;
it is not blindly runnable because SQLite lacks portable `ADD COLUMN IF NOT EXISTS`.

Versions 1-4 add conversation ownership/history/routing and structured chunk metadata. V5 adds
course owner/type/visibility/update fields, V6 teaching profiles and conversation profile pinning,
V7 publication state/audit records, V8 document byte accounting, V9 the course language default,
and V10 activity timestamp triggers.
Existing courses become official/public/published; existing
documents, chunks, embeddings, conversations, messages and IDs remain.

## Rehearsal evidence

An ignored copy of the local RAG database was initialized twice. Both runs completed with schema
versions 1-10, eight activity triggers, `PRAGMA integrity_check = ok`, no `foreign_key_check` rows,
and unchanged core counts: 3 courses, 67 documents, 1,937 chunks, 19 conversations and 38 messages.
New profile/publication
tables were empty. This verifies additive/idempotent behavior against the available local data; it
does not prove the unknown production database.

A second, full local recovery rehearsal used the current executable scripts and a later local
checkpoint. The backup contained the RAG database, an Agent database, and 68 uploaded files
(124,209,844 bytes). The RAG source/backup/restore copies matched at 3 courses, 67 documents,
1,937 chunks, 27 conversations and 62 messages; the Agent backup/restore copies matched at 2 tasks.
Both restored databases reported `integrity_check = ok`, zero foreign-key violations and the
expected migration versions (RAG 1-10; Agent 1). Every restored upload path and SHA-256 matched the
source. The Agent source was the latest completed deterministic E2E database because this checkout
does not contain a durable production Agent database; this is local recovery evidence only.

## Production procedure

1. Put the release in maintenance/read-only mode and record current commit/service/env names without
   printing values.
2. Run `ops/backup_v2.sh` with explicit `RAG_DATABASE_PATH`, `AGENT_DATABASE_PATH`,
   `RAG_UPLOAD_DIR`, and `BACKUP_ROOT`. The script uses SQLite online backup for both databases,
   archives uploads without following symlinks, verifies both SQLite copies, writes a versioned
   manifest and SHA-256 set, and publishes only by atomic rename. Preserve the completed output
   directory in access-controlled, immutable off-host storage.
3. Run `ops/restore_v2.sh` into a new isolated directory and start the release against that copy.
4. Initialize twice; verify integrity/foreign keys, versions, row counts, FTS count, document hashes
   and the presence/count of uploaded files.
5. Run deterministic health/auth/private-isolation/conversation/exact-locator/publication smoke tests.
6. Stop the service, take a final consistent backup, deploy code, start one instance and migrate.
7. Verify counts and smoke tests before enabling normal traffic.

Do not copy only the main SQLite file while a live WAL database is active. Use SQLite online backup
or stop the writer and treat database/WAL/SHM consistently. Uploads and DB must be restored from the
same maintenance checkpoint. A hidden `.partial` directory means the operation failed and is not a
usable backup or restore; inspect it without exposing private data, then remove it according to the
incident/evidence policy.

`ops/restore_v2.sh` refuses an existing target and a target inside the backup. It validates the
complete checksum set, manifest version/count/byte totals, rejects duplicate/traversal/symlink or
special archive members, and rechecks both databases before atomically publishing the isolated
restore. Checksums detect corruption but are not signatures: access to the backup store must remain
restricted and tamper-evident.

## Rollback

On integrity, authorization, citation or error-rate failure, stop the new writer, deploy the prior
commit and restore the verified pre-release RAG database, Agent database and uploads as one unit. Do not attempt to
drop additive columns in place. If no V2 writes occurred, the prior binary can ignore additive
schema; once V2 user/profile/publication writes exist, use the full snapshot restore.
