"""Persistence for Canvas import jobs: idempotent creation and lease-based claiming.

Migration 031 created the tables; this is the only code that writes them. Two behaviours
are the reason it exists rather than letting callers run SQL:

* `create_or_get` upserts on the frozen-selection unique key, so a duplicated request
  returns the existing job instead of starting a second import of the same courses;
* `claim` takes a job with a lease. A worker that dies mid-job leaves an expired lease and
  the job becomes claimable again, which is what makes "restart resumes from the checkpoint"
  true rather than aspirational. Claims are bounded by status, so a terminal job is never
  picked up again.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .job import (
    ACTIVE_STATES,
    CREDENTIAL_KIND_CONNECTION,
    TERMINAL_STATES,
    FileRecord,
    ImportJob,
    JobStateError,
)
from .oauth import Connection
from .transient_credential import NEVER_STORED

LEASE_SECONDS = 120


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass(frozen=True)
class ClaimedJob:
    """A job a worker now owns until `leased_until`."""

    job_id: str
    connection_id: str
    owner_user_id: str
    institution_origin: str
    course_ids: tuple[str, ...]
    fingerprint: str
    status: str
    leased_until: str
    credential_ref: str = ""
    credential_kind: str = CREDENTIAL_KIND_CONNECTION
    credential_state: str = NEVER_STORED


class CanvasConnectionRepository:
    """Persistence for a user's link to one Canvas account.

    The row holds identity and bookkeeping only: there is no token column, because the
    credential lives in the encrypted store keyed by `connection_id` (see `credentials.py`).
    `upsert` is keyed by `(owner_user_id, institution_origin, canvas_user_id)`, which is the
    migration's unique constraint, so reconnecting the same school updates one row instead of
    accumulating connections.
    """

    def __init__(self, connection: sqlite3.Connection, *, clock: Callable[[], float] = time.time):
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self._clock = clock

    def upsert(self, connection: Connection, *, connection_id: str) -> str:
        """Insert or refresh the row for this `(owner, institution, Canvas user)` triple."""
        self._connection.execute(
            "INSERT INTO canvas_connections(id, owner_user_id, institution_key, "
            "institution_origin, canvas_user_id, canvas_display_name, granted_scopes, "
            "saved_for_reuse, credential_key_id, credential_expires_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(owner_user_id, institution_origin, canvas_user_id) DO UPDATE SET "
            "institution_key=excluded.institution_key, "
            "canvas_display_name=excluded.canvas_display_name, "
            "granted_scopes=excluded.granted_scopes, "
            "saved_for_reuse=excluded.saved_for_reuse, "
            "credential_key_id=excluded.credential_key_id, "
            "credential_expires_at=excluded.credential_expires_at, "
            "revoked_at=NULL, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
            (
                connection_id,
                connection.subject,
                connection.institution_key,
                connection.origin,
                connection.canvas_user_id,
                connection.canvas_name,
                " ".join(connection.scopes),
                int(connection.saved_for_reuse),
                connection.credential_key_id,
                connection.credential_expires_at,
            ),
        )
        row = self._connection.execute(
            "SELECT id FROM canvas_connections WHERE owner_user_id=? AND institution_origin=? "
            "AND canvas_user_id=?",
            (connection.subject, connection.origin, connection.canvas_user_id),
        ).fetchone()
        if row is None:  # pragma: no cover - the upsert above guarantees a row
            raise JobStateError("the connection row could not be read back after upsert")
        # A reconnect that matched an existing row keeps that row's id: callers must address the
        # connection the database actually holds, not the id they proposed.
        return str(row["id"])

    def get(self, connection_id: str, *, subject: str) -> Connection | None:
        """One connection, but only for the user it belongs to."""
        row = self._connection.execute(
            "SELECT * FROM canvas_connections WHERE id=? AND owner_user_id=? "
            "AND revoked_at IS NULL",
            (connection_id, subject),
        ).fetchone()
        return self._to_connection(row) if row is not None else None

    def for_subject(self, subject: str) -> list[Connection]:
        rows = self._connection.execute(
            "SELECT * FROM canvas_connections WHERE owner_user_id=? AND revoked_at IS NULL "
            "ORDER BY created_at",
            (subject,),
        ).fetchall()
        return [self._to_connection(row) for row in rows]

    def existing_for_account(
        self, *, subject: str, origin: str, canvas_user_id: str
    ) -> Connection | None:
        row = self._connection.execute(
            "SELECT * FROM canvas_connections WHERE owner_user_id=? AND institution_origin=? "
            "AND canvas_user_id=?",
            (subject, origin, canvas_user_id),
        ).fetchone()
        return self._to_connection(row) if row is not None else None

    def for_subject_and_institution(self, *, subject: str, origin: str) -> Connection | None:
        """This user's existing link to one school, whichever Canvas account it names.

        The callback needs this one: the question "is this school already linked to a different
        Canvas account?" cannot be answered by looking up the *new* account id, because a row for
        it does not exist yet — which is exactly how one person's courses would end up filed
        under another person's account.
        """
        row = self._connection.execute(
            "SELECT * FROM canvas_connections WHERE owner_user_id=? AND institution_origin=? "
            "AND revoked_at IS NULL ORDER BY created_at LIMIT 1",
            (subject, origin),
        ).fetchone()
        return self._to_connection(row) if row is not None else None

    def mark_revoked(self, connection_id: str, *, subject: str) -> bool:
        cursor = self._connection.execute(
            "UPDATE canvas_connections SET revoked_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'), "
            "credential_key_id=NULL, credential_expires_at=NULL, saved_for_reuse=0, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE id=? AND owner_user_id=?",
            (connection_id, subject),
        )
        return cursor.rowcount == 1

    def mark_saved_for_reuse(self, connection_id: str, *, subject: str, saved: bool) -> bool:
        """Record the user's explicit choice to keep the connection for later updates.

        Default is not to keep it: an ordinary import stores nothing once the job and its retry
        window are over, and only a deliberate opt-in leaves a credential behind.
        """
        cursor = self._connection.execute(
            "UPDATE canvas_connections SET saved_for_reuse=?, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND owner_user_id=?",
            (1 if saved else 0, connection_id, subject),
        )
        return cursor.rowcount == 1

    @staticmethod
    def _to_connection(row: sqlite3.Row) -> Connection:
        scopes = str(row["granted_scopes"] or "")
        expires = row["credential_expires_at"]
        return Connection(
            connection_id=str(row["id"]),
            subject=str(row["owner_user_id"]),
            institution_key=str(row["institution_key"]),
            origin=str(row["institution_origin"]),
            canvas_user_id=str(row["canvas_user_id"]),
            canvas_name=str(row["canvas_display_name"] or ""),
            scopes=tuple(scopes.split()) if scopes else (),
            saved_for_reuse=bool(row["saved_for_reuse"]),
            credential_key_id=str(row["credential_key_id"] or ""),
            credential_expires_at=float(expires) if expires is not None else None,
        )


class CanvasJobRepository:
    """Small, explicit data access for import jobs. No hidden global state."""

    def __init__(
        self, connection: sqlite3.Connection, *, lease_seconds: int = LEASE_SECONDS
    ) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self._lease_seconds = lease_seconds

    # ------------------------------------------------------------------ creation
    def create_or_get(self, job: ImportJob) -> tuple[str, bool]:
        """Insert the job, or return the existing one for the same frozen selection.

        Returns `(job_id, created)`.
        """
        existing = self._connection.execute(
            "SELECT id FROM canvas_import_jobs WHERE connection_id=? AND selection_fingerprint=?",
            (job.connection_id, job.fingerprint),
        ).fetchone()
        if existing is not None:
            return str(existing["id"]), False
        try:
            self._connection.execute(
                "INSERT INTO canvas_import_jobs(id, connection_id, owner_user_id, "
                "institution_origin, course_ids_json, selection_fingerprint, status, "
                "credential_ref, credential_kind, credential_state) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    job.job_id,
                    job.connection_id,
                    job.subject,
                    job.institution_origin,
                    json.dumps(list(job.course_ids)),
                    job.fingerprint,
                    job.status,
                    # The reference and the kind, never the credential. A job that used a
                    # transient task token records that fact here so a reader can tell it apart
                    # from one backed by a saved connection.
                    job.credential_ref,
                    job.credential_kind,
                    job.credential_state,
                ),
            )
        except sqlite3.IntegrityError as error:
            # A concurrent insert won the race; the unique key is the arbiter, not this code.
            row = self._connection.execute(
                "SELECT id FROM canvas_import_jobs WHERE "
                "connection_id=? AND selection_fingerprint=?",
                (job.connection_id, job.fingerprint),
            ).fetchone()
            if row is None:
                raise
            del error
            return str(row["id"]), False
        return job.job_id, True

    # ------------------------------------------------------------------ claiming
    def claim(self, *, worker_id: str, now: datetime | None = None) -> ClaimedJob | None:
        """Lease one claimable job, or return None.

        Claimable means: still in a working state, and either never leased or leased by a
        worker whose lease has expired (a crashed worker must not strand a job).
        """
        moment = now or _now()
        lease_until = _stamp(moment + timedelta(seconds=self._lease_seconds))
        placeholders = ",".join("?" for _ in ACTIVE_STATES)
        row = self._connection.execute(
            f"SELECT * FROM canvas_import_jobs WHERE status IN ({placeholders}) "
            "AND (leased_until IS NULL OR leased_until < ?) "
            "ORDER BY created_at LIMIT 1",
            (*ACTIVE_STATES, _stamp(moment)),
        ).fetchone()
        if row is None:
            return None
        self._connection.execute(
            "UPDATE canvas_import_jobs SET leased_until=?, worker_id=?, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (lease_until, worker_id, row["id"]),
        )
        return ClaimedJob(
            job_id=str(row["id"]),
            connection_id=str(row["connection_id"]),
            owner_user_id=str(row["owner_user_id"]),
            institution_origin=str(row["institution_origin"]),
            course_ids=tuple(json.loads(row["course_ids_json"])),
            fingerprint=str(row["selection_fingerprint"]),
            status=str(row["status"]),
            leased_until=lease_until,
            credential_ref=str(row["credential_ref"] or ""),
            credential_kind=str(row["credential_kind"] or CREDENTIAL_KIND_CONNECTION),
            credential_state=str(row["credential_state"] or NEVER_STORED),
        )

    # ------------------------------------------------------------------ credentials
    def credential_of(self, job_id: str) -> tuple[str, str, str]:
        """`(ref, kind, state)` for a job. Never a token: there is none to return."""
        row = self._connection.execute(
            "SELECT credential_ref, credential_kind, credential_state FROM canvas_import_jobs "
            "WHERE id=?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise JobStateError(f"no job {job_id}")
        return (
            str(row["credential_ref"] or ""),
            str(row["credential_kind"] or CREDENTIAL_KIND_CONNECTION),
            str(row["credential_state"] or NEVER_STORED),
        )

    def set_credential_state(self, job_id: str, state: str) -> bool:
        """Record a lifecycle transition on the job. Returns whether a row changed."""
        cursor = self._connection.execute(
            "UPDATE canvas_import_jobs SET credential_state=?, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (state, job_id),
        )
        return cursor.rowcount == 1

    # ------------------------------------------------------------------ progress
    def touch(
        self,
        job_id: str,
        *,
        worker_id: str,
        status: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Renew this worker's lease, optionally moving the working status, and report ownership.

        Returns False when the row is no longer owned by `worker_id` — an expired lease that a
        second worker has already taken. That return value is the whole point of the method:
        two workers must never write one job, and the only reliable way to know is to make the
        write conditional on the worker id and look at what it affected.
        """
        if status == "DONE":
            raise JobStateError("DONE is not a job state")
        if status is not None and status in TERMINAL_STATES:
            raise JobStateError(f"{status} is terminal: use set_status for a finished job")
        moment = now or _now()
        assignments = ["leased_until=?", "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')"]
        values: list[object] = [_stamp(moment + timedelta(seconds=self._lease_seconds))]
        if status is not None:
            assignments.insert(0, "status=?")
            values.insert(0, status)
        values.extend([job_id, worker_id])
        cursor = self._connection.execute(
            f"UPDATE canvas_import_jobs SET {', '.join(assignments)} WHERE id=? AND worker_id=?",
            values,
        )
        return cursor.rowcount == 1

    def set_target_course(self, job_id: str, target_course_id: str) -> None:
        """Remember the private course this import writes into.

        Written before the first file is ingested, so a worker that dies and resumes reuses
        the course it already created instead of creating a second private course for the
        same request.
        """
        if not target_course_id:
            raise JobStateError("a target course id is required")
        self._connection.execute(
            "UPDATE canvas_import_jobs SET target_course_id=?, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (target_course_id, job_id),
        )

    def target_course_of(self, job_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT target_course_id FROM canvas_import_jobs WHERE id=?", (job_id,)
        ).fetchone()
        if row is None or row["target_course_id"] is None:
            return None
        return str(row["target_course_id"])

    def set_status(
        self, job_id: str, status: str, *, error_code: str = "", error_message: str = ""
    ) -> None:
        if status == "DONE":
            raise JobStateError("DONE is not a job state")
        self._connection.execute(
            "UPDATE canvas_import_jobs SET status=?, error_code=?, error_message=?, "
            "leased_until=NULL, worker_id=NULL, "
            "completed_at=CASE WHEN ? IN ('COMPLETED','COMPLETED_WITH_WARNINGS','NEEDS_REAUTH',"
            "'FAILED','CANCELLED') THEN "
            "strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE completed_at END, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (status, error_code or None, error_message or None, status, job_id),
        )

    def release(self, job_id: str) -> None:
        """Give the lease back without changing the status (used after a short batch)."""
        self._connection.execute(
            "UPDATE canvas_import_jobs SET leased_until=NULL, worker_id=NULL, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (job_id,),
        )

    def status_of(self, job_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT status FROM canvas_import_jobs WHERE id=?", (job_id,)
        ).fetchone()
        return str(row["status"]) if row else None

    def snapshot(self, job_id: str) -> sqlite3.Row | None:
        """The whole job row, for the status route.

        Deliberately the raw row: the route reports the same fields the worker writes, so a
        status page cannot drift from the state machine by re-deriving them.
        """
        row = self._connection.execute(
            "SELECT * FROM canvas_import_jobs WHERE id=?", (job_id,)
        ).fetchone()
        return row if row is not None else None

    def upsert_file(
        self,
        job_id: str,
        *,
        origin: str,
        course_id: str,
        file_id: str,
        display_name: str,
        size: int,
        updated_at: str = "",
        etag: str = "",
        status: str = "PENDING",
        folder_or_module: str = "",
    ) -> str:
        """Insert or refresh one file row, keyed by external identity.

        Returns the row id. A refresh that sets `PENDING` also clears the recorded content
        hash, because a pending row has no verified bytes.
        """
        existing = self._connection.execute(
            "SELECT id FROM canvas_import_files WHERE job_id=? AND origin=? AND "
            "source_course_id=? AND source_file_id=?",
            (job_id, origin, str(course_id), str(file_id)),
        ).fetchone()
        if existing is not None:
            # A row that goes back to PENDING has no verified bytes, so it must not keep the
            # previous version's hash: a later run would compare that hash with a stale file
            # on disk, find them equal, and ingest the old version as if it were the new one.
            self._connection.execute(
                "UPDATE canvas_import_files SET display_name=?, size_bytes=?, source_updated_at=?, "
                "etag=?, status=?, source_folder_or_module=?, "
                "bytes_sha256=CASE WHEN ?='PENDING' THEN '' ELSE bytes_sha256 END, "
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (
                    display_name,
                    size,
                    updated_at,
                    etag,
                    status,
                    folder_or_module,
                    status,
                    existing["id"],
                ),
            )
            return str(existing["id"])
        row_id = uuid.uuid4().hex
        self._connection.execute(
            "INSERT INTO canvas_import_files(id, job_id, origin, source_course_id, source_file_id, "
            "display_name, size_bytes, source_updated_at,"
            " etag, status, source_folder_or_module) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                row_id,
                job_id,
                origin,
                str(course_id),
                str(file_id),
                display_name,
                size,
                updated_at,
                etag,
                status,
                folder_or_module,
            ),
        )
        return row_id

    def list_files(self, job_id: str) -> list[FileRecord]:
        """Every file row for a job, oldest first, as the worker's own record type.

        This is what makes a restart resume instead of repeat: the worker rebuilds its view
        of the job from these rows rather than from anything held in memory.
        """
        rows = self._connection.execute(
            "SELECT * FROM canvas_import_files WHERE job_id=? ORDER BY created_at, rowid",
            (job_id,),
        ).fetchall()
        return [
            FileRecord(
                origin=str(row["origin"]),
                course_id=str(row["source_course_id"]),
                file_id=str(row["source_file_id"]),
                display_name=str(row["display_name"]),
                size=int(row["size_bytes"]),
                source_updated_at=str(row["source_updated_at"]),
                etag=str(row["etag"]),
                folder_or_module=str(row["source_folder_or_module"]),
                bytes_sha256=str(row["bytes_sha256"]),
                local_document_id=str(row["local_document_id"] or ""),
                local_document_version_id=str(row["local_document_version_id"] or ""),
                parse_state=str(row["parse_state"]),
                index_state=str(row["index_state"]),
                status=str(row["status"]),
                error_class=str(row["error_class"] or ""),
                error_detail=str(row["error_detail"] or ""),
                attempts=int(row["attempts"]),
            )
            for row in rows
        ]

    def record_file_result(
        self,
        job_id: str,
        *,
        origin: str,
        course_id: str,
        file_id: str,
        status: str,
        sha256: str = "",
        document_id: str = "",
        error_class: str = "",
        error_detail: str = "",
        parse_state: str = "",
        index_state: str = "",
        attempts: int = 0,
    ) -> None:
        """Checkpoint one file's result. The row must already exist: discovery creates it.

        Refusing to insert here is deliberate — a result for a file the job never listed is a
        defect, and inventing a row for it would hide the defect behind a plausible record.
        """
        cursor = self._connection.execute(
            "UPDATE canvas_import_files SET status=?, bytes_sha256=?, local_document_id=?, "
            "error_class=?, error_detail=?, parse_state=?, index_state=?, attempts=?, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE job_id=? AND origin=? AND source_course_id=? AND source_file_id=?",
            (
                status,
                sha256,
                document_id or None,
                error_class or None,
                error_detail or None,
                parse_state,
                index_state,
                attempts,
                job_id,
                origin,
                str(course_id),
                str(file_id),
            ),
        )
        if cursor.rowcount != 1:
            raise JobStateError(
                f"no file row for {origin} {course_id} {file_id}: discovery must record it first"
            )


