"""Import-job states, freezing, per-file records and the honest completion verdict.

Task B4. The state machine and the per-file rules are pure, so these tests can pin every
transition and every refusal without a worker or a database.
"""

from __future__ import annotations

import pytest

from app.canvas.job import (
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
    FILE_FAILED,
    FILE_INDEXED,
    FILE_PENDING,
    FILE_SKIPPED_IDENTICAL,
    FILE_WARNING,
    FORBIDDEN,
    INDEXING,
    INGESTING,
    NEEDS_REAUTH,
    NETWORK,
    QUEUED,
    RATE_LIMIT,
    VERIFYING,
    FileRecord,
    JobStateError,
    new_job,
    retry_delay_seconds,
    same_request,
    selection_fingerprint,
)

CITYU = "https://canvas.cityu.edu.hk"


def job(**overrides):
    base = {
        "job_id": "job-1",
        "connection_id": "conn-1",
        "subject": "user-1",
        "institution_origin": CITYU,
        "course_ids": ["560", "240"],
    }
    base.update(overrides)
    return new_job(**base)


def ready_for_files(state):
    """Walk a job to the state in which per-file results are recorded.

    The machine deliberately has no shortcut from DOWNLOADING to INDEXING: verifying
    and ingesting are separate facts, so a test that skipped them would be testing a
    state sequence the product does not have.
    """
    state.transition(AWAITING_SELECTION)
    state.transition(QUEUED)
    state.transition(DOWNLOADING)
    state.transition(VERIFYING)
    state.transition(INGESTING)
    state.transition(INDEXING)
    return state


def record(file_id: str = "1", *, course: str = "560", size: int = 10) -> FileRecord:
    return FileRecord(
        origin=CITYU, course_id=course, file_id=file_id, display_name=f"f{file_id}.pdf", size=size
    )


# ------------------------------------------------------------------ fingerprint
def test_the_same_selection_in_a_different_order_is_the_same_request() -> None:
    first = job(course_ids=["560", "240"])
    second = job(course_ids=["240", "560"])
    assert first.fingerprint == second.fingerprint
    assert same_request(first, second) is True


def test_a_different_subject_connection_or_course_set_is_a_different_request() -> None:
    base = job()
    assert job(subject="user-2").fingerprint != base.fingerprint
    assert job(connection_id="conn-2").fingerprint != base.fingerprint
    assert job(course_ids=["560"]).fingerprint != base.fingerprint
    assert (
        job(institution_origin="https://cityu-dg.instructure.com").fingerprint != base.fingerprint
    )


def test_a_changed_material_version_is_a_new_request_not_a_no_op() -> None:
    before = job(material_versions={"560": "v1"})
    after = job(material_versions={"560": "v2"})
    assert before.fingerprint != after.fingerprint


def test_a_selection_must_name_at_least_one_course() -> None:
    with pytest.raises(JobStateError):
        selection_fingerprint(
            connection_id="c", subject="s", institution_origin=CITYU, course_ids=[]
        )


# ------------------------------------------------------------------ transitions
def test_the_happy_path_is_the_documented_sequence() -> None:
    state = job()
    for target in (
        AWAITING_SELECTION,
        QUEUED,
        DOWNLOADING,
        "VERIFYING",
        "INGESTING",
        INDEXING,
        COMPLETED,
    ):
        state.transition(target)
    assert state.status == COMPLETED
    assert state.is_terminal is True


def test_illegal_transitions_are_refused() -> None:
    state = job()
    for target in (COMPLETED, DOWNLOADING, INDEXING):
        with pytest.raises(JobStateError):
            state.transition(target)
    state.transition(AWAITING_SELECTION)
    with pytest.raises(JobStateError):
        state.transition(DISCOVERING)
    with pytest.raises(JobStateError):
        state.transition("NOT_A_STATE")


def test_a_finished_job_is_not_reopened() -> None:
    state = job()
    state.transition(AWAITING_SELECTION)
    state.transition(QUEUED)
    state.transition(CANCELLED)
    assert state.cancel() is False
    with pytest.raises(JobStateError):
        state.transition(DOWNLOADING)


def test_a_job_needing_reauthorisation_can_resume_after_reconnecting() -> None:
    state = job()
    state.transition(AWAITING_SELECTION)
    state.transition(QUEUED)
    state.transition(NEEDS_REAUTH)
    assert state.is_terminal is True
    state.transition(QUEUED)  # the user authorised again
    assert state.status == QUEUED


def test_cancelling_is_idempotent_and_keeps_what_was_already_done() -> None:
    state = job()
    state.transition(AWAITING_SELECTION)
    state.transition(QUEUED)
    done = state.add_file(record("1"))
    done.finish(FILE_INDEXED)
    assert state.cancel() is True
    assert state.cancel() is False
    assert [r.status for r in state.files] == [FILE_INDEXED]


# ------------------------------------------------------------------ file identity
def test_files_are_keyed_by_origin_course_and_file_id_not_by_name() -> None:
    state = job()
    first = state.add_file(record("1"))
    # Same display name, different Canvas file id → a separate file, not an overwrite.
    second = state.add_file(
        FileRecord(origin=CITYU, course_id="560", file_id="2", display_name="f1.pdf", size=10)
    )
    assert first is not second
    assert len(state.files) == 2
    # Same id again → the same record.
    assert state.add_file(record("1")) is first


