from time import time
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.auth import AuthenticatedUser, require_admin, require_user
from app.models import (
    ConversationCreate,
    ConversationDetail,
    ConversationPage,
    ConversationSummary,
    ConversationUpdate,
    QaChatRequest,
    RetrievalDiagnosticsRequest,
)
from app.services.qa import QaService

router = APIRouter()


@router.post("/api/admin/retrieval/diagnostics")
def retrieval_diagnostics(
    payload: RetrievalDiagnosticsRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> dict[str, object]:
    _service(request).require_course(
        payload.course_id, owner_user_id=user.user_id, is_admin=user.is_admin
    )
    return _service(request).retrieval_diagnostics(
        course_id=payload.course_id,
        question=payload.question,
    )


def _service(request: Request) -> QaService:
    service: QaService = request.app.state.qa_service
    return service


@router.get("/api/conversations", response_model=ConversationPage)
def list_conversations(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    course_id: str | None = Query(default=None, alias="courseId"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
) -> dict[str, object]:
    service = _service(request)
    if course_id is not None:
        service.require_course(
            course_id, owner_user_id=user.user_id, is_admin=user.is_admin
        )
    return service.list_conversations(
        owner_user_id=user.user_id,
        course_id=course_id,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/api/conversations",
    response_model=ConversationSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    payload: ConversationCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, object]:
    service = _service(request)
    service.require_course(
        payload.course_id, owner_user_id=user.user_id, is_admin=user.is_admin
    )
    return service.create_conversation(
        owner_user_id=user.user_id,
        course_id=payload.course_id,
        preferred_language=payload.preferred_language.value,
    )


@router.get("/api/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, object]:
    return _service(request).get_conversation(
        owner_user_id=user.user_id,
        conversation_id=conversation_id,
    )


@router.patch("/api/conversations/{conversation_id}", response_model=ConversationSummary)
def rename_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, object]:
    return _service(request).rename_conversation(
        owner_user_id=user.user_id,
        conversation_id=conversation_id,
        title=payload.title,
    )


@router.delete(
    "/api/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation(
    conversation_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> Response:
    _service(request).delete_conversation(
        owner_user_id=user.user_id,
        conversation_id=conversation_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/qa/chat")
def chat(
    payload: QaChatRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> StreamingResponse:
    service = _service(request)
    service.require_course(
        payload.course_id, owner_user_id=user.user_id, is_admin=user.is_admin
    )
    if payload.conversation_id is not None:
        service.require_conversation(
            owner_user_id=user.user_id,
            course_id=payload.course_id,
            conversation_id=payload.conversation_id,
        )
    settings = request.app.state.settings
    if not service.database.consume_rate_limit(
        owner_user_id=user.user_id,
        action="rag_qa",
        limit=settings.rag_qa_requests_per_minute,
        now_epoch_seconds=int(time()),
    ):
        from app.errors import ApiError

        raise ApiError(429, "RATE_LIMITED", "Too many AI requests. Please try again shortly.")
    return StreamingResponse(
        service.stream(
            owner_user_id=user.user_id,
            course_id=payload.course_id,
            question=payload.question,
            conversation_id=payload.conversation_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
