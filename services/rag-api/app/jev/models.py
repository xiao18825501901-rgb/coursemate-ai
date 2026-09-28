"""Internal request/response model for the Jev gateway.

This is deliberately independent of the TypeSafe SDK. The SDK adapter
(:class:`app.jev.gateway.SdkTransport`) is the only place that touches the
third-party types, and it is written exclusively from the verified signature
(``TypeSafeClient.system_one(state, questions)`` with ``Choice``/``Noul``/
``Score`` question objects). Nothing here invents an endpoint, model id, limit
or payload field.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class JevQuestion:
    """One question handed to a transport (mirrors the SDK question types)."""

    key: str
    primitive: str  # Choice | Noul | Score
    instructions: str
    # Choice: {option_id: description}; Score: [level_description, ...]; Noul: None.
    criteria: dict[str, str] | list[str] | None = None


@dataclass(frozen=True)
class JevCall:
    """A single transport call: one shared state, one or more questions."""

    state: dict[str, Any]
    questions: dict[str, JevQuestion]
    # Server-derived transport context.  It is never accepted from a browser
    # and is excluded from the semantic state passed to the model.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class JevAnswer:
    """A validated, typed answer for one question."""

    choice: str | None = None
    noul: float | None = None
    score: str | None = None  # Score level key, e.g. "0".."4"
    probability: float | None = None
    # The Score primitive's own numeric value when the provider answered with a decimal on the
    # definition's scale instead of a level key — measured live: `3.99` on a 0..4 definition, `2.0`
    # on a 0..2 one. It is carried unmodified and `score` stays None, because which level a `3.99`
    # is depends on boundaries the catalogue has not calibrated yet. Consumers that can use a
    # continuous value (reranking does) read this; consumers that need a level wait for the
    # calibration rather than being handed a guess.
    score_value: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class JevResult:
    """A transport result for a call."""

    answers: dict[str, JevAnswer]
    request_id: str | None = None
    model_version: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CacheScope:
    """The authorization/course/version dimensions that bound a cached suggestion.

    ``owner_scope_hash`` is a server-derived digest of (owner user id,
    authorization scope) — never a client-supplied value — so a cached suggestion
    can never be reused across owner scopes.
    """

    owner_scope_hash: str | None = None
    course_id: str | None = None
    workspace_id: str | None = None
    material_revision: str | None = None
    node_id: str | None = None
    spec_version: str | None = None
    question_hash: str | None = None
    input_hash: str | None = None
    provider_model_version: str | None = None


def owner_scope_hash(owner_user_id: str, scope: str) -> str:
    """Server-derived digest identifying one authorization scope for one owner."""
    return hashlib.sha256(f"{owner_user_id}\x00{scope}".encode()).hexdigest()


def input_hash(definition_key: str, state: dict[str, Any]) -> str:
    """Stable digest of a decision's definition + authorized inputs."""
    canonical = {"key": definition_key, "state": _canonical(state)}
    payload = _encode(canonical)
    return hashlib.sha256(payload.encode()).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def _encode(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
