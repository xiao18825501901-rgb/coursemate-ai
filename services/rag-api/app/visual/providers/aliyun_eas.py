from __future__ import annotations

from app.visual.providers.base import ProviderJob, ProviderResult, ProviderStatus


class ProviderNotConfigured(RuntimeError):
    pass


class AlibabaEASComfyProvider:
    """Phase-B adapter boundary. Phase A deliberately contains no transport."""

    name = "aliyun_eas"

    @staticmethod
    def _disabled() -> None:
        raise ProviderNotConfigured("NOT_CONFIGURED: Alibaba EAS is not available in Phase A")

    def submit(self, compiled: dict[str, object], *, idempotency_key: str) -> ProviderJob:
        self._disabled()
        raise AssertionError("unreachable")

    def get_status(self, provider_job_id: str) -> ProviderStatus:
        self._disabled()
        raise AssertionError("unreachable")

    def get_result(self, provider_job_id: str) -> ProviderResult:
        self._disabled()
        raise AssertionError("unreachable")

    def cancel(self, provider_job_id: str) -> None:
        self._disabled()
