from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.storage.backends import LocalStorageBackend
from app.visual.planner import MockVisualPlannerProvider
from app.visual.providers.base import ProviderResult
from app.visual.providers.mock_comfy import MockComfyProvider
from app.visual.service import FrozenVisualInput, VisualQuotaExceeded, VisualService
from app.visual.store import VisualJobStore, VisualStateConflict
from app.visual.workflows import WorkflowRegistry


def make_service(
    tmp_path: Path, **setting_changes: object
) -> tuple[VisualService, MockComfyProvider]:
    settings = Settings(
        _env_file=None,
        app_env="test",
        rag_provider_mode="deterministic",
        v3_enabled=True,
        visual_engine_enabled=True,
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        storage_cache_dir=tmp_path / "cache",
        **setting_changes,
    )
    database = Database(settings)
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility) "
            "VALUES('course-1','Private course','user-1','user','private')"
        )
    provider = MockComfyProvider(complete_after_polls=1)
    service = VisualService(
        store=VisualJobStore(database),
        planner=MockVisualPlannerProvider(),
        provider=provider,
        storage=LocalStorageBackend(settings.upload_dir / "objects"),
        workflows=WorkflowRegistry.default_mock(),
        settings=settings,
    )
    return service, provider


def request(
    *, request_id: str = "request-1", question: str = "Explain a gravitational lens"
) -> FrozenVisualInput:
    return FrozenVisualInput(
        request_id=request_id,
        user_id="user-1",
        course_id="course-1",
        pair_id="pair-1",
        message_id="message-1",
        node_id=None,
        action="visual",
        question=question,
        answer="A course-grounded answer about the requested concept.",
        evidence=(
            {
                "source_id": "document-1",
                "source_version": "version-1",
                "locator": "page 1",
                "supported_claim": "The evidence supports the concept.",
            },
        ),
        scope_key="private:user-1",
        language="en",
    )


def test_service_renders_valid_asset_and_reuses_private_cache(tmp_path: Path) -> None:
    service, provider = make_service(tmp_path)
    first, created = service.create_job(request())
    assert created is True
    completed = service.run_once("worker-1")
    assert completed is not None and completed["status"] == "COMPLETED"
    first_assets = service.store.assets_for_job(str(first["id"]), user_id="user-1")
    assert len(first_assets) == 1
    assert first_assets[0]["mime_type"] == "image/png"
    assert provider.submit_count == 1

    second, _ = service.create_job(request(request_id="request-2"))
    cached = service.run_once("worker-1")
    assert cached is not None and cached["id"] == second["id"]
    assert cached["status"] == "COMPLETED"
    assert cached["cache_hit"] == 1
    assert provider.submit_count == 1
    assert (
        service.store.assets_for_job(str(second["id"]), user_id="user-1")[0]["id"]
        == first_assets[0]["id"]
    )


def test_deterministic_diagram_never_invokes_provider(tmp_path: Path) -> None:
    service, provider = make_service(tmp_path)
    value = request(question="Show the CPU pipeline stages")
    value = FrozenVisualInput(**{**value.__dict__, "action": "diagram"})
    service.create_job(value)
    completed = service.run_once("worker-1")
    assert completed is not None and completed["status"] == "COMPLETED"
    assert provider.submit_count == 0
    asset = service.store.assets_for_job(str(completed["id"]), user_id="user-1")[0]
    assert asset["mime_type"] == "image/svg+xml"
    assert asset["semantic_validation"] == "PASS"


def test_invalid_provider_output_fails_without_publishing_asset(tmp_path: Path) -> None:
    service, provider = make_service(tmp_path)
    job, _ = service.create_job(request())
    provider.set_mode(str(job["id"]), "invalid")
    failed = service.run_once("worker-1")
    assert failed is not None and failed["status"] == "FAILED"
    assert failed["error_code"] == "INVALID_PROVIDER_OUTPUT"
    assert service.store.assets_for_job(str(job["id"]), user_id="user-1") == []


def test_invalid_provider_receipt_fails_before_asset_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, provider = make_service(tmp_path)
    job, _ = service.create_job(request())
    monkeypatch.setattr(
        provider,
        "get_result",
        lambda _job_id: ProviderResult(
            content=b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"\x00\x00\x00\x01\x00\x00\x00\x01",
            mime_type="image/png",
            width=1,
            height=1,
            duration_seconds=None,
            model_version="mock-fixture-v1",
            semantic_validation="UNTRUSTED",
            gpu_seconds=-1,
            actual_cost_micros=-1,
        ),
    )
    failed = service.run_once("worker-1")
    assert failed is not None and failed["status"] == "FAILED"
    assert failed["error_code"] == "INVALID_PROVIDER_OUTPUT"
    assert service.store.assets_for_job(str(job["id"]), user_id="user-1") == []


def test_failed_generative_job_can_create_a_linked_deterministic_fallback(
    tmp_path: Path,
) -> None:
    service, provider = make_service(tmp_path)
    original, _ = service.create_job(request())
    provider.set_mode(str(original["id"]), "invalid")
    failed = service.run_once("worker-1")
    assert failed is not None and failed["status"] == "FAILED"

    fallback, created = service.fallback_job(
        str(original["id"]), "user-1", request_id="fallback-request-1"
    )
    assert created is True
    assert fallback["parent_job_id"] == original["id"]
    completed = service.run_once("worker-1")
    assert completed is not None and completed["status"] == "COMPLETED"
    assert completed["renderer"] == "SVG"
    assert provider.submit_count == 1


