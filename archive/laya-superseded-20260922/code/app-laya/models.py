"""Internal request/response model for the Laya semantic-decision adapter.

These dataclasses are the frozen cross-workstream interface. The ``kind`` field uses
the lowercase names the self-hosted Laya service speaks (``choice`` / ``score`` /
``noul``), matching the official ``RLAgent.system_one(state, questions)`` entry
point. Nothing here imports ``typesafe_sdk`` or reads a TypeSafe credential.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal["choice", "score", "noul"]

KINDS = frozenset({"choice", "score", "noul"})

# Official HF snapshot: convaiinnovations/laya @ multilingual.
DEFAULT_MODEL_REVISION = "1c5edc17a7acd8701df6fc341c0d179f1c62c982"
DEFAULT_COMPILER_VERSION = "1.0.0"


@dataclass(frozen=True)
class LayaQuestion:
    """One question handed to the Laya service.

    ``criteria`` shape is primitive-specific and is passed through verbatim:
    choice -> ``{option_id: description}``, score -> ``[level_description, ...]``,
    noul -> ``None`` (the service renders noul options as ``[false, true]``).
    """

    kind: Kind
    instructions: str
    criteria: dict[str, str] | list[str] | None = None

    def option_count(self) -> int:
        if self.kind == "choice":
            if isinstance(self.criteria, dict):
                return len(self.criteria)
            return len(self.criteria or ())
        if self.kind == "score":
            return len(self.criteria) if self.criteria is not None else 0
        return 2  # noul options are always [false, true]


@dataclass(frozen=True)
class LayaRequest:
    """Everything the Laya service needs for one decision.

    ``deadline_ms`` is an absolute wall-clock epoch-ms bound; a reply arriving after
    it must be discarded, never applied to a newer business request.
    """

    definition_id: str
    definition_version: str
    state: dict[str, Any]
    questions: dict[str, LayaQuestion]
    deadline_ms: int
    request_id: str
    compiler_version: str
    model_revision: str


@dataclass(frozen=True)
class LayaAnswer:
    """A typed answer for one question.

    ``confidence`` is always surfaced with ``confidence_kind="distribution_concentration"``
    (1 - normalized entropy of the recorded probabilities); it is never a ``p_correct``.
    Noul answers carry ``noul`` = P(true) and no confidence (0.0 is a sentinel, not a value).
    """

    kind: Kind
    choice: str | None = None
    score: float | None = None
    noul: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    confidence_kind: str = "distribution_concentration"
    legend: dict[str, str] | None = None
    act_probability: float | None = None


@dataclass(frozen=True)
class LayaDiagnostics:
    """Per-call diagnostics recorded with the reply.

    Model-internal flags (``truncated_state`` / ``truncated_head`` /
    ``options_shortened`` / ``per_option_tokens``) are not observable from the
    client side of the HTTP boundary and default to ``False`` / ``[]``; the
    inference-service owner may enrich them later. ``content_hash`` covers the full
    request (definition id+version, state, questions) and matches the receipt
    ``input_hash``.
    """

    input_tokens: int
    truncated_state: bool
    truncated_head: bool
    options_shortened: bool
    per_option_tokens: list[int]
    option_count: int
    retained_chars: int
    content_hash: str
    deadline_ms: int
    model_revision: str
    compiler_version: str


@dataclass(frozen=True)
class LayaReply:
    """A transport reply: one answer per requested question id plus diagnostics."""

    provider: str = "laya"
    answers: dict[str, LayaAnswer] = field(default_factory=dict)
    diagnostics: LayaDiagnostics | None = None
    latency_ms: float = 0.0
    model_revision: str = ""
    status: str = "ok"


@dataclass(frozen=True)
class LayaScope:
    """The authorization/course/version dimensions bounding a cached suggestion.

    Mirrors the Jev cache-scope keys: a cached suggestion is only reused when every
    dimension in scope matches, and ``model_revision`` (from ``LayaRequest``) is the
    provider-model-version dimension.
    """

    owner_scope_hash: str | None = None
    course_id: str | None = None
    workspace_id: str | None = None
    material_revision: str | None = None
    node_id: str | None = None
    spec_version: str | None = None
    question_hash: str | None = None
    input_hash: str | None = None


def request_content_hash(
    definition_id: str,
    definition_version: str,
    state: dict[str, Any],
    questions: dict[str, LayaQuestion],
) -> str:
    """Stable digest of a full request (definition + state + questions).

    Distinct from ``app.laya.compiler.content_hash`` (the input-compiler workstream's
    provenance hash over ``(decision_key, primitive, instructions, criteria, state)``).
    """
    canonical_questions = {
        str(qid): {
            "kind": q.kind,
            "instructions": q.instructions,
            "criteria": _canonical(q.criteria),
        }
        for qid, q in sorted(questions.items(), key=lambda kv: str(kv[0]))
    }
    payload = {
        "definition_id": definition_id,
        "definition_version": definition_version,
        "state": _canonical(state),
        "questions": canonical_questions,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, bool):
        return 1 if value else 0
    return value
