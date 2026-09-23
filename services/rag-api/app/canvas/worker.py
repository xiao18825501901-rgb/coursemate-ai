"""The Canvas import worker: claim one job, fetch its files, ingest them, record the outcome.

Everything this module needs already exists as a rule somewhere else, and it deliberately
does not restate any of them:

* `job.py` says what an import *is* (states, legal transitions, the frozen selection, the
  per-file record and the verdict a set of file results has earned);
* `worker_decisions.py` says what a failure *means* (never retry a 403, honour the school's
  `Retry-After`, let a credential failure end the batch);
* `store.py` owns the rows (idempotent creation, leases, per-file checkpoints);
* `adapter.py` owns every Canvas call, and `IngestionService` owns every write into a course.

What is left for the worker is the sequencing and the honesty of the record: which phase the
job is in, what each file ended as, and when the job is finished. Four properties are the
reason this is a module rather than a script:

1. **The database is the only state.** A run rebuilds the job from `canvas_import_files`
   rows, so a killed worker resumes from the checkpoint instead of restarting the import.
   In-memory progress is never consulted for a decision.
2. **One writer.** Every progress write is conditional on this worker still holding the
   lease. If ownership is gone the run stops immediately rather than racing the new owner.
3. **Nothing is invented.** A file that was not parsed is `DOWNLOAD_ONLY`; a course that
   could not be listed is a warning the user sees; a job with any unfinished file is not
   terminal at all. There is no path here that writes a document row by hand — ingestion goes
   through `IngestionService`, exactly as an HTTP upload would.
4. **The worker holds no token.** It asks an injected factory for an adapter whose token
   provider reads the encrypted credential store, so nothing in this file can leak one.

Downloads land in `work_dir` under a path derived from the external identity, which is what
lets a resumed run reuse bytes it already verified. A local copy is deleted only once the
same bytes are stored durably by the course store; anything else stays, because it is the
only copy CourseMate has.
"""

from __future__ import annotations

import hashlib
import logging
import pathlib
import re
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from app.errors import ApiError
from app.learning.uploads import MEDIA_TYPES
from app.models import CourseCreate
from app.services.ingestion import IngestionService

from .adapter import CanvasCourse, CanvasReadAdapter, CanvasReadError
from .job import (
    AWAITING_SELECTION,
    CANCELLED,
    COMPLETED,
    COMPLETED_WITH_WARNINGS,
    DISCOVERING,
    DOWNLOADING,
    EMPTY,
    EXPIRED_TOKEN,
    FAILED,
    FILE_CANCELLED,
    FILE_DOWNLOAD_ONLY,
    FILE_DOWNLOADED,
    FILE_INDEXED,
    FILE_PENDING,
    FILE_SKIPPED_IDENTICAL,
    FILE_TERMINAL,
    FILE_WARNING,
    INDEXING,
    INGESTING,
    NEEDS_REAUTH,
    NETWORK,
    NOT_FOUND,
    QUEUED,
    RATE_LIMIT,
    REJECTED_BY_LIMITS,
    TERMINAL_STATES,
    TOO_LARGE,
    TRANSITIONS,
    UNSUPPORTED,
    VERIFYING,
    FileRecord,
    ImportJob,
    JobStateError,
)
from .store import CanvasJobRepository, ClaimedJob
from .worker_decisions import outcome_for_download, outcome_for_error, should_stop_job

LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_FILES_PER_RUN: Final = 200
DEFAULT_MAX_ATTEMPTS: Final = 3
# A `Retry-After` longer than this is respected by ending the run and letting the next one
# continue, rather than holding the lease asleep for minutes.
MAX_RATE_LIMIT_WAIT_SECONDS: Final = 120.0
# Longest error text kept on a row: details are for a human reading the import screen.
MAX_ERROR_DETAIL: Final = 500
DOWNLOADED: Final = "DOWNLOADED"

# States a worker may work on. DISCOVERING and AWAITING_SELECTION belong to the interactive
# flow: a job in either one is waiting for the student, and a worker that moved it forward
# would be answering a question nobody asked.
WORKABLE_STATES: Final = (QUEUED, DOWNLOADING, VERIFYING, INGESTING, INDEXING)

# What `_import_file` reports back to the batch loop.
_CONTINUE: Final = ""
_DEFER: Final = "defer"
_REAUTH: Final = "needs_reauth"


class _LeaseLost(RuntimeError):
    """Another worker owns this job now; the run must stop without writing anything."""


class _NeedsReauth(RuntimeError):
    """The credential stopped working: the whole batch ends, whichever file noticed."""

    def __init__(self, error_class: str, detail: str) -> None:
        super().__init__(f"{error_class}: {detail}")
        self.error_class = error_class
        self.detail = detail


@dataclass(frozen=True)
class RunResult:
    """What one `run_once` did, for the caller's log and for tests to assert on."""

    job_id: str
    status: str
    processed: int = 0
    skipped: int = 0
    pending: int = 0
    stopped: str = ""


