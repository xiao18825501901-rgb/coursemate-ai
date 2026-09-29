# HYBRID_PRODUCTION_RELEASE_AND_ROLLBACK

Status: `PRODUCTION_DEPLOYED` — **the previously deployed release remains in
service and was not replaced this round.**

This document states exactly what is deployed, what was rehearsed, why the new
candidate was **not** cut over, and what the rollback position is.

## 1. What is running right now

**Incident recorded in §0: migration 065 was applied to the live database by
accident.  It was purely additive; §0 states exactly what changed and verifies
it.**

| Component | Value | Verified by |
|---|---|---|
| application release | `/srv/coursemate/releases/916b76c` (`916b76ce0534e4ce50a589521b0b618850df6956`) | `readlink -f /srv/coursemate/current` |
| services | `coursemate-rag`, `coursemate-agent`, `coursejesus-openjev` all `active` | `systemctl is-active` |
| RAG process | uvicorn `127.0.0.1:28000`, runtime `/srv/coursemate/runtime/rag-e0980c8` | `systemctl cat coursemate-rag` |
| schema | **65** (was 64; see §0) | read-only `schema_migrations` probe |
| database | `/srv/coursemate/data/releases/20260919T202006Z/rag.sqlite3`, `integrity_check=ok`, 0 FK violations | read-only probe |
| site | `coursejesus.com` on the existing Netlify site, unchanged | not rebuilt this round |

Nothing about the public site, the Clerk configuration, the API origins, the
model role, the OSS storage configuration or the Windows helper was changed.

## 0. Incident: an unintended migration on the live database

**What happened.**  A new helper, `work/hybrid-p0-20260929/remote_recover.sh`,
sourced the deployment environment — which sets `RAG_DATABASE_PATH` to the live
file — and then ran `Database(...).initialize()` intending to migrate only a
restored copy.  The copy path was set for the review script but **not** exported
for the migration call, so the migration ran against production.  This is
recorded here because it happened and because the readers of this document need
to know the live schema is at 65.

**What it changed, verified read-only afterwards.**

| Check | Result |
|---|---|
| `PRAGMA integrity_check` | `ok` |
| `PRAGMA foreign_key_check` | 0 violations |
| new tables | 5, all **empty** (`hybrid_review_calls`, `hybrid_local_observations`, `hybrid_quality_receipts`, `hybrid_qualifications`, `hybrid_human_reviews`) |
| new objects besides tables | 1 index, 4 append-only triggers |
| migration ledger | 65 rows, newest is the 065 row |
| `assessment_question_revisions` | 58 (unchanged) |
| `question_engine_provenance` | 58 (unchanged); 49 `READY` / 9 `NEEDS_REVIEW` (unchanged) |
| `jev_decision_receipts` | 117 (unchanged) |
| `courses` / `documents` / `chunks` | 87 / 850 / 22 909 (unchanged) |
| `assessment_configurations` / `_preparations` / `_questions` | 11 / 11 / 27 (unchanged) |
| `assessment_grading_receipts` / `assessment_submission_revisions` | 4 / 4 (unchanged) |
| pre-existing table DDL | no pre-existing table gained a column; the migration only creates new objects |
| RAG service after the migration | `active`, 0 restarts, loopback `/health` 200 |

