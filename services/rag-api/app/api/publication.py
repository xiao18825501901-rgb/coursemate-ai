from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import FileResponse

from app.auth import AuthenticatedUser, require_admin, require_user
from app.errors import ApiError
from app.learning.workspaces import original_path
from app.models import (
    PublicationRequest,
    PublicationRequestPage,
    PublicationReview,
    PublicationSnapshot,
    PublicationSubmit,
)
from app.services.publication import PublicationService

router = APIRouter()


def _service(request: Request) -> PublicationService:
    service: PublicationService = request.app.state.publication_service
    return service


@router.post(
    "/api/courses/{course_id}/publication-requests",
    response_model=PublicationRequest,
    status_code=status.HTTP_201_CREATED,
)
def submit_publication(
    course_id: str,
    payload: PublicationSubmit,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> PublicationRequest:
    return _service(request).submit(
        course_id,
        payload,
        owner_user_id=user.user_id,
        is_admin=user.is_admin,
    )


@router.delete(
    "/api/courses/{course_id}/publication-requests/current",
    status_code=status.HTTP_204_NO_CONTENT,
)
def withdraw_publication(
    course_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> Response:
    _service(request).withdraw(
        course_id,
        owner_user_id=user.user_id,
        is_admin=user.is_admin,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/admin/publication-requests", response_model=PublicationRequestPage)
def pending_publications(
    request: Request,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> PublicationRequestPage:
    return PublicationRequestPage(items=_service(request).list_pending())


@router.get(
    "/api/admin/publication-requests/{request_id}/snapshot",
    response_model=PublicationSnapshot,
)
def publication_snapshot(
    request_id: str,
    request: Request,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> PublicationSnapshot:
    return _service(request).snapshot(request_id)


@router.api_route(
    "/api/admin/publication-requests/{request_id}/documents/{version_id}/content",
    methods=["GET", "HEAD"],
)
def publication_document_content(
    request_id: str,
    version_id: str,
    request: Request,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> FileResponse:
    service = _service(request)
    version = service.scoped_document(request_id, version_id)
    path = original_path(service.database, version)
    if path is None:
        raise ApiError(410, "ORIGINAL_UNAVAILABLE", "The reviewed source is unavailable.")
    return FileResponse(
        path,
        media_type=version["media_type"],
        filename=version["filename"],
        content_disposition_type="attachment",
        headers={
            "Cache-Control": "private, no-store",
            "Vary": "Authorization",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/api/admin/publication-requests/{request_id}/review",
    response_model=PublicationRequest,
)
def review_publication(
    request_id: str,
    payload: PublicationReview,
    request: Request,
    admin: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> PublicationRequest:
    return _service(request).review(
        request_id,
        payload,
        reviewer_user_id=admin.user_id,
    )


@router.delete(
    "/api/admin/courses/{course_id}/publication",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unpublish_course(
    course_id: str,
    request: Request,
    admin: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> Response:
    _service(request).unpublish(course_id, actor_user_id=admin.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
