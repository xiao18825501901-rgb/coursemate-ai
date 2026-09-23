"""The task-level transient Canvas credential: it exists for one task, then it is gone.

These tests are about the properties the owner asked for by name — never persisted, unusable
immediately after the Canvas reads it was granted for, and correct on success, warning, cancel,
expiry and restart. Each one asserts a mechanism rather than an intention: the bytes are
actually zeroed, the receipt actually cannot contain the token, and a credential that expired
actually refuses the next read.

The clock is injected, so "thirty minutes pass" is a test rather than a pause.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.canvas.transient_credential import (
    DESTROYED,
    DESTROYING,
    EXPIRED,
    LOST_ON_RESTART,
    NEVER_STORED,
    PRESENT_TRANSIENTLY,
    REASON_HARD_TIMEOUT,
    REASON_IDLE_TIMEOUT,
    REASON_TASK_CANCELLED,
    REASON_TASK_COMPLETED,
    REASON_TASK_FAILED,
    CredentialRefused,
    CredentialUnavailable,
    TransientCanvasCredentialStore,
)

SUBJECT = "user-1"
ORIGIN = "https://cityu.instructure.com"
TOKEN = "1~aVeryLongCanvasPersonalAccessTokenValue0000000000000000"


class Clock:
    """A monotonic stand-in the test drives by hand."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def open_task(store: TransientCanvasCredentialStore, *, token: str = TOKEN, subject: str = SUBJECT):
    return store.open_task(
        subject=subject,
        connection_id="conn-1",
        institution_key="cityu",
        institution_origin=ORIGIN,
        token=token,
        canvas_user_id="4242",
        canvas_display_name="Student One",
    )


def test_a_new_task_credential_is_present_transiently_and_renders_nothing_secret() -> None:
    store = TransientCanvasCredentialStore()
    credential = open_task(store)
    assert credential.state == PRESENT_TRANSIENTLY
    assert credential.secret_present is True
    assert store.state(credential.credential_ref) == PRESENT_TRANSIENTLY
    # The credential reference is an opaque id, not derived from the token: two tasks for the
    # same user must not be linkable through it.
    assert TOKEN not in credential.credential_ref
    assert len(credential.credential_ref) == 32
    for rendered in (repr(credential), repr(store), json.dumps(credential.receipt())):
        assert TOKEN not in rendered
    assert "redacted" in repr(credential)


def test_the_pasted_value_must_be_one_opaque_token_or_the_task_is_not_opened() -> None:
    store = TransientCanvasCredentialStore()
    for candidate in ("", "   ", "\n", TOKEN + " " + TOKEN, TOKEN.replace("~", " "), "x" * 513):
        with pytest.raises(CredentialRefused):
            open_task(store, token=candidate)
    assert store.live_count() == 0, "a refused paste must not leave a held credential"


def test_a_trailing_newline_is_stripped_because_that_is_what_a_paste_carries() -> None:
    store = TransientCanvasCredentialStore()
    credential = open_task(store, token=f"{TOKEN}\r\n")
    assert store.claim_for_reads(credential.credential_ref) == TOKEN


def test_the_store_refuses_impossible_lifetimes_instead_of_guessing() -> None:
    with pytest.raises(ValueError):
        TransientCanvasCredentialStore(idle_ttl_seconds=0)
    with pytest.raises(ValueError):
        TransientCanvasCredentialStore(hard_ttl_seconds=60, idle_ttl_seconds=61)


def test_destroying_zeroes_the_bytes_and_a_second_destroy_changes_nothing() -> None:
    store = TransientCanvasCredentialStore()
    credential = open_task(store)
    buffer = credential._secret
    assert bytes(buffer).decode("utf-8") == TOKEN
    destroyed = store.destroy(credential.credential_ref, reason=REASON_TASK_COMPLETED)
    assert destroyed is not None
    assert destroyed.state == DESTROYED
    assert bytes(buffer) == b"\x00" * len(TOKEN), (
        "the stored bytes must be overwritten, not dropped"
    )
    assert destroyed.zeroed_bytes == len(TOKEN)
    assert destroyed.secret_present is False
    assert destroyed.destroy_reason == REASON_TASK_COMPLETED
    assert destroyed.destroyed_wall > 0

    assert store.destroy(credential.credential_ref, reason=REASON_TASK_FAILED) is None
    receipt = store.receipt_for(credential.credential_ref)
    assert receipt is not None
    assert receipt["state"] == DESTROYED
    assert receipt["destroy_reason"] == REASON_TASK_COMPLETED, "the first end is the reported one"
    assert store.state(credential.credential_ref) == DESTROYED


