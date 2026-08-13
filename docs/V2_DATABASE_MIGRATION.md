# V2 Database Migration and Recovery

## Migration model

`app.db.Database.initialize()` is the executable source of truth. It inspects `PRAGMA table_info`,
adds missing fields, creates tables/indexes, repairs null legacy timestamps and records versions.
`services/rag-api/migrations/005_007_v2_course_platform.sql`, `008_user_course_storage_quotas.sql`,
and `009_course_language_preference.sql` are the operations-readable SQL records;
it is not blindly runnable because SQLite lacks portable `ADD COLUMN IF NOT EXISTS`.

Versions 1-4 add conversation ownership/history/routing and structured chunk metadata. V5 adds
course owner/type/visibility/update fields, V6 teaching profiles and conversation profile pinning,
V7 publication state/audit records, V8 document byte accounting, and V9 the course language default.
Existing courses become official/public/published; existing
documents, chunks, embeddings, conversations, messages and IDs remain.

## Rehearsal evidence

An ignored copy of the local RAG database was initialized twice. Both runs completed with schema
versions 1-9, `PRAGMA integrity_check = ok`, no `foreign_key_check` rows, and unchanged core counts:
3 courses, 67 documents, 1,937 chunks, 17 conversations and 34 messages. New profile/publication
tables were empty. This verifies additive/idempotent behavior against the available local data; it
does not prove the unknown production database.

## Production procedure

1. Put the release in maintenance/read-only mode and record current commit/service/env names without
   printing values.
2. Run `ops/backup_v2.sh` with explicit database, upload and backup-root paths. Preserve the output
   directory off-host and record its hashes.
3. Run `ops/restore_v2.sh` into a new isolated directory and start the release against that copy.
4. Initialize twice; verify integrity/foreign keys, versions, row counts, FTS count, document hashes
   and the presence/count of uploaded files.
5. Run deterministic health/auth/private-isolation/conversation/exact-locator/publication smoke tests.
6. Stop the service, take a final consistent backup, deploy code, start one instance and migrate.
7. Verify counts and smoke tests before enabling normal traffic.

Do not copy only the main SQLite file while a live WAL database is active. Use SQLite online backup
or stop the writer and treat database/WAL/SHM consistently. Uploads and DB must be restored from the
same checkpoint.

## Rollback

On integrity, authorization, citation or error-rate failure, stop the new writer, deploy the prior
commit and restore the verified pre-release database plus uploads as one unit. Do not attempt to
drop additive columns in place. If no V2 writes occurred, the prior binary can ignore additive
schema; once V2 user/profile/publication writes exist, use the full snapshot restore.
