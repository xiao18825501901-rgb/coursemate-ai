# The task-level transient Canvas credential

**Status:** implemented and tested (`CANVAS_TRANSIENT_PAT_IMPLEMENTED`).
**Scope of this document:** the technical design of the one-off credential path, what it
deliberately does *not* do, and the four places where the implementation deviates from a literal
reading of the brief — each with its reason. The separate question of whether this path may be
offered to the public is answered in `CANVAS_ACCESS_POLICY_STATUS.md`, not here.

Measured at revision `bb9fbfc` (source) on 2026-09-24. Every claim below is a property of the code
in this repository; the numbers come from the test runs named in §7.

---

## 1. What problem this solves

The public way to reach a school's Canvas is the school's own OAuth page. That path is written and
tested, and it is blocked on one thing that is not ours: the school has not issued a Developer Key,
so `CANVAS_OAUTH_LIVE = WAITING_INSTITUTION`. The owner's own testing must not be blocked by that,
and the product must not pretend the school has approved anything.

So there is a third path, narrower than either existing one:

* the user pastes a Canvas personal access token **for one import task**;
* the service reads what that one task needs — the account identity, the course list, the file
  bytes — and nothing else;
* the credential is destroyed as soon as those reads are finished, **before** any parsing or
  indexing;
* it is never written to the business database, to disk, to a log line or to a response body;
* it is offered only when a deployment enables it for a listed account, and the deployment default
  is **off**.

The local bridge (migration 033) solves a different problem and stays as it is: there the token
never reaches the server at all, because the user's own machine does the reading. This path is the
opposite trade — the token reaches the service, in exchange for working with no school-side setup.

## 2. The lifecycle, and where each state comes from

Six states, which are the whole vocabulary (`app/canvas/transient_credential.py`):

| State | Meaning | Reached when |
| --- | --- | --- |
| `NEVER_STORED` | No credential was ever held for this reference | An unknown reference is asked about; a saved-connection job |
| `PRESENT_TRANSIENTLY` | Bytes are held in this process, usable | A paste that passed the identity check |
| `DESTROYING` | The bytes are being overwritten | Inside `destroy()`, for the duration of one buffer pass |
| `DESTROYED` | The bytes are zeroes and the entry is gone | The reads finished, the user disconnected, the task was cancelled, the job failed |
| `EXPIRED` | The idle or hard limit passed before the reads finished | 30 minutes idle, or 24 hours from creation |
| `LOST_ON_RESTART` | The process that held it is not this one | A reference the database records as live, asked about by a process that never saw it |

Three properties make these states trustworthy rather than decorative:

1. **The bytes are overwritten, not dropped.** The token is held in a `bytearray`, so `destroy()`
   writes zeroes over it in place and records how many bytes it blanked. A Python `str` cannot be
   wiped, which is why the token is not kept as one.
2. **The lifetime is measured on the monotonic clock.** A wall-clock step (NTP, a restored
   snapshot) cannot shorten or extend a credential; the wall clock is used only to render the
   receipt's timestamps.
3. **Expiry needs no background work.** It is applied on every access and by an explicit `sweep()`
   — deliberately *not* by a reaper thread, because a background loop over a credential is exactly
   the background processing this path is supposed to avoid.

`DESTROYING` is observable because "it was being destroyed when the process died" is a different
fact from "it was destroyed", and the lifecycle evidence has to be able to say which.

## 3. What the database is allowed to know

Migration 035 (`services/rag-api/migrations/035_canvas_task_credential.sql`) adds three columns to
`canvas_import_jobs` — `credential_ref`, `credential_kind` (`connection` | `transient_task`) and
`credential_state` — plus `canvas_credential_lifecycle_events`, whose rows are transitions.

What is stored: an opaque random reference, the kind, the state, the reason, the number of Canvas
reads the credential performed, how many bytes were blanked, and which process lifetime held it.

