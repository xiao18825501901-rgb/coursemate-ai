# CANVAS IMPORT JOB CONTRACT (task B4)

**State of this document.** Round-44 design pass, updated in round 69. The contract is now
implemented: migration 031 created the tables, `app/canvas/store.py` owns the rows,
`app/canvas/worker.py` runs a job (round 68), and `app/api/canvas.py` is the route layer that turns
a confirmed selection into a queued job (round 69). **No import has ever run against a real school**
and no school key exists, so every statement here about Canvas behaviour is contractual, not
observed. It was written against the repository's existing persistence conventions rather than
invented ones, so the implementation is a port, not a parallel universe.

## 1. What it reuses

| Existing mechanism | Where | How the import uses it |
|---|---|---|
| Job table shape | `assessment_preparation_jobs` (migration 027) | same conventions: `id TEXT PRIMARY KEY`, owner/scope columns with `REFERENCES … ON DELETE RESTRICT`, a CHECK-constrained `status`, `error_code`/`error_message`, `created_at`/`updated_at`/`completed_at` as `strftime('%Y-%m-%dT%H:%M:%fZ','now')`, and a `UNIQUE(...)` idempotency key |
| Budget reservations | `learning_model_call_reservations` (021/027) | any model-backed step (classification, knowledge draft) reserves before it spends, exactly as the existing pipeline does |
| Receipts | `jev_decision_receipts` (028) | stage transitions that must be auditable get a receipt; the import does not invent a second audit mechanism |
| Durable queue precedents | `feedback_reports` (030), `assessment_preparation_jobs` (027) | the worker claims work by status + lease, not by a long HTTP request |
| Publication workflow | `publication_review_snapshots` / `overlay_publication_requests` (019/020) | the campus-library half of task C publishes through these; a student's private import never touches them |

The worker itself: a small independent process that leases jobs from the table. The pack allows a
minimal worker rather than a cluster ("没有适用持久机制就做最小独立 worker + SQLite job 表"), and the
existing project already runs with one writer, so no new distributed platform is introduced.

## 2. States

```text
DISCOVERING → AWAITING_SELECTION → QUEUED → DOWNLOADING → VERIFYING → INGESTING → INDEXING
                                                   ↓            ↓           ↓          ↓
COMPLETED / COMPLETED_WITH_WARNINGS / NEEDS_REAUTH / FAILED / CANCELLED
```

| State | Meaning | Terminal? |
|---|---|---|
| `DISCOVERING` | enumerating the user's student courses and file metadata for the selection step | no |
| `AWAITING_SELECTION` | discovery finished; waiting for the user to confirm courses (frozen at confirmation) | no |
| `QUEUED` | selection frozen, waiting for a worker | no |
| `DOWNLOADING` | fetching file bytes, per-file checkpoints | no |
| `VERIFYING` | size/hash/type checks on the downloaded bytes | no |
| `INGESTING` | handing verified bytes to the real ingestion path (original + document version) | no |
| `INDEXING` | chunks/embeddings/classification for the ingested material | no |
| `COMPLETED` | every selected file reached a final per-file state | **yes** |
| `COMPLETED_WITH_WARNINGS` | finished, but some files are `FORBIDDEN`/`EMPTY`/`UNSUPPORTED`/`DOWNLOAD_ONLY` | **yes** |
| `NEEDS_REAUTH` | the connection's credential expired and could not be refreshed; the user must re-authorise | **yes** |
| `FAILED` | unrecoverable error for the job as a whole | **yes** |
| `CANCELLED` | the user cancelled; work stops at a checkpoint | **yes** |

`COMPLETED_WITH_WARNINGS` exists precisely so that "0 files because the course is empty" and "403
because the school locked it" can never be reported as a successful 100% import.

## 3. Identity, idempotency and freezing

* **Idempotency key**: `UNIQUE(connection_id, owner_user_id, selection_fingerprint)` where the
  fingerprint hashes the frozen selection (institution origin, the ordered course ids, and the
  per-course material version observed at confirmation). Re-submitting the same request returns the
  existing job instead of creating a second one.
* **Freezing at confirmation**: choosing "all accessible historical courses" freezes the set
  discovered at that moment. It does not watch for future courses and it does not widen to all
  Canvas resources. Current-term courses are a separate, deliberate selection rather than being
  silently folded into "all history".
* **Replay**: re-running a completed job's request, or restarting the worker, resumes from the last
  per-file checkpoint. It never re-creates the course, never re-charges an already-paid indexing
  step, and never re-downloads bytes whose hash already matches.
* **Connection binding**: the job stores `connection_id` only; the tokens are resolved at run time
  through the credential store (see `CANVAS_OAUTH_AND_SCOPES.md` §6). A job can therefore fail with
  `NEEDS_REAUTH` without ever having written a token to the database.

