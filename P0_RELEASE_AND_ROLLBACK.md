# P0 Release and Rollback

## Release contents

The candidate is production `d854b0e` plus only P0 Do-One, prompt auto-map reconciliation, tests, lockfile security refresh and reports. No database migration is added; production schema 66 remains the expected schema.

## Pre-deploy gates

1. Re-read production symlink/release, service health, flags, free space, schema/integrity and tree counts.
2. Confirm `AUTO_KNOWLEDGE_MAP_LEGACY_BACKFILL_ENABLED=false`.
3. Create checksummed off-host backups of all three SQLite databases and uploads metadata/content; restore-check copies without writing production databases.
4. Build/test the exact committed candidate and scan the published bundle for secrets/private paths.
5. Deploy backend-compatible code before the web bundle; restart only CourseJesus services.
6. Verify health, worker, schema, origin and commit marker, then run normal-Clerk production acceptance.

## Rollback

- Prefer feature disable/forward fix. If Do-One is unsafe, disable its entry while preserving assessment.
- If new-tree generation is unsafe, disable new event generation while keeping active trees readable and legacy backfill off.
- Code rollback points `/srv/coursemate/current` to the prior release and restarts CourseJesus services only.
- Never restore an old database over post-release student answers, chats, courses or uploads. There is no P0 schema migration, so the prior code remains read-compatible.
- Candidate/job records and immutable tree revisions remain for diagnosis; a failed candidate never replaces an active tree.

Production commands, backup hashes, release id, health results and rollback rehearsal evidence will be appended after execution.

