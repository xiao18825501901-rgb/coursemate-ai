"""Minimal HTTP route for submitting a user-initiated feedback report.

The report is triaged (one batched Jev call) and queued for human review; the
deterministic backend owns persistence and the human review, so this route only
records and classifies.  A report body (free text + question/answer) is refused
unless the caller sets ``attach_body``.

There is no live Jev call here: the gateway uses the default ``SdkTransport``,
which fails typed with ``JevNotConfiguredError`` while no TypeSafe credential
exists, so the report degrades to ``OTHER`` + middle severity and is still queued.

The queue is durable (`feedback_reports`, migration 030) and has exactly one
reader: the admin-only listing below, which is what makes it a queue a reviewer can
actually work through rather than an in-process list that vanishes on restart.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel

from app.auth import AuthenticatedUser, require_admin, require_user
from app.errors import ApiError
from app.jev.feedback_triage import (
    CATEGORIES,
    FeedbackReport,
    FeedbackTriage,
    FeedbackValidationError,
)
from app.jev.gateway import JevGateway
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService
from app.services.feedback_store import FeedbackStore

router = APIRouter()


class FeedbackSubmit(BaseModel):
    """The report payload: identifiers plus the opt-in gated body fields."""

    course_id: str
    message_id: str | None = None
    run_id: str | None = None
    model: str | None = None
    template_version: str | None = None
    app_version: str | None = None
    category: str | None = None
    product_surface: str = "learn"
    report_text: str | None = None
    question: str | None = None
    answer: str | None = None
    attach_body: bool = False


def _triage(request: Request) -> FeedbackTriage:
    existing: FeedbackTriage | None = getattr(request.app.state, "feedback_triage", None)
    if existing is not None:
        return existing
    # Reuse the one shared semantic-decision layer assembled at app startup (see
    # app.main.create_app); do not build a second gateway/service here. The local
    # fallback only covers app factories that never mount the shared layer.
    service = getattr(request.app.state, "jev_service", None)
    if service is None:
        database = request.app.state.database
        service = SemanticDecisionService(
            JevGateway(receipt_store=SqlReceiptStore(database))
        )
    triage = FeedbackTriage(service)
    request.app.state.feedback_triage = triage
    return triage


def _store(request: Request) -> FeedbackStore:
    database = request.app.state.database
    return FeedbackStore(database)


@router.post("/api/feedback", status_code=status.HTTP_201_CREATED)
def submit_feedback(
    payload: FeedbackSubmit,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, object]:
    if not payload.attach_body and any(
        (payload.report_text, payload.question, payload.answer)
    ):
        raise ApiError(
            400,
            "BODY_NOT_OPTED_IN",
            "The report text and question/answer body require attach_body=true.",
        )
    if payload.category is not None and payload.category not in CATEGORIES:
        raise ApiError(
            400, "INVALID_CATEGORY", f"category must be one of {CATEGORIES}."
        )

    report = FeedbackReport(
        course_id=payload.course_id,
        message_id=payload.message_id,
        run_id=payload.run_id,
        model=payload.model,
        template_version=payload.template_version,
        app_version=payload.app_version,
        category_hint=payload.category,
        product_surface=payload.product_surface,
        report_text=payload.report_text,
        question_text=payload.question,
        answer_text=payload.answer,
        attach_body=payload.attach_body,
    )
    try:
        result = _triage(request).submit(
            report, owner_user_id=user.user_id, authorization_scope="feedback"
        )
    except FeedbackValidationError as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    # The queue is durable and idempotent by report key: a repeated submission of the
    # same report is recorded once, and the row survives a restart.
    report_id = _store(request).record(
        result, owner_user_id=user.user_id, authorization_scope="feedback"
    )
    return {**result.as_dict(), "report_id": report_id}


@router.get("/api/feedback/queue")
def feedback_queue(
    request: Request,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    status_filter: Annotated[str, Query(alias="status")] = "OPEN",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    """The human review queue (admin only).

    Reports are listed most severe first and then oldest first. A body appears only
    for the reports whose submitter opted in; every other row carries identifiers
    alone. Nothing here can resolve, delete or act on a report — a reviewer reads it
    and works the case, which is the whole scope this module was given.
    """
    selected = None if status_filter == "ALL" else status_filter
    items = _store(request).queue(status=selected, limit=limit, offset=offset)
    return {"status": status_filter, "count": len(items), "reports": items}


@router.get("/api/feedback/mine")
def my_feedback(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, object]:
    """This caller's own reports only, so a user can see what they sent."""
    items = _store(request).owned(user.user_id, limit=limit)
    return {"count": len(items), "reports": items}
