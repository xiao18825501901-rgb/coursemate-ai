# Core generation release and recovery

Status: `DEPLOYED_WITH_OPEN_ACCEPTANCE_BLOCKERS`

## Candidate boundary

- Preserve all current production databases, files, receipts and OpenJev
  artifacts.
- Add Schema 64 only after a verified consistent backup and isolated rehearsal.
- Deploy backend/worker-compatible source before the matching web bundle.
- Keep the 13 Map50 targets paused.
- Do not enable the four unqualified OpenJev hard-gate definitions.

## Required release sequence

1. Freeze a source commit after full regression, typecheck, production build,
   secret scan and diff review.
2. Create consistent online backups of RAG, UI and Agent SQLite databases plus
   the exact attachment/upload recovery unit.  Copy the backup off the constrained
   host and verify checksums and isolated restore.
3. Rehearse Schema 63 -> 64 on the restored copy; verify integrity, foreign keys,
   counts, old sessions, old READY configurations and rollback compatibility.
4. Stage an immutable application release; retain `/srv/coursemate/releases/b63401e`
   as the code rollback.
5. Apply the additive migration through the reviewed startup path, switch the
   application symlink, restart only the RAG service, and verify loopback plus
   public tunneled health.
6. Publish the matching Netlify production bundle only after backend compatibility
   checks pass.
7. Run bounded authenticated teaching and recovery acceptance.  Do not repeat an
   UNKNOWN provider operation id.

## Daily rollback

Prefer a code-only symlink rollback when the previous release can open Schema 64.
This preserves post-release chats, submissions, grades and files.  A database
restore is an incident-recovery action only and must merge/preserve new user data;
the pre-release database must never be copied over live data as a routine rollback.

## Stop conditions

- backup or isolated restore is not verified;
- migration rehearsal changes immutable historical rows;
- disk headroom cannot safely stage the release and backup;
- production identity/MFA is unavailable for the required final acceptance;
- a provider operation is UNKNOWN;
- a new Question Engine flow would require bypassing the unqualified semantic gate.

## Verified rehearsal evidence

- A production-consistent online backup copy was downloaded and verified by its
  outer SHA-256 plus individual RAG/UI/Agent database hashes.
- Schema 63 -> 64 completed with `integrity_check=ok`, zero foreign-key
  violations and unchanged fingerprints for all pre-existing tables checked by
  the rehearsal tool (including 87 courses, 850 documents and 22,909 chunks).
- A second startup against the migrated copy was idempotent. The previous
  `b63401e` readiness query filters to versions `<=63`, so a code-only rollback
remains compatible with the additive Schema 64 without overwriting new data.

## Executed production release

- Application SHA: `916b76ce0534e4ce50a589521b0b618850df6956`.
- Immutable backend release: `/srv/coursemate/releases/916b76c`; current symlink
  resolves to this directory.
- Release archive SHA-256:
  `004738cdfd03bf9526ccad61a6f42a2052563191b348d098fea9514cb424f23b`.
- Pre-release backup:
  `/srv/coursemate/backups/coursemate-v2-20260928T200126.170700Z`.
  Its manifest, checksums, three SQLite databases, uploads and share archives
  were verified, and an isolated restore completed successfully before cutover.
- Only `coursemate-rag` was restarted for the backend cutover.  Agent and OpenJev
  remained running.  Public RAG, integrated UI-extension and Agent health all
  returned 200 afterward.
- Netlify production deploy: `6abacab3d2f4fb9cbfb7d8e9`; the custom domain
  returned the matching build SHA.
- The monitor backup root had retained an obsolete path and could not traverse
  the root-only backup parent.  The previous monitor configuration was saved as
  `/etc/coursemate/monitor.env.pre-916b76c`; the root now points at the real
  backup collection and is restricted to `root:coursemate`.  The newest verified
  backup is `750` with `640` artifacts.  A fresh monitor run returned `status=ok`
  and the timer remains active.

## Rollback

Use a code-only symlink switch to `/srv/coursemate/releases/b63401e`, restart only
the RAG service, and read back health and Schema 64 compatibility.  This is the
normal rollback because it retains new chats, submissions, grades and files.
Use the verified pre-release backup only for an actual data-corruption incident,
with an explicit merge/preservation plan for post-release user data.

## Remaining release gates

1. OpenJev is operational but not semantically qualified for the four hard
   Question Engine decisions; new do-one and cold Assessment publication remain
   fail-closed.
2. The production Clerk Backend API credential returns HTTP 403, so an automated
   synthetic authenticated browser acceptance could not be created.  Existing
   real users were not impersonated.
3. Thirteen Map50 trees remain paused exactly as handed off.
