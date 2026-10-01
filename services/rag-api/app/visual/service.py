from __future__ import annotations

import hashlib
import json
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

from app.config import Settings
from app.storage.backends import StorageBackend
from app.visual.compiler import CompiledVisual, compile_visual_spec
from app.visual.planner import VisualPlannerProvider
from app.visual.providers.base import ProviderState, VisualRenderer
from app.visual.spec import Renderer, VisualSpec, validate_source_grounding
from app.visual.store import (
    TERMINAL,
    VisualJobCreate,
    VisualJobStore,
    VisualStateConflict,
    VisualStoreQuotaExceeded,
)
from app.visual.validators import InvalidVisualOutput, validate_output
from app.visual.workflows import Workflow, WorkflowRegistry

Action = Literal["auto", "diagram", "visual", "animate"]
DETERMINISTIC_FALLBACKS = {
    Renderer.DETERMINISTIC_DIAGRAM,
    Renderer.SVG,
    Renderer.MERMAID,
    Renderer.GRAPHVIZ,
    Renderer.MANIM,
}


class VisualQuotaExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class FrozenVisualInput:
    request_id: str
    user_id: str
    course_id: str
    pair_id: str
    message_id: str
    node_id: str | None
    action: Action
    question: str
    answer: str
    evidence: tuple[dict[str, str], ...]
    scope_key: str
    language: str


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode()
    return hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


