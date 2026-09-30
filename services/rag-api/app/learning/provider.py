import base64
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter
from typing import Any, Final, Literal, TypeVar
from urllib.parse import urlsplit

from openai import OpenAI
from pydantic import BaseModel, ValidationError

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
from app.provider_client import ProviderTimeouts, build_openai_client, timeouts_for

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
    """Carries safe call metadata without retaining private prompt bodies.

    The run record also carries the call's own failure taxonomy -- error_class,
    terminal status, the HTTP status when there was one, the exception chain and,
    when a response did arrive, the response text.  A complete response that
    failed schema validation is not an upstream outage, and without these fields
    that distinction is unenforceable after the fact.
    """

    def __init__(self, cause: Exception, run: dict[str, Any]) -> None:
        super().__init__(type(cause).__name__)
        self.cause = cause
        self.run = run


# The named layers a provider call can fail in.  They are deliberately about
# *where* the failure happened, not how bad it was: a local input-validation
# failure and an upstream outage both stop a run, and conflating them is what
# makes "provider failure rate" meaningless.
FAILURE_LAYER_LOCAL_INPUT_VALIDATION: Final = "LOCAL_INPUT_VALIDATION"
FAILURE_LAYER_LOCAL_CONFIGURATION: Final = "LOCAL_CONFIGURATION"
FAILURE_LAYER_LOCAL_DURABILITY: Final = "LOCAL_DURABILITY"
FAILURE_LAYER_HTTP_OR_PERMISSION: Final = "HTTP_OR_PERMISSION"
FAILURE_LAYER_UPSTREAM_TRANSPORT: Final = "UPSTREAM_TRANSPORT"
FAILURE_LAYER_PROVIDER_INCOMPLETE: Final = "PROVIDER_INCOMPLETE"
FAILURE_LAYER_PROVIDER_EMPTY_OR_REFUSAL: Final = "PROVIDER_EMPTY_OR_REFUSAL"
FAILURE_LAYER_RESPONSE_SCHEMA: Final = "RESPONSE_SCHEMA"
FAILURE_LAYER_SEMANTIC_OR_REFERENCE: Final = "SEMANTIC_OR_REFERENCE"
FAILURE_LAYER_UNKNOWN: Final = "UNKNOWN"

FAILURE_LAYERS: Final = (
    FAILURE_LAYER_LOCAL_INPUT_VALIDATION,
    FAILURE_LAYER_LOCAL_CONFIGURATION,
    FAILURE_LAYER_LOCAL_DURABILITY,
    FAILURE_LAYER_HTTP_OR_PERMISSION,
    FAILURE_LAYER_UPSTREAM_TRANSPORT,
    FAILURE_LAYER_PROVIDER_INCOMPLETE,
    FAILURE_LAYER_PROVIDER_EMPTY_OR_REFUSAL,
    FAILURE_LAYER_RESPONSE_SCHEMA,
    FAILURE_LAYER_SEMANTIC_OR_REFERENCE,
    FAILURE_LAYER_UNKNOWN,
)

# ApiError codes the adapter raises itself, and the layer each belongs to.
_LOCAL_ERROR_LAYERS: Final[dict[str, str]] = {
    "MODEL_LIVE_BLOCKED": FAILURE_LAYER_LOCAL_CONFIGURATION,
    "MODEL_ENDPOINT_INVALID": FAILURE_LAYER_LOCAL_CONFIGURATION,
    "CONTEXT_BUDGET": FAILURE_LAYER_LOCAL_INPUT_VALIDATION,
    "IMAGE_MODEL_LIMIT": FAILURE_LAYER_LOCAL_INPUT_VALIDATION,
    "MODEL_OUTPUT_LIMIT_INVALID": FAILURE_LAYER_LOCAL_INPUT_VALIDATION,
    "MODEL_EMPTY_OUTPUT": FAILURE_LAYER_PROVIDER_EMPTY_OR_REFUSAL,
    "MODEL_INCOMPLETE": FAILURE_LAYER_PROVIDER_INCOMPLETE,
    "AUTO_LEDGER_WRITE_FAILED": FAILURE_LAYER_LOCAL_DURABILITY,
}
_SCHEMA_ERROR_CLASSES: Final[frozenset[str]] = frozenset({"SCHEMA_INVALID", "ValidationError"})
_TRANSPORT_ERROR_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "APITimeoutError",
        "APIConnectionError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "RemoteProtocolError",
        "InternalServerError",
        "ServiceUnavailableError",
        "APIError",
    }
)
_HTTP_ERROR_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "APIStatusError",
        "BadRequestError",
        "AuthenticationError",
        "PermissionDeniedError",
        "NotFoundError",
        "UnprocessableEntityError",
        "RateLimitError",
        "ConflictError",
    }
)


