from dataclasses import dataclass
from typing import Annotated, Protocol

from clerk_backend_api import (  # type: ignore[attr-defined]
    AuthenticateRequestOptions,
    authenticate_request,
)
from clerk_backend_api.security.types import AuthStatus
from fastapi import Depends, Request

from app.config import Settings
from app.errors import ApiError


class AuthVerifier(Protocol):
    def authenticate(self, request: Request) -> str | None: ...


class ClerkAuthVerifier:
    def __init__(self, settings: Settings) -> None:
        self.options = AuthenticateRequestOptions(
            secret_key=settings.clerk_secret_key.get_secret_value()
            if settings.clerk_secret_key
            else None,
            jwt_key=settings.clerk_jwt_key.get_secret_value()
            if settings.clerk_jwt_key
            else None,
            authorized_parties=[settings.web_origin],
            accepts_token=["session_token"],
        )
        self.configured = bool(settings.clerk_secret_key or settings.clerk_jwt_key)

    def authenticate(self, request: Request) -> str | None:
        if not self.configured:
            return None
        state = authenticate_request(request, self.options)
        if state.status != AuthStatus.SIGNED_IN or state.payload is None:
            return None
        subject = state.payload.get("sub")
        return subject if isinstance(subject, str) and subject else None


class TestAuthVerifier:
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

    def authenticate(self, request: Request) -> str | None:
        if request.headers.get("authorization") == "Bearer test-session-token":
            return self.user_id
        return None


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    is_admin: bool


def require_user(request: Request) -> AuthenticatedUser:
    verifier: AuthVerifier = request.app.state.auth_verifier
    user_id = verifier.authenticate(request)
    if user_id is None:
        raise ApiError(401, "UNAUTHENTICATED", "A valid sign-in session is required.")
    settings: Settings = request.app.state.settings
    return AuthenticatedUser(user_id=user_id, is_admin=user_id in settings.admin_user_id_set)


def require_admin(
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> AuthenticatedUser:
    if not user.is_admin:
        raise ApiError(403, "ADMIN_REQUIRED", "Administrator access is required.")
    return user
