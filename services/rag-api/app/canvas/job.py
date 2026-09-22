"""Import-job state machine, idempotency and per-file records.

Task B4 of the CourseJesus pack: "持久后台 job … 状态机 DISCOVERING / AWAITING_SELECTION /
QUEUED / DOWNLOADING / VERIFYING / INGESTING / INDEXING / COMPLETED /
COMPLETED_WITH_WARNINGS / NEEDS_REAUTH / FAILED / CANCELLED … 同一 import request 有幂等 key，
server 冻结 connection/本人身份/所选 course IDs/材料版本/范围 … 每文件 checkpoint … 取消不删
已有资料".

This module is the pure part of that contract: the states and their legal transitions, the
frozen selection and its idempotency fingerprint, the per-file record and its final states,
and the decisions the job layer must make (may this job start, is it finished, does it count
as complete or as completed-with-warnings). It performs **no** I/O — no Canvas call, no
database, no filesystem — so it can be tested exhaustively and reused by whichever worker
implementation is added next.

The row shape follows the repository's existing `assessment_preparation_jobs` conventions
(migration 027): `id TEXT PRIMARY KEY`, scope columns with `REFERENCES … ON DELETE RESTRICT`,
a CHECK-constrained `status`, `error_code`/`error_message`, `created_at`/`updated_at`/
`completed_at` as `strftime('%Y-%m-%dT%H:%M:%fZ','now')`, and a `UNIQUE(...)` idempotency key.
The migration and the worker are the parts still missing, and this docstring says so rather
than implying the job runs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

DISCOVERING = "DISCOVERING"
AWAITING_SELECTION = "AWAITING_SELECTION"
QUEUED = "QUEUED"
DOWNLOADING = "DOWNLOADING"
VERIFYING = "VERIFYING"
INGESTING = "INGESTING"
INDEXING = "INDEXING"
COMPLETED = "COMPLETED"
COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
NEEDS_REAUTH = "NEEDS_REAUTH"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

ALL_STATES = (
    DISCOVERING,
    AWAITING_SELECTION,
    QUEUED,
    DOWNLOADING,
    VERIFYING,
    INGESTING,
    INDEXING,
    COMPLETED,
    COMPLETED_WITH_WARNINGS,
    NEEDS_REAUTH,
    FAILED,
    CANCELLED,
)
TERMINAL_STATES = (COMPLETED, COMPLETED_WITH_WARNINGS, NEEDS_REAUTH, FAILED, CANCELLED)
ACTIVE_STATES = tuple(state for state in ALL_STATES if state not in TERMINAL_STATES)

# Legal forward transitions. Anything absent is refused, which is what keeps a cancelled job
# from quietly resuming and a finished job from being rewritten.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    DISCOVERING: (AWAITING_SELECTION, FAILED, CANCELLED, NEEDS_REAUTH),
    AWAITING_SELECTION: (QUEUED, FAILED, CANCELLED),
    QUEUED: (DOWNLOADING, FAILED, CANCELLED, NEEDS_REAUTH),
    DOWNLOADING: (VERIFYING, INGESTING, COMPLETED_WITH_WARNINGS, FAILED, CANCELLED, NEEDS_REAUTH),
    VERIFYING: (INGESTING, DOWNLOADING, COMPLETED_WITH_WARNINGS, FAILED, CANCELLED, NEEDS_REAUTH),
    INGESTING: (INDEXING, COMPLETED_WITH_WARNINGS, FAILED, CANCELLED, NEEDS_REAUTH),
    INDEXING: (COMPLETED, COMPLETED_WITH_WARNINGS, FAILED, CANCELLED, NEEDS_REAUTH),
    COMPLETED: (),
    COMPLETED_WITH_WARNINGS: (),
    NEEDS_REAUTH: (QUEUED, CANCELLED),  # a re-authorised connection may resume the job
    FAILED: (),
    CANCELLED: (),
}

# Per-file error classes (pack §5 of the job contract).
EMPTY = "EMPTY"
FORBIDDEN = "FORBIDDEN"
NOT_FOUND = "NOT_FOUND"
UNSUPPORTED = "UNSUPPORTED"
EXPIRED_TOKEN = "EXPIRED_TOKEN"
RATE_LIMIT = "RATE_LIMIT"
NETWORK = "NETWORK"
TOO_LARGE = "TOO_LARGE"
REJECTED_BY_LIMITS = "REJECTED_BY_LIMITS"
HASH_MISMATCH = "HASH_MISMATCH"

# Per-file terminal states. Warnings are not failures: an empty folder or a locked file is a
# finished outcome that the user can see, not a broken import.
FILE_PENDING = "PENDING"
FILE_DOWNLOADED = "DOWNLOADED"
FILE_DOWNLOAD_ONLY = "DOWNLOAD_ONLY"
FILE_INDEXED = "INDEXED"
FILE_SKIPPED_IDENTICAL = "SKIPPED_IDENTICAL"
FILE_WARNING = "WARNING"
FILE_FAILED = "FAILED"
FILE_CANCELLED = "CANCELLED"

FILE_TERMINAL = (
    FILE_DOWNLOAD_ONLY,
    FILE_INDEXED,
    FILE_SKIPPED_IDENTICAL,
    FILE_WARNING,
    FILE_FAILED,
    FILE_CANCELLED,
)
WARNING_CLASSES = (EMPTY, FORBIDDEN, NOT_FOUND, UNSUPPORTED, TOO_LARGE, REJECTED_BY_LIMITS)


class JobStateError(RuntimeError):
    """An illegal transition or a malformed job."""


def selection_fingerprint(
    *,
    connection_id: str,
    subject: str,
    institution_origin: str,
    course_ids: list[str],
    material_versions: dict[str, str] | None = None,
) -> str:
    """The idempotency key for one frozen selection.

    Course ids are sorted so the same set in a different order is the same request, and the
    material versions observed at confirmation are included, so re-submitting after the
    school changed a course is a *new* request rather than a silent no-op.
    """
    if not connection_id or not subject or not institution_origin:
        raise JobStateError("connection, subject and institution are all required")
    if not course_ids:
        raise JobStateError("a selection must name at least one course")
    payload = {
        "connection_id": connection_id,
        "subject": subject,
        "origin": institution_origin,
        "course_ids": sorted(str(course) for course in course_ids),
        "material_versions": dict(sorted((material_versions or {}).items())),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass
class FileRecord:
    """One file's external identity, local result and checkpoint."""

    origin: str
    course_id: str
    file_id: str
    display_name: str
    size: int = 0
    source_updated_at: str = ""
    etag: str = ""
    folder_or_module: str = ""
    bytes_sha256: str = ""
    local_document_id: str = ""
    local_document_version_id: str = ""
    parse_state: str = ""
    index_state: str = ""
    status: str = FILE_PENDING
    error_class: str = ""
    error_detail: str = ""
    attempts: int = 0

    @property
    def key(self) -> tuple[str, str, str]:
        """The external identity: `origin + course_id + file_id`, never the filename."""
        return (self.origin, str(self.course_id), str(self.file_id))

    def version_changed(self, *, size: int, source_updated_at: str, etag: str = "") -> bool:
        """True when the same file id now carries different content.

        The pack forbids "same id, new version → skipped forever", so any of these changing
        means the file must be fetched again rather than assumed identical.
        """
        if size != self.size:
            return True
        if source_updated_at and source_updated_at != self.source_updated_at:
            return True
        return bool(etag and etag != self.etag)

    def finish(self, status: str, *, error_class: str = "", detail: str = "") -> None:
        if status not in FILE_TERMINAL:
            raise JobStateError(f"{status} is not a terminal file status")
        if error_class and error_class not in WARNING_CLASSES + (
            EXPIRED_TOKEN,
            RATE_LIMIT,
            NETWORK,
            HASH_MISMATCH,
        ):
            raise JobStateError(f"unknown error class {error_class}")
        self.status = status
        self.error_class = error_class
        self.error_detail = detail

    @property
    def is_warning(self) -> bool:
        return self.status == FILE_WARNING

    @property
    def is_failure(self) -> bool:
        return self.status == FILE_FAILED