def classify_failure_layer(*, error_class: str, status: str) -> str:
    """Name the layer a failed call failed in, from the recorded facts only.

    An unknown code is reported as UNKNOWN rather than being folded into the
    nearest-sounding bucket: an unattributed failure is a fact worth keeping.
    """
    if status == "BLOCKED":
        return _LOCAL_ERROR_LAYERS.get(error_class, FAILURE_LAYER_LOCAL_CONFIGURATION)
    if error_class in _LOCAL_ERROR_LAYERS:
        return _LOCAL_ERROR_LAYERS[error_class]
    if error_class in _SCHEMA_ERROR_CLASSES:
        return FAILURE_LAYER_RESPONSE_SCHEMA
    if error_class in _TRANSPORT_ERROR_CLASSES:
        return FAILURE_LAYER_UPSTREAM_TRANSPORT
    if error_class in _HTTP_ERROR_CLASSES:
        return FAILURE_LAYER_HTTP_OR_PERMISSION
    return FAILURE_LAYER_UNKNOWN


def _cause_chain(error: BaseException, *, limit: int = 4) -> list[str]:
    """The exception type chain, which is where an httpx timeout shows itself."""
    chain: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and len(chain) < limit and id(current) not in seen:
        seen.add(id(current))
        chain.append(type(current).__name__)
        current = current.__cause__ or current.__context__
    return chain


def _timeout_kind(error: BaseException) -> str | None:
    """Which timeout fired, when the chain names one."""
    for name in _cause_chain(error):
        folded = name.casefold()
        if "timeout" in folded:
            if "connect" in folded:
                return "CONNECT"
            if "read" in folded:
                return "READ"
            if "write" in folded:
                return "WRITE"
            if "pool" in folded:
                return "POOL"
            return "UNSPECIFIED"
    return None


def repair_stray_quotes(candidate: str) -> str | None:
    """Escape quote characters that were meant to sit inside a string value.

    A model writing prose inside a JSON string sometimes emits a bare quote --
    quoting another solution's step numbering, say -- which ends the string early and
    makes the whole document unparseable.  A live review was lost exactly that way,
    and because the response was otherwise complete and well terminated, the parse
    failure surfaced as a schema rejection and read like a content problem.

    Only a quote that cannot be structural is escaped: one not followed by the
    punctuation that ends a key or a value.  The repaired text is returned only when
    it actually parses, so a guess is never passed on, and the caller still validates
    whatever comes back against its schema.  Backslash escapes already present are
    copied through untouched.
    """
    out: list[str] = []
    in_string = False
    index = 0
    length = len(candidate)
    while index < length:
        char = candidate[index]
        if in_string and char == "\\":
            out.append(candidate[index : index + 2])
            index += 2
            continue
        if char == '"':
            if not in_string:
                in_string = True
                out.append(char)
            else:
                rest = candidate[index + 1 :].lstrip()
                if rest[:1] in {":", ",", "}", "]", ""}:
                    in_string = False
                    out.append(char)
                else:
                    out.append('\\"')
            index += 1
            continue
        out.append(char)
        index += 1
    repaired = "".join(out)
    try:
        json.loads(repaired)
    except ValueError:
        return None
    return repaired


