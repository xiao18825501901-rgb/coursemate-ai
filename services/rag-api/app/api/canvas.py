"""HTTP routes for the Canvas private import (task B2/B3).

These are the only paths by which a real school authorisation can start or finish, so the route
layer is deliberately thin and every decision it could get wrong is made by a tested module
instead:

* the institution is named by **key** and resolved through the registry, so a caller cannot
  submit a `base_url` and reuse another school's client secret;
* the callback's `redirect_uri` is the institution's registered value, and the redirect after
  the callback is a **fixed relative path** — there is no `return_url` parameter by which a
  caller could steer a user somewhere else;
* the state is one-time, short-lived and bound to `(subject, institution)` before any outbound
  request, so a forged or replayed callback cannot attach an account;
* a token never appears in a response body. What a caller may see about a connection is its id,
  the school, the Canvas display name, the granted scopes and an expiry — all read from the
  database row, never from the credential store;
* importing is a job: the selection is frozen into an idempotency fingerprint, and the same
  selection returns the same job instead of starting a second import.

When a school has no Developer Key — or the deployment has no credential-encryption key — these
routes report `NOT_CONFIGURED` so the UI can show the local-upload fallback. They never accept a
personal access token in place of the school's OAuth flow and never store a token in the clear.

Honest limit, stated here rather than discovered later: the state and credential stores are
constructed per process unless the application wires shared ones (`app.state.canvas_oauth`). A
multi-worker deployment therefore needs a shared state store before the flow is enabled for real
users; until then a callback may land on a worker that did not issue the state.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.auth import AuthenticatedUser, require_user
from app.canvas.adapter import (
    EXPIRED_TOKEN,
    FORBIDDEN,
    NOT_FOUND,
    RATE_LIMIT,
    CanvasReadAdapter,
    CanvasReadError,
)
from app.canvas.credentials import CredentialStoreUnavailable, credential_store_from_settings
from app.canvas.job import AWAITING_SELECTION, QUEUED, TERMINAL_STATES, new_job
from app.canvas.oauth import (
    CanvasOAuthClient,
    Connection,
    CredentialStore,
    InMemoryStateStore,
    OAuthError,
    SqlStateStore,
    StateStore,
    token_provider_for,
)
from app.canvas.registry import InstitutionConnectionRegistry, UnknownInstitutionError
from app.canvas.store import CanvasConnectionRepository, CanvasJobRepository
from app.config import Settings
from app.db import Database
from app.errors import ApiError

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations/canvas", tags=["canvas"])

# Where the browser lands after the callback, whatever happened. The path is configuration
# (`CANVAS_RETURN_PATH`) and never a request parameter: nothing in the query string can steer a
# user off the product. The outcome is appended as a query the UI reads on load.
IMPORT_STATUS_PARAM = "canvas"
CONNECTED = "connected"
DENIED = "denied"
FAILED = "failed"

CANVAS_UNAVAILABLE_CODES = {
    EXPIRED_TOKEN: (status.HTTP_401_UNAUTHORIZED, "CANVAS_NEEDS_REAUTH"),
    FORBIDDEN: (status.HTTP_403_FORBIDDEN, "CANVAS_FORBIDDEN"),
    NOT_FOUND: (status.HTTP_404_NOT_FOUND, "CANVAS_NOT_FOUND"),
    RATE_LIMIT: (status.HTTP_429_TOO_MANY_REQUESTS, "CANVAS_RATE_LIMITED"),
}


class ImportSelection(BaseModel):
    """The frozen selection: which connection, which Canvas courses, and nothing else."""

    connection_id: str = Field(min_length=1, max_length=64)
    course_ids: list[str] = Field(min_length=1, max_length=50)
    save_connection: bool = False


# ---------------------------------------------------------------------------------- plumbing
def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def _registry(request: Request) -> InstitutionConnectionRegistry:
    existing = getattr(request.app.state, "canvas_registry", None)
    return (
        existing
        if isinstance(existing, InstitutionConnectionRegistry)
        else InstitutionConnectionRegistry()
    )


def _credential_store(request: Request) -> CredentialStore | None:
    """The deployment's credential store, or None when it cannot be used."""
    existing = getattr(request.app.state, "canvas_credentials", None)
    if existing is not None:
        return cast(CredentialStore, existing)
    try:
        return credential_store_from_settings(_settings(request))
    except CredentialStoreUnavailable:
        LOGGER.warning("canvas credentials are configured but unusable")
        return None


