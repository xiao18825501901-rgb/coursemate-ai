"""The worker's decision table: what a failure means, and whether to come back to it."""

from __future__ import annotations

import pytest

from app.canvas.adapter import (
    EXPIRED_TOKEN,
    FORBIDDEN,
    INVALID_RESPONSE,
    NETWORK,
    NOT_FOUND,
    RATE_LIMIT,
    SERVER_ERROR,
    CanvasReadError,
)
from app.canvas.job import EMPTY, FILE_FAILED, FILE_WARNING
from app.canvas.worker_decisions import (
    outcome_for_download,
    outcome_for_error,
    should_stop_job,
)


def error(category: str, *, retry_after: float | None = None) -> CanvasReadError:
    return CanvasReadError(
        category, "detail", status=429 if category == RATE_LIMIT else None, retry_after=retry_after
    )


def test_a_locked_file_is_a_warning_and_is_never_retried() -> None:
    outcome = outcome_for_error(error(FORBIDDEN), attempt=3)
    assert (outcome.status, outcome.error_class) == (FILE_WARNING, FORBIDDEN)
    assert outcome.retryable is False


def test_a_missing_file_is_a_warning_not_a_failure() -> None:
    outcome = outcome_for_error(error(NOT_FOUND))
    assert outcome.status == FILE_WARNING
    assert outcome.retryable is False


def test_rate_limit_honours_the_wait_the_school_asked_for() -> None:
    outcome = outcome_for_error(error(RATE_LIMIT, retry_after=30.0), attempt=1)
    assert outcome.error_class == RATE_LIMIT
    assert outcome.retry_after == 30.0
    assert outcome.retryable is True
    # Not yet a result: the file stays pending rather than being marked finished.
    assert outcome.status == "PENDING"


def test_rate_limit_without_a_header_still_backs_off() -> None:
    first = outcome_for_error(error(RATE_LIMIT), attempt=1)
    later = outcome_for_error(error(RATE_LIMIT), attempt=4)
    assert first.retry_after == 2.0 and later.retry_after == 16.0


def test_network_and_server_errors_are_retried_with_backoff() -> None:
    for category in (NETWORK, SERVER_ERROR):
        outcome = outcome_for_error(error(category), attempt=2)
        assert outcome.retryable is True, category
        assert outcome.status == "PENDING"


def test_an_expired_credential_fails_the_file_and_stops_the_job() -> None:
    outcome = outcome_for_error(error(EXPIRED_TOKEN))
    assert (outcome.status, outcome.error_class) == (FILE_FAILED, EXPIRED_TOKEN)
    assert outcome.retryable is False
    assert should_stop_job(outcome) is True
    # Every other outcome lets the batch continue.
    assert should_stop_job(outcome_for_error(error(FORBIDDEN))) is False


def test_an_invalid_response_is_a_hard_failure() -> None:
    outcome = outcome_for_error(error(INVALID_RESPONSE))
    assert outcome.status == FILE_FAILED and outcome.retryable is False


def test_an_unclassified_exception_is_a_defect_and_fails_the_file() -> None:
    outcome = outcome_for_error(ValueError("boom"))
    assert outcome.status == FILE_FAILED
    assert outcome.error_class == NETWORK
    assert "ValueError" in outcome.detail


def test_a_zero_byte_file_is_a_warning_not_a_download() -> None:
    outcome = outcome_for_download(bytes_written=0, declared_size=0, sha256="")
    assert (outcome.status, outcome.error_class) == (FILE_WARNING, EMPTY)


def test_a_short_read_is_a_hash_mismatch() -> None:
    outcome = outcome_for_download(bytes_written=10, declared_size=99, sha256="a" * 64)
    assert outcome.status == FILE_FAILED
    assert outcome.error_class == "HASH_MISMATCH"


def test_a_changed_hash_mid_download_is_refused() -> None:
    outcome = outcome_for_download(
        bytes_written=10, declared_size=10, sha256="a" * 64, expected_sha256="b" * 64
    )
    assert outcome.status == FILE_FAILED and outcome.error_class == "HASH_MISMATCH"


def test_a_clean_download_is_downloaded_and_then_ingested() -> None:
    outcome = outcome_for_download(bytes_written=10, declared_size=10, sha256="a" * 64)
    assert (outcome.status, outcome.error_class) == ("DOWNLOADED", "")
    assert outcome.retryable is False


@pytest.mark.parametrize("category", [FORBIDDEN, NOT_FOUND, INVALID_RESPONSE, EXPIRED_TOKEN])
def test_terminal_outcomes_never_carry_a_retry(category: str) -> None:
    """No terminal outcome may carry a delay, or the worker would retry a finished file."""
    outcome = outcome_for_error(error(category), attempt=5)
    assert outcome.status in (FILE_WARNING, FILE_FAILED)
    assert outcome.retry_after is None
    assert outcome.retryable is False