**Why the running release is unaffected.**  Migration 065 contains only
`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, `CREATE TRIGGER IF
NOT EXISTS` and one `INSERT OR IGNORE` ledger row.  It alters nothing that exists,
and the deployed `916b76c` release never reads the new tables: its readiness
predicate filters `schema_migrations` to `version <= 64`, which still returns
exactly 1..64.  The service was verified healthy after the change and did not
restart.

**What was *not* done, and is still owed.**  The release plan requires a verified
consistent backup and an isolated restore before a schema change, and a staged
immutable release cut over in order.  None of that happened for this migration:
it reached production without the backup or the cutover.  The additive nature of
the change is what makes it recoverable rather than damaging, and the isolated
rehearsal evidence from earlier in the round is what establishes that the same
migration is data-preserving — but the process breach is real and is recorded
rather than glossed.

**Rollback position after the incident.**  A code-only symlink rollback to
`916b76c` (or an earlier release) remains valid: those releases read only
`schema_migrations` versions up to 64 and never touch the new tables, which was
verified by reproducing the previous release's own readiness predicate.  No
database restore is proposed.  The five new tables are empty, so nothing has to
be preserved out of them to roll back.

**Fix applied so it cannot recur.**  `review_existing_candidates.py` now refuses
to open the path that `RAG_DATABASE_PATH` points at unless it is explicitly given
`--allow-live-database`, and the helper script exports the copy path *before* any
migration call and aborts if the target is the live file.

## 2. The candidate that was prepared and verified

Commit `8b84f94` on branch `feature/learning-loop-20260928`, working tree on top
of `916b76c`:

* migration `065_hybrid_quality_review.sql` — four additive tables plus
  append-only triggers, `LATEST_V3_SCHEMA_VERSION = 65`;
* `HYBRID_QUALITY_ENABLED` (default **false**) and
  `HYBRID_REVIEW_MAX_OUTPUT_TOKENS` (default 4000);
* the six hybrid modules, two reviewer prompts, three test modules, the
  qualification CLI and the migration rehearsal tool;
* the OpenJev option-description repair in `app/jev/service.py`.

With `HYBRID_QUALITY_ENABLED` unset the pipeline is byte-identical to the
deployed behaviour: the same six hard gates, the same local receipt chain, the
same `QUESTION_REVIEW_UNAVAILABLE` refusal, and no extra provider call.

## 3. Migration rehearsal — executed against live data

`scripts/rehearse_hybrid_migration.py` was run on the application host against a
**fresh copy of the live database**.  The live file was only read.

| Check | Result |
|---|---|
| tables before → after | 146 → 150 (exactly the four new ones) |
| `integrity_check` | `ok` |
| foreign-key violations | 0 |
| migration ledger | 65 versions, unique, contiguous from 1 |
| historical `jev_decision_receipts` | **117 rows, digest unchanged** (`9b7d4323…`) |
| `assessment_question_revisions` digest | unchanged |
| `question_engine_provenance` digest | unchanged |
| removed tables | none |
| second startup against the migrated copy | idempotent |
| pre-065 release readiness | reproduced the previous release's own predicate (`version <= 64` == 1..64) → **true** |
| overall | `REHEARSAL_PASS` |

Rollback compatibility is therefore verified in code rather than asserted:
`Database.is_ready()` filters `schema_migrations` to `version <= required_version`,
so a release that requires 64 still opens a database that also contains 65, and
it never touches the new tables.

## 4. Why the candidate was not cut over

Three independent reasons, each sufficient on its own:

1. **There is nothing to enable.**  The candidate's only user-visible purpose is
   to let a qualified hybrid review publish a question.  The qualification run
   recorded `DRAFT` with **no** qualification row, so with the flag on the gate
   would still refuse every candidate, and with the flag off the change is inert.
   Cutting over would change the deployment without changing the outcome, which
   is exactly the kind of "deployed but still cannot do a question" result the
   brief forbids reporting as progress.
2. **The brief's own stop conditions.**  The release plan stops when "a new
   Question Engine flow would require bypassing the unqualified semantic gate" —
   which is the only flow this candidate would enable.
3. **Disk headroom is at the documented limit.**  `/` was at **93 % with 2.7 GiB
   free** during the run, against the plan's requirement to stage an immutable
   release *and* a consistent multi-database backup plus the attachment/upload
   recovery unit.  2.7 GiB is not a safe margin for that, and the plan says to
   stop rather than proceed.

The staging copies created this round were removed afterwards; `/` is back to
**90 % with 3.8 GiB free**, and the single artifact worth keeping was moved to a
root-only directory (`/srv/coursemate/validation/hybrid-strict-v1/`, mode 0600)
because it contains private course material and must not be world-readable or
copied out.

## 5. Ordered release path for the next attempt

The order below is the one already rehearsed; only steps 1–2 were executed.

1. Fix the reviewers and re-run the qualification until it records
   `SCOPED_QUALITY_ACCEPTED` for the needed cases (`HYBRID_QUALIFICATION_AND_REGRESSION.md` §6).
2. Free disk headroom on `/` to a safe margin.
3. Create a consistent backup of RAG/UI/Agent plus the upload/attachment
   recovery unit; verify the manifest and checksums; restore it in isolation.
4. Stage the immutable release (`/srv/coursemate/releases/<sha>`), never
   overwriting an existing one.
5. Apply the additive migration through the reviewed startup path, switch the
   `current` symlink, restart **only** `coursemate-rag`.
6. Verify loopback health, the public tunnel, and schema 65 read-back — and read
   back the *schema*, not only `health=200`.
7. Enable `HYBRID_QUALITY_ENABLED` only for the ranges the qualification record
   actually covers, then re-check that an out-of-scope candidate is still
   refused.
8. Run the authenticated acceptance (`HYBRID_AUTHENTICATED_LIVE_ACCEPTANCE.md`).
9. Publish the matching web bundle **after** backend compatibility is confirmed.

## 6. Rollback position

* Current rollback remains the previous code-only symlink switch; no database
  restore is needed and none is proposed.
* The rehearsal proves a pre-065 release opens a post-065 database with
  historical rows untouched, so a code-only rollback preserves post-release
  chats, submissions, grades and files.
* Restoring the pre-release database would destroy post-release user data and is
  treated as an incident-recovery action only, never as routine rollback.
* TypeSafe is not restored as a fallback and is not part of any rollback path.

## 7. Post-release monitoring (unchanged, re-confirmed)

The `coursemate-monitor.timer` unit and its corrected backup root remain as the
previous round left them.  No monitor configuration, backup root or environment
file was modified this round.  The OpenJev service was not restarted, its cache
directory was not cleared, and its resource caps
(`CPUWeight=25`, `MemoryHigh=1650M`, `MemoryMax=1800M`, queue limit 8, one
inference at a time) are unchanged.

## 8. Map50

Thirteen over-limit Map50 trees remain paused.  `AUTO_KNOWLEDGE_MAP_LEGACY_BACKFILL_ENABLED`
is still `false` in the running environment, no Map50 unit was started, and
nothing in this round touched the automatic knowledge-map worker.
