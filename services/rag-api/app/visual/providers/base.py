from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class RendererTemporarilyUnavailable(RuntimeError):
    """The gateway proved that a request was rejected before provider execution."""

    def __init__(self, code: str, *, status_code: int, safe_to_retry: bool) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.safe_to_retry = safe_to_retry


class ProviderState(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProviderJob:
    id: str


@dataclass(frozen=True)
class ProviderStatus:
    state: ProviderState
    error_code: str | None = None


@dataclass(frozen=True)
class ProviderResult:
    content: bytes
    mime_type: str
    width: int | None
    height: int | None
    duration_seconds: float | None
    model_version: str
    semantic_validation: str = "LIMITED"
    gpu_seconds: float | None = None
    actual_cost_micros: int | None = None


class VisualRenderer(Protocol):
    name: str

    def job_id_for(self, idempotency_key: str) -> str: ...
    def submit(self, compiled: dict[str, object], *, idempotency_key: str) -> ProviderJob: ...
    def get_status(self, provider_job_id: str) -> ProviderStatus: ...
    def get_result(self, provider_job_id: str) -> ProviderResult: ...
    def cancel(self, provider_job_id: str) -> None: ...
