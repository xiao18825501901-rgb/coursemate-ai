"""ToolIntentCheck: the fixed-order guard for model-proposed, side-effecting tool calls.

This module answers one question: *is this side-effecting tool call actually
authorized by the user's own message, or did the model invent it?*  It is a guard
around the original tool execution, never a replacement for it, and it never grants
a permission the actor does not already hold.

The order is fixed and nothing may skip it::

    1. schema + permission checks              (code, deterministic)
    2. optional Jev intent check                (``tool.intent.v1``, only when needed)
    3. re-check permission and object revision  (code, immediately before execution)
    4. the original tool executes               (the caller, only on ALLOW)

Deterministic guarantees (all enforced here, none delegated to Jev):

* a pure read never needs the intent check and never gains an approval dialog;
* an explicitly legitimate action (deterministic button + schema-validated +
  permission already held) is allowed with zero Jev calls and no new dialog;
* a side-effecting call whose required permissions the actor does not hold is
  refused in code before Jev is ever reached — a ``CONSISTENT`` verdict is an intent
  signal only, never an authorization;
* instructions found inside documents or tool output are never user authorization:
  the only authorization input Jev ever sees is the user's own ``user_message``
  (plus the proposed tool, its arguments and the actor scope — the tool arguments
  are forwarded so Jev can see *what* the call would do, not *who authorized it*);
* if the object revision changed between the intent check and execution, the stale
  judgement is never used — the call is refused and must be re-checked;
* ``INCONSISTENT_WITH_INTENT`` / ``AMBIGUOUS`` / unavailable always require
  confirmation for the side effect — never auto-allow, and plain chat never fails
  (the caller still answers the user's message; only the write is held).

The highest reasoning tier does not regain a dollar-risk gate: the permission and
revision re-checks run unconditionally for every side-effecting call, independent of
reasoning strength.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from app.jev.catalog import load_catalog
from app.jev.gateway import DecisionRequest
from app.jev.models import CacheScope, owner_scope_hash
from app.jev.service import SemanticDecisionService

TOOL_INTENT_KEY: Final = "tool.intent.v1"

CONSISTENT: Final = "CONSISTENT"
INCONSISTENT_WITH_INTENT: Final = "INCONSISTENT_WITH_INTENT"
AMBIGUOUS: Final = "AMBIGUOUS"
_INTENT_LABELS: Final = frozenset({CONSISTENT, INCONSISTENT_WITH_INTENT, AMBIGUOUS})

# Verdict outcomes returned to the caller.
ALLOW: Final = "ALLOW"
REQUIRE_CONFIRMATION: Final = "REQUIRE_CONFIRMATION"
REFUSE_UNAUTHORIZED: Final = "REFUSE_UNAUTHORIZED"
REFUSE_STALE: Final = "REFUSE_STALE"


@dataclass(frozen=True)
class ToolIntentResult:
    """The guard's verdict: whether the original tool may execute, and why."""

    verdict: str
    reason: str
    used_jev: bool = False
    jev_label: str | None = None
    receipt_id: str | None = None
    path: str = "deterministic"
    jev_calls: int = 0


def _has_permission(actor: frozenset[str], required: frozenset[str]) -> bool:
    return required <= actor


def _revision_changed(object_revision: str | None, current_revision: str | None) -> bool:
    return (
        object_revision is not None
        and current_revision is not None
        and object_revision != current_revision
    )


def needs_intent_check(*, is_read_only: bool, explicit: bool) -> bool:
    """Deterministic predicate: only model-proposed side-effecting calls need Jev.

    A pure read never needs the check; an explicitly legitimate action (deterministic
    button) never gains a new approval dialog.  The highest reasoning tier does not
    change this: the predicate is tier-independent.
    """
    return (not is_read_only) and (not explicit)