def _oauth(request: Request) -> CanvasOAuthClient | None:
    """The shared OAuth client, or a per-process one when the app did not wire a shared copy.

    A deployment that builds its own client here still gets the **shared** state store when the
    schema is there, because a per-request client with an in-memory store could never validate its
    own state on a later request. The in-memory store is the fallback only for a deployment without
    the V3 schema, where the routes report `SCHEMA_NOT_READY` before any of this runs.
    """
    existing = getattr(request.app.state, "canvas_oauth", None)
    if isinstance(existing, CanvasOAuthClient):
        # A client without a credential store cannot persist a token, so it is not configured:
        # trusting one would mean the flow completes and the credential silently vanishes.
        return existing if existing.credentials is not None else None
    store = _credential_store(request)
    if store is None:
        return None
    state_store: StateStore = (
        SqlStateStore(_database(request)) if _state_tables_ready(request) else InMemoryStateStore()
    )
    return CanvasOAuthClient(
        registry=_registry(request),
        state_store=state_store,
        credential_store=store,
    )


def _state_tables_ready(request: Request) -> bool:
    """Whether migration 034 has run, so the shared state store can be used."""
    cached = getattr(request.app.state, "canvas_state_tables_ready", None)
    if cached is not None:
        return bool(cached)
    with _database(request).connect() as connection:
        row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='canvas_oauth_states'"
        ).fetchone()
    ready = row is not None
    request.app.state.canvas_state_tables_ready = ready
    return ready


def _tables_ready(request: Request) -> bool:
    """Whether the canvas tables exist in this deployment.

    They are created by migration 031, which is applied with the V3 schema: a deployment running
    without the private-course model has nowhere to put a connection or a job. Rather than
    failing with a missing-table 500, the integration reports itself unavailable, and the UI then
    shows the local-upload fallback instead of an error page.
    """
    cached = getattr(request.app.state, "canvas_tables_ready", None)
    if cached is not None:
        return bool(cached)
    with _database(request).connect() as connection:
        row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='canvas_connections'"
        ).fetchone()
    ready = row is not None
    request.app.state.canvas_tables_ready = ready
    return ready


def _require_tables(request: Request) -> None:
    if not _tables_ready(request):
        raise _canvas_unavailable("SCHEMA_NOT_READY")


def return_target(request: Request, outcome: str) -> str:
    """The configured return path with the outcome appended, fragment preserved.

    The UI is hash-routed, so the configured path may be `/ui-extension/#/courses`: the query
    goes before the fragment (`#` is not part of a query string) and the fragment is kept.
    """
    configured = _settings(request).canvas_return_path or "/"
    path, separator, fragment = configured.partition("#")
    joiner = "&" if "?" in path else "?"
    return f"{path}{joiner}{IMPORT_STATUS_PARAM}={outcome}" + (f"#{fragment}" if separator else "")


def _adapter(
    request: Request,
    *,
    connection_id: str,
    origin: str,
    registry: InstitutionConnectionRegistry,
    token_provider: Callable[[], str | None],
) -> CanvasReadAdapter:
    """One read-only adapter, built through the app's factory when it has one.

    The factory exists so the whole route surface can be exercised against a simulated school
    without a second code path in production: the default is the real adapter.
    """
    factory = getattr(request.app.state, "canvas_adapter_for", None)
    if callable(factory):
        return cast(
            CanvasReadAdapter,
            factory(
                connection_id=connection_id,
                origin=origin,
                registry=registry,
                token_provider=token_provider,
            ),
        )
    return CanvasReadAdapter(
        connection_id=connection_id,
        origin=origin,
        token_provider=token_provider,
        registry=registry,
    )


def _canvas_unavailable(reason: str) -> ApiError:
    return ApiError(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "CANVAS_NOT_CONFIGURED",
        "Canvas import is not available on this deployment yet.",
        details={"reason": reason},
    )


