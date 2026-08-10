from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.models import QaChatRequest
from app.services.qa import QaService

router = APIRouter()


def _service(request: Request) -> QaService:
    service: QaService = request.app.state.qa_service
    return service


@router.post("/api/qa/chat")
def chat(payload: QaChatRequest, request: Request) -> StreamingResponse:
    service = _service(request)
    service.require_course(payload.course_id)
    return StreamingResponse(
        service.stream(course_id=payload.course_id, question=payload.question),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