def material_media_type(extension: str) -> str | None:
    """The media type to store this extension under, or None when it is not indexable.

    The allow-list is `app.learning.uploads.MEDIA_TYPES` — the same one an HTTP upload is
    checked against — so a worker cannot store material the rest of the product would
    refuse. The canonical member is preferred over `application/octet-stream`, which is the
    permissive fallback the upload validator also accepts.
    """
    allowed = MEDIA_TYPES.get(extension.casefold())
    if not allowed:
        return None
    preferred = sorted(name for name in allowed if name != "application/octet-stream")
    return preferred[0] if preferred else sorted(allowed)[0]


def safe_upload_name(display_name: str, *, file_id: str) -> str:
    """A filename that is safe to store, derived from the school's name for the file.

    The upload path refuses names containing path separators or control characters, and a
    Canvas file may legitimately be named something this product cannot store verbatim.
    Replacing the offending characters keeps the document findable under a recognisable
    name; the school's original spelling stays in `canvas_import_files.display_name`.
    """
    name = pathlib.PurePosixPath(display_name.replace("\\", "/")).name.strip()
    name = "".join(
        character if ord(character) >= 32 and character != "\x7f" else "_" for character in name
    )
    if not name or name in {".", ".."}:
        name = f"canvas-file-{file_id}"
    if len(name) > 200:
        suffix = pathlib.PurePosixPath(name).suffix
        name = name[: 200 - len(suffix)] + suffix
    return name


def target_course_slug(*, institution_host: str, course_ids: Sequence[str]) -> str:
    """A valid `CourseCreate.id` for the private course one selection imports into.

    Derived from the institution host and the frozen selection, so re-running the same
    import addresses the same id, and the id stays inside the model's `[a-z0-9-]` pattern.
    """
    key = re.sub(r"[^a-z0-9]+", "-", institution_host.casefold()).strip("-") or "canvas"
    digest = hashlib.sha256(
        ",".join(sorted(str(course) for course in course_ids)).encode("utf-8")
    ).hexdigest()[:12]
    return f"canvas-{key}-{digest}"[:50].rstrip("-")


def target_course_name(courses: Sequence[CanvasCourse]) -> str:
    """A user-facing name for the imported private course, marked as a Canvas import."""
    names = [course.name.strip() or course.course_code.strip() or course.id for course in courses]
    suffix = "（Canvas 导入）"
    if not names:
        return f"Canvas 课程{suffix}"[:120]
    head = names[0] if len(names) == 1 else f"{names[0]} 等 {len(names)} 门课程"
    return head[: 120 - len(suffix)] + suffix


def default_target_course_resolver(
    ingestion: IngestionService, repository: CanvasJobRepository
) -> Callable[[ClaimedJob, ImportJob, Sequence[CanvasCourse]], str]:
    """Create the private course an import writes into, once, through the course service.

    The course is created the way any student creates one (`is_admin=False`), which is what
    makes it `course_type='user'`, `visibility='private'`, `publication_status='private'`,
    subject to the user quota, and invisible to the administrator publishing pipeline. The
    link back to Canvas is the job row's `target_course_id` plus `institution_origin`, which
    is a real foreign key rather than a label; the description restates it for a human. No
    document, version, chunk or index row is written here.
    """

    def resolve(claimed: ClaimedJob, job: ImportJob, courses: Sequence[CanvasCourse]) -> str:
        existing = repository.target_course_of(claimed.job_id)
        if existing:
            return existing
        host = urlsplit(claimed.institution_origin).hostname or "canvas"
        payload = CourseCreate(
            id=target_course_slug(institution_host=host, course_ids=job.course_ids),
            name=target_course_name(courses),
            description=(
                f"由 {claimed.institution_origin} 的 Canvas 课程导入"
                f"（{len(job.course_ids)} 门课程），仅导入者本人可见。"
            ),
        )
        course = ingestion.create_course(
            payload, owner_user_id=claimed.owner_user_id, is_admin=False
        )
        repository.set_target_course(claimed.job_id, course.id)
        return course.id

    return resolve