## 4. Per-file record

Every file gets one row, and these columns are the contract:

| Column | Why it exists |
|---|---|
| `origin`, `source_course_id`, `source_file_id`, `source_folder_or_module` | the external identity; `origin + course_id + file_id` is the unique key, **never the filename** |
| `source_updated_at`, `size`, `etag` | the version evidence used to decide "new version" versus "already have it" |
| `bytes_sha256` | local identity for dedupe and for proving the download is intact |
| `local_document_id`, `local_document_version_id` | the link into the real `documents`/`document_versions` rows created by ingestion |
| `parse_state`, `index_state` | kept separate from the download state (see §6) |
| `error_class`, `error_detail` | classified failure, shown per file |
| `status`, `attempts`, `leased_until`, `updated_at` | worker bookkeeping |

Rules that follow from the pack and are enforced here:

* **Same name, different file id → both are kept.** The name is display only.
* **Same file id, new version → not skipped forever.** A changed `source_updated_at`/`size`/`etag`
  creates a new local material version instead of being ignored.
* **Filename is not a path.** Storage paths are generated server-side so that an uploaded name
  cannot escape the storage root or contain illegal characters.

Per-file error classes: `EMPTY`, `FORBIDDEN`, `NOT_FOUND`, `UNSUPPORTED`, `EXPIRED_TOKEN`,
`RATE_LIMIT`, `NETWORK`, `TOO_LARGE`, `REJECTED_BY_LIMITS`, `HASH_MISMATCH`.

## 5. Scheduling, retry and cancellation

* **Concurrency**: at most N jobs per connection (and per institution) at once, so one student's
  import cannot exhaust the school's rate limit for everyone.
* **Backoff**: `429` and `Retry-After` are honoured with exponential backoff and jitter; retries
  apply only to idempotent reads.
* **Never retry a `403`.** A `403` is recorded as `FORBIDDEN` and surfaced; the importer does not
  probe repeatedly in the hope it becomes allowed, and it does not treat every `403` as "the school
  disabled the endpoint" — the message distinguishes what was actually observed.
* **Cancellation** stops at the next checkpoint and deletes nothing the user already has. Deleting
  imported material is a separate, explicit user action.
* **Restart** resumes the current file/checkpoint only; it does not recreate the course or re-run
  paid indexing.

## 6. Bytes, parsing and indexing are three separate facts

```text
raw bytes (stored, hashed, immutable)
  → parse state  (PARSEABLE / DOWNLOAD_ONLY / PENDING / FAILED)
  → index state  (INDEXED / PENDING / SKIPPED)
```

* Video and other unparseable formats are `DOWNLOAD_ONLY`: stored, previewable, and explicitly
  **not** counted as material a model can learn from.
* Large files stream to disk; RAM never equals the file size.
* Archive safety: extraction (if ever needed) enforces entry count, total size, nesting depth, and
  rejects absolute paths, `..`, symlinks and zip bombs; scripts and macros are never executed, and
  uploaded HTML is never served as an active page from the site's origin.
* Temporary download files are written outside the library and moved in atomically once size and
  hash pass. A failed download leaves no half-ingested document.

## 7. From import to a real private course

The import ends in a **real** course, not a card pointing at Canvas:

1. Create an owner-scoped private course (`kind=user/private`, display marked as "来自 Canvas")
   through the existing course service — not by hand-inserting rows.
2. Store originals and create `documents` + `document_versions` through the existing
   `IngestionService`, then chunks and the index, then the existing template/classification step,
   with the same quota and budget checks as any other upload.
3. Quota: estimate files/bytes/temp space/index size **before** starting, and tell the user; do not
   reject normal course files wholesale and do not turn quotas into "unlimited disk".
4. Sync later: append new versions/new files only. Local edits and learning bindings are preserved,
   a source deletion marks `source_removed` while the local copy stays, and nothing is silently
   deleted because Canvas no longer lists it. A disconnected school does not remove imported files.
5. References and download links point at the local `document`/`document_version` rows the site is
   allowed to serve — never at an expired Canvas signed URL.
6. Expensive steps (classification/embeddings) run per material revision and per batch, reusing a
   legitimate existing index for an identical hash, and never leak the fact that another user has
   the same file.

## 8. Idempotency across the database and the filesystem

The pack notes that a stage spanning the database and stored files is not a single atomic SQL
transaction. The contract therefore uses receipt/outbox rows for the stages that must be
auditable: a stage writes its intent, performs the file work, then records completion; a crash
between the two is detected on restart and reconciled from the file's hash, not from a guess.

## 9. Honest limits

