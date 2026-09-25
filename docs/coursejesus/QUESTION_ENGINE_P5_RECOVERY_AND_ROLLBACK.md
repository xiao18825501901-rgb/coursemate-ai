# CourseJesus P5 recovery and rollback evidence

Date: 2026-09-25
Verdict: **rollback runtime verified in isolation; no production cutover performed**

## Recovery boundary

The primary rollback unit is the verified pre-migration backup described in
`QUESTION_ENGINE_P5_PRODUCTION_MIGRATION.md`. A rollback after opening the new release must not
blindly restore that backup over newer chats, grades, questions, attachments or receipts. New data
must first be protected and reconciled; otherwise use the schema-compatible old runtime or a
forward fix.

Credential recovery is external (`EXTERNAL_NOT_INCLUDED`). Database restore must not revive an
expired or disconnected credential.

## Static compatibility

The actual old release tree `/srv/coursemate/releases/4ef5064` was checked against a disposable
schema-39 copy. It saw max migration 39 while its own schema level is 25; required tables/columns
were present, integrity was ok, foreign-key violations were zero, the historical pool predicate
was byte-identical and the tool returned `ROLLBACK_SAFE_WITH_MIGRATED_DB`.

Evidence SHA-256:
`b88dc2dddaaafdcc44d0333e092a724c4d7995d08375f47d3e1008b6cf6e037d`.

## Actual old-runtime rehearsal

Static inspection was not treated as sufficient. The real old application release was started on
`127.0.0.1:28139` against a disposable migrated production snapshot with a deterministic provider
and no external calls. `/health` returned HTTP 200 with `rag-api`; initialization completed; the
database remained schema 1–39 with integrity ok and FK 0. The representative old-business row
fingerprint was identical before and after:

`ff530e655eda9811216fe1535894e4ac95730710efe3519f39641fc84024a22c`.

This proves the old runtime can initialize/read the migrated snapshot without destructive replay.
It does not prove every future schema-39 feature is usable through the old UI. In particular, P5
new-question preparation remains degraded when required Jev modes are unavailable.

## Monitoring recovery

The initial post-backup monitor remained red because `/srv/coursemate/backups` had become
root-only, preventing the configured `coursemate` monitor from traversing
`/srv/coursemate/backups/post-aa3ffc2`. The verified backup was copied without overwrite into that
configured root, all nine checksums passed, and the parent was changed to group-traversable only.
The existing one-shot monitor then returned success at `2026-09-25T07:50:39Z`:

- RAG healthy (20 ms);
- Agent healthy (3 ms);
- backup age 4,015 seconds;
- free disk 28,376,305,664 bytes.

RAG, Agent and nginx remained active. This is pre-release monitoring evidence, not a post-release
acceptance result.

### Post-release monitoring

At `2026-09-25T13:06:07.221455Z` the frozen monitor returned `status=ok`: RAG and Agent HTTPS
health passed, the latest verified backup was 194 seconds old, and free space was 26,900,791,296
bytes. The monitor intentionally rejects HTTP health URLs; an initial localhost invocation was
therefore a configuration failure and was rerun against the real HTTPS ingress.

On the Singapore relay, Caddy and `coursemate-api-tunnel` were active, the loopback forwards on
38000/38001 were listening, Caddy validation passed, and all three relayed health endpoints
returned HTTP 200. From the public client, `qqttai.com`, RAG, mounted UI and Agent returned 200;
unauthenticated `/me` returned 401; and the CORS preflight allowed only the production site origin.

## Cutover rollback order

1. drain writers and paid generation; verify no PREPARING/CLAIMED work is active;
2. take a new consistent final backup and restore it once in isolation;
3. record exact backend release, frontend deploy ID, config/model/Jev modes and backup hash;
4. deploy immutable backend and matched frontend under a maintenance window;
5. if failure occurs before reopening, restore the frozen unit or switch to the verified old runtime;
6. if failure occurs after new writes, preserve the current data first and prefer compatible rollback
   or forward repair; never discard new user data automatically.

The cutover completed without invoking rollback. The stopped-writer backup was restored in
isolation before migration, and the post-release recovery unit was independently restored after
the signed-in acceptance:

- cutover backup: `/srv/coursemate/backups/coursemate-v2-20260925T115551.985225Z`;
- post-release backup:
  `/srv/coursemate/backups/post-e0980c8-p5-20260925/coursemate-v2-20260925T130253.544550Z`;
- post-release restore:
  `/srv/coursemate/rehearsals/p5-post-release-20260925T130253Z/restored`;
- restored schemas: RAG 39, UI 14, Agent 1; SQLite integrity `ok`, FK 0;
- active backend/frontend: `e0980c8` / `6ab6650875f30b0bb26558f0`.

If rollback becomes necessary after new writes, operators must first preserve the current state.
They must not automatically restore the pre-cutover snapshot over newer production data. The
verified old runtime remains an emergency compatibility option, with the previously documented
degraded P5 preparation capability.