def build_tool_intent_scope(
    owner_user_id: str,
    authorization_scope: str,
    *,
    course_id: str | None = None,
    workspace_id: str | None = None,
    material_revision: str | None = None,
    node_id: str | None = None,
    spec_version: int | str | None = None,
) -> CacheScope:
    """Build the genuinely-scoped :class:`CacheScope` the gateway's receipt needs.

    ``owner_scope_hash`` is server-derived (``owner_user_id`` + ``authorization_scope``)
    and never client-supplied, so two owners can never share a cached judgement, and a
    private scope can never hash the same as a public one.
    """
    return CacheScope(
        owner_scope_hash=owner_scope_hash(owner_user_id, authorization_scope),
        course_id=course_id,
        workspace_id=workspace_id,
        material_revision=material_revision,
        node_id=node_id,
        spec_version=str(spec_version) if spec_version is not None else None,
    )


class ToolIntentCheck:
    """The single guard for side-effecting tool-call intent."""

    def __init__(self, service: SemanticDecisionService | None) -> None:
        self.service = service

    def authorize(
        self,
        *,
        user_message: str,
        proposed_tool: str,
        tool_arguments: dict[str, Any],
        actor_scope: str,
        actor_permissions: frozenset[str],
        required_permissions: frozenset[str],
        is_read_only: bool = False,
        explicit: bool = False,
        object_revision: str | None = None,
        current_revision: str | None = None,
        owner_user_id: str,
        authorization_scope: str,
        course_id: str | None = None,
        workspace_id: str | None = None,
        material_revision: str | None = None,
        node_id: str | None = None,
        spec_version: int | str | None = None,
    ) -> ToolIntentResult:
        """Run the fixed-order guard and return whether the original tool may execute.

        ``owner_user_id``/``authorization_scope`` scope the Jev receipt (server-derived
        and never client-supplied), so a CONSISTENT verdict can never be reused across
        owners and a private scope can never hash the same as a public one.
        """

        # 1. Schema + permission checks (code).  Pure reads and explicit actions never
        #    reach Jev and never gain a new approval dialog.
        if is_read_only:
            return ToolIntentResult(ALLOW, "read_only", path="deterministic:read_only")
        if explicit:
            if not _has_permission(actor_permissions, required_permissions):
                return ToolIntentResult(
                    REFUSE_UNAUTHORIZED, "missing_permission",
                    path="deterministic:missing_permission",
                )
            if _revision_changed(object_revision, current_revision):
                return ToolIntentResult(
                    REFUSE_STALE, "revision_changed", path="deterministic:revision_changed"
                )
            return ToolIntentResult(ALLOW, "explicit", path="deterministic:explicit")

        # A side-effecting model-proposed call: the permission gate runs in code before
        # Jev, so a CONSISTENT verdict can never grant a permission the actor lacked.
        if not _has_permission(actor_permissions, required_permissions):
            return ToolIntentResult(
                REFUSE_UNAUTHORIZED, "missing_permission",
                path="deterministic:missing_permission",
            )

        # 2. Optional Jev intent check over the user's own message only, in a
        #    genuinely-scoped cache scope so the receipt is never owner-less.
        scope = build_tool_intent_scope(
            owner_user_id,
            authorization_scope,
            course_id=course_id,
            workspace_id=workspace_id,
            material_revision=material_revision,
            node_id=node_id,
            spec_version=spec_version,
        )
        label, used, receipt_id, made = self._evaluate_intent(
            user_message=user_message,
            proposed_tool=proposed_tool,
            tool_arguments=tool_arguments,
            actor_scope=actor_scope,
            scope=scope,
        )
        jev_calls = 1 if made else 0

        if label != CONSISTENT:
            reason = f"intent:{label}" if label is not None else "intent:unavailable"
            return ToolIntentResult(
                REQUIRE_CONFIRMATION,
                reason,
                used_jev=used,
                jev_label=label,
                receipt_id=receipt_id,
                path="fallback:require_confirmation",
                jev_calls=jev_calls,
            )

        # 3. Re-check permission and object revision immediately before execution.
        #    A stale judgement is never used.
        if not _has_permission(actor_permissions, required_permissions):
            return ToolIntentResult(
                REFUSE_UNAUTHORIZED,
                "missing_permission_on_recheck",
                used_jev=used,
                jev_label=label,
                receipt_id=receipt_id,
                path="fallback:missing_permission_on_recheck",
                jev_calls=jev_calls,
            )
        if _revision_changed(object_revision, current_revision):
            return ToolIntentResult(
                REFUSE_STALE,
                "revision_changed",
                used_jev=used,
                jev_label=label,
                receipt_id=receipt_id,
                path="fallback:revision_changed",
                jev_calls=jev_calls,
            )

        # 4. The original tool executes (the caller runs it on ALLOW).
        return ToolIntentResult(
            ALLOW,
            "intent_consistent",
            used_jev=used,
            jev_label=label,
            receipt_id=receipt_id,
            path="jev",
            jev_calls=jev_calls,
        )

    def _evaluate_intent(
        self,
        *,
        user_message: str,
        proposed_tool: str,
        tool_arguments: dict[str, Any],
        actor_scope: str,
        scope: CacheScope,
    ) -> tuple[str | None, bool, str | None, bool]:
        """Run ``tool.intent.v1`` over the four required fields."""
        service = self.service
        if service is None:
            return (None, False, None, False)
        definition = load_catalog().get(TOOL_INTENT_KEY)
        criteria = {
            CONSISTENT: "The user's own message authorizes this action",
            INCONSISTENT_WITH_INTENT: "The user asked something else",
            AMBIGUOUS: "The message does not settle the write",
        }
        state: dict[str, Any] = {
            "user_message": user_message,
            "proposed_tool": proposed_tool,
            "tool_arguments": tool_arguments,
            "actor_scope": actor_scope,
        }
        request = DecisionRequest(
            definition=definition,
            state=state,
            caller_role="tool_intent",
            cache_scope=scope,
            criteria=criteria,
        )
        decision = service.gateway.evaluate(request)
        used = decision.mode == "on" and decision.suggestion is not None
        label: str | None = None
        if (
            used
            and decision.suggestion is not None
            and decision.suggestion.choice in _INTENT_LABELS
        ):
            label = decision.suggestion.choice
        return (label, used, decision.receipt_id, True)