@dataclass
class ImportJob:
    """A frozen import request and its progress."""

    job_id: str
    connection_id: str
    subject: str
    institution_origin: str
    course_ids: tuple[str, ...]
    fingerprint: str
    status: str = DISCOVERING
    files: list[FileRecord] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""
    error_code: str = ""
    error_message: str = ""
    saved_connection: bool = False

    # ------------------------------------------------------------- transitions
    def can_transition(self, target: str) -> bool:
        return target in TRANSITIONS.get(self.status, ())

    def transition(self, target: str, *, now: str = "") -> None:
        if target not in ALL_STATES:
            raise JobStateError(f"unknown state {target}")
        if not self.can_transition(target):
            raise JobStateError(f"{self.status} → {target} is not a legal transition")
        self.status = target
        if now:
            self.updated_at = now
        if target in TERMINAL_STATES and now:
            self.completed_at = now

    def cancel(self, *, now: str = "") -> bool:
        """Cancel at a checkpoint. Idempotent, and a finished job is not reopened."""
        if self.status in TERMINAL_STATES:
            return False
        self.transition(CANCELLED, now=now)
        return True

    # ------------------------------------------------------------------ files
    def add_file(self, record: FileRecord) -> FileRecord:
        """Add or refresh a file, keyed by external identity.

        A file already present keeps its local links (an ingested document is not thrown
        away because the same file id was seen again), and a changed version moves it back
        to pending instead of leaving it marked as done.
        """
        for existing in self.files:
            if existing.key == record.key:
                if existing.version_changed(
                    size=record.size, source_updated_at=record.source_updated_at, etag=record.etag
                ):
                    existing.status = FILE_PENDING
                    existing.size = record.size
                    existing.source_updated_at = record.source_updated_at
                    existing.etag = record.etag
                return existing
        self.files.append(record)
        return record

    def pending_files(self) -> list[FileRecord]:
        return [record for record in self.files if record.status not in FILE_TERMINAL]

    def checkpoint(self) -> dict[str, Any]:
        """What a restart needs: the frozen request, the state, and per-file progress."""
        return {
            "job_id": self.job_id,
            "status": self.status,
            "fingerprint": self.fingerprint,
            "connection_id": self.connection_id,
            "subject": self.subject,
            "course_ids": list(self.course_ids),
            "files": [
                {
                    "key": list(record.key),
                    "status": record.status,
                    "sha256": record.bytes_sha256,
                    "document_id": record.local_document_id,
                    "error_class": record.error_class,
                }
                for record in self.files
            ],
        }

    # ------------------------------------------------------------------ verdict
    def finished_status(self) -> str:
        """The terminal state this job has actually earned.

        `COMPLETED` is only for a job whose files all reached a good terminal state; anything
        that produced a warning is `COMPLETED_WITH_WARNINGS`, so "0 files because the folder
        was empty" and "403 because the school locked it" can never be reported as a clean
        100% import. A token failure outranks both: the user has to re-authorise.
        """
        if any(
            record.error_class == EXPIRED_TOKEN
            or record.status == FILE_FAILED
            and record.error_class == EXPIRED_TOKEN
            for record in self.files
        ):
            return NEEDS_REAUTH
        if not self.files:
            return COMPLETED_WITH_WARNINGS
        if any(record.status == FILE_FAILED for record in self.files):
            return FAILED
        # A cancelled file, an unparseable download and a blocked/locked file are all
        # outcomes the user must see; only "every file indexed or already identical" is a
        # clean success.
        if any(
            record.status in (FILE_WARNING, FILE_DOWNLOAD_ONLY, FILE_CANCELLED)
            for record in self.files
        ):
            return COMPLETED_WITH_WARNINGS
        return COMPLETED

    def advance_to_terminal(self, *, now: str = "") -> str:
        """Move to the state the files justify, from whichever working state we are in."""
        target = self.finished_status()
        if self.status != target:
            if not self.can_transition(target):
                # A job interrupted mid-download may still hold pending files; report the
                # outcome from INGESTING/INDEXING or from any other legal predecessor.
                if target in TRANSITIONS.get(self.status, ()):  # pragma: no cover - defensive
                    pass
                else:
                    raise JobStateError(f"{self.status} → {target} is not a legal transition")
            self.transition(target, now=now)
        return target

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for record in self.files:
            counts[record.status] = counts.get(record.status, 0) + 1
        return {
            "job_id": self.job_id,
            "status": self.status,
            "files": len(self.files),
            "by_status": counts,
            "courses": len(self.course_ids),
        }


