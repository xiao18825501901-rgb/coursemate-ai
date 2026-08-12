from time import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.auth import AuthenticatedUser, require_user
from app.models import ConversationDetail, QaChatRequest
from app.services.qa import QaService

router = APIRouter()


def _service(request: Request) -> QaService:
    service: QaService = request.app.state.qa_service
    return service


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


@router.post("/api/qa/chat")
def chat(
    payload: QaChatRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> StreamingResponse:
    service = _service(request)
    service.require_course(payload.course_id)
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
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
