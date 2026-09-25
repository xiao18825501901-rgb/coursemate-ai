"""HTTP routes for the Canvas private import (task B2/B3).

These are the only paths by which a real school authorisation can start or finish, so the route
layer is deliberately thin and every decision it could get wrong is made by a tested module
instead:

* the institution is named by **key** and resolved through the registry, so a caller cannot
  submit a `base_url` and reuse another school's client secret;
* the callback's `redirect_uri` is the institution's registered value, and the redirect after
  the callback is a **fixed relative path** 鈥?there is no `return_url` parameter by which a
  caller could steer a user somewhere else;
* the state is one-time, short-lived and bound to `(subject, institution)` before any outbound
  request, so a forged or replayed callback cannot attach an account;
* a token never appears in a response body. What a caller may see about a connection is its id,
  the school, the Canvas display name, the granted scopes and an expiry 鈥?all read from the
  database row, never from the credential store;
* importing is a job: the selection is frozen into an idempotency fingerprint, and the same
  selection returns the same job instead of starting a second import.

When a school has no Developer Key 鈥?or the deployment has no credential-encryption key 鈥?these
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
from pydantic import BaseModel, ConfigDict, Field

from app.auth import AuthenticatedUser, require_user
from app.canvas.adapter import (
    API_RESPONSE_NOT_JSON,
    EXPIRED_TOKEN,
    FORBIDDEN,
    NOT_FOUND,
    RATE_LIMIT,
    CanvasReadAdapter,
    CanvasReadError,
)
from app.canvas.credentials import CredentialStoreUnavailable, credential_store_from_settings
from app.canvas.job import (
    AWAITING_SELECTION,
    CREDENTIAL_KIND_CONNECTION,
    CREDENTIAL_KIND_TRANSIENT_TASK,
    QUEUED,
    TERMINAL_STATES,
    new_job,
)
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
from app.canvas.store import (
    CanvasConnectionRepository,
    CanvasCredentialLifecycleRepository,
    CanvasJobRepository,
)
from app.canvas.transient_credential import (
    DESTROYED,
    EXPIRED,
    HARD_TTL_SECONDS,
    LOST_ON_RESTART,
    PRESENT_TRANSIENTLY,
    SELECTION_IDLE_TTL_SECONDS,
    CredentialRefused,
    TaskCredential,
    TransientCanvasCredentialStore,
)
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
    API_RESPONSE_NOT_JSON: (status.HTTP_502_BAD_GATEWAY, "API_RESPONSE_NOT_JSON"),
}


class ImportSelection(BaseModel):
    """The frozen selection: which connection, which Canvas courses, and nothing else.

    `extra="forbid"` is deliberate and load-bearing: without it a body could carry a
    `personal_access_token` and have it silently ignored, which is exactly the kind of near-miss
    that makes "this service never accepts a credential here" untrue in practice. A credential is
    accepted on one route, and everywhere else a body containing one is refused.
    """

    model_config = ConfigDict(extra="forbid")

    connection_id: str = Field(min_length=1, max_length=64)
    course_ids: list[str] = Field(min_length=1, max_length=50)
    save_connection: bool = False
    # Only ever a reference to a credential held in this process, never a credential. A caller
    # that names one is saying "use the token this task was given", and an unknown reference is
    # refused rather than treated as "no credential".
    credential_ref: str = Field(default="", max_length=64)


class TaskCredentialRequest(BaseModel):
    """The one request in this service that carries a credential, and only for its owner.

    The module docstring's rule is that no route accepts a personal access token in place of the
    school's OAuth flow. This is the deliberate, single exception, and the four things that keep
    it from becoming a second import system:

    * the deployment must enable it (`CANVAS_TASK_CREDENTIAL_ENABLED`, off by default);
    * the account must be listed as an owner (`CANVAS_TASK_CREDENTIAL_USERS`, defaulting to the
      administrators), so it is not a public multi-user path;
    * the credential is never stored 鈥?it is held in this process for one task and destroyed
      when that task's Canvas reads are done;
    * the school must still be one the registry knows, addressed by key or by its exact origin.

    `extra="forbid"` stays: this model has exactly the fields it needs, and a caller cannot smuggle
    in a scope, a user id or a return path.
    """

    model_config = ConfigDict(extra="forbid")

    institution_key: str = Field(default="", max_length=64)
    canvas_base_url: str = Field(default="", max_length=200)
    personal_access_token: str = Field(min_length=1, max_length=512)
    canvas_user_id: str = Field(default="", max_length=64)


class TaskCredentialForget(BaseModel):
    """Why a credential stopped existing, when the caller is the one ending it."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="user_disconnected", max_length=64)



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