def test_a_destroyed_credential_cannot_be_read_and_the_adapter_sees_no_token() -> None:
    store = TransientCanvasCredentialStore()
    credential = open_task(store)
    provider = store.provider(credential.credential_ref)
    assert provider() == TOKEN
    store.destroy(credential.credential_ref, reason=REASON_TASK_COMPLETED)
    with pytest.raises(CredentialUnavailable) as raised:
        store.claim_for_reads(credential.credential_ref)
    assert raised.value.state == DESTROYED
    # `None` is what makes `CanvasReadAdapter` raise EXPIRED_TOKEN, the refusal path the import
    # worker already maps to "this needs a credential again".
    assert provider() is None


def test_an_idle_credential_expires_and_its_bytes_are_zeroed() -> None:
    clock = Clock()
    store = TransientCanvasCredentialStore(clock=clock)
    credential = open_task(store)
    buffer = credential._secret
    clock.advance(30 * 60)
    changed = store.sweep()
    assert [item.state for item in changed] == [EXPIRED]
    assert changed[0].destroy_reason == REASON_IDLE_TIMEOUT
    assert bytes(buffer) == b"\x00" * len(TOKEN)
    assert store.state(credential.credential_ref) == EXPIRED
    with pytest.raises(CredentialUnavailable) as raised:
        store.claim_for_reads(credential.credential_ref)
    assert raised.value.state == EXPIRED


def test_reads_keep_a_task_alive_but_never_past_the_hard_cap() -> None:
    clock = Clock()
    store = TransientCanvasCredentialStore(clock=clock)
    credential = open_task(store)
    ref = credential.credential_ref
    for _ in range(4):
        clock.advance(29 * 60)
        assert store.claim_for_reads(ref) == TOKEN
    assert store.state(ref) == PRESENT_TRANSIENTLY, "an active import is not killed by idleness"

    clock.advance(24 * 60 * 60)
    changed = store.sweep()
    assert [item.destroy_reason for item in changed] == [REASON_HARD_TIMEOUT]
    assert store.state(ref) == EXPIRED
    with pytest.raises(CredentialUnavailable):
        store.claim_for_reads(ref)


def test_the_lifetime_is_measured_on_the_monotonic_clock_a_wall_clock_cannot_shorten_it() -> None:
    clock = Clock()
    wall = Clock(1_700_000_000.0)
    store = TransientCanvasCredentialStore(clock=clock, wall_clock=wall)
    credential = open_task(store)
    # The wall clock is moved backwards by a year (an NTP step, a restored snapshot). The
    # credential's lifetime is not a function of it.
    wall.now -= 365 * 24 * 60 * 60
    assert store.claim_for_reads(credential.credential_ref) == TOKEN
    assert credential.created_wall == 1_700_000_000.0
    # And a wall clock that jumps forward does not expire it either.
    wall.now += 10 * 365 * 24 * 60 * 60
    assert store.state(credential.credential_ref) == PRESENT_TRANSIENTLY


def test_every_way_a_task_can_end_is_a_distinguishable_receipt() -> None:
    store = TransientCanvasCredentialStore()
    reasons = [
        REASON_TASK_COMPLETED,
        REASON_TASK_FAILED,
        REASON_TASK_CANCELLED,
    ]
    refs = []
    for reason in reasons:
        credential = open_task(store)
        store.claim_for_reads(credential.credential_ref)
        store.destroy(credential.credential_ref, reason=reason)
        refs.append(credential.credential_ref)
    receipts = store.receipts()
    assert [item["destroy_reason"] for item in receipts] == reasons
    assert all(item["state"] == DESTROYED for item in receipts)
    assert all(item["read_calls"] == 1 for item in receipts)
    assert all(item["subject"] == SUBJECT for item in receipts)