def _canvas_http_error(error: CanvasReadError) -> ApiError:
    code, name = CANVAS_UNAVAILABLE_CODES.get(
        error.category, (status.HTTP_502_BAD_GATEWAY, "CANVAS_UNAVAILABLE")
    )
    return ApiError(
        code,
        name,
        "The school could not be read.",
        details={"category": error.category},
    )


def _public_connection(connection: Connection) -> dict[str, Any]:
    """What a caller may see about a connection: never a token, never a key."""
    return {
        "connectionId": connection.connection_id,
        "institutionKey": connection.institution_key,
        "origin": connection.origin,
        "canvasName": connection.canvas_name,
        "savedForReuse": connection.saved_for_reuse,
        "scopes": list(connection.scopes),
        "expiresAt": connection.credential_expires_at,
    }


def _owned_connection(request: Request, user: AuthenticatedUser, connection_id: str) -> Connection:
    _require_tables(request)
    with _database(request).connect() as connection:
        stored = CanvasConnectionRepository(connection).get(connection_id, subject=user.user_id)
    if stored is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "CONNECTION_NOT_FOUND", "That connection was not found."
        )
    return stored


def _connection_adapter(
    request: Request, user: AuthenticatedUser, connection_id: str
) -> tuple[CanvasReadAdapter, Connection]:
    """A read-only adapter for *this user's* connection, or a typed refusal."""
    client = _oauth(request)
    if client is None:
        raise _canvas_unavailable("NO_CREDENTIAL_KEY")
    stored = _owned_connection(request, user, connection_id)
    try:
        institution = client.registry.by_origin(stored.origin)
    except UnknownInstitutionError as error:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "CONNECTION_INSTITUTION_UNKNOWN",
            "This connection names a school that is no longer configured.",
        ) from error
    if institution.key != stored.institution_key:
        # A stored row can only be used against the institution that issued it.
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "CONNECTION_INSTITUTION_MISMATCH",
            "This connection cannot be used against that school.",
        )
    adapter = _adapter(
        request,
        connection_id=stored.connection_id,
        origin=stored.origin,
        registry=client.registry,
        token_provider=token_provider_for(stored, client),
    )
    return adapter, stored


# ------------------------------------------------------------------------------ availability
@router.get("/institutions")
def list_institutions(
    request: Request, user: Annotated[AuthenticatedUser, Depends(require_user)]
) -> dict[str, Any]:
    """Which schools can be connected right now, and why not when they cannot."""
    del user
    registry = _registry(request)
    credentials_ready = _credential_store(request) is not None
    tables_ready = _tables_ready(request)
    institutions = []
    for institution in registry.institutions:
        configured = institution.state == "AVAILABLE"
        reason = "" if configured else "NO_DEVELOPER_KEY"
        if configured and not credentials_ready:
            reason = "NO_CREDENTIAL_KEY"
        if configured and not tables_ready:
            reason = "SCHEMA_NOT_READY"
        institutions.append(
            {
                "key": institution.key,
                "label": institution.label,
                "origin": institution.origin,
                "connectable": configured and credentials_ready and tables_ready,
                "reason": reason,
                "scopes": list(institution.scopes),
            }
        )
    return {
        "institutions": institutions,
        "credentialsReady": credentials_ready,
        "tablesReady": tables_ready,
    }


@router.get("/connections")
def list_connections(
    request: Request, user: Annotated[AuthenticatedUser, Depends(require_user)]
) -> dict[str, Any]:
    _require_tables(request)
    with _database(request).connect() as connection:
        rows = CanvasConnectionRepository(connection).for_subject(user.user_id)
    return {"connections": [_public_connection(row) for row in rows]}