def _task_credential_store(request: Request) -> TransientCanvasCredentialStore:
    """The process's transient store. One per app, because that is what "in memory" means here."""
    existing = getattr(request.app.state, "canvas_task_credentials", None)
    if isinstance(existing, TransientCanvasCredentialStore):
        return existing
    created = TransientCanvasCredentialStore()
    request.app.state.canvas_task_credentials = created
    return created


def _task_credential_capability(request: Request, user: AuthenticatedUser) -> dict[str, Any]:
    """Whether *this* caller may use the task-credential path, and why not when they may not.

    Kept separate from the OAuth capability on purpose: the owner's own testing is not evidence
    that the school has approved a public token path, and the two answers must be reportable
    independently (`PAT_CODE_AND_OWNER_TEST` versus `PAT_PUBLIC_ROLLOUT_ELIGIBILITY`).
    """
    settings = _settings(request)
    if not settings.canvas_task_credential_enabled:
        return {"available": False, "reason": "TASK_CREDENTIAL_DISABLED", "ownerOnly": True}
    if user.user_id not in settings.canvas_task_credential_user_set:
        return {"available": False, "reason": "NOT_LISTED_FOR_TASK_CREDENTIAL", "ownerOnly": True}
    if not _tables_ready(request):
        return {"available": False, "reason": "SCHEMA_NOT_READY", "ownerOnly": True}
    return {
        "available": True,
        "reason": "",
        "ownerOnly": True,
        "idleMinutes": int(SELECTION_IDLE_TTL_SECONDS // 60),
        "maxHours": int(HARD_TTL_SECONDS // 3600),
    }


def _require_task_credential_owner(request: Request, user: AuthenticatedUser) -> None:
    capability = _task_credential_capability(request, user)
    if not capability["available"]:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "CANVAS_TASK_CREDENTIAL_FORBIDDEN",
            "This deployment does not offer the one-off credential import for this account.",
            details={"reason": capability["reason"]},
        )


def _public_task_credential(credential: TaskCredential) -> dict[str, Any]:
    """What a caller may see about a task credential: its state, never its value."""
    return {
        "credentialRef": credential.credential_ref,
        "state": credential.state,
        "connectionId": credential.connection_id,
        "institutionKey": credential.institution_key,
        "origin": credential.institution_origin,
        "canvasUserId": credential.canvas_user_id,
        "canvasName": credential.canvas_display_name,
        "readCalls": credential.read_calls,
        "expiresAt": credential.created_wall + (credential.idle_expires_at - credential.created_at),
        "hardExpiresAt": credential.created_wall + (
            credential.hard_expires_at - credential.created_at
        ),
    }


def _owned_task_credential(
    request: Request, user: AuthenticatedUser, credential_ref: str
) -> TaskCredential:
    """This user's live task credential, or a typed refusal that says which state it is in."""
    credential = _task_credential_store(request).record(credential_ref)
    if credential is None or credential.subject != user.user_id:
        state = _task_credential_store(request).state(credential_ref)
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "TASK_CREDENTIAL_NOT_FOUND",
            "That import credential is no longer held.",
            details={"state": state},
        )
    return credential


