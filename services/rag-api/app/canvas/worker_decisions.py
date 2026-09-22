"""Turn what the adapter reports into what the job records, and when to try again.

The worker needs one place where an outcome becomes a decision, so that "a locked file is
never retried" and "a rate limit is retried after the wait the school asked for" are rules
of the code rather than habits of whoever writes the loop. This module is that place: it
takes the error classes `CanvasReadAdapter` raises, the HTTP status behind them, and the
phase the job is in, and returns the file status, the recorded error class and the retry
delay (or `None` for "do not retry").

Kept separate from `job.py` on purpose: `job.py` describes what an import *is*, this
describes what the worker should *do* about a failure, and the two change for different
reasons.
"""

from __future__ import annotations

from dataclasses import dataclass

from .adapter import (
    EXPIRED_TOKEN,
    FORBIDDEN,
    INVALID_RESPONSE,
    NETWORK,
    NOT_FOUND,
    RATE_LIMIT,
    SERVER_ERROR,
    CanvasReadError,
)
from .job import (
    EMPTY,
    FILE_DOWNLOAD_ONLY,
    FILE_FAILED,
    FILE_SKIPPED_IDENTICAL,
    FILE_WARNING,
    HASH_MISMATCH,
    REJECTED_BY_LIMITS,
    TOO_LARGE,
    UNSUPPORTED,
    retry_delay_seconds,
)

# Outcomes that end a file's run without a retry, and how they are recorded.
TERMINAL_OUTCOMES: dict[str, tuple[str, str]] = {
    FORBIDDEN: (FILE_WARNING, FORBIDDEN),
    NOT_FOUND: (FILE_WARNING, NOT_FOUND),
    INVALID_RESPONSE: (FILE_FAILED, INVALID_RESPONSE),
    HASH_MISMATCH: (FILE_FAILED, HASH_MISMATCH),
    TOO_LARGE: (FILE_WARNING, TOO_LARGE),
    REJECTED_BY_LIMITS: (FILE_WARNING, REJECTED_BY_LIMITS),
    EMPTY: (FILE_WARNING, EMPTY),
    UNSUPPORTED: (FILE_DOWNLOAD_ONLY, UNSUPPORTED),
    "IDENTICAL": (FILE_SKIPPED_IDENTICAL, ""),
}


@dataclass(frozen=True)
class FileOutcome:
    """What to record for one file, and whether to come back to it."""

    status: str
    error_class: str
    retry_after: float | None
    detail: str = ""

    @property
    def retryable(self) -> bool:
        return self.retry_after is not None


def outcome_for_error(error: BaseException, *, attempt: int = 1) -> FileOutcome:
    """Classify an adapter failure into a file outcome.

    `EXPIRED_TOKEN` is special: it is not this file's fault, the whole job has to stop and
    the user has to authorise again, so it is reported as a failure carrying the class the
    job-level verdict looks for (`NEEDS_REAUTH`) and never as a retry.
    """
    if isinstance(error, CanvasReadError):
        category = error.category
        detail = error.detail
        if category == EXPIRED_TOKEN:
            return FileOutcome(FILE_FAILED, EXPIRED_TOKEN, None, detail)
        terminal = TERMINAL_OUTCOMES.get(category)
        if terminal is not None:
            return FileOutcome(terminal[0], terminal[1], None, detail)
        if category in (RATE_LIMIT, NETWORK, SERVER_ERROR):
            delay = retry_delay_seconds(category, attempt=attempt, retry_after=error.retry_after)
            # A retryable failure is not yet a result: the file stays pending, and the delay
            # is what the job layer waits. Recording it as a warning would finish the file.
            return FileOutcome("PENDING", category, delay or 1.0, detail)
        return FileOutcome(FILE_FAILED, category, None, detail)
    # Anything that is not a classified adapter error is a defect, not a Canvas condition:
    # fail the file rather than guessing that it is transient.
    return FileOutcome(FILE_FAILED, NETWORK, None, f"{type(error).__name__}: {error}")


def outcome_for_download(
    *, bytes_written: int, declared_size: int | None, sha256: str, expected_sha256: str = ""
) -> FileOutcome:
    """Decide an outcome from a completed download, before ingestion."""
    if bytes_written == 0:
        return FileOutcome(FILE_WARNING, EMPTY, None, "the file is zero bytes")
    if declared_size is not None and bytes_written != declared_size:
        return FileOutcome(
            FILE_FAILED,
            HASH_MISMATCH,
            None,
            f"read {bytes_written} bytes but the source declared {declared_size}",
        )
    if expected_sha256 and sha256 != expected_sha256:
        return FileOutcome(FILE_FAILED, HASH_MISMATCH, None, "content hash changed mid-download")
    return FileOutcome("DOWNLOADED", "", None)


def should_stop_job(outcome: FileOutcome) -> bool:
    """A credential failure stops the batch immediately instead of failing file by file.

    Continuing would produce one `NEEDS_REAUTH` per file and hammer the school with requests
    it has already refused.
    """
    return outcome.error_class == EXPIRED_TOKEN