def extract_json_object(text: str) -> str | None:
    """The one JSON object a response body contains, if it contains one.

    Only the outermost balanced object is returned, and only when the text has a
    single candidate: a body with two objects is ambiguous, so it is left alone and
    refused as before.  The result is validated by the caller against the same
    schema, so this changes what is *parsed*, never what is *accepted*.
    """
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        # A bare object is normally left to the caller's schema check.  One that does
        # not parse at all is different: it never reaches the schema, so the failure
        # is reported as a content rejection when it is a syntax one.  Repaired only
        # when the repair demonstrably parses.
        return repair_stray_quotes(stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end <= start:
        return None
    candidate = stripped[start : end + 1]
    if candidate.count("{") != candidate.count("}"):
        return None
    try:
        json.loads(candidate)
    except ValueError:
        return repair_stray_quotes(candidate)
    return candidate


def schema_error_summary(error: Any, *, limit: int = 12) -> list[str]:
    """Bounded, value-free description of a pydantic schema rejection.

    Format is "field.path: error_kind", for example
    "task_contract.facts.0.role: literal_error".  The offending value is
    deliberately not included: it is model output derived from private course
    material, and the field is what a diagnosis needs.
    """
    entries: list[str] = []
    for item in getattr(error, "errors", lambda: [])():
        location = ".".join(str(part) for part in item.get("loc", ())) or "<root>"
        entries.append(f"{location}: {item.get('type', 'unknown')}")
        if len(entries) >= limit:
            break
    return entries


def _http_status(error: BaseException) -> int | None:
    for candidate in (error, error.__cause__):
        value = getattr(candidate, "status_code", None)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
    return None


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
        # The phase budgets this provider may use, recorded on every run.
        self.timeouts: ProviderTimeouts = ProviderTimeouts()
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

    def _timeouts_for_run(self, max_output_tokens: int) -> ProviderTimeouts:
        """The policy this call will use, once the output budget is known.

        A larger output budget legitimately needs a longer read, so the read and
        write budgets follow the configured model timeout, widened when the caller
        asks for more than the configured maximum.  Every value stays finite.
        """
        configured = float(self.settings.v3_model_timeout_seconds)
        extra = max(0, max_output_tokens - self.settings.v3_max_output_tokens)
        # Roughly one second of generation per extra thousand tokens, which is a
        # bounded allowance rather than an open-ended one.
        allowance = configured + (extra / 1000.0)
        return timeouts_for(read_seconds=allowance, write_seconds=allowance)

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
        max_output_tokens: int | None = None,
        transport_event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[Output, dict[str, Any]]:
        settings = self.settings
        safe_images = images or []
        effective_max_output_tokens = (
            settings.v3_max_output_tokens
            if max_output_tokens is None
            else max_output_tokens
        )
        if not 500 <= effective_max_output_tokens <= 8_000:
            raise ApiError(
                422,
                "MODEL_OUTPUT_LIMIT_INVALID",
                "The model output-token limit must be between 500 and 8000.",
            )

        def emit(phase: str, **values: Any) -> None:
            event = {"phase": phase, **values}
            # A per-call durability sink is part of the request's safety
            # boundary and therefore runs first.  An optional diagnostic sink
            # may observe the same event but cannot replace durable evidence.
            if transport_event_sink is not None:
                transport_event_sink(event)
            if (
                self.transport_event_sink is not None
                and self.transport_event_sink is not transport_event_sink
            ):
                self.transport_event_sink(event)

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
            # What this call was allowed to take, per phase.  Recorded rather than
            # assumed, because the SDK default was 5 s connect against 600 s read
            # and neither number appeared anywhere.
            "timeouts": self._timeouts_for_run(effective_max_output_tokens).as_receipt(),
        }
        response_received = False
        send_intent_recorded = False
        contract_terminal_recorded = False
        raw_output_text: str | None = None
        rejection_summary: list[str] | None = None
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
                    # The model timeout is the read budget, not the whole story: the
                    # connect, write and pool budgets are explicit too, and the
                    # policy object is recorded in the run so a receipt says what
                    # the call was allowed to take.
                    self.timeouts = timeouts_for(
                        read_seconds=settings.v3_model_timeout_seconds,
                        write_seconds=settings.v3_model_timeout_seconds,
                    )
                    self.client = build_openai_client(
                        api_key=settings.v3_model_api_key.get_secret_value(),
                        base_url=base_url,
                        timeouts=self.timeouts,
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
                emit(
                    "SEND_INTENT",
                    provider=run["provider"],
                    model=self.model,
                    protocol="responses",
                    role=role,
                    input_hash=run["input_hash"],
                    template_version=template_version,
                    schema_version=schema_version or schema.__name__,
                    max_output_tokens=effective_max_output_tokens,
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
                        max_output_tokens=effective_max_output_tokens,
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
                        max_output_tokens=effective_max_output_tokens,
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
                emit(
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
                    emit(
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
                if not raw_output_text or not raw_output_text.strip():
                    # An empty body from a call that reported itself complete is
                    # its own failure: it is not a schema defect in our request and
                    # it is not an upstream outage, and calling it SCHEMA_INVALID
                    # would hide a provider-side refusal.
                    emit(
                        "CONTRACT_REJECTED",
                        role=role,
                        input_hash=run["input_hash"],
                        provider_response_id=response.id,
                        reason="MODEL_EMPTY_OUTPUT",
                    )
                    contract_terminal_recorded = True
                    raise ApiError(
                        502,
                        "MODEL_EMPTY_OUTPUT",
                        "A completed response carried no output text.",
                    )
                # The complete response and the rejection reason are kept in
                # *local* variables, not in the run.  The run is the receipt shape
                # that AuthorProviderRun and StrongReviewRun validate with
                # extra="forbid", so writing a diagnostic key into it made every
                # live call fail validation -- which is exactly what the staging
                # probe caught.  They are attached to the failure below, where the
                # run is read rather than validated.
                try:
                    output = schema.model_validate_json(raw_output_text)
                except ValidationError as schema_error:
                    # A complete response whose body is not parseable JSON can still
                    # contain exactly one JSON object wrapped in prose or a fence.
                    # Extracting it is not a relaxation: the extracted text is
                    # validated against the same schema, so a response that does not
                    # satisfy the contract is refused exactly as before.  One
                    # measured run lost a paid call to "<root>: json_invalid".
                    extracted = extract_json_object(raw_output_text)
                    if extracted is None:
                        rejection_summary = schema_error_summary(schema_error)
                        raise
                    try:
                        output = schema.model_validate_json(extracted)
                    except ValidationError:
                        rejection_summary = schema_error_summary(schema_error)
                        raise schema_error from None
                    emit(
                        "RESPONSE_EXTRACTED_JSON",
                        role=role,
                        input_hash=run["input_hash"],
                        provider_response_id=response.id,
                        response_chars=len(raw_output_text),
                        extracted_chars=len(extracted),
                    )
                    rejection_summary = None
                else:
                    rejection_summary = None
                emit(
                    "CONTRACT_VALID",
                    role=role,
                    input_hash=run["input_hash"],
                    provider_response_id=response.id,
                    schema_version=schema_version or schema.__name__,
                )
                contract_terminal_recorded = True
        except Exception as error:
            try:
                if send_intent_recorded and not response_received:
                    emit(
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
                    emit(
                        "CONTRACT_REJECTED",
                        role=role,
                        input_hash=run["input_hash"],
                        provider_response_id=run["provider_response_id"],
                        reason=(
                            error.code
                            if isinstance(error, ApiError)
                            else type(error).__name__
                        ),
                    )
            except Exception as evidence_error:
                # A response whose durable evidence transition failed is
                # uncertain even when the provider transport itself returned.
                # Preserve that fact and never let an observer failure trigger
                # an automatic paid retry.
                error = evidence_error
            ledger_failed = (
                isinstance(error, ApiError)
                and error.code == "AUTO_LEDGER_WRITE_FAILED"
            )
            terminal_status = (
                "UNKNOWN"
                if ledger_failed
                else
                "BLOCKED"
                if isinstance(error, ApiError)
                and error.code in {"MODEL_LIVE_BLOCKED", "MODEL_ENDPOINT_INVALID"}
                else "FAILED"
                if response_received or isinstance(error, (ApiError, ValueError))
                else "UNKNOWN"
            )
            error_class = (
                error.code
                if isinstance(error, ApiError)
                else "SCHEMA_INVALID"
                if isinstance(error, ValueError)
                else type(error).__name__[:100]
            )
            run.update(
                finished_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                latency_ms=max(0, round((perf_counter() - started) * 1000)),
                status=terminal_status,
                error_class=error_class,
                # The facts needed to attribute the failure, recorded at the only
                # place that still has them.
                failure_layer=classify_failure_layer(
                    error_class=error_class, status=terminal_status
                ),
                http_status=_http_status(error),
                timeout_kind=_timeout_kind(error),
                cause_chain=_cause_chain(error),
                response_received=response_received,
                max_output_tokens=effective_max_output_tokens,
                schema_error_summary=rejection_summary,
                response_digest=(
                    sha256(raw_output_text.encode()).hexdigest()
                    if isinstance(raw_output_text, str)
                    else None
                ),
                # Persisted here and nowhere else: a failure keeps the complete
                # response so it can be re-parsed offline, and a success does not
                # carry it into the receipt.
                response_text=raw_output_text if response_received else None,
            )
            raise ProviderCallFailure(error, run) from error
        run.update(
            finished_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            status="COMPLETED",
            error_class=None,
        )
        return output, run