def _task_institution(
    request: Request, registry: InstitutionConnectionRegistry, payload: TaskCredentialRequest
) -> Any:
    """The school a task credential is for: by key, or by an exact registered origin.

    A caller cannot submit an arbitrary base URL and have the service talk to it: the address is
    matched against the registry, which is the same rule the OAuth flow follows.
    """
    if payload.institution_key:
        try:
            return registry.by_key(payload.institution_key)
        except UnknownInstitutionError as error:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "CANVAS_INSTITUTION_UNKNOWN",
                "That school is not one this deployment knows.",
            ) from error
    if payload.canvas_base_url:
        try:
            return registry.by_origin(payload.canvas_base_url)
        except UnknownInstitutionError as error:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "CANVAS_INSTITUTION_UNKNOWN",
                "That address is not a school this deployment knows.",
            ) from error
    raise ApiError(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "CANVAS_INSTITUTION_REQUIRED",
        "Name the school this credential belongs to.",
    )


def _record_credential_event(
    request: Request,
    *,
    credential: TaskCredential,
    state: str,
    reason: str = "",
    job_id: str = "",
) -> None:
    """Append the lifecycle receipt. Best effort by design: an audit row must never be the reason
    a credential fails to be destroyed."""
    try:
        with _database(request).connect() as connection:
            CanvasCredentialLifecycleRepository(connection).record(
                credential_ref=credential.credential_ref,
                subject=credential.subject,
                institution_origin=credential.institution_origin,
                state=state,
                reason=reason,
                read_calls=credential.read_calls,
                zeroed_bytes=credential.zeroed_bytes,
                store_instance_id=_task_credential_store(request).instance_id,
                job_id=job_id,
            )
    except Exception:  # noqa: BLE001 - see the docstring
        LOGGER.warning("could not record a Canvas credential lifecycle event")


def _institution_for_origin(
    request: Request, registry: InstitutionConnectionRegistry, origin: str
) -> Any:
    try:
        return registry.by_origin(origin)
    except UnknownInstitutionError as error:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "CONNECTION_INSTITUTION_UNKNOWN",
            "This connection names a school that is no longer configured.",
        ) from error


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
    institution = _institution_for_origin(request, client.registry, stored.origin)
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


def _task_credential_adapter(
    request: Request, user: AuthenticatedUser, credential_ref: str
) -> CanvasReadAdapter:
    """A read-only adapter that reads with a task credential instead of a stored one.

    The token comes from the transient store at call time and nowhere else, so a credential that
    has been destroyed makes the read fail as `EXPIRED_TOKEN` rather than being read from a copy.
    """
    _require_task_credential_owner(request, user)
    store = _task_credential_store(request)
    credential = _owned_task_credential(request, user, credential_ref)
    return _adapter(
        request,
        connection_id=credential.connection_id,
        origin=credential.institution_origin,
        registry=_registry(request),
        token_provider=store.provider(credential_ref),
    )


# ------------------------------------------------------------------------------ availability
@router.get("/institutions")
def list_institutions(
    request: Request, user: Annotated[AuthenticatedUser, Depends(require_user)]
) -> dict[str, Any]:
    """Which schools can be connected right now, and why not when they cannot."""
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
        # A separate answer from `credentialsReady`, which is about the deployment's ability to
        # store an OAuth credential. This one is about the one-off task credential and is scoped
        # to the caller, so the UI can offer it to the owner without offering it to everyone.
        "taskCredential": _task_credential_capability(request, user),
    }


