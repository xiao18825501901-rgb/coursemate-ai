from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import FileResponse

from app.auth import AuthenticatedUser, require_admin, require_user
from app.errors import ApiError
from app.learning.workspaces import original_path
from app.models import (
    OfficialKnowledgeDraftPage,
    OfficialKnowledgePublicationRequest,
    OfficialKnowledgePublicationRequestPage,
    OfficialKnowledgePublicationSubmit,
    OverlayPublicationRequest,
    OverlayPublicationRequestPage,
    OverlayPublicationSubmit,
    PublicationRequest,
    PublicationRequestPage,
    PublicationReview,
    PublicationSnapshot,
    PublicationSubmit,
)
from app.services.knowledge_publication import KnowledgePublicationService
from app.services.overlay_publication import OverlayPublicationService
from app.services.publication import PublicationService

router = APIRouter()


def _service(request: Request) -> PublicationService:
    service: PublicationService = request.app.state.publication_service
    return service


def _knowledge_service(request: Request) -> KnowledgePublicationService:
    service: KnowledgePublicationService = request.app.state.knowledge_publication_service
    return service


def _overlay_service(request: Request) -> OverlayPublicationService:
    service: OverlayPublicationService = request.app.state.overlay_publication_service
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


@router.get(
    "/api/admin/knowledge-publication-drafts",
    response_model=OfficialKnowledgeDraftPage,
)
def official_knowledge_drafts(
    request: Request,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> OfficialKnowledgeDraftPage:
    return OfficialKnowledgeDraftPage(items=_knowledge_service(request).list_drafts())


@router.post(
    "/api/admin/knowledge-publication-requests",
    response_model=OfficialKnowledgePublicationRequest,
    status_code=status.HTTP_201_CREATED,
)
def submit_official_knowledge(
    payload: OfficialKnowledgePublicationSubmit,
    request: Request,
    admin: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> OfficialKnowledgePublicationRequest:
    return _knowledge_service(request).submit(payload, submitter_user_id=admin.user_id)


@router.get(
    "/api/admin/knowledge-publication-requests",
    response_model=OfficialKnowledgePublicationRequestPage,
)
def pending_official_knowledge(
    request: Request,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> OfficialKnowledgePublicationRequestPage:
    return OfficialKnowledgePublicationRequestPage(
        items=_knowledge_service(request).list_pending()
    )


@router.get(
    "/api/admin/knowledge-publication-requests/{request_id}/snapshot",
    response_model=PublicationSnapshot,
)
def official_knowledge_snapshot(
    request_id: str,
    request: Request,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> PublicationSnapshot:
    return _knowledge_service(request).snapshot(request_id)


@router.post(
    "/api/admin/knowledge-publication-requests/{request_id}/review",
    response_model=OfficialKnowledgePublicationRequest,
)
def review_official_knowledge(
    request_id: str,
    payload: PublicationReview,
    request: Request,
    admin: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> OfficialKnowledgePublicationRequest:
    return _knowledge_service(request).review(
        request_id,
        payload,
        reviewer_user_id=admin.user_id,
    )


@router.delete(
    "/api/admin/knowledge-publication-requests/{request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def withdraw_official_knowledge(
    request_id: str,
    request: Request,
    admin: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> Response:
    _knowledge_service(request).withdraw(request_id, actor_user_id=admin.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/api/learning/workspaces/{workspace_id}/overlay-publication-requests",
    response_model=OverlayPublicationRequest,
    status_code=status.HTTP_201_CREATED,
)
def submit_overlay_publication(
    workspace_id: str,
    payload: OverlayPublicationSubmit,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> OverlayPublicationRequest:
    return _overlay_service(request).submit(
        workspace_id,
        payload,
        owner_user_id=user.user_id,
    )


@router.get(
    "/api/learning/workspaces/{workspace_id}/overlay-publication-requests/current",
    response_model=OverlayPublicationRequest,
)
def current_overlay_publication(
    workspace_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> OverlayPublicationRequest:
    return _overlay_service(request).current(workspace_id, owner_user_id=user.user_id)


@router.delete(
    "/api/learning/workspaces/{workspace_id}/overlay-publication-requests/current",
    status_code=status.HTTP_204_NO_CONTENT,
)
def withdraw_overlay_publication(
    workspace_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> Response:
    _overlay_service(request).withdraw_current(workspace_id, owner_user_id=user.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/api/admin/overlay-publication-requests",
    response_model=OverlayPublicationRequestPage,
)
def pending_overlay_publications(
    request: Request,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> OverlayPublicationRequestPage:
    return OverlayPublicationRequestPage(items=_overlay_service(request).list_pending())


@router.get(
    "/api/admin/overlay-publication-requests/{request_id}/snapshot",
    response_model=PublicationSnapshot,
)
def overlay_publication_snapshot(
    request_id: str,
    request: Request,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> PublicationSnapshot:
    return _overlay_service(request).snapshot(request_id)


@router.post(
    "/api/admin/overlay-publication-requests/{request_id}/review",
    response_model=OverlayPublicationRequest,
)
def review_overlay_publication(
    request_id: str,
    payload: PublicationReview,
    request: Request,
    admin: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> OverlayPublicationRequest:
    return _overlay_service(request).review(
        request_id,
        payload,
        reviewer_user_id=admin.user_id,
    )


@router.api_route(
    "/api/admin/overlay-publication-requests/{request_id}/documents/{version_id}/content",
    methods=["GET", "HEAD"],
)
def overlay_review_document_content(
    request_id: str,
    version_id: str,
    request: Request,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> FileResponse:
    service = _overlay_service(request)
    version = service.scoped_document(request_id, version_id, public_access=False)
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


@router.get("/api/shared-overlays/{request_id}", response_model=PublicationSnapshot)
def shared_overlay(
    request_id: str,
    request: Request,
    response: Response,
    _user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> PublicationSnapshot:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    return _overlay_service(request).public_snapshot(request_id)


@router.api_route(
    "/api/shared-overlays/{request_id}/documents/{version_id}/content",
    methods=["GET", "HEAD"],
)
def shared_overlay_document_content(
    request_id: str,
    version_id: str,
    request: Request,
    _user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> FileResponse:
    service = _overlay_service(request)
    version = service.scoped_document(request_id, version_id, public_access=True)
    path = original_path(service.database, version)
    if path is None:
        raise ApiError(410, "ORIGINAL_UNAVAILABLE", "The shared source is unavailable.")
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
