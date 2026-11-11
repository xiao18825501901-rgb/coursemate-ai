import time

import pytest
from pydantic import SecretStr
from test_visual_service import make_service, request

from app.config import Settings
from app.db import Database
from app.errors import ApiError
from app.learning.generic_provider import generic_model_settings
from app.learning.provider import ProviderCallFailure
from app.learning.structured_calls import GenericStructuredCalls
from app.visual.compiler import compile_visual_spec
from app.visual.language_planner import VisualLanguagePlannerProvider
from app.visual.planner import GroundedPolicyVisualPlannerProvider, MockVisualPlannerProvider


class ControlledPlanProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        outcome: str = "success",
        foreign_source: bool = False,
        placeholder: bool = False,
        exact_labels: bool = False,
        video_duration_seconds: float | None = None,
    ) -> None:
        self.settings = generic_model_settings(settings)
        self.cache_model = "qwen3.8-max"
        self.cache_protocol = "chat_completions"
        self.cache_region = "ENDPOINT_CN"
        self.outcome = outcome
        self.foreign_source = foreign_source
        self.placeholder = placeholder
        self.exact_labels = exact_labels
        self.video_duration_seconds = video_duration_seconds
        self.calls = 0

    def generate(self, schema, *, context, transport_event_sink, **kwargs):
        transport_event_sink({"phase": "SEND_INTENT"})
        self.calls += 1
        if self.outcome == "unknown":
            raise ProviderCallFailure(
                TimeoutError("TEST_ONLY plan timeout"),
                {
                    "status": "UNKNOWN",
                    "error_class": "TimeoutError",
                    "failure_layer": "PROVIDER_TRANSPORT",
                    "response_received": False,
                },
            )
        transport_event_sink(
            {
                "phase": "RESPONSE_COMPLETE",
                "returned_model": "qwen3.8-max",
                "usage_reported": True,
                "input_tokens": 100,
                "output_tokens": 200,
                "provider_response_id": "TEST_ONLY-plan-response",
            }
        )
        spec = MockVisualPlannerProvider().plan(
            question=context["question"],
            answer=context["answer"],
            evidence=context["evidence"],
            action=context["action"],
            language=context["language"],
        )
        if self.foreign_source:
            spec.source_grounding[0].source_id = "foreign-source"
        if self.placeholder:
            spec.visual_goal = "main concept"
            spec.must_include = ["Show the supported concept."]
        if self.exact_labels:
            spec.exact_labels = ["CPU socket area"]
        if self.video_duration_seconds is not None:
            spec.duration_seconds = self.video_duration_seconds
        return schema.model_validate(spec.model_dump(by_alias=True)), {
            "provider_response_id": "TEST_ONLY-plan-response",
        }


def planner_context(
    tmp_path,
    visual_request=None,
    visual_settings: dict[str, object] | None = None,
    **provider_options,
):
    visual, _renderer = make_service(tmp_path, **(visual_settings or {}))
    job, _ = visual.create_job(visual_request or request())
    claimed = visual.store.claim_next("worker", now_epoch=time.time(), lease_seconds=300)
    assert claimed is not None
    job = visual.store.transition(str(job["id"]), "PLANNING", expected={"QUEUED"})
    settings = visual.settings.model_copy(
        update={
            "generic_llm_enabled": True,
            "cj_qwen_api_key": SecretStr("TEST_ONLY-placeholder"),
            "cj_qwen_capability_receipt_id": "TEST_ONLY-capability",
            "cj_qwen_secret_generation_id": "TEST_ONLY-generation",
        }
    )
    provider = ControlledPlanProvider(settings, **provider_options)
    calls = GenericStructuredCalls(Database(settings), settings, provider)
    planner = VisualLanguagePlannerProvider(
        calls=calls,
        fallback=GroundedPolicyVisualPlannerProvider(),
    )
    return planner, visual, job, provider


def test_completed_plan_is_reused_from_shared_ledger_and_bound_to_job(tmp_path):
    planner, visual, job, provider = planner_context(tmp_path)

    first = planner.plan_job(job=job, worker_id="worker")
    second = planner.plan_job(
        job=visual.store.get(str(job["id"])),
        worker_id="worker",
    )

    assert first == second
    assert provider.calls == 1
    with visual.store.database.connect() as connection:
        receipt = connection.execute("SELECT * FROM generic_llm_calls").fetchone()
    assert receipt["role"] == "VISUAL_LANGUAGE_PLAN"
    assert receipt["source_visual_job_id"] == job["id"]
    assert receipt["status"] == "COMPLETED"
    assert receipt["model_id"] == "qwen3.8-max"


def test_unknown_visual_plan_is_durable_and_never_replayed(tmp_path):
    planner, visual, job, provider = planner_context(tmp_path, outcome="unknown")

    with pytest.raises(TimeoutError):
        planner.plan_job(job=job, worker_id="worker")
    with pytest.raises(ApiError) as replay:
        planner.plan_job(job=visual.store.get(str(job["id"])), worker_id="worker")

    assert replay.value.code == "MODEL_REQUEST_UNCERTAIN"
    assert provider.calls == 1
    with visual.store.database.connect() as connection:
        receipt = connection.execute("SELECT * FROM generic_llm_calls").fetchone()
    assert receipt["status"] == "UNKNOWN"
    assert receipt["output_json"] is None


