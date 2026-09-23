"""HTTP surface for the Local Canvas Bridge.

This is the route set a *local* tool talks to, so two things matter more here than anywhere else:

1. **No credential can be posted.** Every request model forbids extra fields, so a bridge that sends
   `token`, `pat`, `password` or anything else the schema does not name is refused with a 422
   instead of having the value quietly ignored. Combined with there being no column for one
   (`033_canvas_local_bridge.sql`), "the token never reaches CourseJesus" is a property of the code
   rather than a promise in a document.
2. **A session belongs to one user and one school.** The user's own authentication is required on
   every route, the session's owner must match it, and the school is the one recorded when the
   session was opened — a bridge cannot point a session at another school by sending a different
   origin.

The bridge authenticates exactly like the web app does (the user's own token), which is why these
routes use the same `require_user` dependency as the rest of the API.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from app.auth import AuthenticatedUser, require_user
from app.canvas.local_bridge import (
    DiscoveredCourse,
    LocalBridgeService,
    LocalSessionRepository,
)
from app.canvas.registry import InstitutionConnectionRegistry, UnknownInstitutionError
from app.config import Settings
from app.db import Database
from app.errors import ApiError
from app.services.ingestion import IngestionService

router = APIRouter(prefix="/api/integrations/canvas/local-sessions", tags=["canvas-local"])

# A refusal that names the missing prerequisite instead of a 500 when the tables are absent. The V3
# schema creates them with migration 033; a deployment without it has nowhere to put a session.
SCHEMA_NOT_READY = "SCHEMA_NOT_READY"


class OpenSessionRequest(BaseModel):
    """Opening a session needs a registered school and nothing else."""

    model_config = ConfigDict(extra="forbid")

    institution_key: str = Field(min_length=1, max_length=64)
    # Present only when the user asked for a school that is not in the registry yet. It is used to
    # *identify* the school for the record, never to build an outbound request: an unregistered
    # origin cannot be connected, and the page says so.
    canvas_base_url: str = Field(default="", max_length=200)


class ClaimRequest(BaseModel):
    """The first bridge call: the one-time code, plus what the bridge says about its account."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=8, max_length=200)
    canvas_user_id: str = Field(min_length=1, max_length=64)
    canvas_display_name: str = Field(default="", max_length=200)
    host_label: str = Field(default="", max_length=120)


class DiscoveredCourseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canvas_course_id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=200)
    course_code: str = Field(default="", max_length=64)
    term: str = Field(default="", max_length=64)
    enrollment_state: str = Field(default="", max_length=32)
    workflow_state: str = Field(default="", max_length=32)
    file_count: int = Field(default=0, ge=0)
    size_bytes: int = Field(default=0, ge=0)


class DiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    courses: list[DiscoveredCourseModel] = Field(min_length=1, max_length=500)


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canvas_course_ids: list[str] = Field(min_length=1, max_length=200)


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def _ingestion(request: Request) -> IngestionService:
    return cast(IngestionService, request.app.state.ingestion_service)


def _registry(request: Request) -> InstitutionConnectionRegistry:
    existing = getattr(request.app.state, "canvas_registry", None)
    return (
        existing
        if isinstance(existing, InstitutionConnectionRegistry)
        else InstitutionConnectionRegistry()
    )


def _tables_ready(request: Request) -> bool:
    cached = getattr(request.app.state, "canvas_local_tables_ready", None)
    if cached is not None:
        return bool(cached)
    with _database(request).connect() as connection:
        row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='canvas_local_sessions'"
        ).fetchone()
    ready = row is not None
    request.app.state.canvas_local_tables_ready = ready
    return ready


@contextmanager
def local_service(request: Request) -> Iterator[LocalBridgeService]:
    """The service bound to one connection, opened and closed inside the handler.

    A context manager rather than a FastAPI generator dependency: SQLite connections may only be
    used from the thread that created them, and a sync generator dependency's teardown can run on a
    different threadpool worker — the first version of this route set failed exactly there. Managing
    the connection inside the handler keeps one request on one thread.
    """
    if not _tables_ready(request):
        raise ApiError(
            503,
            SCHEMA_NOT_READY,
            "The local Canvas bridge needs the V3 schema (migration 033) in this deployment.",
        )
    with _database(request).connect() as connection:
        # Autocommit: the ingestion service writes on its own connections, and a held implicit
        # transaction here would block its `BEGIN IMMEDIATE`.
        connection.isolation_level = None
        yield LocalBridgeService(LocalSessionRepository(connection), ingestion=_ingestion(request))


