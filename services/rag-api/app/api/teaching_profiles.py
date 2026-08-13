from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.auth import AuthenticatedUser, require_user
from app.models import (
    TeachingProfile,
    TeachingProfileBuilderRequest,
    TeachingProfileInput,
    TeachingProfilePage,
    TeachingProfilePreview,
)
from app.services.teaching_profiles import TeachingProfileService

router = APIRouter()


def _service(request: Request) -> TeachingProfileService:
    service: TeachingProfileService = request.app.state.teaching_profile_service
    return service


@router.post("/api/teaching-profiles/preview", response_model=TeachingProfilePreview)
def preview_profile(
    payload: TeachingProfileBuilderRequest,
    request: Request,
    _user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> TeachingProfilePreview:
    return _service(request).preview(payload)


@router.get(
    "/api/courses/{course_id}/teaching-profiles",
    response_model=TeachingProfilePage,
)
def list_profiles(
    course_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> TeachingProfilePage:
    return TeachingProfilePage(
        items=_service(request).list_profiles(
            course_id, owner_user_id=user.user_id, is_admin=user.is_admin
        )
    )


@router.post(
    "/api/courses/{course_id}/teaching-profiles",
    response_model=TeachingProfile,
    status_code=status.HTTP_201_CREATED,
)
def save_profile(
    course_id: str,
    payload: TeachingProfileInput,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> TeachingProfile:
    return _service(request).save(
        course_id,
        payload,
        owner_user_id=user.user_id,
        is_admin=user.is_admin,
    )


@router.post(
    "/api/courses/{course_id}/teaching-profiles/{version}/restore",
    response_model=TeachingProfile,
    status_code=status.HTTP_201_CREATED,
)
def restore_profile(
    course_id: str,
    version: int,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> TeachingProfile:
    return _service(request).restore(
        course_id,
        version,
        owner_user_id=user.user_id,
        is_admin=user.is_admin,
    )