def test_foreign_grounding_is_rejected_and_not_retried(tmp_path):
    planner, visual, job, provider = planner_context(tmp_path, foreign_source=True)

    with pytest.raises(ApiError) as rejected:
        planner.plan_job(job=job, worker_id="worker")
    with pytest.raises(ApiError):
        planner.plan_job(job=visual.store.get(str(job["id"])), worker_id="worker")

    assert rejected.value.code == "VISUAL_PLAN_OUTPUT_REJECTED"
    assert provider.calls == 1
    with visual.store.database.connect() as connection:
        receipt = connection.execute("SELECT * FROM generic_llm_calls").fetchone()
    assert receipt["status"] == "FAILED"
    assert receipt["output_json"] is None


def test_placeholder_visual_content_is_rejected_without_retry(tmp_path):
    planner, visual, job, provider = planner_context(tmp_path, placeholder=True)

    with pytest.raises(ApiError) as rejected:
        planner.plan_job(job=job, worker_id="worker")
    with pytest.raises(ApiError):
        planner.plan_job(job=visual.store.get(str(job["id"])), worker_id="worker")

    assert rejected.value.code == "VISUAL_PLAN_OUTPUT_REJECTED"
    assert provider.calls == 1
    with visual.store.database.connect() as connection:
        receipt = connection.execute("SELECT * FROM generic_llm_calls").fetchone()
    assert receipt["status"] == "FAILED"


def test_generated_renderer_exact_text_is_overlaid_without_reaching_prompt(tmp_path):
    planner, visual, job, _provider = planner_context(tmp_path, exact_labels=True)

    spec = planner.plan_job(job=job, worker_id="worker")
    compiled = compile_visual_spec(spec)

    assert spec.exact_labels == ["CPU socket area"]
    assert "CPU socket area" not in compiled.positive_prompt
    assert [overlay.text for overlay in compiled.overlays] == ["CPU socket area"]


def test_planner_prompt_does_not_downgrade_physical_visual_tasks_to_svg(tmp_path):
    planner, _visual, _job, _provider = planner_context(tmp_path)

    assert "explicitly visual task to SVG" in planner.prompt.text
    assert "select COMFY_IMAGE" in planner.prompt.text
    assert "real physical object whose continuous motion must be observed" in planner.prompt.text
    assert "select COMFY_VIDEO" in planner.prompt.text


def test_planner_fits_model_duration_to_bounded_wan_window(tmp_path):
    grounded_claim = (
        "The circular platter rotates continuously around the fixed central spindle while "
        "one actuator arm performs a bounded radial sweep that moves the read/write head "
        "across different radial positions; the drive body remains fixed."
    )
    value = request(
        request_id="request-hdd-video-duration",
        question=(
            "Teach mechanical hard disk platter rotation and bounded actuator "
            "arm radial motion."
        ),
    )
    value = type(value)(
        **{
            **value.__dict__,
            "answer": grounded_claim,
            "evidence": (
                {
                    "source_id": "document-1",
                    "source_version": "version-1",
                    "locator": "page 1",
                    "supported_claim": grounded_claim,
                },
            ),
        }
    )
    planner, _visual, job, provider = planner_context(
        tmp_path,
        visual_request=value,
        visual_settings={"visual_video_enabled": True},
        video_duration_seconds=8.0,
    )

    spec = planner.plan_job(job=job, worker_id="worker")
    replay = planner.plan_job(job=job, worker_id="worker")
    compiled = compile_visual_spec(spec)

    assert provider.calls == 1
    assert replay == spec
    assert spec.renderer.value == "COMFY_VIDEO"
    assert spec.duration_seconds == 5.0
    assert compiled.frames == 121
    assert "3 to 5 seconds" in planner.prompt.text


class SpyPlanner:
    prompt = GroundedPolicyVisualPlannerProvider().prompt

    def __init__(self):
        self.calls = 0

    def plan(self, **kwargs):
        self.calls += 1
        return GroundedPolicyVisualPlannerProvider().plan(**kwargs)


def test_disabled_visual_assistance_stops_before_any_planner_call(tmp_path):
    service, _provider = make_service(tmp_path)
    service.store.set_assistance_preference(
        "user-1",
        "course-1",
        enabled=False,
        consent_version="visual-assistance-v1",
        request_id="disable-before-plan",
    )
    planner = SpyPlanner()
    service.planner = planner
    service.create_job(request(request_id="request-disabled-before-plan"))

    result = service.run_once("worker-1")

    assert result is not None
    assert result["status"] == "FAILED"
    assert result["error_code"] == "VISUAL_ASSISTANCE_NOT_ENABLED"
    assert planner.calls == 0


def test_application_wires_visual_jobs_to_the_shared_qwen_planner(tmp_path):
    from test_visual_api_integration import FakeAuthVerifier, FakeEmbeddingProvider

    from app.main import create_app

    settings = Settings(
        _env_file=None,
        app_env="test",
        rag_provider_mode="deterministic",
        v3_enabled=True,
        generic_llm_enabled=True,
        cj_qwen_api_key=SecretStr("TEST_ONLY-placeholder"),
        cj_qwen_capability_receipt_id="TEST_ONLY-capability",
        cj_qwen_secret_generation_id="TEST_ONLY-generation",
        visual_engine_enabled=True,
        visual_provider="mock",
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        storage_cache_dir=tmp_path / "cache",
    )

    application = create_app(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )

    assert isinstance(
        application.state.visual_service.planner,
        VisualLanguagePlannerProvider,
    )