# ---------------------------------------------------------------------------- authorisation
@router.get("/connect")
def start_authorisation(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    institution: Annotated[str, Query(min_length=1, max_length=64)],
) -> RedirectResponse:
    """Send the signed-in user to their school to authorise read-only access."""
    client = _oauth(request)
    if client is None:
        raise _canvas_unavailable("NO_CREDENTIAL_KEY")
    try:
        url = client.start(
            user.user_id, institution, return_path=_settings(request).canvas_return_path
        )
    except UnknownInstitutionError as error:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "UNKNOWN_INSTITUTION", "That school is not supported."
        ) from error
    except OAuthError as error:
        raise _canvas_unavailable(error.reason) from error
    # 303 so the browser follows with a GET and the authorisation URL is never re-posted.
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/oauth/callback")
def oauth_callback(
    request: Request,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    error_description: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Finish the authorisation: validate the state, exchange the code, bind the identity.

    This route is reached by the *school's* redirect, so it cannot require a session header: the
    one-time state is what proves which signed-in user started it, and it is validated before
    any outbound request. No credential is written into the response, and the redirect target is
    a fixed path.
    """
    client = _oauth(request)
    if client is None:
        return RedirectResponse(
            return_target(request, FAILED), status_code=status.HTTP_303_SEE_OTHER
        )
    params = {
        key: value
        for key, value in (
            ("code", code),
            ("state", state),
            ("error", error),
            ("error_description", error_description),
        )
        if value
    }
    try:
        completed = client.complete(params)
    except CanvasReadError as read_error:
        LOGGER.warning("canvas callback could not exchange the code: %s", read_error.category)
        return RedirectResponse(
            return_target(request, FAILED), status_code=status.HTTP_303_SEE_OTHER
        )
    except OAuthError as oauth_error:
        # A denial is a normal outcome the user chose; everything else failed. The school's own
        # message is logged, never echoed into a redirect target.
        LOGGER.info("canvas callback refused: %s", oauth_error.reason)
        outcome = DENIED if oauth_error.reason == "ACCESS_DENIED" else FAILED
        target = return_target(request, outcome)
        return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)

    canvas_user_id, canvas_name = _identity(
        request, completed.institution.origin, client.registry, completed.tokens.access_token
    )
    with _database(request).connect() as connection:
        repository = CanvasConnectionRepository(connection)
        # The question is "is this school already linked to a *different* Canvas account?", so
        # the lookup is by user and institution — not by the account id that has no row yet.
        existing = repository.for_subject_and_institution(
            subject=completed.state.subject, origin=completed.institution.origin
        )
        try:
            bound = completed.bind(
                canvas_user_id=canvas_user_id,
                canvas_name=canvas_name,
                connection_id=existing.connection_id if existing else uuid.uuid4().hex,
                credential_store=client.credentials,
                previous=existing,
            )
        except OAuthError as replacement_error:
            # A different Canvas account cannot take over an existing connection. The user has
            # to disconnect first, which is a decision rather than a silent rebind.
            LOGGER.warning("canvas callback refused a rebind: %s", replacement_error.reason)
            return RedirectResponse(
                return_target(request, FAILED), status_code=status.HTTP_303_SEE_OTHER
            )
        repository.upsert(bound, connection_id=bound.connection_id)
    return RedirectResponse(
        return_target(request, CONNECTED), status_code=status.HTTP_303_SEE_OTHER
    )


def _identity(
    request: Request,
    origin: str,
    registry: InstitutionConnectionRegistry,
    access_token: str,
) -> tuple[str, str]:
    """The Canvas identity behind the new token, read once and never guessed."""
    adapter = _adapter(
        request,
        connection_id="identity-check",
        origin=origin,
        registry=registry,
        token_provider=lambda: access_token,
    )
    profile = adapter.profile()
    if not profile.id:
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            "CANVAS_IDENTITY_UNAVAILABLE",
            "The school did not return an account identity for this authorisation.",
        )
    return str(profile.id), profile.name


# ------------------------------------------------------------------------------------ courses
@router.get("/courses")
def list_canvas_courses(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    connection_id: Annotated[str, Query(min_length=1, max_length=64)],
) -> dict[str, Any]:
    """The student's own readable courses, for the import selection screen."""
    adapter, _stored = _connection_adapter(request, user, connection_id)
    try:
        courses = adapter.student_courses()
    except CanvasReadError as error:
        raise _canvas_http_error(error) from error
    return {
        "courses": [
            {
                "id": course.id,
                "name": course.name,
                "courseCode": course.course_code,
                "term": course.term,
                "workflowState": course.workflow_state,
                "readable": course.is_readable_history,
            }
            for course in courses
        ]
    }


# ------------------------------------------------------------------------------------ imports
@router.post("/imports", status_code=status.HTTP_202_ACCEPTED)
def create_import(
    payload: ImportSelection,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    """Freeze a selection into a job. The same selection returns the same job."""
    stored = _owned_connection(request, user, payload.connection_id)
    course_ids = [str(course) for course in payload.course_ids]
    if any(not course.isdigit() for course in course_ids):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "INVALID_COURSE_ID",
            "Canvas course ids are numeric.",
        )
    job = new_job(
        job_id=uuid.uuid4().hex,
        connection_id=stored.connection_id,
        subject=user.user_id,
        institution_origin=stored.origin,
        course_ids=course_ids,
    )
    # Confirming the selection is the only legal way into QUEUED, and it is what the worker
    # looks for: a job waiting for the student is never picked up.
    job.transition(AWAITING_SELECTION)
    job.transition(QUEUED)
    with _database(request).connect() as connection:
        repository = CanvasJobRepository(connection)
        job_id, created = repository.create_or_get(job)
        if payload.save_connection:
            CanvasConnectionRepository(connection).mark_saved_for_reuse(
                stored.connection_id, subject=user.user_id, saved=True
            )
        row = repository.snapshot(job_id)
    return {
        "jobId": job_id,
        "created": created,
        "status": str(row["status"]) if row else QUEUED,
        "courseIds": sorted(course_ids),
    }


@router.get("/imports/{job_id}")
def import_status(
    job_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    _require_tables(request)
    with _database(request).connect() as connection:
        repository = CanvasJobRepository(connection)
        row = repository.snapshot(job_id)
        if row is None or str(row["owner_user_id"]) != user.user_id:
            # Another user's job is reported as absent, not as forbidden: whether it exists is
            # not something an unrelated account should be able to probe.
            raise ApiError(status.HTTP_404_NOT_FOUND, "JOB_NOT_FOUND", "That import was not found.")
        files = repository.list_files(job_id)
    counts: dict[str, int] = {}
    for record in files:
        counts[record.status] = counts.get(record.status, 0) + 1
    return {
        "jobId": job_id,
        "status": str(row["status"]),
        "errorCode": str(row["error_code"] or ""),
        "errorMessage": str(row["error_message"] or ""),
        "targetCourseId": str(row["target_course_id"] or ""),
        "courses": len(json.loads(str(row["course_ids_json"]))),
        "files": len(files),
        "byStatus": counts,
    }


@router.post("/imports/{job_id}/cancel")
def cancel_import(
    job_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    """Cancel at the next checkpoint. Imported material is left alone."""
    _require_tables(request)
    with _database(request).connect() as connection:
        repository = CanvasJobRepository(connection)
        row = repository.snapshot(job_id)
        if row is None or str(row["owner_user_id"]) != user.user_id:
            raise ApiError(status.HTTP_404_NOT_FOUND, "JOB_NOT_FOUND", "That import was not found.")
        current = str(row["status"])
        if current in TERMINAL_STATES:
            return {"jobId": job_id, "status": current, "cancelled": False}
        repository.set_status(job_id, "CANCELLED")
    return {"jobId": job_id, "status": "CANCELLED", "cancelled": True}


@router.delete("/connections/{connection_id}")
def disconnect(
    connection_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    """Revoke at the school and forget the local credential.

    The school call is best-effort; the local forget is not, because a disconnect that leaves a
    usable credential behind is worse than one that leaves a stale token at the school.
    """
    stored = _owned_connection(request, user, connection_id)
    client = _oauth(request)
    revoked_remote = False
    if client is not None:
        try:
            revoked_remote = client.revoke(stored)
        except (CanvasReadError, OAuthError):
            revoked_remote = False
    store = client.credentials if client is not None else _credential_store(request)
    if store is not None:
        store.clear(connection_id)
    with _database(request).connect() as connection:
        CanvasConnectionRepository(connection).mark_revoked(connection_id, subject=user.user_id)
    return {"connectionId": connection_id, "revoked": True, "revokedAtSchool": revoked_remote}