class CanvasImportWorker:
    """Runs one claimed job as far as it can go, one checkpoint at a time."""

    def __init__(
        self,
        *,
        repository: CanvasJobRepository,
        ingestion: IngestionService,
        adapter_for: Callable[[ClaimedJob], CanvasReadAdapter],
        target_course_for: Callable[[ClaimedJob, ImportJob, Sequence[CanvasCourse]], str],
        work_dir: pathlib.Path,
        max_ingest_bytes: int,
        worker_id: str = "canvas-import-worker",
        max_files_per_run: int = DEFAULT_MAX_FILES_PER_RUN,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        sleeper: Callable[[float], None] = time.sleep,
        credential_release: Callable[[ImportJob, str], None] | None = None,
        credential_available: Callable[[ImportJob], bool] | None = None,
    ) -> None:
        if max_files_per_run < 1 or max_attempts < 1:
            raise ValueError("the worker needs at least one file and one attempt per run")
        self.repository = repository
        self.ingestion = ingestion
        self.adapter_for = adapter_for
        self.target_course_for = target_course_for
        self.work_dir = pathlib.Path(work_dir)
        self.max_ingest_bytes = max_ingest_bytes
        self.worker_id = worker_id
        self.max_files_per_run = max_files_per_run
        self.max_attempts = max_attempts
        self._sleep = sleeper
        # Called once per run, at the point where this run's Canvas reads are finished and before
        # anything is parsed or indexed. It is how a transient task credential stops existing at
        # the right moment instead of at the end of the job. Absent for a saved connection, which
        # is a credential the user chose to keep.
        self._credential_release = credential_release
        # Answers "can this job still read Canvas?". Absent means yes, which is the truth for a
        # saved connection; a job with a transient credential is wired to the store so a destroyed
        # token stops the reading without stopping the indexing of bytes already fetched.
        self._credential_available = credential_available

    # -------------------------------------------------------------------- entry points
    def drain(self, *, max_jobs: int = 1) -> list[RunResult]:
        """Run up to `max_jobs` claimable jobs, then tidy the worker's own storage."""
        results: list[RunResult] = []
        for _ in range(max(0, max_jobs)):
            result = self.run_once()
            if result is None:
                break
            results.append(result)
        self.cleanup_empty_directories()
        return results

    def run_once(self) -> RunResult | None:
        """Claim one job and work it. Returns None when there is nothing to claim."""
        claimed = self.repository.claim(worker_id=self.worker_id)
        if claimed is None:
            return None
        try:
            return self._process(claimed)
        except _LeaseLost:
            # Another worker owns the job now: writing anything would corrupt its run.
            LOGGER.warning("canvas import job %s was taken over; stopping", claimed.job_id)
            return RunResult(claimed.job_id, claimed.status, stopped="lease_lost")
        except _NeedsReauth as stop:
            return self._finish(
                self._load(claimed),
                [],
                reauth=(stop.error_class, stop.detail),
                stopped="reauth",
            )
        except JobStateError as error:
            # Logged as well as recorded: a job-state failure used to leave a status in the row
            # and nothing anywhere else, which is the hardest kind of failure to diagnose.
            LOGGER.warning("canvas import job %s failed a state check: %s", claimed.job_id, error)
            return self._fail(claimed, "JOB_STATE", str(error), stopped="job_state")
        except ApiError as error:
            return self._fail(claimed, error.code, error.message, stopped="api_refused")
        except Exception as error:  # noqa: BLE001 - a defect must not strand a lease
            LOGGER.exception("canvas import job %s failed unexpectedly", claimed.job_id)
            return self._fail(
                claimed, "WORKER_DEFECT", f"{type(error).__name__}: {error}", stopped="defect"
            )

    # ------------------------------------------------------------------ the run itself
    def _load(self, claimed: ClaimedJob) -> ImportJob:
        """Rebuild the job from its rows. Nothing held in memory survives a restart."""
        return ImportJob(
            job_id=claimed.job_id,
            connection_id=claimed.connection_id,
            subject=claimed.owner_user_id,
            institution_origin=claimed.institution_origin,
            course_ids=claimed.course_ids,
            fingerprint=claimed.fingerprint,
            status=claimed.status,
            files=self.repository.list_files(claimed.job_id),
            credential_ref=claimed.credential_ref,
            credential_kind=claimed.credential_kind,
            credential_state=claimed.credential_state,
        )

    def _process(self, claimed: ClaimedJob) -> RunResult:
        job = self._load(claimed)
        if job.status in (DISCOVERING, AWAITING_SELECTION):
            # The student has not confirmed a selection yet. Releasing the lease is not a
            # failure: it keeps a crashed worker's job reclaimable and leaves the state alone.
            self.repository.release(job.job_id)
            return RunResult(
                job.job_id, job.status, pending=len(job.pending_files()), stopped="awaiting_user"
            )
        if job.is_terminal:
            self.repository.release(job.job_id)
            return RunResult(job.job_id, job.status, stopped="already_finished")

        failures: list[tuple[str, str, str]] = []
        # Can this run read Canvas at all? For a saved connection the answer is always yes. For a
        # job that borrowed a transient credential it is a real question — the credential is
        # destroyed once its reads are done — and the answer decides whether this run re-checks
        # the school (which is a read) or simply finishes the bytes already on disk (which is not).
        may_read = self._credential_available is None or self._credential_available(job)
        pending = job.pending_files()
        # A job that cannot read needs a credential if it has no file list yet (discovery is a
        # read) or if any listed file still needs its bytes. An empty file list plus no credential
        # must never fall through to "the course was empty", which would report a dead token as a
        # finished import with warnings.
        if not may_read and (
            not job.files or any(self._needs_fetch(job, record) for record in pending)
        ):
            # Bytes that are not on disk cannot be fetched without a credential. Anything already
            # fetched is still indexed first — it would be wasteful to drop it — and then the job
            # says plainly that a new credential is needed.
            existing_target = self.repository.target_course_of(job.job_id)
            if existing_target:
                self._ingest_pass(job, existing_target, failures)
            return self._finish(
                job,
                [],
                reauth=(
                    EXPIRED_TOKEN,
                    "the credential for this task is no longer available; a new one is needed",
                ),
                stopped="reauth",
            )
        adapter = self.adapter_for(claimed) if may_read else None
        courses: list[CanvasCourse] = []
        if adapter is not None:
            courses = self._enrolled_courses(adapter, job, failures)
            self._discover(job, adapter, courses, failures)
            self._advance(job, DOWNLOADING)

        if not job.files:
            # An import that found nothing is COMPLETED_WITH_WARNINGS, never a clean success.
            return self._finish(job, failures, reauth=None, stopped="no_files")

        target_course_id = self._target_course(claimed, job, courses)
        processed = 0
        deferred: set[tuple[str, str, str]] = set()
        stopped = ""
        reauth: tuple[str, str] | None = None
        while adapter is not None:
            # Only records that still need *bytes* are candidates here. A downloaded file stays
            # non-terminal until it is ingested, so without this filter the download pass would
            # keep picking the file it had just fetched and never reach the next one.
            candidates = [
                record
                for record in job.pending_files()
                if record.key not in deferred and self._needs_fetch(job, record)
            ]
            if not candidates:
                # No file left to fetch. A record that still needs bytes and was deferred in this
                # run means the job is *not* finished: reporting a terminal state here would turn
                # "the school timed out on three files" into a clean import. A record that merely
                # needs ingesting is not a stop at all — the ingest pass below handles it.
                remaining_fetch = [
                    record for record in job.pending_files() if self._needs_fetch(job, record)
                ]
                stopped = "deferred" if remaining_fetch else ""
                break
            if processed >= self.max_files_per_run:
                stopped = "batch_limit"
                break
            if not self.repository.touch(job.job_id, worker_id=self.worker_id):
                raise _LeaseLost(job.job_id)
            if self.repository.status_of(job.job_id) == CANCELLED:
                # Stop reading at the next checkpoint. What was already fetched is still indexed
                # below: the bytes are on disk, parsing needs no credential, and throwing them
                # away would delete value the user's token already paid for. The files that were
                # never fetched are marked CANCELLED after the ingest pass.
                stopped = "cancelled"
                break
            record = candidates[0]
            processed += 1
            reason = self._fetch_file(job, record, adapter, failures)
            if reason == _DEFER:
                deferred.add(record.key)
            elif reason == _REAUTH:
                reauth = (record.error_class or EXPIRED_TOKEN, record.error_detail)
                stopped = "reauth"
                break

        # The reads are over for this run. Everything after this line parses and indexes bytes
        # that are already on disk, and a credential must not be alive for any of it: that is the
        # owner's rule, and the reason the download and ingest passes are separate.
        reads_finished = not any(self._needs_fetch(job, record) for record in job.pending_files())
        if reads_finished:
            self._release_credential(job, "canvas_reads_complete")
        if stopped == "reauth":
            # A dead credential is a terminal verdict, not a pause: the user has to act. The
            # credential is released above whether it died or the run simply finished reading.
            self._release_credential(job, "credential_failed")
            return self._finish(job, failures, reauth=reauth, stopped="reauth")
        # A cancellation is captured *before* the ingest pass, because indexing writes working
        # phases of its own (`INGESTING`, `INDEXING`) and would otherwise wipe the row's
        # CANCELLED marker — which is how a cancelled import could come back to life and finish.
        cancelled = stopped == "cancelled" or self.repository.status_of(job.job_id) == CANCELLED
        # Bytes fetched before this run stopped are still indexed: they were read legitimately,
        # they are already on disk, and parsing needs no credential. Dropping them would throw
        # away work the user already paid for with their token.
        ingested = self._ingest_pass(job, target_course_id, failures)
        if cancelled:
            # The user cancelled while this run was working. Report that, restore the row's own
            # verdict, and never let the finish path write a terminal *success* over it.
            for record in job.pending_files():
                self._record(
                    job,
                    record,
                    FILE_CANCELLED,
                    detail="the import was cancelled before this file was reached",
                )
            self.repository.set_status(job.job_id, CANCELLED)
            self._release_credential(job, "task_cancelled")
            return self._working_result(job, processed, "cancelled")
        if stopped:
            # Not finished: hand the lease back unchanged so the next run continues here.
            self.repository.release(job.job_id)
            return self._working_result(job, processed, stopped)
        if ingested >= self.max_files_per_run and any(
            self._reusable(self._sink(job.job_id, record), record)
            for record in job.pending_files()
        ):
            # The ingest batch limit was reached with bytes still waiting. Not finished, and the
            # next run needs no credential for them: they are already downloaded.
            self.repository.release(job.job_id)
            return self._working_result(job, processed, "batch_limit")
        skipped = sum(1 for record in job.files if record.status == FILE_SKIPPED_IDENTICAL)
        result = self._finish(job, failures, reauth=reauth, stopped="")
        return RunResult(
            result.job_id,
            result.status,
            processed=processed,
            skipped=skipped,
            pending=result.pending,
            stopped=result.stopped,
        )

    def _needs_fetch(self, job: ImportJob, record: FileRecord) -> bool:
        """Whether this record still needs a Canvas read, i.e. whether the credential is needed."""
        if record.status in (FILE_DOWNLOADED, FILE_DOWNLOAD_ONLY, FILE_INDEXED):
            return False
        if record.status == FILE_SKIPPED_IDENTICAL:
            return False
        return not self._reusable(self._sink(job.job_id, record), record)

    def _release_credential(self, job: ImportJob, reason: str) -> None:
        """Tell the caller this job's Canvas reads are over. Never called for a saved connection.

        A job that borrowed a transient credential must be told when to destroy it, and this is
        the single point where that happens. The callback is given the reason so the receipt can
        distinguish a completed read pass from a cancelled task or a credential that died.
        """
        if not job.uses_transient_credential or self._credential_release is None:
            return
        try:
            self._credential_release(job, reason)
        except Exception:  # noqa: BLE001 - a release failure must not become an import failure
            LOGGER.exception("releasing the task credential for job %s failed", job.job_id)

    def _ingest_pass(
        self,
        job: ImportJob,
        target_course_id: str,
        failures: list[tuple[str, str, str]],
    ) -> int:
        """Parse and index every file whose bytes are already on disk. Needs no credential.

        This pass exists as a separate step so that "the credential was destroyed before indexing"
        is a property of the control flow rather than a claim about timing. It is also what makes
        a second run able to finish a job whose token is already gone.
        """
        ingested = 0
        for record in list(job.pending_files()):
            if ingested >= self.max_files_per_run:
                break
            sink = self._sink(job.job_id, record)
            if not self._reusable(sink, record):
                continue
            if not self.repository.touch(job.job_id, worker_id=self.worker_id):
                raise _LeaseLost(job.job_id)
            self._ingest(job, record, sink, target_course_id, failures)
            ingested += 1
        return ingested

    def _working_result(self, job: ImportJob, processed: int, stopped: str) -> RunResult:
        """A run that ended before the job did: report the phase the job is really in."""
        return RunResult(
            job.job_id,
            self.repository.status_of(job.job_id) or job.status,
            processed=processed,
            pending=len(job.pending_files()),
            stopped=stopped,
        )

    # ----------------------------------------------------------------------- discovery
    def _enrolled_courses(
        self,
        adapter: CanvasReadAdapter,
        job: ImportJob,
        failures: list[tuple[str, str, str]],
    ) -> list[CanvasCourse]:
        """The student's own readable courses, filtered to the frozen selection.

        The selection comes from our own database, but it was chosen in a browser, so it is
        re-checked against the live enrolment list instead of trusted: a course id the student
        is not enrolled in must not be read, whoever put it there.
        """
        try:
            own = {course.id: course for course in adapter.student_courses()}
        except CanvasReadError as error:
            self._stop_or_classify(error, "enrollments", failures)
            return []
        selected: list[CanvasCourse] = []
        for course_id in job.course_ids:
            course = own.get(course_id)
            if course is None:
                failures.append(
                    (
                        course_id,
                        NOT_FOUND,
                        "the course is not among this account's active or completed enrolments",
                    )
                )
                continue
            if not course.is_readable_history:
                failures.append(
                    (
                        course_id,
                        NOT_FOUND,
                        f"the course state is {course.workflow_state!r}, which is not readable",
                    )
                )
                continue
            selected.append(course)
        return selected

    def _discover(
        self,
        job: ImportJob,
        adapter: CanvasReadAdapter,
        courses: Sequence[CanvasCourse],
        failures: list[tuple[str, str, str]],
    ) -> None:
        """List every selected course's files and record one row per external identity."""
        for course in courses:
            try:
                entries = adapter.course_files(course.id)
            except CanvasReadError as error:
                self._stop_or_classify(error, course.id, failures)
                continue
            for entry in entries:
                record = job.add_file(
                    FileRecord(
                        origin=job.institution_origin,
                        course_id=course.id,
                        file_id=entry.id,
                        display_name=entry.display_name,
                        size=entry.size,
                        source_updated_at=entry.updated_at,
                        folder_or_module=entry.folder_id,
                    )
                )
                # The identity is always written; the *status* written back is the row's own,
                # so a file whose version changed returns to PENDING while an unchanged file
                # keeps whatever checkpoint it had reached.
                self.repository.upsert_file(
                    job.job_id,
                    origin=job.institution_origin,
                    course_id=course.id,
                    file_id=entry.id,
                    display_name=entry.display_name,
                    size=entry.size,
                    updated_at=entry.updated_at,
                    status=record.status,
                    folder_or_module=entry.folder_id,
                )

    def _stop_or_classify(
        self, error: CanvasReadError, context: str, failures: list[tuple[str, str, str]]
    ) -> None:
        """A dead credential ends the whole batch; anything else is this item's problem."""
        outcome = outcome_for_error(error, attempt=1)
        if should_stop_job(outcome):
            raise _NeedsReauth(outcome.error_class, outcome.detail or context)
        failures.append((context, outcome.error_class, outcome.detail))

    # --------------------------------------------------------------------- target course
    def _target_course(
        self, claimed: ClaimedJob, job: ImportJob, courses: Sequence[CanvasCourse]
    ) -> str:
        target = self.repository.target_course_of(job.job_id)
        if target is None:
            target = self.target_course_for(claimed, job, courses)
        if not target:
            raise JobStateError("the import produced no private course to write into")
        return target

    # ------------------------------------------------------------------------- per file
    def _fetch_file(
        self,
        job: ImportJob,
        record: FileRecord,
        adapter: CanvasReadAdapter,
        failures: list[tuple[str, str, str]],
    ) -> str:
        """Fetch and verify one file's bytes. Returns _CONTINUE, _DEFER or _REAUTH.

        Downloading and ingesting are separate methods because they are separate *phases* of a
        run: every fetch happens before any parse or index, so the credential the fetch needed is
        destroyed in between rather than living on through the indexing work.
        """
        if record.attempts >= self.max_attempts:
            self._record(
                job,
                record,
                FILE_WARNING,
                error_class=record.error_class or NETWORK,
                detail=f"gave up after {record.attempts} attempts: {record.error_detail}",
            )
            failures.append((record.file_id, record.error_class or NETWORK, record.error_detail))
            return _CONTINUE

        sink = self._sink(job.job_id, record)
        if self._reusable(sink, record):
            return _CONTINUE
        if record.size and record.size > self.max_ingest_bytes:
            detail = (
                f"the file is {record.size} bytes, above the "
                f"{self.max_ingest_bytes}-byte ingestion limit"
            )
            self._record(job, record, FILE_WARNING, error_class=TOO_LARGE, detail=detail)
            failures.append((record.file_id, TOO_LARGE, detail))
            return _CONTINUE
        decision = self._download(job, record, adapter, sink)
        if decision in {_DEFER, _REAUTH}:
            return decision
        if record.status != FILE_DOWNLOADED:
            failures.append((record.file_id, record.error_class, record.error_detail))
        return _CONTINUE

    def _download(
        self,
        job: ImportJob,
        record: FileRecord,
        adapter: CanvasReadAdapter,
        sink: pathlib.Path,
    ) -> str:
        """Download and verify one file, retrying only what the rules allow."""
        while True:
            attempt = record.attempts + 1
            try:
                url = adapter.course_file_download_url(record.course_id, record.file_id)
                result = adapter.download(url, sink)
            except CanvasReadError as error:
                outcome = outcome_for_error(error, attempt=attempt)
                if should_stop_job(outcome):
                    self._record(
                        job,
                        record,
                        outcome.status,
                        error_class=outcome.error_class,
                        detail=outcome.detail,
                        attempts=attempt,
                    )
                    return _REAUTH
                if outcome.retryable:
                    wait = min(outcome.retry_after or 1.0, MAX_RATE_LIMIT_WAIT_SECONDS)
                    self._record(
                        job,
                        record,
                        FILE_PENDING,
                        error_class=outcome.error_class,
                        detail=outcome.detail,
                        attempts=attempt,
                    )
                    if outcome.error_class == RATE_LIMIT and attempt < self.max_attempts:
                        # The school asked for a specific wait; honouring it and retrying now
                        # is the difference between a throttled import and a failed one.
                        self._sleep(wait)
                        continue
                    # Anything else retryable is left for the next run rather than holding
                    # this batch on one unresponsive file.
                    return _DEFER
                self._record(
                    job,
                    record,
                    outcome.status,
                    error_class=outcome.error_class,
                    detail=outcome.detail,
                    attempts=attempt,
                )
                return _CONTINUE
            outcome = outcome_for_download(
                bytes_written=result.bytes_written,
                declared_size=record.size or None,
                sha256=result.sha256,
            )
            if outcome.status != DOWNLOADED:
                self._record(
                    job,
                    record,
                    outcome.status,
                    error_class=outcome.error_class,
                    detail=outcome.detail,
                    sha256=result.sha256,
                    attempts=attempt,
                )
                return _CONTINUE
            break
        self._advance(job, VERIFYING)
        if result.bytes_written > self.max_ingest_bytes:
            detail = f"the download was {result.bytes_written} bytes, above the ingestion limit"
            self._record(
                job,
                record,
                FILE_WARNING,
                error_class=TOO_LARGE,
                detail=detail,
                sha256=result.sha256,
                attempts=record.attempts + 1,
            )
            return _CONTINUE
        # The verified bytes are a checkpoint of their own: a run that dies before ingestion
        # resumes from here instead of fetching the file again.
        self._record(
            job, record, FILE_DOWNLOADED, sha256=result.sha256, attempts=record.attempts + 1
        )
        return _CONTINUE

    def _ingest(
        self,
        job: ImportJob,
        record: FileRecord,
        sink: pathlib.Path,
        target_course_id: str,
        failures: list[tuple[str, str, str]],
    ) -> str:
        """Store the downloaded bytes in the private course through the real ingestion path."""
        filename = safe_upload_name(record.display_name, file_id=record.file_id)
        extension = pathlib.PurePosixPath(filename).suffix.casefold()
        media_type = material_media_type(extension)
        if media_type is None:
            # The bytes are kept and the fact is recorded. CourseMate does not pretend to have
            # read a format it cannot parse, and coverage must never count this file.
            detail = f"{extension or 'no extension'} is not a material type CourseMate can parse"
            self._record(job, record, FILE_DOWNLOAD_ONLY, error_class=UNSUPPORTED, detail=detail)
            failures.append((record.file_id, UNSUPPORTED, detail))
            return _CONTINUE
        content = sink.read_bytes()
        self._advance(job, INGESTING)
        try:
            accepted = self.ingestion.queue_document(
                course_id=target_course_id,
                filename=filename,
                media_type=media_type,
                content=content,
                owner_user_id=job.subject,
                is_admin=False,
            )
        except ApiError as error:
            return self._ingestion_refused(job, record, sink, error, failures)
        self._advance(job, INDEXING)
        self.ingestion.process_document(accepted.document.id, accepted.job.id)
        ingest_job = self.ingestion.get_job(
            accepted.job.id, owner_user_id=job.subject, is_admin=False
        )
        document = self.ingestion.get_document(accepted.document.id)
        if str(ingest_job.status.value) == "completed" and document.chunk_count > 0:
            self._record(
                job,
                record,
                FILE_INDEXED,
                document_id=accepted.document.id,
                parse_state="parsed",
                index_state="indexed",
            )
            # The bytes now live in the course store, so the worker's copy is redundant.
            self._discard(sink)
            return _CONTINUE
        if str(ingest_job.status.value) == "completed":
            # The ingestion layer accepts an extension it has no loader for by marking the
            # document ready with zero chunks. That is stored bytes, not readable material, so
            # it is recorded as DOWNLOAD_ONLY: reporting it as indexed would let a picture or a
            # spreadsheet count towards coverage no model can actually read.
            detail = "the file produced no extractable text (0 chunks)"
            self._record(
                job,
                record,
                FILE_DOWNLOAD_ONLY,
                error_class=UNSUPPORTED,
                document_id=accepted.document.id,
                parse_state="empty",
                index_state="skipped",
                detail=detail,
            )
            failures.append((record.file_id, UNSUPPORTED, detail))
            return _CONTINUE
        # Downloaded but unreadable (a scan with no text layer, for instance). The document
        # row stays, the file is reported as DOWNLOAD_ONLY, and it is not counted as material.
        detail = str(ingest_job.error_message or "the file produced no readable text")
        self._record(
            job,
            record,
            FILE_DOWNLOAD_ONLY,
            error_class=UNSUPPORTED,
            document_id=accepted.document.id,
            parse_state="failed",
            index_state="skipped",
            detail=detail,
        )
        failures.append((record.file_id, UNSUPPORTED, detail))
        return _CONTINUE

    def _ingestion_refused(
        self,
        job: ImportJob,
        record: FileRecord,
        sink: pathlib.Path,
        error: ApiError,
        failures: list[tuple[str, str, str]],
    ) -> str:
        """Translate the ingestion layer's refusals into the frozen per-file vocabulary."""
        existing = error.details.get("documentId")
        if error.code == "DUPLICATE_DOCUMENT" and isinstance(existing, str):
            # The same bytes are already in this course: nothing to add, nothing broken.
            self._record(
                job,
                record,
                FILE_SKIPPED_IDENTICAL,
                document_id=existing,
                parse_state="parsed",
                index_state="indexed",
                detail="identical content is already in this course",
            )
            self._discard(sink)
            return _CONTINUE
        if error.code in {"COURSE_FILE_QUOTA_EXCEEDED", "USER_STORAGE_QUOTA_EXCEEDED"}:
            self._record(
                job, record, FILE_WARNING, error_class=REJECTED_BY_LIMITS, detail=error.message
            )
            failures.append((record.file_id, REJECTED_BY_LIMITS, error.message))
            return _CONTINUE
        if error.code == "FILE_TOO_LARGE":
            self._record(job, record, FILE_WARNING, error_class=TOO_LARGE, detail=error.message)
            failures.append((record.file_id, TOO_LARGE, error.message))
            return _CONTINUE
        if error.code == "EMPTY_FILE":
            self._record(job, record, FILE_WARNING, error_class=EMPTY, detail=error.message)
            failures.append((record.file_id, EMPTY, error.message))
            return _CONTINUE
        if error.status_code >= 500:
            # Our own side broke. Keep the verified bytes and the checkpoint, and let the next
            # run try again rather than telling the student their file is unreadable.
            self._record(
                job,
                record,
                FILE_PENDING,
                error_class=NETWORK,
                detail=f"{error.code}: {error.message}",
                attempts=record.attempts + 1,
            )
            return _DEFER
        self._record(
            job,
            record,
            FILE_DOWNLOAD_ONLY,
            error_class=UNSUPPORTED,
            parse_state="rejected",
            index_state="skipped",
            detail=f"{error.code}: {error.message}",
        )
        failures.append((record.file_id, UNSUPPORTED, error.message))
        return _CONTINUE

    # ------------------------------------------------------------------------ outcomes
    def _finish(
        self,
        job: ImportJob,
        failures: Sequence[tuple[str, str, str]],
        *,
        reauth: tuple[str, str] | None,
        stopped: str,
    ) -> RunResult:
        """Write the terminal state the file results justify, and nothing kinder."""
        if reauth is None and job.pending_files():
            raise JobStateError("refusing to finish a job that still has unfinished files")
        if reauth is not None:
            target = NEEDS_REAUTH
        else:
            target = job.finished_status()
            if failures and target == COMPLETED:
                # Material the user is not getting is a warning, whatever the file rows say.
                target = COMPLETED_WITH_WARNINGS
        if job.status != target:
            if not job.can_transition(target):
                raise JobStateError(f"{job.status} → {target} is not a legal transition")
            job.transition(target)
        if reauth is not None:
            code, message = reauth
        elif failures:
            code, message = failures[0][1], failures[0][2]
        else:
            code, message = "", ""
        self.repository.set_status(
            job.job_id, target, error_code=code, error_message=message[:MAX_ERROR_DETAIL]
        )
        return RunResult(job.job_id, target, pending=len(job.pending_files()), stopped=stopped)

    def _fail(self, claimed: ClaimedJob, code: str, message: str, *, stopped: str) -> RunResult:
        """Record a defect as a failed job, but only while this worker still owns it.

        Reads nothing but the job row: this runs on the way out of a failure, so it must not
        depend on the very code that just failed (a broken `list_files` must still be able to
        report a failed job rather than losing the error inside the error handler).
        """
        if not self.repository.touch(claimed.job_id, worker_id=self.worker_id):
            return RunResult(claimed.job_id, claimed.status, stopped="lease_lost")
        current = self.repository.status_of(claimed.job_id)
        if current is not None and current in TERMINAL_STATES:
            return RunResult(claimed.job_id, current, stopped="already_finished")
        status = current or claimed.status
        target = NEEDS_REAUTH if code == EXPIRED_TOKEN else FAILED
        if target not in TRANSITIONS.get(status, ()):
            target = FAILED if FAILED in TRANSITIONS.get(status, ()) else status
        if target != status:
            self.repository.set_status(
                claimed.job_id, target, error_code=code, error_message=message[:MAX_ERROR_DETAIL]
            )
            return RunResult(claimed.job_id, target, stopped=stopped)
        self.repository.release(claimed.job_id)
        return RunResult(claimed.job_id, status, stopped=stopped)

    def _record(
        self,
        job: ImportJob,
        record: FileRecord,
        status: str,
        *,
        error_class: str = "",
        detail: str = "",
        sha256: str | None = None,
        document_id: str = "",
        parse_state: str = "",
        index_state: str = "",
        attempts: int | None = None,
    ) -> None:
        """Set one file's result in memory and write the checkpoint in the same step."""
        if status in FILE_TERMINAL:
            record.finish(status, error_class=error_class, detail=detail[:MAX_ERROR_DETAIL])
        else:
            record.status = status
            record.error_class = error_class
            record.error_detail = detail[:MAX_ERROR_DETAIL]
        if sha256 is not None:
            record.bytes_sha256 = sha256
        if document_id:
            record.local_document_id = document_id
        if parse_state:
            record.parse_state = parse_state
        if index_state:
            record.index_state = index_state
        if attempts:
            record.attempts = attempts
        self.repository.record_file_result(
            job.job_id,
            origin=record.origin,
            course_id=record.course_id,
            file_id=record.file_id,
            status=record.status,
            sha256=record.bytes_sha256,
            document_id=record.local_document_id,
            error_class=record.error_class,
            error_detail=record.error_detail,
            parse_state=record.parse_state,
            index_state=record.index_state,
            attempts=record.attempts,
        )

    def _advance(self, job: ImportJob, target: str) -> bool:
        """Move the job's phase if that is legal and this worker still owns the lease."""
        if job.status == target:
            return True
        if not job.can_transition(target):
            # Already past this phase (a resumed run): a working state is not rewritten
            # backwards, because doing so would deny a legal forward transition later.
            return False
        job.transition(target)
        if not self.repository.touch(job.job_id, worker_id=self.worker_id, status=target):
            raise _LeaseLost(job.job_id)
        return True

    # ------------------------------------------------------------------- worker storage
    def _sink(self, job_id: str, record: FileRecord) -> pathlib.Path:
        """A per-file path derived from the external identity, so a resume finds it again."""
        digest = hashlib.sha256("|".join(record.key).encode("utf-8")).hexdigest()[:32]
        directory = self.work_dir / job_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory / digest

    @staticmethod
    def _reusable(sink: pathlib.Path, record: FileRecord) -> bool:
        """True when a previously verified copy of exactly these bytes is still on disk.

        Only a `DOWNLOADED` row qualifies, because that is the only state in which
        `bytes_sha256` is known to describe the version now being asked for: a row that went
        back to `PENDING` after the school changed the file keeps the *old* hash until the new
        bytes are verified, and reusing old bytes for a new version would be a silent
        correctness failure.
        """
        if record.status != FILE_DOWNLOADED or not record.bytes_sha256:
            return False
        if not sink.is_file():
            return False
        digest = hashlib.sha256()
        with sink.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest() == record.bytes_sha256

    @staticmethod
    def _discard(sink: pathlib.Path) -> None:
        """Drop the worker's copy of bytes that are now stored durably elsewhere."""
        try:
            sink.unlink(missing_ok=True)
        except OSError as error:  # pragma: no cover - a leftover file is not a job failure
            LOGGER.warning("could not remove %s: %s", sink, error)

    def cleanup_empty_directories(self) -> None:
        """Remove per-job directories that hold nothing, e.g. after a clean import.

        Deliberately conservative: a directory with any file left in it stays, because those
        are bytes whose only copy is here (an unparseable download, a failed file).
        """
        if not self.work_dir.is_dir():
            return
        for directory in sorted(self.work_dir.iterdir()):
            if not directory.is_dir():
                continue
            try:
                if not any(directory.iterdir()):
                    shutil.rmtree(directory, ignore_errors=True)
            except OSError as error:  # pragma: no cover - defensive
                LOGGER.warning("could not inspect %s: %s", directory, error)