# ------------------------------------------------------------------- task credentials
@router.post("/task-credentials", status_code=status.HTTP_201_CREATED)
def open_task_credential(
    payload: TaskCredentialRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    """Hold a pasted credential for one import task, after proving whose Canvas account it is.

    The identity is read once, with the pasted token, before anything is held: a token that
    belongs to somebody else, or to nobody, must fail here rather than produce a task that stores
    another person's material under this user's name.
    """
    _require_tables(request)
    _require_task_credential_owner(request, user)
    registry = _registry(request)
    institution = _task_institution(request, registry, payload)
    # A personal access token is already a credential for this student's own Canvas account.
    # It does not depend on an institution-issued OAuth Developer Key; the registry entry is
    # still required so the token can only be sent to an allow-listed origin.
    try:
        canvas_user_id, canvas_name = _identity(
            request, institution.origin, registry, payload.personal_access_token
        )
    except CanvasReadError as error:
        # The school refused the token. Reported as the school's answer, and nothing is stored.
        raise _canvas_http_error(error) from error
    if payload.canvas_user_id and payload.canvas_user_id != canvas_user_id:
        # The caller may pin the account it expects; a token that belongs to another account is
        # refused instead of quietly binding the wrong identity.
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "CANVAS_ACCOUNT_MISMATCH",
            "That credential does not belong to the Canvas account this task named.",
        )
    store = _task_credential_store(request)
    connection = Connection(
        connection_id=uuid.uuid4().hex,
        subject=user.user_id,
        institution_key=institution.key,
        origin=institution.origin,
        canvas_user_id=canvas_user_id,
        canvas_name=canvas_name,
        scopes=(),
        saved_for_reuse=False,
        # No encrypted credential is written for a task credential, and these two columns are how
        # a reader can tell: a stored connection always names a key id.
        credential_key_id="",
        credential_expires_at=None,
    )
    with _database(request).connect() as connection_handle:
        # Identity and bookkeeping only. `upsert` is keyed by (owner, origin, canvas user), so a
        # second task for the same account reuses the row instead of accumulating connections.
        connection_id = CanvasConnectionRepository(connection_handle).upsert(
            connection, connection_id=connection.connection_id
        )
    try:
        credential = store.open_task(
            subject=user.user_id,
            connection_id=connection_id,
            institution_key=institution.key,
            institution_origin=institution.origin,
            token=payload.personal_access_token,
            canvas_user_id=canvas_user_id,
            canvas_display_name=canvas_name,
        )
    except CredentialRefused as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "CANVAS_CREDENTIAL_REFUSED",
            str(error),
        ) from error
    _record_credential_event(request, credential=credential, state=PRESENT_TRANSIENTLY)
    return {
        **_public_task_credential(credential),
        "connectionId": connection_id,
        "sameAccountReused": connection_id != connection.connection_id,
    }


