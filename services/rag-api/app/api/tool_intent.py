"""Internal HTTP endpoint for the Jev tool-intent guard (``tool.intent.v1``).

This is the token-authenticated, internal surface the Node agent service calls at
the real execution boundary to decide whether a model-proposed, side-effecting
tool call is actually authorized by the user's own message. It is a thin wrapper
around :class:`app.jev.tool_intent.ToolIntentCheck`; the guard (already finished
and tested) owns every semantic decision. This route only:

* authenticates the caller with a constant-time token comparison (never logging or
  echoing the token);
* bounds the request body so a caller cannot blow up the Jev state payload;
* resolves the one shared semantic-decision layer — it never builds a second
  gateway while the shared layer exists;
* writes NOTHING except the Jev receipt the guard itself records inside the gate.

Router registration is applied by the owning workstream in ``app/main.py`` (this
module must NOT edit it):

    from app.api.tool_intent import router as tool_intent_router  # next to feedback import
    application.include_router(tool_intent_router)               # next to feedback include
"""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.errors import ApiError
from app.jev.gateway import JevGateway
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService
from app.jev.tool_intent import ToolIntentCheck

router = APIRouter()

_INTERNAL_TOKEN_ENV = "JEV_TOOL_INTENT_TOKEN"
_INTERNAL_TOKEN_HEADER = "X-CourseMate-Internal-Token"

_MAX_USER_MESSAGE = 8_000
_MAX_PROPOSED_TOOL = 200
_MAX_TOOL_ARGUMENT_KEYS = 64
_MAX_TOOL_ARGUMENTS_CHARS = 12_000
_MAX_ACTOR_SCOPE = 64
_MAX_PERMISSIONS = 32
_MAX_PERMISSION = 128
_MAX_REVISION = 200
_MAX_IDENTIFIER = 128
_MAX_SCOPE_IDENTIFIER = 200

Permission = Annotated[str, StringConstraints(max_length=_MAX_PERMISSION)]


class ToolIntentRequest(BaseModel):
    """Bounded payload for one tool-intent authorization decision."""

    user_message: str = Field(max_length=_MAX_USER_MESSAGE)
    proposed_tool: str = Field(max_length=_MAX_PROPOSED_TOOL)
    tool_arguments: dict[str, object] = Field(max_length=_MAX_TOOL_ARGUMENT_KEYS)
    actor_scope: str = Field(max_length=_MAX_ACTOR_SCOPE)
    actor_permissions: list[Permission] = Field(max_length=_MAX_PERMISSIONS)
    required_permissions: list[Permission] = Field(max_length=_MAX_PERMISSIONS)
    is_read_only: bool = False
    explicit: bool = False
    object_revision: str | None = Field(default=None, max_length=_MAX_REVISION)
    current_revision: str | None = Field(default=None, max_length=_MAX_REVISION)
    owner_user_id: str = Field(max_length=_MAX_IDENTIFIER)
    authorization_scope: str = Field(max_length=_MAX_IDENTIFIER)
    course_id: str | None = Field(default=None, max_length=_MAX_SCOPE_IDENTIFIER)
    workspace_id: str | None = Field(default=None, max_length=_MAX_SCOPE_IDENTIFIER)
    material_revision: str | None = Field(default=None, max_length=_MAX_SCOPE_IDENTIFIER)
    node_id: str | None = Field(default=None, max_length=_MAX_SCOPE_IDENTIFIER)
    spec_version: str | None = Field(default=None, max_length=_MAX_SCOPE_IDENTIFIER)

    @model_validator(mode="after")
    def _bound_tool_arguments_size(self) -> ToolIntentRequest:
        size = len(json.dumps(self.tool_arguments, ensure_ascii=False, default=str))
        if size > _MAX_TOOL_ARGUMENTS_CHARS:
            raise ValueError(
                f"tool_arguments exceeds the {_MAX_TOOL_ARGUMENTS_CHARS}-character bound"
            )
        return self


def require_internal_token(
    x_coursemate_internal_token: Annotated[
        str | None, Header(alias=_INTERNAL_TOKEN_HEADER)
    ] = None,
) -> None:
    """Authenticate an internal caller with a constant-time token comparison.

    A missing/blank configured token means the endpoint is disabled (503); a
    mismatched header is an authentication failure (401). The token is never
    logged or echoed.
    """
    expected = os.environ.get(_INTERNAL_TOKEN_ENV)
    if not expected:
        raise ApiError(
            503,
            "INTERNAL_ENDPOINT_DISABLED",
            "The tool-intent internal endpoint is disabled on this deployment.",
        )
    provided = x_coursemate_internal_token
    if provided is None or not hmac.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    ):
        raise ApiError(
            401,
            "INVALID_INTERNAL_TOKEN",
            "The internal token is missing or incorrect.",
        )


def _resolve_service(request: Request) -> SemanticDecisionService:
    existing: SemanticDecisionService | None = getattr(
        request.app.state, "jev_service", None
    )
    if existing is not None:
        return existing
    return SemanticDecisionService(
        JevGateway(receipt_store=SqlReceiptStore(request.app.state.database))
    )


@router.post("/api/jev/tool-intent")
def tool_intent(
    payload: ToolIntentRequest,
    request: Request,
    _authenticated: Annotated[None, Depends(require_internal_token)],
) -> dict[str, Any]:
    service = _resolve_service(request)
    result = ToolIntentCheck(service).authorize(
        user_message=payload.user_message,
        proposed_tool=payload.proposed_tool,
        tool_arguments=payload.tool_arguments,
        actor_scope=payload.actor_scope,
        actor_permissions=frozenset(payload.actor_permissions),
        required_permissions=frozenset(payload.required_permissions),
        is_read_only=payload.is_read_only,
        explicit=payload.explicit,
        object_revision=payload.object_revision,
        current_revision=payload.current_revision,
        owner_user_id=payload.owner_user_id,
        authorization_scope=payload.authorization_scope,
        course_id=payload.course_id,
        workspace_id=payload.workspace_id,
        material_revision=payload.material_revision,
        node_id=payload.node_id,
        spec_version=payload.spec_version,
    )
    return asdict(result)