* The rows, the repository and the worker now exist (see §10). There is still **no HTTP route and
  no UI entry**, and **no Canvas call has ever been made to a school**: the adapter and the worker
  are exercised against a simulated HTTP surface only.
* The state names and error classes are fixed here so that the UI, the worker and the tests cannot
  drift; changing them later is a migration, not an edit.
* Nothing in this contract claims a school key: until one exists the job path is exercised only
  against a mock OAuth adapter and simulated Canvas responses, and the connection status stays
  `NOT_CONFIGURED`.

## 10. What is implemented, and what the worker actually does (round 68)

`app/canvas/worker.py` runs one claimed job. Its order is: claim a lease → re-check the frozen
selection against the student's **own live enrolments** (a course id the student is not enrolled in
is refused before it is read, whoever wrote it) → list each selected course's files and record one
row per `origin + course_id + file_id` → create or reuse the private course → then per file:
download URL from that file's own metadata record, stream the bytes, verify size and hash, store the
copy, and hand the bytes to `IngestionService.queue_document` + `process_document` → checkpoint the
result → write the state the file results have earned.

Decisions that are easy to get wrong, and are now pinned by tests:

* **A phase is only moved forward.** `VERIFYING`, `INGESTING` and `INDEXING` are set once each, on
  the way through; a resumed run never rewrites a working state backwards.
* **A retryable failure is not a result.** A `429` sleeps the school's interval (bounded) and
  retries that file; other transport failures leave the row `PENDING` and defer it to the next run,
  so one unresponsive file cannot hold the batch.
* **A `403` is terminal for that file.** One attempt, recorded `FORBIDDEN`, and the import ends
  `COMPLETED_WITH_WARNINGS` rather than clean.
* **A dead credential ends the batch** with `NEEDS_REAUTH`; the untouched files stay `PENDING`, so
  re-authorising resumes the same job instead of starting over.
* **A job is never finished while a file is unfinished.** If every remaining file was deferred in a
  run, the job stays in its working state and its lease is released.
* **Zero chunks is not material.** The ingestion layer accepts an extension it has no loader for by
  marking the document `ready` with `chunk_count = 0`. The worker records that as `DOWNLOAD_ONLY`,
  not `INDEXED`, because a stored picture is not text a model can read — and it must never count
  towards coverage.
* **Cancel stops at the checkpoint.** Remaining files become `CANCELLED`; imported documents and
  their bytes are left alone.

Two deliberate debts, stated rather than hidden:

1. The downloaded copy of a file that could not be parsed stays on disk. It is the only copy
   CourseMate has, and deleting it would be the "cancel deletes your material" mistake in a
   different costume. `cleanup_empty_directories()` removes only directories that hold nothing.
2. A row that is `PENDING` is downloaded again rather than reused from disk. Only a `DOWNLOADED`
   row has a hash that is known to describe the version now being asked for; a row that went back to
   pending after the school changed the file still holds the previous hash, and reusing those bytes
   would silently ingest stale content. The same reasoning is why `ImportJob.add_file` clears the
   hash when it detects a new version.

The school's file domain is also not yet pinned per institution: `Institution.download_hosts` is
empty for both schools because guessing a Canvas CDN host would break real downloads, so the
download rule today is "public HTTPS, validated at every hop" plus the origin's own host. Once a
live response names the file domain, it goes in the institution's `download_hosts` and the rule
tightens to that host alone — the mechanism is already tested.

## 11. Who writes a job (round 69)

A job is created by `POST /api/integrations/canvas/imports`, and only there. The route:

1. resolves the connection **for the signed-in user** (another user's connection is reported as
   absent, not forbidden);
2. rejects empty or non-numeric course ids — the selection is a list of Canvas ids, never a
   `base_url` or a search term;
3. builds the job with `new_job`, whose fingerprint covers the connection, the owner, the
   institution origin, the sorted course ids and the observed material versions, then moves it
   `AWAITING_SELECTION → QUEUED` (the only legal way in);
4. calls `create_or_get`, so the same frozen selection returns the **same** job with
   `created: false` rather than starting a second import;
5. stores the private course's id on the job once the worker creates it, so a resumed run reuses
   that course.

`GET /imports/{id}` reports the job row itself — status, error code, target course, per-file counts
— so the status page cannot drift from the state machine by re-deriving anything.
`POST /imports/{id}/cancel` moves the job to `CANCELLED` only from a working state and reports
`cancelled: false` for a job that already finished; it never deletes documents, chunks or stored
bytes. `DELETE /connections/{id}` revokes at the school (best effort) and **always** forgets the
local credential, because a disconnect that leaves a usable credential behind is worse than one
that leaves a stale token at the school.

The route layer holds no Canvas logic of its own: every school call goes through
`CanvasReadAdapter` or `CanvasOAuthClient`, and every row goes through the two repositories.
