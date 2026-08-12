from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, Request, UploadFile, status

from app.auth import AuthenticatedUser, require_admin, require_user
from app.models import (
    Course,
    CourseCreate,
    CoursePage,
    DocumentPage,
    Health,
    IngestionJob,
    UploadAccepted,
)
from app.services.ingestion import IngestionService

router = APIRouter()


def _service(request: Request) -> IngestionService:
    service: IngestionService = request.app.state.ingestion_service
    return service


@router.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", service="rag-api")


@router.post("/api/courses", response_model=Course, status_code=status.HTTP_201_CREATED)
def create_course(
    payload: CourseCreate,
    request: Request,
    _user: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> Course:
    return _service(request).create_course(payload)


@router.get("/api/courses", response_model=CoursePage)
def list_courses(
    request: Request,
    _user: Annotated[AuthenticatedUser, Depends(require_user)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, alias="pageSize", ge=1, le=100),
) -> CoursePage:
    return _service(request).list_courses(page=page, page_size=page_size)


@router.get("/api/courses/{course_id}/documents", response_model=DocumentPage)
def list_documents(
    course_id: str,
    request: Request,
    _user: Annotated[AuthenticatedUser, Depends(require_user)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, alias="pageSize", ge=1, le=100),
) -> DocumentPage:
    return _service(request).list_documents(course_id, page=page, page_size=page_size)


@router.post(
    "/api/courses/{course_id}/documents",
    response_model=UploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    course_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    _user: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> UploadAccepted:
    service = _service(request)
    content = await file.read(service.settings.max_upload_bytes + 1)
    accepted = service.queue_document(
        course_id=course_id,
        filename=file.filename or "",
        media_type=file.content_type or "application/octet-stream",
        content=content,
    )
    background_tasks.add_task(
        service.process_document,
        accepted.document.id,
        accepted.job.id,
    )
    return accepted


@router.get("/api/ingestion-jobs/{job_id}", response_model=IngestionJob)
def get_ingestion_job(
    job_id: str,
    request: Request,
    _user: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> IngestionJob:
    return _service(request).get_job(job_id)
