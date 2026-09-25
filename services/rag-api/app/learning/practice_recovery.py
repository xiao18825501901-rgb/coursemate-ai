"""Evidence-only inventory and explicit reconciliation for orphaned practice calls.

This module never calls a model, reopens an operation, or deletes a receipt.  It
classifies the immutable local evidence and appends an operator reconciliation
only after the caller attests that all writers for the database are drained.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

Classification = Literal[
    "COMPLETED",
    "FAILED",
    "NOT_SENT",
    "UPSTREAM_FAILED",
    "UPSTREAM_UNKNOWN",
    "LEGACY_UPSTREAM_UNKNOWN",
    "UPSTREAM_COMPLETED_NO_RESULT",
    "RECONCILED_NOT_SENT",
    "RECONCILED_UPSTREAM_FAILED",
    "RECONCILED_UPSTREAM_UNKNOWN",
    "RECONCILED_UPSTREAM_COMPLETED_NO_RESULT",
]
Disposition = Literal[
    "NOT_SENT",
    "UPSTREAM_FAILED",
    "UPSTREAM_UNKNOWN",
    "UPSTREAM_COMPLETED_NO_RESULT",
]
PRACTICE_OPERATION_ACTIVE_WINDOW_SECONDS = 660


class PracticeRecoveryError(RuntimeError):
    """A fail-closed recovery refusal with no private model payload."""


@dataclass(frozen=True, slots=True)
class PracticeOperationInspection:
    workspace_id: str
    operation_id: str
    question_revision_id: str
    owner_ref: str
    kind: str
    status: str
    classification: Classification
    within_active_window: bool
    age_seconds: int | None
    guard_version: str | None
    reservation_statuses: tuple[str, ...]
    run_statuses: tuple[str, ...]
    reconciliation_id: str | None
    disposition: str | None
    evidence_hash: str | None
    operator_ref: str | None
    retry_operation_id: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _age_seconds(value: str, now: datetime) -> int | None:
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return max(0, int((now - observed.astimezone(UTC)).total_seconds()))


def _classification(
    *,
    status: str,
    guard_version: str | None,
    reservations: tuple[str, ...],
    runs: tuple[str, ...],
    disposition: str | None,
) -> Classification:
    if status == "COMPLETED":
        return "COMPLETED"
    if status == "FAILED":
        return "FAILED"
    if disposition is not None:
        return f"RECONCILED_{disposition}"  # type: ignore[return-value]
    states = set(reservations) | set(runs)
    if "COMPLETED" in states or "LEGACY_COMPLETED" in states:
        return "UPSTREAM_COMPLETED_NO_RESULT"
    if "RESERVED" in states or "UNKNOWN" in states:
        return "UPSTREAM_UNKNOWN"
    if states and states <= {"FAILED", "BLOCKED"}:
        return "UPSTREAM_FAILED"
    if guard_version is None:
        return "LEGACY_UPSTREAM_UNKNOWN"
    return "NOT_SENT"


def _inspect_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    now: datetime,
    active_window_seconds: int,
) -> PracticeOperationInspection:
    workspace_id = str(row["workspace_id"])
    operation_id = str(row["operation_id"])
    guard = connection.execute(
        "SELECT guard_version FROM practice_operation_metering_guards "
        "WHERE workspace_id=? AND operation_id=?",
        (workspace_id, operation_id),
    ).fetchone()
    reservations = tuple(
        str(item["status"])
        for item in connection.execute(
            "SELECT status FROM learning_model_call_reservations "
            "WHERE workspace_id=? AND operation_id=? ORDER BY created_at,id",
            (workspace_id, operation_id),
        ).fetchall()
    )
    runs = tuple(
        str(item["status"])
        for item in connection.execute(
            "SELECT status FROM learning_model_run_evidence "
            "WHERE workspace_id=? AND operation_id=? ORDER BY started_at,id",
            (workspace_id, operation_id),
        ).fetchall()
    )
    reconciliation = connection.execute(
        "SELECT rowid,* FROM practice_operation_reconciliations "
        "WHERE workspace_id=? AND operation_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
        (workspace_id, operation_id),
    ).fetchone()
    retry = None
    if reconciliation is not None:
        retry = connection.execute(
            "SELECT new_operation_id FROM practice_operation_retry_links "
            "WHERE reconciliation_id=?",
            (reconciliation["id"],),
        ).fetchone()
    age = _age_seconds(str(row["updated_at"]), now)
    guard_version = str(guard["guard_version"]) if guard is not None else None
    disposition = str(reconciliation["disposition"]) if reconciliation is not None else None
    return PracticeOperationInspection(
        workspace_id=workspace_id,
        operation_id=operation_id,
        question_revision_id=str(row["question_revision_id"]),
        owner_ref=hashlib.sha256(str(row["owner_user_id"]).encode()).hexdigest()[:16],
        kind=str(row["kind"]),
        status=str(row["status"]),
        classification=_classification(
            status=str(row["status"]),
            guard_version=guard_version,
            reservations=reservations,
            runs=runs,
            disposition=disposition,
        ),
        within_active_window=age is not None and age <= active_window_seconds,
        age_seconds=age,
        guard_version=guard_version,
        reservation_statuses=reservations,
        run_statuses=runs,
        reconciliation_id=(str(reconciliation["id"]) if reconciliation is not None else None),
        disposition=disposition,
        evidence_hash=(
            str(reconciliation["evidence_hash"]) if reconciliation is not None else None
        ),
        operator_ref=(
            str(reconciliation["operator_ref"]) if reconciliation is not None else None
        ),
        retry_operation_id=(str(retry["new_operation_id"]) if retry is not None else None),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def inspect_practice_operations(
    connection: sqlite3.Connection,
    *,
    workspace_id: str | None = None,
    operation_id: str | None = None,
    active_window_seconds: int = PRACTICE_OPERATION_ACTIVE_WINDOW_SECONDS,
    now: datetime | None = None,
) -> list[PracticeOperationInspection]:
    """Return metadata-only classifications; no prompt, answer or user id is exposed."""

    if active_window_seconds < 30:
        raise PracticeRecoveryError("active window must be at least 30 seconds")
    clauses = ["1=1"]
    values: list[str] = []
    if workspace_id is not None:
        clauses.append("workspace_id=?")
        values.append(workspace_id)
    if operation_id is not None:
        clauses.append("operation_id=?")
        values.append(operation_id)
    rows = connection.execute(
        "SELECT * FROM practice_interaction_operations WHERE "
        + " AND ".join(clauses)
        + " ORDER BY created_at,workspace_id,operation_id",
        values,
    ).fetchall()
    observed_at = now or datetime.now(UTC)
    return [
        _inspect_row(
            connection,
            row,
            now=observed_at,
            active_window_seconds=active_window_seconds,
        )
        for row in rows
    ]


def reconcile_practice_operation(
    connection: sqlite3.Connection,
    *,
    workspace_id: str,
    operation_id: str,
    expected_classification: str,
    disposition: Disposition,
    operator_ref: str,
    evidence: bytes,
    writers_drained: bool,
    active_window_seconds: int = PRACTICE_OPERATION_ACTIVE_WINDOW_SECONDS,
) -> PracticeOperationInspection:
    """Append one reconciliation after exact evidence and writer-drain checks."""

    if not writers_drained:
        raise PracticeRecoveryError("all writers must be drained before reconciliation")
    if not evidence:
        raise PracticeRecoveryError("non-empty evidence is required")
    normalized_operator = operator_ref.strip()
    if not 1 <= len(normalized_operator) <= 150:
        raise PracticeRecoveryError("operator reference must contain 1 to 150 characters")
    allowed: dict[str, Disposition] = {
        "NOT_SENT": "NOT_SENT",
        "UPSTREAM_FAILED": "UPSTREAM_FAILED",
        "UPSTREAM_UNKNOWN": "UPSTREAM_UNKNOWN",
        "LEGACY_UPSTREAM_UNKNOWN": "UPSTREAM_UNKNOWN",
        "UPSTREAM_COMPLETED_NO_RESULT": "UPSTREAM_COMPLETED_NO_RESULT",
    }
    try:
        connection.execute("BEGIN IMMEDIATE")
        rows = inspect_practice_operations(
            connection,
            workspace_id=workspace_id,
            operation_id=operation_id,
            active_window_seconds=active_window_seconds,
        )
        if not rows:
            raise PracticeRecoveryError("practice operation was not found")
        current = rows[0]
        if current.reconciliation_id is not None:
            raise PracticeRecoveryError("practice operation is already reconciled")
        if current.status != "CLAIMED":
            raise PracticeRecoveryError("only a CLAIMED operation can be reconciled")
        if current.classification != expected_classification:
            raise PracticeRecoveryError(
                "classification changed: "
                f"expected {expected_classification}, observed {current.classification}"
            )
        required_disposition = allowed.get(current.classification)
        if required_disposition is None or disposition != required_disposition:
            raise PracticeRecoveryError(
                f"disposition {disposition} does not match {current.classification}"
            )
        reconciliation_id = f"prec_{uuid4().hex}"
        connection.execute(
            "INSERT INTO practice_operation_reconciliations("
            "id,workspace_id,operation_id,disposition,evidence_hash,operator_ref) "
            "VALUES(?,?,?,?,?,?)",
            (
                reconciliation_id,
                workspace_id,
                operation_id,
                disposition,
                hashlib.sha256(evidence).hexdigest(),
                normalized_operator,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return inspect_practice_operations(
        connection,
        workspace_id=workspace_id,
        operation_id=operation_id,
        active_window_seconds=active_window_seconds,
    )[0]