What is never stored: the token, any part of it, any hash that could be tested against a guess, and
the Canvas base URL plus token pair. `canvas_connections.credential_key_id` stays empty for a task
credential, which is how a reader can tell that no encrypted credential file was written for it.

The event table is what makes the ordering claim checkable after the fact: the destruction
timestamp exists next to the job's own progress, so "the credential was cleared before indexing"
is a comparison rather than a promise.

The three `canvas_import_jobs` columns are added by guarded `ALTER TABLE` statements in
`app/db.py`, following the pattern migrations 023 and 025 established, because SQLite has no
`ADD COLUMN IF NOT EXISTS` and every migration file is re-run on every start.

## 4. The ordering rule, and the one structural change it forced

The owner's rule: the credential must be unusable immediately after the Canvas reads it was given,
and before indexing. That is a statement about **control flow**, so the worker was restructured
(`app/canvas/worker.py`):

* `_fetch_file` downloads and verifies bytes. It never parses anything.
* `_ingest_pass` parses and indexes bytes that are already on disk. It makes no Canvas call and
  takes no credential argument.
* Between the two, `_release_credential` is called — once per run — when no file still needs a
  fetch.

Three consequences worth stating plainly, because each is a behaviour change:

1. **A run that only finishes already-downloaded files needs no credential at all.** It skips
   discovery entirely. This is what lets a job continue after its token is gone.
2. **A stopped run still indexes what it fetched.** If a run hit its batch limit, was cancelled, or
   a file was deferred, the bytes already on disk are parsed before the run reports its stop. They
   were read legitimately and parsing needs no credential; dropping them would throw away work the
   user paid for with their token. The owner's rule "cancel does not delete what is already
   imported" is preserved in the stronger form: at a cancel checkpoint, everything downloaded so
   far is kept, and only the files never fetched are marked `CANCELLED`.
3. **A cancellation is captured before the ingest pass and restored after it.** Indexing writes
   `INGESTING`/`INDEXING` of its own, and without this the row's `CANCELLED` verdict was overwritten
   — a cancelled job could finish as a success. That was a real defect, found by a test written for
   this change (`test_a_cancellation_never_resurrects_a_finished_looking_job`).

The credential is released at the end of *every* run in which the reads finished, including the
cancel and failure paths. When reads remain, it is **not** released: destroying it there would turn
an ordinary long import into a re-authorisation prompt. The 24-hour hard cap is the bound on that,
which is the reason the cap is a day rather than the length of one worker run.

## 5. The HTTP surface, and the one exception it makes

`app/api/canvas.py`:

| Route | Purpose |
| --- | --- |
| `POST /api/integrations/canvas/task-credentials` | Hold a pasted credential for one task, after reading the Canvas identity with it |
| `GET /api/integrations/canvas/task-credentials/{ref}` | The lifecycle state, reconciled against this process |
| `POST /api/integrations/canvas/task-credentials/{ref}/forget` | Destroy it now |
| `GET /api/integrations/canvas/courses?connection_id=…&credential_ref=…` | The same course list route, reading with the task credential |
| `POST /api/integrations/canvas/imports` | Takes an opaque `credential_ref`; records the kind and the reference, never the credential |
| `GET /api/integrations/canvas/imports/{id}` | Adds `credentialState` and `needsCredential` |
| `GET /api/integrations/canvas/institutions` | Adds `taskCredential: {available, reason, ownerOnly, idleMinutes, maxHours}` for the calling account |

The module docstring of `app/api/canvas.py` states that no route accepts a personal access token in
place of the school's OAuth flow. This is the deliberate, single exception, and three gates keep it
from becoming a second import system:

1. `CANVAS_TASK_CREDENTIAL_ENABLED` — **off by default**;
2. `CANVAS_TASK_CREDENTIAL_USERS` — a listed account, defaulting to the existing administrators;
3. the institution registry — a pasted token is only ever tried against a school this deployment
   knows, by key or by exact registered origin.