class VisualService:
    """Durable Phase-A visual pipeline; it never participates in text generation."""

    def __init__(
        self,
        *,
        store: VisualJobStore,
        planner: VisualPlannerProvider,
        provider: VisualRenderer,
        storage: StorageBackend,
        workflows: WorkflowRegistry,
        settings: Settings,
    ) -> None:
        self.store = store
        self.planner = planner
        self.provider = provider
        self.storage = storage
        self.workflows = workflows
        self.settings = settings

    def create_job(self, value: FrozenVisualInput) -> tuple[dict[str, object], bool]:
        if not self.settings.visual_engine_enabled:
            raise RuntimeError("VISUAL_ENGINE_DISABLED")
        if value.action == "auto" and not self.settings.visual_auto_enabled:
            raise RuntimeError("AUTO_VISUAL_DISABLED")
        existing = self.store.get_by_request(value.user_id, value.request_id)
        frozen = asdict(value)
        frozen["evidence"] = list(value.evidence)
        frozen_json = _canonical(frozen)
        request_hash = _sha(frozen_json)
        if existing is not None:
            return self.store.create(
                VisualJobCreate(
                    request_id=value.request_id,
                    request_hash=request_hash,
                    user_id=value.user_id,
                    course_id=value.course_id,
                    pair_id=value.pair_id,
                    message_id=value.message_id,
                    node_id=value.node_id,
                    action=value.action,
                    source_snapshot_hash=self._source_hash(value),
                    frozen_input_json=frozen_json,
                    prompt_version=self.planner.prompt.version,
                    prompt_hash=self.planner.prompt.sha256,
                    provider=self.provider.name,
                )
            )
        self._enforce_gpu_quota(value.user_id)
        return self._create_job_record(
            VisualJobCreate(
                request_id=value.request_id,
                request_hash=request_hash,
                user_id=value.user_id,
                course_id=value.course_id,
                pair_id=value.pair_id,
                message_id=value.message_id,
                node_id=value.node_id,
                action=value.action,
                source_snapshot_hash=self._source_hash(value),
                frozen_input_json=frozen_json,
                prompt_version=self.planner.prompt.version,
                prompt_hash=self.planner.prompt.sha256,
                provider=self.provider.name,
            )
        )

    def _source_hash(self, value: FrozenVisualInput) -> str:
        return _sha(_canonical({"answer": value.answer, "evidence": value.evidence}))

    def _create_job_record(self, value: VisualJobCreate) -> tuple[dict[str, object], bool]:
        try:
            return self.store.create(
                value,
                max_user_active=self.settings.visual_max_concurrent_jobs_per_user,
                max_global_active=self.settings.visual_max_concurrent_jobs_global,
            )
        except VisualStoreQuotaExceeded as error:
            raise VisualQuotaExceeded(str(error)) from error

    def _enforce_gpu_quota(self, user_id: str) -> None:
        _images, _videos, gpu_seconds = self.store.daily_completed_counts(
            user_id, datetime.now(UTC).date().isoformat()
        )
        if (
            self.settings.visual_max_gpu_seconds_per_user_day > 0
            and gpu_seconds >= self.settings.visual_max_gpu_seconds_per_user_day
        ):
            raise VisualQuotaExceeded("daily visual GPU quota exceeded")

    def _enforce_renderer_quota(self, user_id: str, renderer: Renderer) -> None:
        images, videos, _gpu_seconds = self.store.daily_completed_counts(
            user_id, datetime.now(UTC).date().isoformat()
        )
        if renderer is Renderer.COMFY_VIDEO:
            if videos >= self.settings.visual_max_video_jobs_per_user_day:
                raise VisualQuotaExceeded("daily visual video quota exceeded")
        elif images >= self.settings.visual_max_images_per_user_day:
            raise VisualQuotaExceeded("daily visual image quota exceeded")

    def run_once(self, worker_id: str) -> dict[str, object] | None:
        claimed = self.store.claim_next(
            worker_id,
            now_epoch=time.time(),
            lease_seconds=self.settings.visual_worker_lease_seconds,
        )
        if claimed is None:
            return None
        return self.process_claimed(claimed, worker_id=worker_id)

    def cancel_job(self, job_id: str, user_id: str) -> dict[str, object]:
        job = self.store.get(job_id, user_id=user_id)
        if job is None:
            raise KeyError(job_id)
        cancelled = self.store.cancel(job_id, user_id)
        provider_job_id = job.get("provider_job_id")
        if provider_job_id:
            with suppress(Exception):
                self.provider.cancel(str(provider_job_id))
            # The durable database flag is authoritative. Provider cancel is
            # best-effort and a late result is suppressed before publication.
        return cancelled

    def retry_job(
        self, job_id: str, user_id: str, *, request_id: str
    ) -> tuple[dict[str, object], bool]:
        parent = self.store.get(job_id, user_id=user_id)
        if parent is None:
            raise KeyError(job_id)
        if parent["status"] != "FAILED":
            raise VisualStateConflict("only failed visual jobs can be retried")
        retry_count = int(str(parent["retry_count"])) + 1
        if retry_count > self.settings.visual_max_retries:
            raise VisualStateConflict("visual retry limit reached")
        self._enforce_gpu_quota(user_id)
        request_hash = _sha(
            _canonical(
                {
                    "parent_job_id": job_id,
                    "request_id": request_id,
                    "frozen_input_json": parent["frozen_input_json"],
                }
            )
        )
        return self._create_job_record(
            VisualJobCreate(
                request_id=request_id,
                request_hash=request_hash,
                user_id=user_id,
                course_id=str(parent["course_id"]),
                pair_id=str(parent["pair_id"]),
                message_id=str(parent["message_id"]),
                node_id=str(parent["node_id"]) if parent["node_id"] else None,
                action=str(parent["action"]),  # type: ignore[arg-type]
                source_snapshot_hash=str(parent["source_snapshot_hash"]),
                frozen_input_json=str(parent["frozen_input_json"]),
                prompt_version=str(parent["prompt_version"]),
                prompt_hash=str(parent["prompt_hash"]),
                provider=str(parent["provider"]),
                parent_job_id=job_id,
                retry_count=retry_count,
            )
        )

    def fallback_available(self, job: dict[str, object]) -> bool:
        if job.get("status") != "FAILED" or not job.get("visual_spec_json"):
            return False
        if int(str(job.get("retry_count") or 0)) >= self.settings.visual_max_retries:
            return False
        try:
            spec = VisualSpec.model_validate_json(str(job["visual_spec_json"]))
        except ValueError:
            return False
        return Renderer(spec.fallback_renderer) in DETERMINISTIC_FALLBACKS

    def fallback_job(
        self, job_id: str, user_id: str, *, request_id: str
    ) -> tuple[dict[str, object], bool]:
        parent = self.store.get(job_id, user_id=user_id)
        if parent is None:
            raise KeyError(job_id)
        if not self.fallback_available(parent):
            raise VisualStateConflict("deterministic visual fallback is not available")
        self._enforce_gpu_quota(user_id)
        frozen = json.loads(str(parent["frozen_input_json"]))
        frozen["request_id"] = request_id
        frozen["action"] = "diagram"
        frozen_json = _canonical(frozen)
        retry_count = int(str(parent["retry_count"])) + 1
        request_hash = _sha(
            _canonical(
                {
                    "parent_job_id": job_id,
                    "request_id": request_id,
                    "fallback": "diagram",
                    "frozen_input_json": frozen_json,
                }
            )
        )
        return self._create_job_record(
            VisualJobCreate(
                request_id=request_id,
                request_hash=request_hash,
                user_id=user_id,
                course_id=str(parent["course_id"]),
                pair_id=str(parent["pair_id"]),
                message_id=str(parent["message_id"]),
                node_id=str(parent["node_id"]) if parent["node_id"] else None,
                action="diagram",
                source_snapshot_hash=str(parent["source_snapshot_hash"]),
                frozen_input_json=frozen_json,
                prompt_version=str(parent["prompt_version"]),
                prompt_hash=str(parent["prompt_hash"]),
                provider=self.provider.name,
                parent_job_id=job_id,
                retry_count=retry_count,
            )
        )

    def process_claimed(self, claimed: dict[str, object], *, worker_id: str) -> dict[str, object]:
        job_id = str(claimed["id"])
        current = self.store.get(job_id)
        if current is None:
            raise KeyError(job_id)
        if current["status"] in TERMINAL or current["cancel_requested"]:
            return current
        try:
            if current["status"] in {"QUEUED", "RETRYING"}:
                current = self.store.transition(
                    job_id, "PLANNING", expected={str(current["status"])}
                )
            frozen = json.loads(str(current["frozen_input_json"]))
            resumed = current["status"] in {"RENDERING", "VALIDATING"}
            if resumed:
                if not current.get("visual_spec_json"):
                    raise RuntimeError("PROVIDER_UNKNOWN")
                spec = VisualSpec.model_validate_json(str(current["visual_spec_json"]))
            else:
                spec = self.planner.plan(
                    question=str(frozen["question"]),
                    answer=str(frozen["answer"]),
                    evidence=list(frozen["evidence"]),
                    action=str(frozen["action"]),  # type: ignore[arg-type]
                    language=str(frozen["language"]),
                )
            allowed_sources = {
                (str(item["source_id"]), str(item["source_version"])) for item in frozen["evidence"]
            }
            validate_source_grounding(spec, allowed_sources)
            if not resumed:
                self._enforce_renderer_quota(str(current["user_id"]), spec.renderer)
            compiled = compile_visual_spec(spec)
            spec_json = spec.model_dump_json(by_alias=True)
            spec_hash = _sha(spec_json)
            if resumed and current.get("visual_spec_hash") != spec_hash:
                raise RuntimeError("PROVIDER_UNKNOWN")
            workflow = self._workflow(spec)
            cache_key = self._cache_key(current, frozen, spec, spec_hash, workflow)
            current = self.store.patch(
                job_id,
                {
                    "visual_spec_json": spec_json,
                    "visual_spec_version": spec.visual_spec_version,
                    "visual_spec_hash": spec_hash,
                    "renderer": spec.renderer.value,
                    "workflow_id": workflow.workflow_id,
                    "workflow_version": workflow.version,
                    "model_version": workflow.model_version,
                    "cache_key": cache_key,
                },
            )
            if current["status"] == "VALIDATING":
                linked = self.store.assets_for_job(job_id, user_id=str(current["user_id"]))
                if linked:
                    asset = linked[0]
                    if spec.cache_policy == "REUSE":
                        self._cache_asset(
                            current,
                            frozen,
                            spec,
                            spec_hash,
                            workflow,
                            asset,
                            cache_key,
                        )
                    return self.store.transition(
                        job_id,
                        "COMPLETED",
                        expected={"VALIDATING"},
                        fields={
                            "output_bytes": int(str(asset["size_bytes"])),
                            "model_version": asset["model_version"],
                        },
                    )
            cached = self.store.cache_get(cache_key, str(frozen["scope_key"]))
            if (
                current["status"] == "PLANNING"
                and cached is not None
                and spec.cache_policy == "REUSE"
            ):
                self.store.link_asset(job_id, str(cached["id"]), role="cached")
                self.store.transition(job_id, "VALIDATING", expected={"PLANNING"})
                return self.store.transition(
                    job_id,
                    "COMPLETED",
                    expected={"VALIDATING"},
                    fields={
                        "cache_hit": 1,
                        "output_bytes": int(str(cached["size_bytes"])),
                    },
                )
            if not spec.should_generate:
                if current["status"] != "PLANNING":
                    raise RuntimeError("PROVIDER_UNKNOWN")
                self.store.transition(job_id, "VALIDATING", expected={"PLANNING"})
                return self.store.transition(job_id, "COMPLETED", expected={"VALIDATING"})
            if spec.renderer is Renderer.COMFY_VIDEO and not self.settings.visual_video_enabled:
                raise RuntimeError("VIDEO_DISABLED")
            if spec.renderer in {Renderer.COMFY_IMAGE, Renderer.COMFY_VIDEO}:
                if current["status"] == "PLANNING":
                    current = self.store.transition(job_id, "RENDERING", expected={"PLANNING"})
                elif current["status"] not in {"RENDERING", "VALIDATING"}:
                    raise RuntimeError("PROVIDER_UNKNOWN")
                result = self._render_provider(job_id, compiled)
                current = self.store.get(job_id) or current
                if current["status"] == "CANCELLED" or current["cancel_requested"]:
                    return current
                if current["status"] == "RENDERING":
                    self.store.transition(job_id, "VALIDATING", expected={"RENDERING"})
                content = result.content
                mime_type = result.mime_type
                if result.semantic_validation not in {"PASS", "LIMITED", "UNCERTAIN"}:
                    raise InvalidVisualOutput("provider semantic receipt is invalid")
                if result.gpu_seconds is not None and result.gpu_seconds < 0:
                    raise InvalidVisualOutput("provider GPU receipt is invalid")
                if result.actual_cost_micros is not None and result.actual_cost_micros < 0:
                    raise InvalidVisualOutput("provider cost receipt is invalid")
                width, height = validate_output(
                    content,
                    mime_type=mime_type,
                    width=result.width,
                    height=result.height,
                    duration_seconds=result.duration_seconds,
                    max_bytes=self.settings.visual_max_output_bytes,
                    max_width=self.settings.visual_max_width,
                    max_height=self.settings.visual_max_height,
                    max_duration_seconds=self.settings.visual_max_duration_seconds,
                )
                semantic_validation = result.semantic_validation
                gpu_seconds = result.gpu_seconds
                actual_cost = result.actual_cost_micros
                model_version = result.model_version
                duration = result.duration_seconds
            else:
                if current["status"] == "PLANNING":
                    self.store.transition(job_id, "VALIDATING", expected={"PLANNING"})
                elif current["status"] != "VALIDATING":
                    raise RuntimeError("PROVIDER_UNKNOWN")
                content = self._deterministic_bytes(compiled, spec)
                mime_type = "image/svg+xml"
                width, height = validate_output(
                    content,
                    mime_type=mime_type,
                    width=1024,
                    height=576,
                    duration_seconds=None,
                    max_bytes=self.settings.visual_max_output_bytes,
                    max_width=self.settings.visual_max_width,
                    max_height=self.settings.visual_max_height,
                    max_duration_seconds=self.settings.visual_max_duration_seconds,
                )
                semantic_validation = "PASS"
                gpu_seconds = 0.0
                actual_cost = None
                model_version = workflow.model_version
                duration = None
            current = self.store.get(job_id) or current
            if current["status"] == "CANCELLED" or current["cancel_requested"]:
                return current
            asset = self._publish_asset(
                current,
                spec,
                workflow,
                content=content,
                mime_type=mime_type,
                width=width,
                height=height,
                duration_seconds=duration,
                semantic_validation=semantic_validation,
                model_version=model_version,
            )
            self.store.link_asset(job_id, str(asset["id"]))
            if spec.cache_policy == "REUSE":
                self._cache_asset(
                    current,
                    frozen,
                    spec,
                    spec_hash,
                    workflow,
                    asset,
                    cache_key,
                )
            return self.store.transition(
                job_id,
                "COMPLETED",
                expected={"VALIDATING"},
                fields={
                    "gpu_seconds": gpu_seconds,
                    "actual_cost_micros": actual_cost,
                    "output_bytes": len(content),
                    "model_version": model_version,
                },
            )
        except VisualStateConflict:
            current = self.store.get(job_id)
            if current is not None and current["status"] == "CANCELLED":
                return current
            raise
        except Exception as error:
            current = self.store.get(job_id)
            if current is None or current["status"] in TERMINAL:
                return current or claimed
            if isinstance(error, InvalidVisualOutput):
                code = "INVALID_PROVIDER_OUTPUT"
            elif isinstance(error, VisualQuotaExceeded):
                code = "QUOTA_EXCEEDED"
            else:
                code = self._safe_error(error)
            return self.store.transition(
                job_id,
                "FAILED",
                expected={str(current["status"])},
                fields={"error_code": code, "error_detail_safe": code},
            )

    def _workflow(self, spec: VisualSpec) -> Workflow:
        if spec.renderer in {Renderer.COMFY_IMAGE, Renderer.COMFY_VIDEO}:
            return self.workflows.select(spec.renderer, self.provider.name)
        return Workflow(
            workflow_id="deterministic-" + spec.renderer.value.lower(),
            version="1",
            renderer_type=spec.renderer,
            provider="deterministic",
            enabled=True,
            allowed_inputs=(),
            outputs=("image",),
            model_version="deterministic-v1",
        )

    def _cache_key(
        self,
        job: dict[str, object],
        frozen: dict[str, object],
        spec: VisualSpec,
        spec_hash: str,
        workflow: Workflow,
    ) -> str:
        return self.store.cache_key(
            course_id=str(job["course_id"]),
            scope_key=str(frozen["scope_key"]),
            source_snapshot_hash=str(job["source_snapshot_hash"]),
            visual_spec_hash=spec_hash,
            renderer=spec.renderer.value,
            renderer_version="phase-a-1",
            prompt_version=str(job["prompt_version"]),
            workflow_id=workflow.workflow_id,
            workflow_version=workflow.version,
            model_version=workflow.model_version,
            language=spec.language,
        )

    def _cache_asset(
        self,
        job: dict[str, object],
        frozen: dict[str, object],
        spec: VisualSpec,
        spec_hash: str,
        workflow: Workflow,
        asset: dict[str, object],
        cache_key: str,
    ) -> None:
        self.store.cache_put(
            cache_key=cache_key,
            asset_id=str(asset["id"]),
            scope_key=str(frozen["scope_key"]),
            course_id=str(job["course_id"]),
            source_snapshot_hash=str(job["source_snapshot_hash"]),
            visual_spec_hash=spec_hash,
            renderer=spec.renderer.value,
            renderer_version="phase-a-1",
            prompt_version=str(job["prompt_version"]),
            workflow_id=workflow.workflow_id,
            workflow_version=workflow.version,
            model_version=str(asset["model_version"]),
            language=spec.language,
        )

    def _render_provider(self, job_id: str, compiled: CompiledVisual):
        current = self.store.get(job_id)
        if current is None:
            raise KeyError(job_id)
        provider_job_id = current.get("provider_job_id")
        if provider_job_id:
            submitted_id = str(provider_job_id)
        else:
            submitted = self.provider.submit(
                compiled.model_dump(mode="json"), idempotency_key=job_id
            )
            submitted_id = submitted.id
            self.store.patch(job_id, {"provider_job_id": submitted_id})
        for _ in range(25):
            current = self.store.get(job_id)
            if current is None or current["status"] == "CANCELLED" or current["cancel_requested"]:
                self.provider.cancel(submitted_id)
                raise RuntimeError("CANCELLED")
            status = self.provider.get_status(submitted_id)
            if status.state is ProviderState.COMPLETED:
                return self.provider.get_result(submitted_id)
            if status.state is ProviderState.FAILED:
                raise RuntimeError(status.error_code or "PROVIDER_FAILED")
            if status.state is ProviderState.CANCELLED:
                raise RuntimeError("PROVIDER_CANCELLED")
            if status.state is ProviderState.UNKNOWN:
                raise RuntimeError("PROVIDER_UNKNOWN")
        raise RuntimeError("PROVIDER_TIMEOUT")

    @staticmethod
    def _deterministic_bytes(compiled: CompiledVisual, spec: VisualSpec) -> bytes:
        if compiled.deterministic_source.lstrip().startswith("<svg"):
            return compiled.deterministic_source.encode()
        label = spec.visual_goal.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="576">'
            '<rect width="1024" height="576" fill="white"/>'
            f'<text x="512" y="288" text-anchor="middle" font-family="sans-serif">{label}</text>'
            "</svg>"
        ).encode()

    def _publish_asset(
        self,
        job: dict[str, object],
        spec: VisualSpec,
        workflow: Workflow,
        *,
        content: bytes,
        mime_type: str,
        width: int | None,
        height: int | None,
        duration_seconds: float | None,
        semantic_validation: str,
        model_version: str,
    ) -> dict[str, object]:
        digest = _sha(content)
        asset_id = "visual-asset-" + _sha(str(job["id"]))[:32]
        suffix = "svg" if mime_type == "image/svg+xml" else "png"
        key = f"visual-assets/{job['course_id']}/{asset_id}/{digest}.{suffix}"
        stored = self.storage.put_bytes(
            key, content, expected_sha256=digest, content_type=mime_type
        )
        asset_type = (
            "VIDEO"
            if spec.renderer is Renderer.COMFY_VIDEO
            else (
                "IMAGE"
                if spec.renderer is Renderer.COMFY_IMAGE
                else ("ANIMATION" if spec.visual_type.value == "ANIMATION" else "DIAGRAM")
            )
        )
        return self.store.create_asset(
            {
                "id": asset_id,
                "origin_job_id": str(job["id"]),
                "user_id": str(job["user_id"]),
                "course_id": str(job["course_id"]),
                "message_id": str(job["message_id"]),
                "type": asset_type,
                "renderer": spec.renderer.value,
                "mime_type": mime_type,
                "width": width,
                "height": height,
                "duration_seconds": duration_seconds,
                "storage_backend": stored.backend,
                "storage_bucket": stored.bucket,
                "storage_key": stored.key,
                "storage_version_id": stored.version_id,
                "sha256": digest,
                "size_bytes": len(content),
                "thumbnail_asset_id": None,
                "alt_text": spec.visual_goal,
                "prompt_version": str(job["prompt_version"]),
                "model_version": model_version,
                "workflow_id": workflow.workflow_id,
                "workflow_version": workflow.version,
                "semantic_validation": semantic_validation,
                "created_at": _now(),
                "expires_at": None,
            }
        )

    @staticmethod
    def _safe_error(error: Exception) -> str:
        value = str(error)
        allowed = {
            "VIDEO_DISABLED",
            "PROVIDER_FAILED",
            "PROVIDER_CANCELLED",
            "PROVIDER_UNKNOWN",
            "PROVIDER_TIMEOUT",
            "CANCELLED",
        }
        if value in allowed or value.startswith("MOCK_"):
            return value
        return "VISUAL_PROCESSING_FAILED"