def test_a_new_version_of_the_same_file_id_is_not_skipped_forever() -> None:
    state = job()
    existing = state.add_file(record("1", size=10))
    existing.finish(FILE_SKIPPED_IDENTICAL)
    state.add_file(record("1", size=99))  # the school re-uploaded it
    assert existing.status == FILE_PENDING
    assert existing.size == 99
    assert existing in state.pending_files()


def test_a_new_version_drops_the_previous_hash_and_parse_state() -> None:
    """The recorded hash describes the *previous* version, so a worker that trusts it would
    ingest stale bytes for a file the school has since changed."""
    state = job()
    existing = state.add_file(record("1", size=10))
    existing.finish(FILE_INDEXED)
    existing.bytes_sha256 = "hash-of-the-old-version"
    existing.parse_state = "parsed"
    existing.index_state = "indexed"

    state.add_file(record("1", size=99))

    assert existing.bytes_sha256 == ""
    assert (existing.parse_state, existing.index_state) == ("", "")
    assert existing.status == FILE_PENDING
    # The document the previous version produced stays linked: it is a true historical fact.
    existing.local_document_id = "doc-old"
    state.add_file(record("1", size=100))
    assert existing.local_document_id == "doc-old"


def test_an_unchanged_file_keeps_its_local_links() -> None:
    state = job()
    existing = state.add_file(record("1"))
    existing.finish(FILE_INDEXED)
    existing.local_document_id = "doc-1"
    state.add_file(record("1"))  # seen again, identical
    assert existing.status == FILE_INDEXED
    assert existing.local_document_id == "doc-1"


def test_terminal_file_states_are_enforced() -> None:
    item = record()
    with pytest.raises(JobStateError):
        item.finish("DOWNLOADING")
    with pytest.raises(JobStateError):
        item.finish(FILE_FAILED, error_class="NOT_A_CLASS")
    item.finish(FILE_WARNING, error_class=FORBIDDEN)
    assert item.is_warning is True and item.is_failure is False


# ------------------------------------------------------------------ verdict
def test_an_empty_selection_is_not_a_clean_success() -> None:
    state = ready_for_files(job())
    assert state.finished_status() == COMPLETED_WITH_WARNINGS
    state.advance_to_terminal()
    assert state.status == COMPLETED_WITH_WARNINGS


def test_a_forbidden_file_makes_the_job_complete_with_warnings_not_a_failure() -> None:
    state = ready_for_files(job())
    ok = state.add_file(record("1"))
    ok.finish(FILE_INDEXED)
    blocked = state.add_file(record("2"))
    blocked.finish(FILE_WARNING, error_class=FORBIDDEN, detail="locked by the school")
    state.advance_to_terminal()
    assert state.status == COMPLETED_WITH_WARNINGS
    assert state.summary()["by_status"] == {FILE_INDEXED: 1, FILE_WARNING: 1}


def test_a_download_only_file_is_a_warning_not_a_clean_index() -> None:
    state = ready_for_files(job())
    video = state.add_file(record("1"))
    video.finish(FILE_DOWNLOAD_ONLY)
    assert state.finished_status() == COMPLETED_WITH_WARNINGS


def test_an_expired_token_outranks_everything_else() -> None:
    state = ready_for_files(job())
    good = state.add_file(record("1"))
    good.finish(FILE_INDEXED)
    expired = state.add_file(record("2"))
    expired.finish(FILE_FAILED, error_class=EXPIRED_TOKEN)
    assert state.finished_status() == NEEDS_REAUTH


def test_a_hard_failure_is_failed_not_completed() -> None:
    state = ready_for_files(job())
    bad = state.add_file(record("1"))
    bad.finish(FILE_FAILED, error_class=NETWORK)
    assert state.finished_status() == FAILED


def test_a_cancelled_file_does_not_make_the_job_a_success() -> None:
    state = ready_for_files(job())
    stopped = state.add_file(record("1"))
    stopped.finish(FILE_CANCELLED)
    assert state.finished_status() in (COMPLETED_WITH_WARNINGS, FAILED)


# ------------------------------------------------------------------ checkpoint
def test_the_checkpoint_carries_what_a_restart_needs() -> None:
    state = job()
    state.transition(AWAITING_SELECTION)
    done = state.add_file(record("1"))
    done.finish(FILE_INDEXED)
    done.bytes_sha256 = "a" * 64
    done.local_document_id = "doc-1"
    state.add_file(record("2"))
    checkpoint = state.checkpoint()
    assert checkpoint["fingerprint"] == state.fingerprint
    assert checkpoint["course_ids"] == ["240", "560"]
    assert checkpoint["files"][0] == {
        "key": [CITYU, "560", "1"],
        "status": FILE_INDEXED,
        "sha256": "a" * 64,
        "document_id": "doc-1",
        "error_class": "",
    }
    assert checkpoint["files"][1]["status"] == FILE_PENDING


# ------------------------------------------------------------------ retries
def test_retry_policy_matches_the_contract() -> None:
    assert retry_delay_seconds(RATE_LIMIT, attempt=1, retry_after=12.0) == 12.0
    assert retry_delay_seconds(RATE_LIMIT, attempt=3) == 8.0
    assert retry_delay_seconds(NETWORK, attempt=2) == 4.0
    assert retry_delay_seconds(NETWORK, attempt=20) == 300.0
    # A locked file is never retried, and neither is an empty folder.
    assert retry_delay_seconds(FORBIDDEN, attempt=1) is None
    assert retry_delay_seconds(EMPTY, attempt=1) is None
