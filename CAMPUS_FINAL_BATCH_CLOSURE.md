# CAMPUS FINAL BATCH CLOSURE

**This is the last local campus batch. It is frozen, its eligibility is recorded, and the local
expansion path from `D:\Canvas` / `D:\Canvas-DG` is closed — as the owner decided on 2026-09-24.**

Nothing in this document is a publication. Every file below is either in a **private** campus
course awaiting one owner rights decision, stored without being parsed, or withheld. The numbers
are read from the frozen manifest and the local ingestion ledger, not from earlier reports.

| | |
|---|---|
| Batch id | `final-local-campus-batch-2026-09-24` |
| Frozen at (T0) | **2026-09-24T14:52:18Z** UTC (2026-09-24T22:52:18+0800 local) |
| Sources (both kept in place, never uploaded) | `D:\Canvas` (202 files, 773,418,255 bytes), `D:\Canvas-DG` (1,719 files, 8,095,437,975 bytes) |
| Frozen manifest | `CAMPUS_FINAL_BATCH_MANIFEST.json` — 1,921 rows, `content_hash` **`f0b452705cf8bf1f…`** |
| Frozen by | `scripts/freeze_campus_final_batch.py` (reads the committed inventory + the local ledger; re-hashes nothing) |
| Reconciliation | **0** files changed since the scan (`unstable_source: []`), **0** files on disk that neither the inventory nor the ledger names |
| Campus courses | **28**, all `visibility=private`, `publication_status=private` |
| Published files | **0** |
| Indexed documents / chunks | 831 documents, 21,056 chunks (28 offerings) |
| Growth switch | `CMUI_CAMPUS_CATALOG_GROWTH` — **unset means `paused`** (fail-closed) |

## 1. Every file's terminal state (measured, sums to 1,921)

| Terminal state | Files | What it means |
|---|---|---|
| `INGESTED_PRIVATE` | **783** | indexable teaching material, ingested through the real `IngestionService` into a private campus course; each row has a `document_id`; **none published** |
| `DOWNLOAD_ONLY` | **876** | stored and recorded, but no loader reads the format (video, archives, data files) — never counted as learnable material and never a coverage basis |
| `WITHHELD_POLICY` | **204** | 170 information/announcement files, 13 training files, 21 personal or restricted files. Not campus-course candidates; the 21 redacted ones are described in §4 |
| `WITHHELD_OWNER_DECISION` | **49** | blocked pending the owner's rights decision (assessment material, unlicensed copies, and files whose source is not verifiable) |
| `NOT_INGESTED` | **7** | academic files that never reached the ledger (physical-education media and similar); listed, not claimed |
| `INTERNAL_SOURCE_RECORD` | **2** | the two `_download_manifest.csv` files themselves |
| `PUBLISHED` | **0** | — |
| `UNSTABLE_SOURCE` / `SOURCE_MISSING` | **0** / **0** | no file changed after the scan and no file is missing |

**Publication is not a code step.** Everything ingested keeps `review_status = NEEDS_REVIEW` and
`publication_basis = OWNER_PLATFORM_IMPORT_INTENT_RIGHTS_UNVERIFIED`. The single decision that
starts publication is the one on `docs/coursejesus/CAMPUS_RIGHTS_REVIEW_LIST.csv` (1,715 rows,
one per file whose rights nobody has verified): a student's own access, or an MIT licence on a
tool, is not a licence to redistribute course material to every registered user. Until that
decision arrives, the correct state of `CAMPUS_CONTENT_PUBLISHED` is **`NOT_STARTED`, and no
report may read as if the campus library were live**. A local ingestion count is not a production
publication count; the production site has no campus course from this batch.

## 2. The pause, and how it is enforced

The expansion path is closed at both ends, and both refusals are tested:

| Path | Behaviour while closed | Exit |
|---|---|---|
| `scripts/scan_campus_inventory.py` (discovery: walks the two roots) | refuses **before** the first walk, so a paused run does not even stat the download directories | **3** |
| `app/campus_ingestion.py::ingest_course` (ingestion: creates courses/documents/chunks) | refuses before reading a source file or writing a row | raises `CampusCatalogGrowthPaused` |
| `scripts/ingest_campus_course.py` | refuses before reading the plan, the files or the database | **3** |
| `scripts/plan_campus_ingestion.py` | **still available**: it reads the frozen committed inventory and writes a plan. It cannot add material, and it is what a closure report is built from | 0 |

`CMUI_CAMPUS_CATALOG_GROWTH` is **fail-closed**: unset means `paused`, so a forgotten variable
cannot reopen a closed batch, and an unknown value raises rather than being ignored (a misspelling
that silently keeps the gate open is the failure this project refuses elsewhere too). Reopening is
one explicit value — `CMUI_CAMPUS_CATALOG_GROWTH=open` — and is a decision to start a *new* batch,
not to extend this one.

