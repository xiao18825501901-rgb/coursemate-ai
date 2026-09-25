import base64
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter
from typing import Any, Literal, TypeVar
from urllib.parse import urlsplit

from openai import OpenAI
from pydantic import BaseModel

from app.config import Settings
from app.errors import ApiError
from app.evaluation.deepseek_contract import (
    REASONING_DISABLED,
    json_schema_text_format,
)
from app.evaluation.provider_safety import (
    validate_deepseek_base_url,
    validate_model_studio_base_url,
)

Output = TypeVar("Output", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ProviderImage:
    media_type: Literal["image/png", "image/jpeg"]
    content: bytes = field(repr=False)
    sha256: str
    source_version_id: str

    def __post_init__(self) -> None:
        if not self.content or sha256(self.content).hexdigest() != self.sha256:
            raise ValueError("Provider image bytes do not match their immutable source version")


class ProviderCallFailure(Exception):
    """Carries safe call metadata without retaining private prompt or response bodies."""

    def __init__(self, cause: Exception, run: dict[str, Any]) -> None:
        super().__init__(type(cause).__name__)
        self.cause = cause
        self.run = run


def _structured_input_payload(
    schema: type[BaseModel],
    *,
    context: dict[str, Any],
    images: list[ProviderImage] | None = None,
) -> str:
    safe_images = images or []
    return json.dumps(
        {
            "authorized_context": context,
            "authorized_images": [
                {
                    "source_version_id": item.source_version_id,
                    "media_type": item.media_type,
                    "sha256": item.sha256,
                    "byte_size": len(item.content),
                }
                for item in safe_images
            ],
            "required_output_schema": schema.model_json_schema(),
        },
        ensure_ascii=False,
    )


def structured_input_hash(
    schema: type[BaseModel],
    *,
    context: dict[str, Any],
    images: list[ProviderImage] | None = None,
) -> str:
    """Return the exact authorized-input identity recorded by ``generate``."""
    payload = _structured_input_payload(schema, context=context, images=images)
    return sha256(payload.encode()).hexdigest()


class LearningProvider:
    """Bounded Responses adapter. No provider fallback, automatic retry or external search tools."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.v3_model
        self.is_deepseek = self.model == "deepseek-flash"
        self.client: OpenAI | None = None
        # Optional evidence sink used by bounded acceptance runners.  Production
        # behavior is unchanged when absent.  A configured sink is fail-closed:
        # if SEND_INTENT cannot be durably recorded, the provider request is not
        # attempted.
        self.transport_event_sink: Callable[[dict[str, Any]], None] | None = None

    def _transport_event(self, phase: str, **values: Any) -> None:
        if self.transport_event_sink is not None:
            self.transport_event_sink({"phase": phase, **values})

    @property
    def cache_model(self) -> str:
        if self.settings.app_env == "test" and self.settings.rag_provider_mode == "deterministic":
            return "FAKE_TEST_ONLY"
        return self.model

    @property
    def cache_protocol(self) -> str:
        if self.settings.app_env == "test" and self.settings.rag_provider_mode == "deterministic":
            return "fixture"
        return "responses"

    @property
    def cache_region(self) -> str:
        if self.settings.app_env == "test" and self.settings.rag_provider_mode == "deterministic":
            return "LOCAL_TEST"
        host = urlsplit(self.settings.v3_model_base_url or "").hostname or ""
        if host == "api.deepseek.com":
            return "ENDPOINT_DEEPSEEK"
        if host == "dashscope-intl.aliyuncs.com":
            return "ENDPOINT_INTL"
        if host == "dashscope.aliyuncs.com":
            return "ENDPOINT_CN"
        if host == "dashscope-us.aliyuncs.com":
            return "ENDPOINT_US"
        if host == "cn-hongkong.dashscope.aliyuncs.com":
            return "ENDPOINT_HK"
        if host.endswith(".maas.aliyuncs.com"):
            return "ENDPOINT_WORKSPACE"
        return "ENDPOINT_UNVERIFIED"

    def generate(
        self,
        schema: type[Output],
        *,
        instructions: str,
        context: dict[str, Any],
        role: str,
        template_version: str = "UNVERSIONED",
        schema_version: str | None = None,
        images: list[ProviderImage] | None = None,
    ) -> tuple[Output, dict[str, Any]]:
        settings = self.settings
        safe_images = images or []
        serialized = _structured_input_payload(
            schema,
            context=context,
            images=safe_images,
        )
        started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        started = perf_counter()
        run: dict[str, Any] = {
            "model": self.cache_model,
            "provider": (
                "deterministic"
                if self.cache_protocol == "fixture"
                else "DEEPSEEK_API"
                if self.is_deepseek
                else "ALIBABA_MODEL_STUDIO_COMPATIBLE"
            ),
            "protocol": self.cache_protocol,
            "region": self.cache_region,
            "role": role,
            "template_version": template_version,
            "schema_version": schema_version or schema.__name__,
            "input_hash": sha256(serialized.encode()).hexdigest(),
            "started_at": started_at,
            "input_tokens": 0,
            "output_tokens": 0,
            "provider_response_id": None,
        }
        response_received = False
        send_intent_recorded = False
        contract_terminal_recorded = False
        try:
            if any(
                len(item.content) > settings.v3_problem_image_max_bytes
                for item in safe_images
            ):
                raise ApiError(
                    413, "IMAGE_MODEL_LIMIT", "The image exceeds the model input limit."
                )
            if settings.app_env == "test" and settings.rag_provider_mode == "deterministic":
                from app.learning.testing import fixture_output

                output = schema.model_validate(fixture_output(schema.__name__, context))
            else:
                if not settings.v3_model_api_key:
                    raise ApiError(
                        503,
                        "MODEL_LIVE_BLOCKED",
                        "Configure the explicit model endpoint key.",
                    )
                if self.is_deepseek:
                    raw_base_url = settings.v3_model_base_url or "https://api.deepseek.com"
                    try:
                        base_url = validate_deepseek_base_url(raw_base_url)
                    except ValueError:
                        raise ApiError(
                            503,
                            "MODEL_ENDPOINT_INVALID",
                            "Use the official DeepSeek base URL (https://api.deepseek.com).",
                        ) from None
                else:
                    if not settings.v3_model_base_url:
                        raise ApiError(
                            503,
                            "MODEL_LIVE_BLOCKED",
                            "Configure the explicit V3 Model Studio endpoint.",
                        )
                    try:
                        base_url = validate_model_studio_base_url(settings.v3_model_base_url)
                    except ValueError:
                        raise ApiError(
                            503,
                            "MODEL_ENDPOINT_INVALID",
                            "Use an explicit Model Studio compatible-mode endpoint.",
                        ) from None
                if len(serialized) > 60000:
                    raise ApiError(422, "CONTEXT_BUDGET", "The bounded unit context is too large.")
                if self.client is None:
                    self.client = OpenAI(
                        api_key=settings.v3_model_api_key.get_secret_value(),
                        base_url=base_url,
                        max_retries=0,
                        timeout=settings.v3_model_timeout_seconds,
                    )
                provider_input: Any = serialized
                if safe_images:
                    content: list[dict[str, str]] = [
                        {"type": "input_text", "text": serialized}
                    ]
                    content.extend(
                        {
                            "type": "input_image",
                            "image_url": "data:"
                            + item.media_type
                            + ";base64,"
                            + base64.b64encode(item.content).decode("ascii"),
                        }
                        for item in safe_images
                    )
                    provider_input = [{"role": "user", "content": content}]
                self._transport_event(
                    "SEND_INTENT",
                    provider=run["provider"],
                    model=self.model,
                    protocol="responses",
                    role=role,
                    input_hash=run["input_hash"],
                    template_version=template_version,
                    schema_version=schema_version or schema.__name__,
                    max_output_tokens=settings.v3_max_output_tokens,
                )
                send_intent_recorded = True
                if self.is_deepseek:
                    # Structured output via the documented Responses text.format
                    # json_schema; native thinking explicitly off.  NO Qwen-only
                    # fields (enable_thinking, max_pixels) are ever emitted.
                    response = self.client.responses.create(
                        model=self.model,
                        instructions=instructions,
                        input=provider_input,
                        max_output_tokens=settings.v3_max_output_tokens,
                        store=False,
                        tools=[],
                        stream=False,
                        extra_body={
                            "reasoning": REASONING_DISABLED,
                            "text": {
                                "format": json_schema_text_format(
                                    schema.__name__, schema.model_json_schema()
                                )
                            },
                        },
                    )
                else:
                    response = self.client.responses.create(
                        model=self.model,
                        instructions=instructions
                        + "\nReturn only one valid JSON object matching the supplied schema.",
                        input=provider_input,
                        max_output_tokens=settings.v3_max_output_tokens,
                        store=False,
                        tools=[],
                        stream=False,
                        extra_body={"enable_thinking": False},
                    )
                response_received = True
                run["provider_response_id"] = response.id
                usage = response.usage
                run["input_tokens"] = usage.input_tokens if usage else 0
                run["output_tokens"] = usage.output_tokens if usage else 0
                raw_output_text = response.output_text
                self._transport_event(
                    "RESPONSE_COMPLETE",
                    provider=run["provider"],
                    model=self.model,
                    protocol="responses",
                    role=role,
                    input_hash=run["input_hash"],
                    provider_response_id=response.id,
                    provider_status=response.status,
                    input_tokens=run["input_tokens"],
                    output_tokens=run["output_tokens"],
                    output_text=raw_output_text,
                )
                if response.status != "completed":
                    self._transport_event(
                        "CONTRACT_REJECTED",
                        role=role,
                        input_hash=run["input_hash"],
                        provider_response_id=response.id,
                        reason="MODEL_INCOMPLETE",
                    )
                    contract_terminal_recorded = True
                    raise ApiError(
                        502,
                        "MODEL_INCOMPLETE",
                        "Incomplete output was not recorded as teaching coverage.",
                    )
                output = schema.model_validate_json(raw_output_text)
                self._transport_event(
                    "CONTRACT_VALID",
                    role=role,
                    input_hash=run["input_hash"],
                    provider_response_id=response.id,
                    schema_version=schema_version or schema.__name__,
                )
                contract_terminal_recorded = True
        except Exception as error:
            if send_intent_recorded and not response_received:
                self._transport_event(
                    "RESPONSE_UNKNOWN",
                    role=role,
                    input_hash=run["input_hash"],
                    error_class=(
                        error.code
                        if isinstance(error, ApiError)
                        else type(error).__name__
                    ),
                )
            elif response_received and not contract_terminal_recorded:
                self._transport_event(
                    "CONTRACT_REJECTED",
                    role=role,
                    input_hash=run["input_hash"],
                    provider_response_id=run["provider_response_id"],
                    reason=(error.code if isinstance(error, ApiError) else type(error).__name__),
                )
            run.update(
                finished_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                latency_ms=max(0, round((perf_counter() - started) * 1000)),
                status=(
                    "BLOCKED"
                    if isinstance(error, ApiError)
                    and error.code in {"MODEL_LIVE_BLOCKED", "MODEL_ENDPOINT_INVALID"}
                    else "FAILED"
                    if response_received or isinstance(error, (ApiError, ValueError))
                    else "UNKNOWN"
                ),
                error_class=(
                    error.code
                    if isinstance(error, ApiError)
                    else "SCHEMA_INVALID"
                    if isinstance(error, ValueError)
                    else type(error).__name__[:100]
                ),
            )
            raise ProviderCallFailure(error, run) from error
        run.update(
            finished_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            status="COMPLETED",
            error_class=None,
        )
        return output, run