@router.get("/task-credentials/{credential_ref}")
def task_credential_state(
    credential_ref: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    """The lifecycle state of one task credential, for the screen that has to explain it."""
    _require_tables(request)
    _require_task_credential_owner(request, user)
    store = _task_credential_store(request)
    credential = store.record(credential_ref)
    if credential is not None and credential.subject == user.user_id:
        return _public_task_credential(credential)
    receipt = store.receipt_for(credential_ref)
    if receipt is not None and receipt["subject"] == user.user_id:
        return {
            "credentialRef": credential_ref,
            "state": receipt["state"],
            "reason": receipt["destroy_reason"],
            "readCalls": receipt["read_calls"],
            "expiresAt": 0.0,
            "hardExpiresAt": 0.0,
        }
    # Never held by this process, or held by a previous one. `reconcile` turns the database's
    # record into the honest current answer: a credential that was live and is not in this
    # process was lost with a restart, and the user has to supply a token again.
    recorded = ""
    with _database(request).connect() as connection:
        row = connection.execute(
            "SELECT credential_state, owner_user_id FROM canvas_import_jobs WHERE credential_ref=?",
            (credential_ref,),
        ).fetchone()
    if row is not None and str(row["owner_user_id"]) == user.user_id:
        recorded = str(row["credential_state"] or "")
    state = store.reconcile(credential_ref, recorded_state=recorded)
    return {"credentialRef": credential_ref, "state": state, "reason": "", "readCalls": 0}


@router.post("/task-credentials/{credential_ref}/forget")
def forget_task_credential(
    credential_ref: str,
    payload: TaskCredentialForget,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    """Destroy the credential now. The user does not have to wait for the task to finish."""
    _require_tables(request)
    _require_task_credential_owner(request, user)
    store = _task_credential_store(request)
    credential = store.record(credential_ref)
    if credential is not None and credential.subject != user.user_id:
        credential = None
    if credential is None:
        return {
            "credentialRef": credential_ref,
            "state": store.state(credential_ref),
            "cleared": False,
        }
    destroyed = store.destroy(credential_ref, reason=payload.reason)
    if destroyed is not None:
        _record_credential_event(
            request, credential=destroyed, state=DESTROYED, reason=payload.reason
        )
    return {
        "credentialRef": credential_ref,
        "state": store.state(credential_ref),
        "cleared": True,
        "readCalls": destroyed.read_calls if destroyed is not None else 0,
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
        # the lookup is by user and institution 鈥?not by the account id that has no row yet.
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
    credential_ref: Annotated[str, Query(max_length=64)] = "",
    include_file_summary: bool = False,
) -> dict[str, Any]:
    """The student's own readable courses, for the import selection screen.

    Reading this list *is* one of the Canvas reads the owner authorised, so it goes through the
    transient credential when the caller names one, and through the stored connection otherwise.
    """
    if credential_ref:
        adapter = _task_credential_adapter(request, user, credential_ref)
    else:
        adapter, _stored = _connection_adapter(request, user, connection_id)
    try:
        courses = adapter.student_courses()
    except CanvasReadError as error:
        raise _canvas_http_error(error) from error
    import_status: dict[str, str] = {}
    if include_file_summary:
        with _database(request).connect() as connection:
            rows = connection.execute(
                "SELECT course_ids_json,status FROM canvas_import_jobs "
                "WHERE owner_user_id=? AND connection_id=? ORDER BY created_at DESC",
                (user.user_id, connection_id),
            ).fetchall()
        for row in rows:
            for course_id in json.loads(str(row["course_ids_json"])):
                import_status.setdefault(str(course_id), str(row["status"]))
    public_courses = []
    for course in courses:
        public = {
            "id": course.id,
            "name": course.name,
            "courseCode": course.course_code,
            "term": course.term,
            "workflowState": course.workflow_state,
            "readable": course.is_readable_history,
        }
        if include_file_summary:
            try:
                files = adapter.course_files(course.id) if course.is_readable_history else []
                public.update(
                    {
                        "fileCount": len(files),
                        "expectedBytes": sum(max(0, item.size) for item in files),
                        "accessibility": (
                            "READABLE" if course.is_readable_history else "NOT_READABLE"
                        ),
                    }
                )
            except CanvasReadError as error:
                if error.category == EXPIRED_TOKEN:
                    raise _canvas_http_error(error) from error
                public.update(
                    {
                        "fileCount": None,
                        "expectedBytes": None,
                        "accessibility": error.category,
                    }
                )
            public["importStatus"] = import_status.get(course.id, "NOT_IMPORTED")
        public_courses.append(public)
    return {
        "courses": public_courses
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
    credential_ref = payload.credential_ref
    if credential_ref:
        # The job borrows this task's credential, so the credential has to be alive and belong to
        # this user at the moment the job is created. A stale reference is refused here rather
        # than becoming a job that can never read anything.
        _require_task_credential_owner(request, user)
        _owned_task_credential(request, user, credential_ref)
    job = new_job(
        job_id=uuid.uuid4().hex,
        connection_id=stored.connection_id,
        subject=user.user_id,
        institution_origin=stored.origin,
        course_ids=course_ids,
        credential_ref=credential_ref,
        credential_kind=(
            CREDENTIAL_KIND_TRANSIENT_TASK if credential_ref else CREDENTIAL_KIND_CONNECTION
        ),
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
        "credentialKind": str(row["credential_kind"]) if row else "connection",
        "credentialState": str(row["credential_state"]) if row else "NEVER_STORED",
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
    # What the screen needs in order to tell the user the truth about the credential: it is gone
    # (`DESTROYED`/`EXPIRED`), it was lost with a restart, or it is still held for this task's
    # remaining Canvas reads. `needsCredential` says whether an import that is not finished
    # cannot proceed without a new token.
    credential_ref = str(row["credential_ref"] or "")
    recorded_state = str(row["credential_state"] or "")
    if credential_ref:
        credential_state = _task_credential_store(request).reconcile(
            credential_ref, recorded_state=recorded_state
        )
    else:
        credential_state = recorded_state or "NEVER_STORED"
    job_status = str(row["status"])
    return {
        "jobId": job_id,
        "status": job_status,
        "errorCode": str(row["error_code"] or ""),
        "errorMessage": str(row["error_message"] or ""),
        "targetCourseId": str(row["target_course_id"] or ""),
        "courses": len(json.loads(str(row["course_ids_json"]))),
        "files": len(files),
        "byStatus": counts,
        "credentialKind": str(row["credential_kind"] or "connection"),
        "credentialState": credential_state,
        "needsCredential": bool(
            str(row["credential_kind"]) == CREDENTIAL_KIND_TRANSIENT_TASK
            and job_status not in TERMINAL_STATES
            and credential_state in (DESTROYED, EXPIRED, LOST_ON_RESTART)
        ),
    }


@router.post("/imports/{job_id}/credential")
def resume_import_credential(
    job_id: str,
    payload: TaskCredentialRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    """Replace a lost task credential without changing the frozen course selection."""

    _require_tables(request)
    _require_task_credential_owner(request, user)
    with _database(request).connect() as connection:
        repository = CanvasJobRepository(connection)
        row = repository.snapshot(job_id)
        if row is None or str(row["owner_user_id"]) != user.user_id:
            raise ApiError(status.HTTP_404_NOT_FOUND, "JOB_NOT_FOUND", "That import was not found.")
        if str(row["credential_kind"]) != CREDENTIAL_KIND_TRANSIENT_TASK:
            raise ApiError(
                409,
                "CANVAS_CREDENTIAL_KIND_MISMATCH",
                "That import does not use a task credential.",
            )
        if str(row["status"]) in {"COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "CANCELLED"}:
            raise ApiError(409, "CANVAS_IMPORT_NOT_RESUMABLE", "That import cannot be resumed.")
        stored = CanvasConnectionRepository(connection).get(
            str(row["connection_id"]), subject=user.user_id
        )
    if stored is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "CONNECTION_NOT_FOUND",
            "That Canvas connection was not found.",
        )
    institution = _task_institution(request, _registry(request), payload)
    if institution.origin != str(row["institution_origin"]):
        raise ApiError(
            409,
            "CANVAS_INSTITUTION_MISMATCH",
            "Use the same Canvas school as the frozen import.",
        )
    try:
        canvas_user_id, canvas_name = _identity(
            request, institution.origin, _registry(request), payload.personal_access_token
        )
    except CanvasReadError as error:
        raise _canvas_http_error(error) from error
    if canvas_user_id != stored.canvas_user_id:
        raise ApiError(
            409,
            "CANVAS_ACCOUNT_MISMATCH",
            "Use the same Canvas account as the frozen import.",
        )
    try:
        credential = _task_credential_store(request).open_task(
            subject=user.user_id,
            connection_id=stored.connection_id,
            institution_key=institution.key,
            institution_origin=institution.origin,
            token=payload.personal_access_token,
            canvas_user_id=canvas_user_id,
            canvas_display_name=canvas_name,
        )
    except CredentialRefused as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "TASK_CREDENTIAL_REFUSED",
            str(error),
        ) from error
    with _database(request).connect() as connection:
        rebound = CanvasJobRepository(connection).resume_with_transient_credential(
            job_id, credential.credential_ref
        )
    if not rebound:
        _task_credential_store(request).destroy(credential.credential_ref, reason="resume_refused")
        raise ApiError(409, "CANVAS_IMPORT_NOT_RESUMABLE", "That import cannot be resumed.")
    _record_credential_event(
        request,
        credential=credential,
        state=PRESENT_TRANSIENTLY,
        reason="resume_after_credential_loss",
        job_id=job_id,
    )
    return {
        "jobId": job_id,
        "credentialRef": credential.credential_ref,
        "credentialState": PRESENT_TRANSIENTLY,
        "status": QUEUED,
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
        credential_ref = str(row["credential_ref"] or "")
        if str(row["credential_kind"]) == CREDENTIAL_KIND_TRANSIENT_TASK and credential_ref:
            destroyed = _task_credential_store(request).destroy(
                credential_ref, reason="task_cancelled"
            )
            if destroyed is not None:
                repository.set_credential_state(job_id, DESTROYED)
                _record_credential_event(
                    request,
                    credential=destroyed,
                    state=DESTROYED,
                    reason="task_cancelled",
                    job_id=job_id,
                )
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
