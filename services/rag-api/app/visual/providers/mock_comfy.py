from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from app.visual.providers.base import (
    ProviderJob,
    ProviderResult,
    ProviderState,
    ProviderStatus,
)

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@dataclass
class _MockJob:
    id: str
    mode: str
    polls: int = 0
    cancelled: bool = False


class MockComfyProvider:
    name = "mock"

    def __init__(self, *, complete_after_polls: int = 2) -> None:
        self.complete_after_polls = max(1, complete_after_polls)
        self.jobs: dict[str, _MockJob] = {}
        self.modes: dict[str, str] = {}
        self.submit_count = 0

    def set_mode(self, idempotency_key: str, mode: str) -> None:
        if mode not in {"success", "fail", "unknown", "invalid", "late"}:
            raise ValueError("Unknown MockComfy mode")
        self.modes[idempotency_key] = mode

    def job_id_for(self, idempotency_key: str) -> str:
        return "mock-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]

    def submit(self, compiled: dict[str, object], *, idempotency_key: str) -> ProviderJob:
        provider_id = self.job_id_for(idempotency_key)
        if provider_id not in self.jobs:
            self.jobs[provider_id] = _MockJob(
                provider_id, self.modes.get(idempotency_key, "success")
            )
            self.submit_count += 1
        return ProviderJob(provider_id)

    def get_status(self, provider_job_id: str) -> ProviderStatus:
        job = self.jobs[provider_job_id]
        job.polls += 1
        if job.cancelled and job.mode != "late":
            return ProviderStatus(ProviderState.CANCELLED)
        if job.mode == "fail":
            return ProviderStatus(ProviderState.FAILED, "MOCK_PROVIDER_FAILED")
        if job.mode == "unknown":
            return ProviderStatus(ProviderState.UNKNOWN, "MOCK_PROVIDER_UNKNOWN")
        if job.polls >= self.complete_after_polls:
            return ProviderStatus(ProviderState.COMPLETED)
        return ProviderStatus(ProviderState.RUNNING)

    def get_result(self, provider_job_id: str) -> ProviderResult:
        job = self.jobs[provider_job_id]
        if job.cancelled and job.mode != "late":
            raise RuntimeError("provider job was cancelled")
        content = b"not-an-image" if job.mode == "invalid" else _PNG
        return ProviderResult(
            content=content,
            mime_type="image/png",
            width=1,
            height=1,
            duration_seconds=None,
            model_version="mock-fixture-v1",
            semantic_validation="LIMITED",
            gpu_seconds=0.0,
            actual_cost_micros=None,
        )

    def cancel(self, provider_job_id: str) -> None:
        self.jobs[provider_job_id].cancelled = True
