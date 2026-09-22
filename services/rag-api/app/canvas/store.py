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
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .job import ACTIVE_STATES, ImportJob, JobStateError

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
                "institution_origin, course_ids_json, selection_fingerprint, status) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    job.job_id,
                    job.connection_id,
                    job.subject,
                    job.institution_origin,
                    json.dumps(list(job.course_ids)),
                    job.fingerprint,
                    job.status,
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
        )

    # ------------------------------------------------------------------ progress
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
    ) -> str:
        """Insert or refresh one file row, keyed by external identity."""
        existing = self._connection.execute(
            "SELECT id FROM canvas_import_files WHERE job_id=? AND origin=? AND "
            "source_course_id=? AND source_file_id=?",
            (job_id, origin, str(course_id), str(file_id)),
        ).fetchone()
        if existing is not None:
            self._connection.execute(
                "UPDATE canvas_import_files SET display_name=?, size_bytes=?, source_updated_at=?, "
                "etag=?, status=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (display_name, size, updated_at, etag, status, existing["id"]),
            )
            return str(existing["id"])
        row_id = uuid.uuid4().hex
        self._connection.execute(
            "INSERT INTO canvas_import_files(id, job_id, origin, source_course_id, source_file_id, "
            "display_name, size_bytes, source_updated_at,"
            " etag, status) VALUES(?,?,?,?,?,?,?,?,?,?)",
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
            ),
        )
        return row_id
