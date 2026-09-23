"""A Canvas credential that lives for exactly one import task and is then destroyed.

The owner-authorised import path is a *task*, not a connection: the user pastes a Canvas
personal access token, the service reads what that one task needs, and the credential becomes
unusable — immediately, before any indexing work starts — and is never written anywhere. This
module is the storage that makes that true rather than merely intended.

What "transient" has to mean, and how each part is enforced here:

1. **It is in this process and nowhere else.** There is no file, no table and no cache. A
   process restart therefore *loses* the credential — which is a state the product must be able
   to report (`LOST_ON_RESTART`), not an accident. Nothing on disk can leak it because nothing
   on disk ever held it. The business database keeps an opaque `credential_ref` and the
   lifecycle *receipt*, never the credential.

2. **The bytes are overwritten when the task is done.** The token is held in a `bytearray`, so
   `destroy()` can zero that buffer in place. A Python `str` cannot be wiped, which is why the
   token is not kept as one. This is a real improvement rather than a claim of perfect
   hygiene, and the limit is stated instead of hidden: the adapter necessarily turns the bytes
   into a `str` for one HTTP request, so copies can exist inside an HTTP client's memory for
   the duration of that request. What this module guarantees is the *stored* credential: gone,
   zeroed, and reported as gone.

3. **It expires on two clocks.** An idle token (the user walked away during course selection)
   dies after `SELECTION_IDLE_TTL_SECONDS`; no task may hold one longer than
   `HARD_TTL_SECONDS` regardless of activity. Expiry is evaluated lazily on every access and
   by an explicit `sweep()`, because a background reaper thread would itself be background
   processing over a credential the owner said must not have any.

4. **Every state is reachable and nameable.** `NEVER_STORED`, `PRESENT_TRANSIENTLY`,
   `DESTROYING`, `DESTROYED`, `EXPIRED` and `LOST_ON_RESTART` are the whole vocabulary, and a
   receipt records which one a task ended in so the lifecycle can be audited after the fact
   (success, warning, cancel, expiry, restart). A destroyed credential is *idempotent*: asking
   again returns the original receipt rather than re-destroying or resurrecting anything.

The token never appears in `repr()`, in a log line, in a receipt or in an exception message.
`TaskCredential.receipt()` is the only serialisable view, and it is built from fields that
cannot contain it.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# The lifecycle vocabulary. These names are persisted as receipts, so they are part of the
# contract rather than internal labels.
NEVER_STORED = "NEVER_STORED"
PRESENT_TRANSIENTLY = "PRESENT_TRANSIENTLY"
DESTROYING = "DESTROYING"
DESTROYED = "DESTROYED"
EXPIRED = "EXPIRED"
LOST_ON_RESTART = "LOST_ON_RESTART"

ALL_STATES = (
    NEVER_STORED,
    PRESENT_TRANSIENTLY,
    DESTROYING,
    DESTROYED,
    EXPIRED,
    LOST_ON_RESTART,
)
# States in which a credential may still be used for Canvas reads.
USABLE_STATES = (PRESENT_TRANSIENTLY,)
# States that mean "the task cannot continue without a new credential from the user".
NEEDS_CREDENTIAL_STATES = (DESTROYED, EXPIRED, LOST_ON_RESTART)

# Why a credential stopped existing. Recorded on the receipt; the owner's requirement is that
# success, warning, cancel, expiry and restart are all distinguishable later.
REASON_READS_COMPLETE = "canvas_reads_complete"
REASON_TASK_COMPLETED = "task_completed"
REASON_TASK_FAILED = "task_failed"
REASON_TASK_CANCELLED = "task_cancelled"
REASON_USER_DISCONNECTED = "user_disconnected"
REASON_IDLE_TIMEOUT = "idle_timeout"
REASON_HARD_TIMEOUT = "hard_timeout"
REASON_WORKER_REFUSED = "worker_refused"

# 30 minutes idle is the selection window: long enough for a student to choose courses, short
# enough that an abandoned browser tab is not a live credential all afternoon.
SELECTION_IDLE_TTL_SECONDS = 30 * 60.0
# 24 hours is a hard cap that no amount of activity extends.
HARD_TTL_SECONDS = 24 * 60 * 60.0
# A Canvas personal access token is a long opaque string. The bound exists so a pasted
# document cannot be buffered as a "credential", not to validate any particular format:
# refusing a token because its shape is unexpected would be guessing at another system's
# format.
MAX_TOKEN_CHARS = 512
# Bound on live tasks per user and on retained receipts, so neither a loop nor a long-lived
# process can grow without limit.
MAX_LIVE_TASKS_PER_SUBJECT = 4
MAX_RECEIPTS = 256


class TransientCredentialError(RuntimeError):
    """The task credential could not be created, used or destroyed."""


class CredentialRefused(TransientCredentialError):
    """The pasted value cannot be held as a credential at all."""


class CredentialUnavailable(TransientCredentialError):
    """The credential is not usable: destroyed, expired, or lost with a restart.

    Carries the state so a caller can report *why* without inspecting internals.
    """

    def __init__(self, state: str, detail: str) -> None:
        super().__init__(f"{state}: {detail}")
        self.state = state
        self.detail = detail


def _blank(buffer: bytearray) -> int:
    """Overwrite a buffer in place with zeroes, returning how many bytes were blanked."""
    length = len(buffer)
    for index in range(length):
        buffer[index] = 0
    return length


@dataclass
class TaskCredential:
    """One task's credential and its lifecycle receipt.

    The secret is a `bytearray` (see the module docstring) and is never rendered by `repr`.
    """

    credential_ref: str
    subject: str
    connection_id: str
    institution_key: str
    institution_origin: str
    canvas_user_id: str = ""
    canvas_display_name: str = ""
    state: str = PRESENT_TRANSIENTLY
    created_wall: float = 0.0
    created_at: float = 0.0
    idle_expires_at: float = 0.0
    hard_expires_at: float = 0.0
    last_read_at: float = 0.0
    read_calls: int = 0
    destroyed_wall: float = 0.0
    destroy_reason: str = ""
    zeroed_bytes: int = 0
    job_id: str = ""
    _secret: bytearray = field(default_factory=bytearray, repr=False)

    # ------------------------------------------------------------------ secret access
    @property
    def secret_present(self) -> bool:
        """True while bytes are held. Says *that* a secret exists, never what it is.

        The test is `any(...)` and not truthiness: a blanked buffer is still a non-empty
        `bytearray`, so `bool()` would report a destroyed credential as still holding one —
        which is the single most misleading thing this class could say.
        """
        return bool(self._secret) and any(self._secret)

    def take_secret(self) -> str:
        """The token as text, for exactly one Canvas read.

        Refuses in every state but `PRESENT_TRANSIENTLY`, so a destroyed credential cannot be
        used again by a caller that forgot to check.
        """
        if self.state != PRESENT_TRANSIENTLY:
            raise CredentialUnavailable(self.state, "this task credential is no longer usable")
        if not self.secret_present:
            raise CredentialUnavailable(self.state, "this task credential holds no bytes")
        return self._secret.decode("utf-8")

    def is_usable(self, now: float) -> bool:
        if self.state != PRESENT_TRANSIENTLY:
            return False
        return now < self.idle_expires_at and now < self.hard_expires_at

    # ------------------------------------------------------------------ receipt
    def receipt(self) -> dict[str, Any]:
        """A serialisable, secret-free account of this credential's life.

        Everything here is safe to write into the business database and to show an operator:
        the states and the timings, none of the credential.
        """
        return {
            "credential_ref": self.credential_ref,
            "subject": self.subject,
            "connection_id": self.connection_id,
            "institution_key": self.institution_key,
            "institution_origin": self.institution_origin,
            "canvas_user_id": self.canvas_user_id,
            "state": self.state,
            "created_at": self.created_wall,
            "idle_expires_at": self.created_wall + (self.idle_expires_at - self.created_at),
            "hard_expires_at": self.created_wall + (self.hard_expires_at - self.created_at),
            "last_read_at": self.created_wall + (self.last_read_at - self.created_at)
            if self.last_read_at
            else 0.0,
            "read_calls": self.read_calls,
            "destroyed_at": self.destroyed_wall,
            "destroy_reason": self.destroy_reason,
            "zeroed_bytes": self.zeroed_bytes,
            "secret_present": self.secret_present,
            "job_id": self.job_id,
        }

    def __repr__(self) -> str:  # pragma: no cover - defence in depth
        return (
            f"TaskCredential(ref={self.credential_ref!r}, subject={self.subject!r}, "
            f"state={self.state!r}, secret=<redacted>)"
        )


class TransientCanvasCredentialStore:
    """Holds one Canvas credential per import task, in this process, for as short a time as
    possible.

    Not a `CredentialStore`: that protocol is the *encrypted, persisted* store for a saved
    connection, and implementing `save()` here would be exactly the persistence this class
    exists to avoid. The two are used for different things and must stay distinguishable —
    a connection the user chose to keep, and a credential that one task borrowed.
    """

    def __init__(
        self,
        *,
        idle_ttl_seconds: float = SELECTION_IDLE_TTL_SECONDS,
        hard_ttl_seconds: float = HARD_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        max_live_tasks: int = MAX_LIVE_TASKS_PER_SUBJECT,
        max_receipts: int = MAX_RECEIPTS,
    ) -> None:
        if idle_ttl_seconds <= 0 or hard_ttl_seconds <= 0:
            raise ValueError("a transient credential needs a positive idle and hard lifetime")
        if idle_ttl_seconds > hard_ttl_seconds:
            raise ValueError("the idle lifetime cannot exceed the hard lifetime")
        self._clock = clock
        self._wall_clock = wall_clock
        self._idle_ttl = float(idle_ttl_seconds)
        self._hard_ttl = float(hard_ttl_seconds)
        self._max_live = max_live_tasks
        self._max_receipts = max_receipts
        self._live: dict[str, TaskCredential] = {}
        self._receipts: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()
        # Names this store instance, so a receipt can be traced to one process lifetime
        # without naming the machine or the user.
        self.instance_id = uuid.uuid4().hex[:12]

    # ------------------------------------------------------------------ opening a task
    def open_task(
        self,
        *,
        subject: str,
        connection_id: str,
        institution_key: str,
        institution_origin: str,
        token: str,
        canvas_user_id: str = "",
        canvas_display_name: str = "",
    ) -> TaskCredential:
        """Hold a pasted token for one task. Refuses rather than storing anything unusable."""
        cleaned = (token or "").strip()
        if not cleaned:
            raise CredentialRefused("no credential was supplied")
        if len(cleaned) > MAX_TOKEN_CHARS:
            raise CredentialRefused(
                f"a pasted credential must be at most {MAX_TOKEN_CHARS} characters"
            )
        if any(character.isspace() for character in cleaned):
            # A Canvas token is one opaque value. Whitespace means the paste was of a line of
            # text rather than of the token, and guessing which part is the token would be
            # inventing a credential the user did not give.
            raise CredentialRefused("a pasted credential must be a single value with no spaces")
        if not subject or not connection_id or not institution_origin:
            raise CredentialRefused("a task credential needs a user, a connection and an origin")
        now = self._clock()
        with self._lock:
            self._expire_due(now)
            live = [item for item in self._live.values() if item.subject == subject]
            if len(live) >= self._max_live:
                raise CredentialRefused(
                    "too many import tasks are already waiting for a credential for this user"
                )
            credential = TaskCredential(
                credential_ref=uuid.uuid4().hex,
                subject=subject,
                connection_id=connection_id,
                institution_key=institution_key,
                institution_origin=institution_origin,
                canvas_user_id=canvas_user_id,
                canvas_display_name=canvas_display_name,
                state=PRESENT_TRANSIENTLY,
                created_wall=self._wall_clock(),
                created_at=now,
                idle_expires_at=now + self._idle_ttl,
                hard_expires_at=now + self._hard_ttl,
                _secret=bytearray(cleaned.encode("utf-8")),
            )
            self._live[credential.credential_ref] = credential
            return credential

    # ------------------------------------------------------------------ using a task
    def record(self, credential_ref: str) -> TaskCredential | None:
        """The live credential, or None once it is gone. Expiry is applied first."""
        with self._lock:
            self._expire_due(self._clock())
            return self._live.get(credential_ref)

    def state(self, credential_ref: str) -> str:
        """The state now: a live one, the receipt of a finished one, else `NEVER_STORED`."""
        credential = self.record(credential_ref)
        if credential is not None:
            return credential.state
        with self._lock:
            receipt = self._receipts.get(credential_ref)
        return str(receipt["state"]) if receipt else NEVER_STORED

    def claim_for_reads(self, credential_ref: str, *, job_id: str = "") -> str:
        """Take the token for Canvas reads, refreshing the idle clock.

        Every read goes through here, which is what keeps an *active* import from being killed
        by the idle timeout while still bounding an abandoned one.
        """
        now = self._clock()
        with self._lock:
            self._expire_due(now)
            credential = self._live.get(credential_ref)
            if credential is None:
                receipt = self._receipts.get(credential_ref)
                state = str(receipt["state"]) if receipt else NEVER_STORED
                raise CredentialUnavailable(state, "this task holds no usable credential")
            token = credential.take_secret()
            credential.read_calls += 1
            credential.last_read_at = now
            credential.idle_expires_at = min(now + self._idle_ttl, credential.hard_expires_at)
            if job_id and not credential.job_id:
                credential.job_id = job_id
            return token

    def note_read(self, credential_ref: str) -> None:
        """Refresh the idle clock for a read that did not go through `claim_for_reads`."""
        with self._lock:
            credential = self._live.get(credential_ref)
            if credential is None or credential.state != PRESENT_TRANSIENTLY:
                return
            now = self._clock()
            credential.read_calls += 1
            credential.last_read_at = now
            credential.idle_expires_at = min(now + self._idle_ttl, credential.hard_expires_at)

    def provider(self, credential_ref: str) -> Callable[[], str | None]:
        """A `token_provider` for `CanvasReadAdapter`.

        Returning None when the credential is gone is deliberate: the adapter already turns a
        falsy token into `EXPIRED_TOKEN`, which the import worker already maps to
        "re-authorise", so a cleared credential takes the existing refusal path rather than a
        new one.
        """

        def provider() -> str | None:
            try:
                return self.claim_for_reads(credential_ref)
            except CredentialUnavailable:
                return None

        return provider

    # ------------------------------------------------------------------ ending a task
    def destroy(self, credential_ref: str, *, reason: str) -> TaskCredential | None:
        """Zero the credential and keep a receipt. Idempotent, never resurrects.

        The transition is `PRESENT_TRANSIENTLY → DESTROYING → DESTROYED` and both steps are
        observable, because "it was being destroyed when the process died" is a different fact
        from "it was destroyed", and the lifecycle evidence has to be able to say which.

        Returns the destroyed instance (whose buffer is now zeroes) the first time, and `None`
        afterwards: the credential itself is gone, and the durable answer for a repeat call is
        `receipt_for()`, which still reports `DESTROYED` with the original timestamp and reason.
        """
        with self._lock:
            credential = self._live.get(credential_ref)
            if credential is None:
                return None
            credential.state = DESTROYING
            credential.zeroed_bytes = _blank(credential._secret)
            credential.state = DESTROYED
            credential.destroy_reason = reason
            credential.destroyed_wall = self._wall_clock()
            self._finish(credential)
            return credential

    def destroy_all_for_subject(self, subject: str, *, reason: str) -> int:
        """Destroy every live credential a user holds. Used when a user disconnects or signs out."""
        with self._lock:
            refs = [
                ref for ref, item in self._live.items() if item.subject == subject
            ]
        destroyed = 0
        for ref in refs:
            if self.destroy(ref, reason=reason) is not None:
                destroyed += 1
        return destroyed

    def sweep(self) -> list[TaskCredential]:
        """Expire everything due, returning the receipts that changed.

        An explicit call rather than a thread: the owner's rule for this path is that no
        background processing touches the credential.
        """
        with self._lock:
            return self._expire_due(self._clock())

    def _expire_due(self, now: float) -> list[TaskCredential]:
        """Apply both clocks. Caller holds the lock."""
        expired: list[TaskCredential] = []
        for credential in list(self._live.values()):
            if credential.state != PRESENT_TRANSIENTLY:
                continue
            if now >= credential.hard_expires_at:
                reason = REASON_HARD_TIMEOUT
            elif now >= credential.idle_expires_at:
                reason = REASON_IDLE_TIMEOUT
            else:
                continue
            credential.state = DESTROYING
            credential.zeroed_bytes = _blank(credential._secret)
            credential.state = EXPIRED
            credential.destroy_reason = reason
            credential.destroyed_wall = self._wall_clock()
            self._finish(credential)
            expired.append(credential)
        return expired

    def _finish(self, credential: TaskCredential) -> None:
        """Move a finished credential out of the live map and into its receipt. Lock held."""
        self._live.pop(credential.credential_ref, None)
        self._receipts[credential.credential_ref] = credential.receipt()
        self._order.append(credential.credential_ref)
        while len(self._order) > self._max_receipts:
            oldest = self._order.pop(0)
            self._receipts.pop(oldest, None)

    # ------------------------------------------------------------------ restart and receipts
    def reconcile(self, credential_ref: str, *, recorded_state: str) -> str:
        """The honest state for a ref the business database remembers.

        A receipt that said `PRESENT_TRANSIENTLY` and whose credential is not in this process
        was lost with a restart — there is no other place it could have been. States that are
        already final (`DESTROYED`, `EXPIRED`, `NEVER_STORED`) are returned as recorded: the
        fact does not become less true because the process restarted.
        """
        with self._lock:
            self._expire_due(self._clock())
            live = self._live.get(credential_ref)
            if live is not None:
                return live.state
            receipt = self._receipts.get(credential_ref)
        if receipt is not None:
            return str(receipt["state"])
        if recorded_state in (PRESENT_TRANSIENTLY, DESTROYING):
            return LOST_ON_RESTART
        return recorded_state or NEVER_STORED

    def live_count(self) -> int:
        with self._lock:
            self._expire_due(self._clock())
            return len(self._live)

    def receipts(self) -> list[dict[str, Any]]:
        """Every finished credential's receipt, oldest first. Contains no secret."""
        with self._lock:
            return [dict(self._receipts[ref]) for ref in self._order if ref in self._receipts]

    def receipt_for(self, credential_ref: str) -> dict[str, Any] | None:
        with self._lock:
            receipt = self._receipts.get(credential_ref)
        return dict(receipt) if receipt else None
