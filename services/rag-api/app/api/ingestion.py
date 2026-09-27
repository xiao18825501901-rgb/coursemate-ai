from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)

from app.auth import AuthenticatedUser, require_user
from app.models import (
    Course,
    CourseCreate,
    CoursePage,
    CourseUpdate,
    DirectUploadCreate,
    DirectUploadGrant,
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
def health(request: Request, response: Response) -> Health:
    if not request.app.state.database.is_ready():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Health(status="unavailable", service="rag-api")
    return Health(status="ok", service="rag-api")


@router.post("/api/courses", response_model=Course, status_code=status.HTTP_201_CREATED)
def create_course(
    payload: CourseCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> Course:
    return _service(request).create_course(
        payload, owner_user_id=user.user_id, is_admin=user.is_admin
    )


@router.get("/api/courses", response_model=CoursePage)
def list_courses(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, alias="pageSize", ge=1, le=100),
) -> CoursePage:
    return _service(request).list_courses(
        page=page, page_size=page_size, owner_user_id=user.user_id, is_admin=user.is_admin
    )


@router.get("/api/courses/{course_id}", response_model=Course)
def get_course(
    course_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> Course:
    return _service(request).get_course(
        course_id,
        owner_user_id=user.user_id,
        is_admin=user.is_admin,
    )


@router.patch("/api/courses/{course_id}", response_model=Course)
def update_course(
    course_id: str,
    payload: CourseUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> Course:
    return _service(request).update_course(
        course_id, payload, owner_user_id=user.user_id, is_admin=user.is_admin
    )


@router.delete("/api/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(
    course_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> Response:
    _service(request).delete_course(
        course_id, owner_user_id=user.user_id, is_admin=user.is_admin
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/courses/{course_id}/documents", response_model=DocumentPage)
def list_documents(
    course_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, alias="pageSize", ge=1, le=100),
) -> DocumentPage:
    return _service(request).list_documents(
        course_id,
        page=page,
        page_size=page_size,
        owner_user_id=user.user_id,
        is_admin=user.is_admin,
    )


@router.delete(
    "/api/courses/{course_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_document(
    course_id: str,
    document_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> Response:
    _service(request).delete_document(
        course_id,
        document_id,
        owner_user_id=user.user_id,
        is_admin=user.is_admin,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> UploadAccepted:
    service = _service(request)
    content = await file.read(service.settings.max_upload_bytes + 1)
    accepted = service.queue_document(
        course_id=course_id,
        filename=file.filename or "",
        media_type=file.content_type or "application/octet-stream",
        content=content,
        owner_user_id=user.user_id,
        is_admin=user.is_admin,
    )
    background_tasks.add_task(
        service.process_document,
        accepted.document.id,
        accepted.job.id,
    )
    return accepted


@router.post(
    "/api/courses/{course_id}/direct-uploads",
    response_model=DirectUploadGrant,
    status_code=status.HTTP_201_CREATED,
)
def begin_direct_upload(
    course_id: str,
    payload: DirectUploadCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> DirectUploadGrant:
    return _service(request).begin_direct_upload(
        course_id=course_id,
        payload=payload,
        owner_user_id=user.user_id,
        is_admin=user.is_admin,
    )


@router.post(
    "/api/direct-uploads/{upload_id}/complete",
    response_model=UploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def complete_direct_upload(
    upload_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> UploadAccepted:
    service = _service(request)
    accepted = service.finalize_direct_upload(
        upload_id=upload_id,
        owner_user_id=user.user_id,
        is_admin=user.is_admin,
    )
    if accepted.job.error_message != "WAITING_CAPACITY":
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
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> IngestionJob:
    return _service(request).get_job(
        job_id, owner_user_id=user.user_id, is_admin=user.is_admin
    )


@router.post(
    "/api/ingestion-jobs/{job_id}/resume",
    response_model=IngestionJob,
    status_code=status.HTTP_202_ACCEPTED,
)
def resume_waiting_ingestion_job(
    job_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> IngestionJob:
    service = _service(request)
    job = service.get_job(job_id, owner_user_id=user.user_id, is_admin=user.is_admin)
    if job.status.value != "queued" or job.error_message != "WAITING_CAPACITY":
        from app.errors import ApiError

        raise ApiError(
            409,
            "INGESTION_NOT_WAITING_CAPACITY",
            "Only a capacity-waiting ingestion job can be resumed.",
        )
    background_tasks.add_task(service.process_document, job.document_id, job.id)
    return job