def new_job(
    *,
    job_id: str,
    connection_id: str,
    subject: str,
    institution_origin: str,
    course_ids: list[str],
    material_versions: dict[str, str] | None = None,
) -> ImportJob:
    """Build a job whose selection is frozen from this point on."""
    return ImportJob(
        job_id=job_id,
        connection_id=connection_id,
        subject=subject,
        institution_origin=institution_origin,
        course_ids=tuple(sorted(str(course) for course in course_ids)),
        fingerprint=selection_fingerprint(
            connection_id=connection_id,
            subject=subject,
            institution_origin=institution_origin,
            course_ids=course_ids,
            material_versions=material_versions,
        ),
    )


def same_request(existing: ImportJob, candidate: ImportJob) -> bool:
    """Idempotency: an identical frozen request returns the existing job, not a second one."""
    return existing.fingerprint == candidate.fingerprint


def retry_delay_seconds(
    error_class: str, *, attempt: int, retry_after: float | None = None
) -> float | None:
    """Backoff for the retryable classes; `None` means do not retry at all.

    A `403` is never retried: the pack is explicit that a hidden or locked course must not be
    re-probed hoping it becomes readable.
    """
    if error_class == RATE_LIMIT:
        return retry_after if retry_after is not None else min(60.0, 2.0**attempt)
    if error_class == NETWORK:
        return min(300.0, 2.0**attempt)
    return None