@router.get("/capability")
def capability(
    request: Request, user: Annotated[AuthenticatedUser, Depends(require_user)]
) -> dict[str, Any]:
    """What this deployment can do, so the page never offers a bridge that is not implemented."""
    del user
    ready = _tables_ready(request)
    local = _settings(request).canvas_local_bridge_enabled
    return {
        "schemaReady": ready,
        "localBridgeEnabled": bool(ready and local),
        "reason": "" if ready and local else (SCHEMA_NOT_READY if not ready else "DISABLED"),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def open_session(
    payload: OpenSessionRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    """Open a session and return the one-time code the user pastes into their terminal.

    The response is the only place the code ever appears. An unregistered school is refused here
    rather than at claim time, so the user is told immediately that the school is not open yet.
    """
    try:
        institution = _registry(request).by_key(payload.institution_key)
    except UnknownInstitutionError as error:
        raise ApiError(
            400,
            "CANVAS_UNKNOWN_INSTITUTION",
            "That school is not in the registry, so CourseJesus cannot open a session for it yet.",
            details={"institutionKey": payload.institution_key},
        ) from error
    with local_service(request) as service:
        session, code = service.open_session(
            user_id=user.user_id,
            institution_key=institution.key,
            institution_origin=institution.origin,
        )
    return {
        "sessionId": session.id,
        "code": code,
        "institutionKey": session.institution_key,
        "institutionOrigin": session.institution_origin,
        "expiresAt": session.expires_at,
        "status": session.status,
    }


@router.get("/{session_id}")
def session_status(
    session_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    with local_service(request) as service:
        return service.status(user_id=user.user_id, session_id=session_id)


@router.post("/claim")
def claim(
    payload: ClaimRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    """The bridge claims its session with the user's own authentication and the one-time code."""
    with local_service(request) as service:
        session = service.claim(
            user_id=user.user_id,
            code=payload.code,
            canvas_user_id=payload.canvas_user_id,
            canvas_display_name=payload.canvas_display_name,
            claimed_by=payload.host_label,
        )
    return session.as_dict()


@router.post("/{session_id}/discovery")
def record_discovery(
    session_id: str,
    payload: DiscoveryRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    """The bridge reports the courses it found on the user's own Canvas account."""
    with local_service(request) as service:
        session = service.record_discovery(
            user_id=user.user_id,
            session_id=session_id,
            courses=[
                DiscoveredCourse(
                    canvas_course_id=item.canvas_course_id,
                    name=item.name,
                    course_code=item.course_code,
                    term=item.term,
                    enrollment_state=item.enrollment_state,
                    workflow_state=item.workflow_state,
                    file_count=item.file_count,
                    size_bytes=item.size_bytes,
                )
                for item in payload.courses
            ],
        )
    return session.as_dict()


@router.get("/{session_id}/courses")
def list_discovered(
    session_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    with local_service(request) as service:
        return service.status(user_id=user.user_id, session_id=session_id)


@router.post("/{session_id}/selection")
def select_courses(
    session_id: str,
    payload: SelectionRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    with local_service(request) as service:
        session = service.select(
            user_id=user.user_id,
            session_id=session_id,
            canvas_course_ids=payload.canvas_course_ids,
        )
    return session.as_dict()


@router.get("/{session_id}/selection")
def read_selection(
    session_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    """What the user chose, for the bridge to poll. The bridge never decides this itself."""
    with local_service(request) as service:
        payload = service.status(user_id=user.user_id, session_id=session_id)
    return {
        "sessionId": payload["sessionId"],
        "status": payload["status"],
        "selectedCourseIds": payload["selectedCourseIds"],
    }


@router.post("/{session_id}/files", status_code=status.HTTP_201_CREATED)
async def upload_file(
    session_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    canvas_course_id: Annotated[str, Form(min_length=1, max_length=64)],
    canvas_file_id: Annotated[str, Form(min_length=1, max_length=64)],
    display_name: Annotated[str, Form(min_length=1, max_length=200)],
    file: Annotated[UploadFile, File()],
    declared_size: Annotated[int, Form(ge=0)] = 0,
    declared_sha256: Annotated[str, Form(max_length=64)] = "",
    source_updated_at: Annotated[str, Form(max_length=40)] = "",
) -> dict[str, Any]:
    """One downloaded file, uploaded as bytes with no credential in sight.

    The field list is the whole contract: a bridge cannot attach a token to this request because the
    signature has nowhere to put one, and the bytes are checked against the declared size and digest
    before anything is written.
    """
    content = await file.read()
    with local_service(request) as service:
        record = service.upload_file(
            user_id=user.user_id,
            session_id=session_id,
            canvas_course_id=canvas_course_id,
            canvas_file_id=canvas_file_id,
            display_name=display_name,
            content=content,
            declared_size=declared_size,
            declared_sha256=declared_sha256,
            source_updated_at=source_updated_at,
        )
    return record.as_dict()


@router.post("/{session_id}/finish")
def finish(
    session_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    with local_service(request) as service:
        return service.finish(user_id=user.user_id, session_id=session_id)


@router.post("/{session_id}/cancel")
def cancel(
    session_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    """Stop a session. Files already ingested stay: they are the user's own private course."""
    with local_service(request) as service:
        return service.cancel(user_id=user.user_id, session_id=session_id)
