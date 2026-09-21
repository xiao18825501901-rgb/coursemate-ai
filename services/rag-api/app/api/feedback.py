"""Minimal HTTP route for submitting a user-initiated feedback report.

The report is triaged (one batched Jev call) and queued for human review; the
deterministic backend owns persistence and the human review, so this route only
records and classifies.  A report body (free text + question/answer) is refused
unless the caller sets ``attach_body``.

There is no live Jev call here: the gateway uses the default ``SdkTransport``,
which fails typed with ``JevNotConfiguredError`` while no TypeSafe credential
exists, so the report degrades to ``OTHER`` + middle severity and is still queued.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from app.auth import AuthenticatedUser, require_user
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
    return result.as_dict()