The credential is read once, for the identity, before anything is held: a token that belongs to
somebody else fails at the door, and nothing is stored. `ImportSelection` now sets
`extra="forbid"`, so a body carrying a `personal_access_token` to any other route is refused rather
than silently ignored — a near-miss that made "no credential is accepted here" untrue in practice
until a test in this change caught it.

## 6. Four deviations from a literal reading of the brief

Each is a real decision, and each is reported rather than quietly taken.

1. **`NEEDS_CREDENTIAL` is not a new job status.** The brief named it for the 24-hour expiry case.
   The job vocabulary is CHECK-constrained in the schema, and adding a value means rebuilding a
   table that other rows reference — a larger risk than the naming is worth, on a database that is
   also the production one. The existing `NEEDS_REAUTH` is the state for "a credential must be
   renewed", it already transitions back to `QUEUED`, and the *reason* is carried losslessly in
   `error_code` and in the lifecycle events. The user-visible condition is exposed as
   `needsCredential: true` in the job status response and stated in words on the screen, so nothing
   about it is hidden behind the status name.
2. **The credential survives between worker runs while reads remain.** A literal reading of
   "unusable immediately after the needed Canvas reads" could be implemented as "one worker run",
   but then the 24-hour hard cap in the brief would be meaningless, and a large selection would ask
   for the token again in the middle of a legitimate import. The rule is applied where it is
   substantive: **all reads, then destroy, then all parsing and indexing**.
3. **Discovery is a Canvas read, so a job with no credential does not run it.** A job whose token is
   gone and which still needs bytes reports `NEEDS_REAUTH` instead of reading; a job whose bytes are
   all present is finished without touching the school. The consequence is honest and stated: a job
   whose list of files has never been read cannot be completed without a credential.
4. **Historical `credential_state` for saved connections.** A job backed by a stored OAuth
   connection records `credential_kind='connection'` and `credential_state='NEVER_STORED'`, because
   the lifecycle vocabulary describes the transient path. `needsCredential` is false for it, so the
   screen never offers to paste a token for a connection that is working, but a reader of the row
   should not read `NEVER_STORED` as "this job had no credential".

## 7. Evidence

| Claim | Evidence | Result |
| --- | --- | --- |
| The lifecycle, TTLs, zeroing, restart and receipts behave as described | `tests/test_canvas_transient_credential.py` | 17 passed |
| The credential is released before indexing, not before the reads are done, and never for a saved connection | `tests/test_canvas_import_worker.py` (4 new tests, incl. an event log that orders the release against the first indexing call) | 32 passed |
| The routes, gates, lifecycle receipts and the "no credential anywhere else" rule | `tests/test_canvas_api_routes.py` | 36 passed |
| Schema 35 applies once, contiguously, and its CHECKs constrain | `work/current-change/probe-schema-35.py`; `tests/test_v3_migration_rehearsal.py` | `versions contiguous: True`, `second migrate kept columns: True`, three CHECKs refused |
| Existing Canvas behaviour is unchanged | the full canvas/schema/database selection | 319 passed, 1 skipped (a POSIX-permission test on Windows) |

Limit, stated rather than implied: those four tests prove the ordering *within a worker run*. The
end-to-end order against a real school is the owner's own small-sample live test, which needs the
replacement token and is reported separately.

## 8. What this design does not claim

* It does not claim the school has approved a token path for students. No institution has been
  asked. That question is `CANVAS_ACCESS_POLICY_STATUS.md`.
* It does not claim the token is unrecoverable from memory. The adapter necessarily turns the held
  bytes into a `str` for one HTTP request, so copies can exist inside an HTTP client for the
  duration of that request. What is guaranteed is the *stored* credential: never written, zeroed on
  destruction, and reported as gone.
* It does not claim the identity check proves the token is the student's own. It proves the token
  authorises the Canvas account it is used as, which is what the import binds material to; a token
  shared between two people would import the same account's material for both.