def authorize_tool_intent(
    service: SemanticDecisionService | None,
    *,
    user_message: str,
    proposed_tool: str,
    tool_arguments: dict[str, Any],
    actor_scope: str,
    actor_permissions: frozenset[str],
    required_permissions: frozenset[str],
    is_read_only: bool = False,
    explicit: bool = False,
    object_revision: str | None = None,
    current_revision: str | None = None,
    owner_user_id: str,
    authorization_scope: str,
    course_id: str | None = None,
    workspace_id: str | None = None,
    material_revision: str | None = None,
    node_id: str | None = None,
    spec_version: int | str | None = None,
) -> ToolIntentResult:
    """Module-level convenience wrapper over :meth:`ToolIntentCheck.authorize`."""
    return ToolIntentCheck(service).authorize(
        user_message=user_message,
        proposed_tool=proposed_tool,
        tool_arguments=tool_arguments,
        actor_scope=actor_scope,
        actor_permissions=actor_permissions,
        required_permissions=required_permissions,
        is_read_only=is_read_only,
        explicit=explicit,
        object_revision=object_revision,
        current_revision=current_revision,
        owner_user_id=owner_user_id,
        authorization_scope=authorization_scope,
        course_id=course_id,
        workspace_id=workspace_id,
        material_revision=material_revision,
        node_id=node_id,
        spec_version=spec_version,
    )


__all__ = [
    "ALLOW",
    "AMBIGUOUS",
    "CONSISTENT",
    "INCONSISTENT_WITH_INTENT",
    "REFUSE_STALE",
    "REFUSE_UNAUTHORIZED",
    "REQUIRE_CONFIRMATION",
    "TOOL_INTENT_KEY",
    "ToolIntentCheck",
    "ToolIntentResult",
    "authorize_tool_intent",
    "build_tool_intent_scope",
    "needs_intent_check",
]