**There is no watcher, cron job, systemd timer or startup scan to remove.** The growth path has
always been these CLIs, run by hand (`scripts/scan_campus_inventory.py`,
`scripts/plan_campus_ingestion.py`, `scripts/ingest_campus_course.py`, plus the batch runners kept
in git-ignored `work/current-change/`). That was verified by reading the scripts and by the
absence of any scheduler entry in the repository; recording it matters, because "we removed the
timer" would otherwise be an unverifiable claim.

### The proof, run against the real source directory

A synthetic file was created in `D:\Canvas` (`_growth_pause_probe_20260924T1452Z.txt`, 79 bytes)
and the two growth paths were invoked:

| Step | Result |
|---|---|
| `scan_campus_inventory.py --root D:\Canvas --out …` | **exit 3**, message naming `CAMPUS_FINAL_BATCH_CLOSURE.md`, and **no inventory file written** |
| `ingest_campus_course.py --course 630 …` | **exit 3**, **no database created** |
| Source directory afterwards | the probe file was **still there** under its original name, and `D:\Canvas` still holds its 202 files — nothing was discovered, ingested, published, moved or deleted |
| Cleanup | the probe file was removed by hand; `D:\Canvas` is back to 202 files, byte-for-byte unchanged |

The same behaviour is pinned by `services/rag-api/tests/test_campus_growth_pause.py` (7 tests),
which also proves the switch itself: unset → paused, `open` → open, an unknown value → refused.

## 3. What the pause does **not** affect

The pause closes one directory-driven growth path. It does not close the product, and the tests
prove it rather than asserting it:

* **Private uploads** — a real upload into a private course still creates a document and chunks
  while the catalog is closed (`test_a_private_upload_still_works_while_growth_is_closed`).
* **Reading existing campus courses** — teaching, question answering, files, previews, shares and
  assessments never consult the growth gate; only discovery and ingestion do.
* **The user's own Canvas private import** — that path is the OAuth import (`canvas_import_*`
  tables, `canvas_connections`), not this batch; it is untouched by this closure.
* **Backups, migrations, rollback, and the test suites** — unchanged.
* **Exercise and assessment generation for existing courses** — unchanged; a curated course gets
  its questions from its own material, which is already indexed.

## 4. Honest limits of this freeze

1. **Local bytes, not Canvas truth.** The `sha256` in the manifest identifies the local copy, so it
   proves identity and deduplication on this machine. It does not prove the file still matches what
   Canvas serves, and it says nothing about redistribution rights.
2. **21 rows are deliberately redacted.** The committed inventory replaces the name and path of
   personal/restricted files (class lists, attendance, individual feedback, submissions) with
   `REDACTED_PERSONAL_OR_RESTRICTED`; the manifest keeps them withheld and never calls them
   missing. Two files that are on disk but in neither the inventory nor the ledger are represented
   in the manifest by **the SHA-256 of their path**, not by the path, for the same reason. The
   unredacted working copy stays out of Git.
3. **`D:\Canvas` has no `file_id` column**, so same-name/different-id detection is complete only
   for the `D:\Canvas-DG` root; the affected rows say so.
4. **The `INGESTABLE` plan count is an upper bound.** 696 planned-ingestable files were not indexed
   — 575 are source code and web assets outside the upload allow-list, 42 exceed the 20 MB limit,
   and ~78 have no extractable text. Teaching the platform to parse those is a **decision**, not a
   cleanup, and it was not taken unilaterally.
5. **This batch is a local record, not production.** No production system was contacted, and no
   production publication exists for these files.

## 5. If the owner later reopens campus expansion

1. Set `CMUI_CAMPUS_CATALOG_GROWTH=open` for the run only, as the explicit decision it is.
2. Scan into a **new** batch id (`scripts/scan_campus_inventory.py`) — never extend this manifest.
3. Plan and ingest with the same CLIs; a changed file is blocked rather than ingested, exactly as
   the batch above did.
4. Return the switch to `paused` (unset) when the batch ends, and record a new closure.

## 6. Evidence

| Artefact | What it shows |
|---|---|
| `CAMPUS_FINAL_BATCH_MANIFEST.json` | the frozen 1,921 rows with hashes, terminal states, the content hash, redaction counts and the two campus-course facts |
| `docs/coursejesus/LOCAL_CAMPUS_INVENTORY.csv` | the committed, redacted scan this freeze reuses |
| `docs/coursejesus/CAMPUS_RIGHTS_REVIEW_LIST.csv` | the 1,715 rows waiting for the owner's single rights decision |
| `docs/coursejesus/CAMPUS_SOURCE_AND_PUBLICATION_MATRIX.md` | the classification policy, the per-course matrix and the misclassification history |
| `services/rag-api/app/campus_growth.py` | the switch, its fail-closed default and the refusals |
| `services/rag-api/tests/test_campus_growth_pause.py` | 7 tests: the switch, the two refusals, and the private upload that still works |
| `work/current-change/campus-library.sqlite3` | the local ledger the per-file states were read from (`campus_material_records`, 1,728 rows) |