def test_a_restart_is_reported_as_lost_not_as_destroyed_or_still_live() -> None:
    first = TransientCanvasCredentialStore()
    credential = open_task(first)
    ref = credential.credential_ref
    # A new process: nothing was persisted, so the credential the database remembers as
    # PRESENT_TRANSIENTLY does not exist here.
    second = TransientCanvasCredentialStore()
    assert second.instance_id != first.instance_id
    assert second.reconcile(ref, recorded_state=PRESENT_TRANSIENTLY) == LOST_ON_RESTART
    assert second.reconcile(ref, recorded_state=DESTROYING) == LOST_ON_RESTART
    # Final states are facts that a restart does not undo.
    assert second.reconcile(ref, recorded_state=DESTROYED) == DESTROYED
    assert second.reconcile(ref, recorded_state=EXPIRED) == EXPIRED
    assert second.reconcile("never-seen", recorded_state=NEVER_STORED) == NEVER_STORED
    assert second.reconcile("unknown-ref", recorded_state="") == NEVER_STORED


def test_a_destroyed_credential_is_reported_from_its_receipt_after_a_restart() -> None:
    store = TransientCanvasCredentialStore()
    credential = open_task(store)
    store.destroy(credential.credential_ref, reason=REASON_TASK_COMPLETED)
    # A restarted process has no in-memory receipt, so the database's recorded state is what
    # answers, and `DESTROYED` is returned rather than invented as lost.
    restarted = TransientCanvasCredentialStore()
    assert (
        restarted.reconcile(credential.credential_ref, recorded_state=DESTROYED) == DESTROYED
    )


def test_one_user_cannot_hold_unbounded_credentials() -> None:
    store = TransientCanvasCredentialStore(max_live_tasks=2)
    first = open_task(store)
    second = open_task(store)
    with pytest.raises(CredentialRefused):
        open_task(store)
    store.destroy(second.credential_ref, reason=REASON_TASK_CANCELLED)
    third = open_task(store)
    assert store.live_count() == 2
    assert {first.credential_ref, third.credential_ref} <= set(store._live)


def test_receipts_are_bounded_and_never_carry_the_token() -> None:
    store = TransientCanvasCredentialStore(max_receipts=2)
    for _ in range(3):
        credential = open_task(store)
        store.destroy(credential.credential_ref, reason=REASON_TASK_COMPLETED)
    receipts = store.receipts()
    assert len(receipts) == 2
    blob = json.dumps(receipts)
    assert TOKEN not in blob
    assert set(receipts[0]) == {
        "credential_ref",
        "subject",
        "connection_id",
        "institution_key",
        "institution_origin",
        "canvas_user_id",
        "state",
        "created_at",
        "idle_expires_at",
        "hard_expires_at",
        "last_read_at",
        "read_calls",
        "destroyed_at",
        "destroy_reason",
        "zeroed_bytes",
        "secret_present",
        "job_id",
    }


def test_the_credential_is_attached_to_the_job_that_took_it() -> None:
    store = TransientCanvasCredentialStore()
    credential = open_task(store)
    store.claim_for_reads(credential.credential_ref, job_id="job-9")
    assert credential.job_id == "job-9"
    # A second job cannot inherit the first job's credential: the raw store is keyed by ref,
    # and the ref is minted per task, so this is a statement about the ref, not about locking.
    store.destroy(credential.credential_ref, reason=REASON_TASK_COMPLETED)
    assert store.receipt_for(credential.credential_ref)["job_id"] == "job-9"


def test_a_user_disconnect_destroys_every_credential_that_user_holds() -> None:
    store = TransientCanvasCredentialStore()
    mine = [open_task(store).credential_ref for _ in range(2)]
    theirs = open_task(store, subject="user-2").credential_ref
    assert store.destroy_all_for_subject(SUBJECT, reason="user_disconnected") == 2
    assert all(store.state(ref) == DESTROYED for ref in mine)
    assert store.state(theirs) == PRESENT_TRANSIENTLY


def test_this_module_has_no_logger_so_it_cannot_log_a_credential() -> None:
    """The strongest form of "this never reaches a log line" is not having a log line."""
    source = (
        pathlib.Path(__file__).resolve().parents[1]
        / "app"
        / "canvas"
        / "transient_credential.py"
    )
    text = source.read_text(encoding="utf-8")
    assert "import logging" not in text
    assert "LOGGER" not in text
    assert "print(" not in text
