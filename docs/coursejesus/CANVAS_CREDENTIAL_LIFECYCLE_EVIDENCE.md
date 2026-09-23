# Canvas credential lifecycle evidence

**What this file is:** the lifecycle of the task-level transient Canvas credential, exercised
through the shipped code and recorded as measurements. It is not a description of intent, and it
does not include anything that has not been run.

**Revision:** `bb9fbfc` (source), measured 2026-09-24.
**Producer:** `work/current-change/canvas-credential-lifecycle-evidence.py` (exit code 0), output kept
at `work/current-change/canvas-credential-lifecycle-evidence.json` and
`work/current-change/credential-evidence-run.log`.

Status codes this supports: `CANVAS_TRANSIENT_PAT_IMPLEMENTED`,
`CANVAS_TASK_CREDENTIAL_CLEARED`, `CANVAS_IMPORTED_PRIVATE_COURSE_LIFECYCLE`.

## 1. Part A — the lifecycle through the real application

`app.main.create_app` with the real registry, the real error handler, the real auth verifier and a
simulated school (`httpx.MockTransport`). Every value below is copied from the JSON the run wrote.

| Step | Measurement |
| --- | --- |
| Paste a token for one task | `201`, state `PRESENT_TRANSIENTLY`, `live_in_process: 1`, `has_token_in_response: false` |
| Read the student's courses with it | `200`, courses `["560", "240"]`, `read_calls: 2` |
| Destroy it on purpose (`forget`, reason `canvas_reads_complete`) | `{cleared: true, state: DESTROYED, readCalls: 2}` |
| Read again after destruction | `404` `TASK_CREDENTIAL_NOT_FOUND`, `details.state: DESTROYED` |
| Ask about a reference never held | `NEVER_STORED` |
| Restart (a store that never saw the reference) | `PRESENT_TRANSIENTLY` in the database → **`LOST_ON_RESTART`**; `DESTROYED` stays `DESTROYED`; unknown → `NEVER_STORED` |
| Idle expiry (30 min, driven clock) | state `EXPIRED`, reason `idle_timeout`, `bytes_zeroed: true`, the provider returns nothing afterwards |
| Hard expiry (24 h, after 4 refreshing reads) | state `EXPIRED`, reason `hard_timeout`, `reads_before_expiry: 4` |
| Is the token in the database anywhere? | `token_anywhere_in_database: false` |

The database's receipts for the whole episode — two rows, and nothing in them is a credential:

```
PRESENT_TRANSIENTLY  reason ""                      read_calls 0  zeroed_bytes  0
DESTROYED            reason "canvas_reads_complete" read_calls 2  zeroed_bytes 53
```

Both rows carry the same `store_instance_id`, which is what makes "the process that held it is the
process that destroyed it" checkable; a row whose credential is absent from this process's store is
reported `LOST_ON_RESTART` instead of being guessed at.

## 2. Part B — the ordering rule, through the real worker

The real `CanvasImportWorker` with the real `IngestionService` and the deterministic embedding
provider, on a job whose `credential_kind` is `transient_task`. The event log records the moment the
credential is released and the moment indexing work actually starts (the log wraps the ingestion
entry point, not the worker's own methods, so the evidence is about the work rather than the code):

```
events: ["release:canvas_reads_complete", "indexing", "indexing"]
release_index: 0
first_indexing_index: 1
release_before_indexing: true
job_status: COMPLETED
credential_kind: transient_task
documents_indexed: 2
```

Two files were fetched, the credential was released, and then both files were parsed and indexed —
in that order, in one run. The complementary property is pinned by
`test_a_credential_is_not_released_while_reads_are_still_outstanding`: a batch-limited run that still
has files to fetch does **not** release the credential and emits no release event at all.

## 3. The lifecycle states, and how each was produced

| State | Produced by | Where |
| --- | --- | --- |
| `NEVER_STORED` | An unknown reference; a saved-connection job | Part A (`unknown_reference`) |
| `PRESENT_TRANSIENTLY` | A paste that passed the identity check | Part A (`open`), Part B (job creation) |
| `DESTROYING` | The transition inside `destroy()`, for one buffer pass | `tests/test_canvas_transient_credential.py` |
| `DESTROYED` | Reads finished, user forgot, task cancelled, job failed | Part A (`forget`), Part B (`release:canvas_reads_complete`) |
| `EXPIRED` | 30 minutes idle; or 24 hours regardless of activity | Part A (`idle_expiry`, `hard_expiry`) |
| `LOST_ON_RESTART` | A reference the database calls live, asked about by another process | Part A (`after_restart`) |

Cancel and failure reach `DESTROYED` through the worker's release callback with their own reasons
(`task_cancelled`, `credential_failed`), so a cancel and a completed read pass are distinguishable
in the receipts rather than both reading "gone".

## 4. Test evidence behind the same claims

| Claim | Test file | Result |
| --- | --- | --- |
| Lifecycle, TTLs, zeroing, restart reconciliation, receipts, bounded storage, no logger | `tests/test_canvas_transient_credential.py` | 17 passed |
| Release before indexing; not released while reads remain; a job with no credential asks for one and reads nothing; a saved connection is never released; a cancellation cannot be resurrected | `tests/test_canvas_import_worker.py` | 32 passed |
| Routes, per-account gate, lifecycle receipts, "a credential is accepted on exactly one route" | `tests/test_canvas_api_routes.py` | 36 passed |
| Schema 35 applies once and its CHECKs constrain | `tests/test_v3_migration_rehearsal.py`, the probe script | contiguous to 35; second start adds nothing; three CHECKs refused |
| No regression in the existing Canvas surface | canvas/schema/database selection | 319 passed, 1 skipped |

## 5. What this evidence does **not** cover

* **No real school was contacted.** The school in Part A is an `httpx.MockTransport`. The owner's own
  small-sample live test against the real Canvas is a separate measurement and is not claimed here —
  it needs the replacement token, supplied through a local hidden prompt.
* **The ordering is proven within one worker run.** The rule as implemented is "all reads, then
  destroy, then all parsing and indexing" per run, with the credential surviving between runs only
  while files still need fetching. A multi-run import against a real school is not measured here.
* **Memory hygiene is bounded, not absolute.** The stored bytes are zeroed and the entry removed; a
  `str` copy exists inside the HTTP client for the duration of each request, which is a property of
  the HTTP library rather than of this design.
* **The counts are from two processes.** `store_instance_id` identifies a process lifetime, and the
  restart case is simulated by a second store instance in the same process, which is the same code
  path a real restart takes (an empty store) but not the same wall-clock event.
