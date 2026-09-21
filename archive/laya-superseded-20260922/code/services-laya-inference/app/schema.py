"""Request/response models for the CourseMate-internal Laya API.

This is a CourseMate-internal contract. It is NOT byte-compatible with any
third-party API (not the Laya SDK, not TypeSafe Jev). The ``answers`` field
preserves the Laya ``system_one``/``predict`` answer shapes verbatim; everything
around it is the server's own envelope.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Typed failure statuses. A client can always branch on ``status`` to degrade
# deterministically; the status field is authoritative, the HTTP code is advisory.
Status = Literal[
    "OK",
    "MODEL_NOT_READY",
    "QUEUE_FULL",
    "DEADLINE_EXCEEDED",
    "UNSUPPORTED_DEFINITION",
    "INPUT_TOO_LONG",
    "INVALID_REQUEST",
    "INFERENCE_ERROR",
]

QuestionType = Literal["choice", "score", "noul"]

# Maximum sizes mirror Settings defaults; kept here so the schema never lets a
# structurally enormous body through before the settings layer sees it.
_MAX_ID_LEN = 128
_MAX_STATE_CHARS = 200_000
_MAX_INSTRUCTION_CHARS = 2_000


class Question(BaseModel):
    """One typed decision question, mirroring the Laya ``system_one`` input shape."""

    type: QuestionType
    instructions: str | list[Any]
    criteria: dict[str, str | None] | list[str] | None = None

    @field_validator("instructions")
    @classmethod
    def _instructions_size(cls, v: str | list[Any]) -> str | list[Any]:
        text = v if isinstance(v, str) else repr(v)
        if len(text) > _MAX_INSTRUCTION_CHARS:
            raise ValueError("instructions too long")
        return v

    @field_validator("criteria")
    @classmethod
    def _criteria_size(cls, v: object) -> object:
        if isinstance(v, dict) and len(v) > 256:
            raise ValueError("too many criteria")
        if isinstance(v, list) and len(v) > 256:
            raise ValueError("too many criteria")
        return v


class DecisionRequest(BaseModel):
    """A single decision to evaluate against the resident multilingual checkpoint."""

    request_id: str = Field(min_length=1, max_length=_MAX_ID_LEN)
    decision_definition_id: str = Field(min_length=1, max_length=_MAX_ID_LEN)
    definition_version: str = Field(min_length=1, max_length=64)
    compiled_state: str | dict[str, Any] | list[Any]
    questions: dict[str, Question]
    deadline_ms: float = Field(gt=0)
    model_revision: str = Field(min_length=1, max_length=64)
    compiler_version: str = Field(min_length=1, max_length=64)

    @field_validator("request_id")
    @classmethod
    def _request_id_charset(cls, v: str) -> str:
        # Reuse the logging charset guard so an id we log is always safe.
        from app.logging import safe_id

        try:
            return safe_id(v)
        except ValueError as exc:  # pragma: no cover - thin re-raise
            raise ValueError(str(exc)) from exc

    @field_validator("deadline_ms")
    @classmethod
    def _deadline_finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("deadline_ms must be finite")
        return v

    @field_validator("compiled_state")
    @classmethod
    def _state_size(cls, v: str | dict[str, Any] | list[Any]) -> str | dict[str, Any] | list[Any]:
        length = len(v) if isinstance(v, str) else len(repr(v))
        if length > _MAX_STATE_CHARS:
            raise ValueError("compiled_state too large")
        return v

    @field_validator("questions")
    @classmethod
    def _question_count(cls, v: dict[str, Question]) -> dict[str, Question]:
        if not v:
            raise ValueError("questions must not be empty")
        if len(v) > 100:
            raise ValueError("too many questions")
        return v


class ErrorDetail(BaseModel):
    code: str
    message: str


class ModelRevisionInfo(BaseModel):
    """Identity of the resident model/SDK/tokenizer, surfaced in every decision."""

    model_name: str
    model_revision: str
    sdk_version: str
    tokenizer_revision: str
    encoder: str
    max_len: int
    head_max_len: int
    vocab_size: int | None = None
    backend: str


class DecisionResponse(BaseModel):
    """Envelope returned for every decision attempt, success or failure."""

    request_id: str
    receipt_id: str
    status: Status
    error: ErrorDetail | None = None
    answers: dict[str, Any] | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    model: ModelRevisionInfo | None = None
    timings: dict[str, float] = Field(default_factory=dict)
    calibration_version: str = "none"


class HealthResponse(BaseModel):
    status: Literal["alive", "ready", "not_ready"]
    backend: str | None = None
    error: str | None = None


class ModelInfoResponse(BaseModel):
    model: ModelRevisionInfo
    ready: bool
    calibration_version: str
    real_inference: bool
    load_error: str | None = None