class CanvasCredentialLifecycleRepository:
    """The receipt of a credential's life: which state, when, and how much it was used.

    This table exists to answer questions after the fact — was the credential destroyed before
    indexing started, was it lost with a restart, was it cleared on cancel — and it can only
    answer them because the credential itself was never written down. Every method here stores
    states and numbers; none of them can store a token, and `record` takes no token argument.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row

    def record(
        self,
        *,
        credential_ref: str,
        subject: str,
        institution_origin: str,
        state: str,
        reason: str = "",
        read_calls: int = 0,
        zeroed_bytes: int = 0,
        store_instance_id: str = "",
        job_id: str = "",
    ) -> str:
        """Append one transition. Returns the id of the event row."""
        event_id = uuid.uuid4().hex
        self._connection.execute(
            "INSERT INTO canvas_credential_lifecycle_events(id, job_id, credential_ref, subject, "
            "institution_origin, state, reason, read_calls, zeroed_bytes, store_instance_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                job_id or None,
                credential_ref,
                subject,
                institution_origin,
                state,
                reason,
                int(read_calls),
                int(zeroed_bytes),
                store_instance_id,
            ),
        )
        return event_id

    def for_ref(self, credential_ref: str) -> list[dict[str, object]]:
        rows = self._connection.execute(
            "SELECT state, reason, read_calls, zeroed_bytes, store_instance_id, created_at "
            "FROM canvas_credential_lifecycle_events WHERE credential_ref=? "
            "ORDER BY created_at, id",
            (credential_ref,),
        ).fetchall()
        return [dict(row) for row in rows]

    def counts_by_state(self, *, subject: str = "") -> dict[str, int]:
        """How many credentials reached each state, for the lifecycle evidence report."""
        if subject:
            rows = self._connection.execute(
                "SELECT state, COUNT(*) AS total FROM canvas_credential_lifecycle_events "
                "WHERE subject=? GROUP BY state",
                (subject,),
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT state, COUNT(*) AS total FROM canvas_credential_lifecycle_events "
                "GROUP BY state"
            ).fetchall()
        return {str(row["state"]): int(row["total"]) for row in rows}