def test_provider_unknown_is_preserved_and_safe_retry_has_lineage(tmp_path: Path) -> None:
    service, provider = make_service(tmp_path)
    original, _ = service.create_job(request())
    provider.set_mode(str(original["id"]), "unknown")
    failed = service.run_once("worker-1")
    assert failed is not None and failed["status"] == "FAILED"
    assert failed["error_code"] == "PROVIDER_UNKNOWN"
    assert failed["actual_cost_micros"] is None

    retry, created = service.retry_job(str(original["id"]), "user-1", request_id="request-retry-1")
    assert created is True
    assert retry["parent_job_id"] == original["id"]
    assert retry["retry_count"] == 1
    provider.set_mode(str(retry["id"]), "unknown")
    completed = service.run_once("worker-1")
    assert completed is not None and completed["id"] == retry["id"]
    assert completed["status"] == "FAILED"
    assert service.store.get(str(original["id"]))["status"] == "FAILED"
    with pytest.raises(VisualStateConflict, match="retry limit"):
        service.retry_job(str(retry["id"]), "user-1", request_id="request-retry-2")


def test_cancelled_job_cannot_publish_late_provider_result(tmp_path: Path) -> None:
    service, provider = make_service(tmp_path)
    job, _ = service.create_job(request())
    provider.set_mode(str(job["id"]), "late")
    claimed = service.store.claim_next("worker-1", now_epoch=100, lease_seconds=30)
    assert claimed is not None
    service.store.cancel(str(job["id"]), "user-1")
    service.process_claimed(claimed, worker_id="worker-1")
    assert service.store.get(str(job["id"]))["status"] == "CANCELLED"
    assert service.store.assets_for_job(str(job["id"]), user_id="user-1") == []


def test_stale_rendering_lease_resumes_same_provider_job_without_resubmit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, provider = make_service(tmp_path)
    provider.complete_after_polls = 2
    job, _ = service.create_job(request())
    claimed = service.store.claim_next("worker-1", now_epoch=100, lease_seconds=10)
    assert claimed is not None
    real_get_status = provider.get_status

    def interrupted(_provider_job_id: str):
        raise KeyboardInterrupt("simulated worker crash")

    monkeypatch.setattr(provider, "get_status", interrupted)
    with pytest.raises(KeyboardInterrupt, match="worker crash"):
        service.process_claimed(claimed, worker_id="worker-1")
    interrupted_job = service.store.get(str(job["id"]))
    assert interrupted_job is not None and interrupted_job["status"] == "RENDERING"
    assert interrupted_job["provider_job_id"]
    assert provider.submit_count == 1

    monkeypatch.setattr(provider, "get_status", real_get_status)
    recovered = service.store.claim_next("worker-2", now_epoch=111, lease_seconds=10)
    assert recovered is not None
    completed = service.process_claimed(recovered, worker_id="worker-2")
    assert completed["status"] == "COMPLETED"
    assert provider.submit_count == 1


def test_restart_after_asset_link_reuses_same_immutable_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, provider = make_service(tmp_path)
    job, _ = service.create_job(request())
    claimed = service.store.claim_next("worker-1", now_epoch=100, lease_seconds=10)
    assert claimed is not None
    real_transition = service.store.transition

    def interrupted_transition(job_id, target, **kwargs):
        if target == "COMPLETED":
            raise KeyboardInterrupt("simulated crash after asset link")
        return real_transition(job_id, target, **kwargs)

    monkeypatch.setattr(service.store, "transition", interrupted_transition)
    with pytest.raises(KeyboardInterrupt, match="asset link"):
        service.process_claimed(claimed, worker_id="worker-1")
    assert len(service.store.assets_for_job(str(job["id"]), user_id="user-1")) == 1

    monkeypatch.setattr(service.store, "transition", real_transition)
    recovered = service.store.claim_next("worker-2", now_epoch=111, lease_seconds=10)
    assert recovered is not None
    completed = service.process_claimed(recovered, worker_id="worker-2")
    assert completed["status"] == "COMPLETED"
    assert len(service.store.assets_for_job(str(job["id"]), user_id="user-1")) == 1
    assert provider.submit_count == 1


def test_quota_blocks_before_any_provider_submission(tmp_path: Path) -> None:
    service, provider = make_service(tmp_path, visual_max_concurrent_jobs_per_user=1)
    service.create_job(request())
    with pytest.raises(VisualQuotaExceeded, match="concurrent"):
        service.create_job(request(request_id="request-2"))
    assert provider.submit_count == 0


def test_daily_image_quota_fails_closed_before_second_provider_submission(
    tmp_path: Path,
) -> None:
    service, provider = make_service(tmp_path, visual_max_images_per_user_day=1)
    service.create_job(request())
    completed = service.run_once("worker-1")
    assert completed is not None and completed["status"] == "COMPLETED"
    assert provider.submit_count == 1

    service.create_job(
        request(request_id="request-2", question="Illustrate a different supported concept")
    )
    rejected = service.run_once("worker-1")
    assert rejected is not None and rejected["status"] == "FAILED"
    assert rejected["error_code"] == "QUOTA_EXCEEDED"
    assert provider.submit_count == 1


def test_disabled_alibaba_boundary_makes_no_network_call(tmp_path: Path) -> None:
    from app.visual.providers.aliyun_eas import AlibabaEASComfyProvider, ProviderNotConfigured

    provider = AlibabaEASComfyProvider()
    with pytest.raises(ProviderNotConfigured, match="NOT_CONFIGURED"):
        provider.submit({}, idempotency_key="never-network")
