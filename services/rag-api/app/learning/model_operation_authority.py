"""Internal worker claim authority shared by routing, reservation and send guards."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import cast

from app.errors import ApiError


@dataclass(frozen=True)
class PreparationClaim:
    preparation_id: str
    worker_id: str


_claim: ContextVar[PreparationClaim | None] = ContextVar("learning_preparation_claim", default=None)


@contextmanager
def preparation_model_claim(preparation_id: str, worker_id: str) -> Iterator[None]:
    """Only the actual claimed server worker enters this scope; no client hint."""
    token = _claim.set(PreparationClaim(preparation_id, worker_id))
    try:
        yield
    finally:
        _claim.reset(token)


def authorize_model_operation(
    connection: sqlite3.Connection, workspace_id: str, operation_id: str,
    *, expected_configuration_id: str | None = None,
) -> sqlite3.Row:
    operation = connection.execute(
        "SELECT * FROM learning_operations WHERE workspace_id=? AND id=?",
        (workspace_id, operation_id),
    ).fetchone()
    if operation is None:
        operation = connection.execute(
            "SELECT * FROM practice_interaction_operations WHERE workspace_id=? AND operation_id=?",
            (workspace_id, operation_id),
        ).fetchone()
    if operation is None:
        raise ApiError(409, "MODEL_OPERATION_NOT_ACTIVE", "The operation is not active.")
    if (
        expected_configuration_id is not None
        and operation["kind"] != "assessment.configured_preparation.worker"
    ):
        raise ApiError(409, "MODEL_OPERATION_NOT_ACTIVE", "A configured worker is required.")
    if operation["kind"] == "assessment.configured_preparation.worker":
        claim = _claim.get()
        if claim is None or operation["status"] not in {"COMPLETED", "RUNNING"}:
            raise ApiError(409, "MODEL_OPERATION_NOT_ACTIVE", "The operation is not active.")
        preparation = connection.execute(
            "SELECT 1 FROM assessment_configuration_preparations prep "
            "JOIN assessment_configurations config ON config.id=prep.configuration_id "
            "JOIN learning_workspaces workspace ON workspace.id=prep.workspace_id "
            "WHERE prep.id=? AND prep.workspace_id=? AND prep.operation_id=? "
            "AND config.workspace_id=workspace.id AND config.owner_user_id=workspace.owner_user_id "
            "AND config.course_id=workspace.course_id AND config.status='FROZEN' "
            "AND prep.status='PREPARING' AND prep.cancel_requested=0 AND prep.lease_owner=? "
            "AND julianday(prep.lease_expires_at)>julianday('now') "
            "AND (? IS NULL OR prep.configuration_id=?)",
            (claim.preparation_id, workspace_id, operation_id, claim.worker_id,
             expected_configuration_id, expected_configuration_id),
        ).fetchone()
        if preparation is None:
            raise ApiError(
                409, "ASSESSMENT_PREPARATION_LEASE_LOST", "The preparation lease is not active."
            )
    elif operation["status"] not in {"RUNNING", "CLAIMED"}:
        raise ApiError(409, "MODEL_OPERATION_NOT_ACTIVE", "The operation is not active.")
    return cast(sqlite3.Row, operation)
