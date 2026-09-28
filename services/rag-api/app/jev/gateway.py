"""The Jev gateway: transport, modes, bounds, receipts and typed errors.

Responsibilities (nothing else):

* injectable transport — :class:`FakeTransport` for tests,
  :class:`OpenJevTransport` for the pinned private production service, and
  :class:`DisabledTransport` for fail-local operation;
* ``off | shadow | on`` per definition key, with ``shadow`` the default;
* request size / batch / timeout / concurrency / cancel bounds;
* one call per decision, never an automatic paid retry;
* a persisted call receipt (model/version, definition, input hash, caller role,
  latency, outcome) — the transport suggestion is recorded, never auto-applied;
* typed errors only: the four required codes plus a request-bound error.

The legacy :class:`SdkTransport` remains solely so historical receipts and
isolated compatibility tests retain their original provider identity.  App
startup never constructs it and it is not an automatic fallback.  New live
traffic can only use an explicitly configured :class:`OpenJevTransport`.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import uuid4

from app.jev.catalog import Catalog, DecisionDefinition, Primitive, load_catalog
from app.jev.errors import (
    JevError,
    JevInvalidResponseError,
    JevNotConfiguredError,
    JevRequestError,
    JevTimeoutError,
    JevUnavailableError,
)
from app.jev.models import (
    CacheScope,
    JevAnswer,
    JevCall,
    JevQuestion,
    JevResult,
)
from app.jev.models import (
    input_hash as compute_input_hash,
)


@dataclass(frozen=True)
class GatewayBounds:
    """Centralized call bounds (the plan's "centralised thresholds" are separate)."""

    max_request_chars: int = 40_000
    max_batch_questions: int = 24
    timeout_seconds: float = 10.0
    max_concurrency: int = 4


# The only runtime modes a definition may be in. `shadow` records the suggestion without using it,
# `on` uses it, `off` does not even call. One source of truth, because the config validator and the
# gateway must refuse the same misspellings.
MODES: frozenset[str] = frozenset({"off", "shadow", "on"})


@dataclass(frozen=True)
class DecisionRequest:
    """Everything the gateway needs to run one decision."""

    definition: DecisionDefinition
    state: dict[str, Any]
    caller_role: str
    cache_scope: CacheScope
    # Choice: {option_id: description}; Score: None (catalog levels); Noul: None.
    criteria: dict[str, str] | list[str] | None = None
    instructions: str | None = None
    cancel_event: Any = None


@dataclass
class Receipt:
    """One persisted call record (model/version/definition/input hash/role/...)."""

    id: str
    definition_key: str
    primitive: str
    mode: str
    caller_role: str
    owner_scope_hash: str | None
    course_id: str | None
    workspace_id: str | None
    material_revision: str | None
    node_id: str | None
    spec_version: str | None
    question_hash: str | None
    input_hash: str
    output_json: str
    outcome: str
    latency_ms: float
    model_version: str | None


@dataclass
class Decision:
    """The gateway result for one decision.

    ``suggestion`` is the validated Jev answer (or ``None`` when the call was
    off, failed, or returned an invalid response). The service layer decides
    whether to *use* it — the gateway only records it.
    """

    definition_key: str
    mode: str
    outcome: str  # off | ok | cache_hit | timeout | unavailable | invalid_response | not_configured
    suggestion: JevAnswer | None
    receipt_id: str | None
    latency_ms: float | None
    model_version: str | None
    input_hash: str


class Transport(Protocol):
    def call(self, call: JevCall, *, timeout_seconds: float) -> JevResult:
        """Run one call; raise a :class:`JevError` subclass on failure."""


class FakeTransport:
    """Test transport with an injectable responder (no billing, no network)."""

    def __init__(self, responder: Any = None, *, model_version: str = "fake-1.0.0") -> None:
        self.responder = responder
        self.model_version = model_version
        self.calls: list[JevCall] = []

    def call(self, call: JevCall, *, timeout_seconds: float) -> JevResult:
        self.calls.append(call)
        if self.responder is None:
            raise JevNotConfiguredError("FakeTransport has no responder configured")
        result = self.responder(call)
        if isinstance(result, JevResult):
            if result.model_version is None:
                result.model_version = self.model_version
            return result
        if isinstance(result, Exception):
            raise result
        if isinstance(result, dict):
            return _result_from_dict(result, self.model_version)
        raise JevInvalidResponseError("FakeTransport responder returned an unknown type")


class DisabledTransport:
    """Fail locally without importing the retired TypeSafe SDK or using a network."""

    model_version = "disabled"

    def call(self, call: JevCall, *, timeout_seconds: float) -> JevResult:
        del call, timeout_seconds
        raise JevUnavailableError(
            "External TypeSafe transport is disabled; no semantic provider is configured."
        )


class OpenJevTransport:
    """One-shot authenticated adapter for the private self-hosted OpenJev service.

    The transport does not decide whether an answer is qualified for a hard
    gate.  It validates the authenticated model response and preserves the full
    distribution; the gateway/receipt admission layer applies qualification.
    No retry is installed here, so one reservation produces at most one HTTP
    inference request.
    """

    provider = "open-jev-selfhost"

    def __init__(
        self,
        *,
        endpoint: str,
        bearer_token: str,
        expected_model_revision: str,
        client: Any | None = None,
    ) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("OPENJEV_ENDPOINT must be an absolute http(s) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("OPENJEV_ENDPOINT must not contain credentials, query, or fragment")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("Plain HTTP is allowed only for a loopback OpenJev endpoint")
        if not bearer_token.strip():
            raise ValueError("OPENJEV_BEARER_TOKEN is required")
        if not expected_model_revision.strip():
            raise ValueError("OPENJEV_MODEL_REVISION is required")
        if client is None:
            import httpx

            client = httpx.Client(follow_redirects=False)
        self.endpoint = endpoint.rstrip("/")
        self.bearer_token = bearer_token
        self.expected_model_revision = expected_model_revision
        self.model_version = f"open-jev:{expected_model_revision}"
        self.client = client

    @staticmethod
    def _language(state: dict[str, Any]) -> str:
        def content(value: Any) -> list[str]:
            if isinstance(value, str):
                return [] if re.fullmatch(r"[A-Za-z0-9_.:-]+", value) else [value]
            if isinstance(value, dict):
                return [item for child in value.values() for item in content(child)]
            if isinstance(value, (list, tuple)):
                return [item for child in value for item in content(child)]
            return []

        text = " ".join(content(state))
        has_zh = bool(re.search(r"[\u3400-\u9fff]", text))
        has_latin = bool(re.search(r"[A-Za-z]", text))
        if has_zh and has_latin:
            return "mixed"
        return "zh" if has_zh else "en"

    @staticmethod
    def _scope_digest(metadata: dict[str, Any]) -> str:
        import hashlib

        payload = json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    def call(self, call: JevCall, *, timeout_seconds: float) -> JevResult:
        import httpx

        request_id = f"openjev_{uuid4().hex}"
        questions: dict[str, dict[str, Any]] = {}
        for key, question in call.questions.items():
            item: dict[str, Any] = {
                "primitive": question.primitive,
                "instructions": question.instructions,
            }
            if isinstance(question.criteria, dict):
                item["options"] = list(question.criteria)
                item["descriptions"] = dict(question.criteria)
            elif isinstance(question.criteria, list):
                item["options"] = list(question.criteria)
            questions[key] = item
        language = self._language(call.state)
        body = {
            "request_id": request_id,
            "operation_id": str(call.metadata.get("operation_id") or request_id),
            "scope_digest": self._scope_digest(call.metadata),
            "case_id": str(call.metadata.get("case_id") or next(iter(call.questions))),
            "case_version": str(call.metadata.get("case_version") or "unknown"),
            "state": call.state,
            "questions": questions,
            "source_language": language,
            "input_transform_version": "coursejesus-openjev-input.v1",
            "truncation": "error",
        }
        try:
            response = self.client.post(
                f"{self.endpoint}/v1/decisions",
                headers={
                    "authorization": f"Bearer {self.bearer_token}",
                    "content-type": "application/json",
                },
                json=body,
                timeout=timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise JevUnavailableError("Self-hosted OpenJev request failed") from error
        if response.status_code != 200:
            raise JevUnavailableError(
                f"Self-hosted OpenJev returned HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise JevInvalidResponseError("Self-hosted OpenJev returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise JevInvalidResponseError("Self-hosted OpenJev response must be an object")
        model = payload.get("model")
        input_info = payload.get("input")
        answers_payload = payload.get("answers")
        if (
            payload.get("status") != "COMPLETED"
            or payload.get("provider") != self.provider
            or not isinstance(model, dict)
            or model.get("revision") != self.expected_model_revision
            or not isinstance(input_info, dict)
            or input_info.get("truncated") is not False
            or input_info.get("source_language") != language
            or input_info.get("served_language") != ("en" if language == "en" else "mixed")
            or not isinstance(answers_payload, dict)
        ):
            raise JevInvalidResponseError("Self-hosted OpenJev response identity is invalid")
        answers: dict[str, JevAnswer] = {}
        for key, question in call.questions.items():
            value = answers_payload.get(key)
            if not isinstance(value, dict):
                raise JevInvalidResponseError(f"Self-hosted OpenJev omitted answer {key}")
            if question.primitive == Primitive.CHOICE:
                probabilities = value.get("probabilities")
                options = list(question.criteria) if isinstance(question.criteria, dict) else []
                if not _probability_distribution(probabilities, options):
                    raise JevInvalidResponseError(f"{key}: invalid probability distribution")
                selected = value.get("choice")
                if (
                    selected not in options
                    or probabilities[selected] != max(probabilities.values())
                ):
                    raise JevInvalidResponseError(
                        f"{key}: selected choice does not match distribution"
                    )
                answers[key] = JevAnswer(choice=str(selected), raw=dict(value))
            elif question.primitive == Primitive.SCORE:
                answers[key] = JevAnswer(
                    score=_normalize_score(value.get("level")), raw=dict(value)
                )
            else:
                probability = _coerce_probability(value.get("probability"))
                confidence = _coerce_probability(value.get("confidence"))
                if (
                    probability is None
                    or confidence is None
                    or abs(confidence - max(probability, 1 - probability)) > 1e-6
                ):
                    raise JevInvalidResponseError(f"{key}: invalid Noul probability contract")
                answers[key] = JevAnswer(
                    noul=probability,
                    probability=probability,
                    raw=dict(value),
                )
        return JevResult(
            answers=answers,
            request_id=str(payload.get("request_id") or request_id),
            model_version=self.model_version,
            metadata={
                "provider": self.provider,
                "model": model,
                "input": input_info,
                "timing": payload.get("timing") or {},
            },
        )


def _probability_distribution(value: Any, options: list[str]) -> bool:
    if not isinstance(value, dict) or set(value) != set(options) or len(options) < 2:
        return False
    probabilities = list(value.values())
    if any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(float(item))
        or not 0 <= float(item) <= 1
        for item in probabilities
    ):
        return False
    return abs(sum(float(item) for item in probabilities) - 1) <= 1e-6


class SdkTransport:
    """Live adapter over ``typesafe-sdk`` (verified signature only).

    Unconfigured (no ``TYPESAFE_API_KEY`` in the environment and none passed in)
    or missing SDK raises :class:`JevNotConfiguredError` before any network access,
    so the live path is a real adapter that fails typed and never invents a
    request. ``TYPESAFE_DEFAULT_MODEL`` overrides the model id, which is the name
    the SDK itself reads, and the default is the SDK's own ``jev-latest``.
    """

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        # The SDK resolves its own credential from the environment, so this
        # guard has to look in the same place: the service builds
        # ``SdkTransport()`` with no arguments, while the ablation CLI passes a
        # key explicitly and that still wins. Before this, the guard always
        # fired in the service, so putting the key in the protected env -- the
        # documented owner action -- could not enable the live path at all.
        # Checked against the 0.7.0 wheel: ``constants.API_KEY_ENV`` is exactly
        # this name and ``Config.resolve`` reads it, so guard and SDK agree.
        self.api_key = (
            api_key if api_key is not None else os.environ.get("TYPESAFE_API_KEY")
        )
        # Same wheel, same check, and two earlier errors corrected here: the SDK
        # reads ``constants.DEFAULT_MODEL_ENV == "TYPESAFE_DEFAULT_MODEL"`` (not
        # ``TYPESAFE_MODEL``, which no one reads) and its own default model is
        # ``constants.DEFAULT_MODEL == "jev-latest"`` (not the ``"jev"`` this
        # adapter used to pin, which would have asked for a model id the SDK
        # does not default to).
        resolved_model = (
            model or os.environ.get("TYPESAFE_DEFAULT_MODEL") or "jev-latest"
        )
        self.model = resolved_model
        self.model_version = resolved_model

    def call(self, call: JevCall, *, timeout_seconds: float) -> JevResult:
        if not self.api_key:
            raise JevNotConfiguredError(
                "TypeSafe API key is not configured; the live Jev path is unavailable."
            )
        try:
            from typesafe_sdk import Choice, Noul, RetryPolicy, Score, TypeSafeClient
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise JevUnavailableError(
                "typesafe-sdk is not installed; cannot reach the live Jev API."
            ) from exc

        questions: dict[str, Any] = {}
        for key, question in call.questions.items():
            if question.primitive == Primitive.CHOICE:
                choice_criteria = (
                    question.criteria if isinstance(question.criteria, dict) else {}
                )
                questions[key] = Choice(
                    instructions=question.instructions,
                    criteria=dict(choice_criteria),
                )
            elif question.primitive == Primitive.SCORE:
                questions[key] = Score(
                    instructions=question.instructions,
                    criteria=list(question.criteria or []),
                )
            else:
                questions[key] = Noul(instructions=question.instructions)

        try:
            # P5 acceptance requires one observable transport attempt per
            # reservation.  The SDK's default policy may retry transient
            # failures, which would make both billing and UNKNOWN recovery
            # ambiguous, so retries are explicitly disabled here.
            client = TypeSafeClient(
                api_key=self.api_key,
                model=self.model,
                retry=RetryPolicy(max_retries=0),
                timeout=timeout_seconds,
            )
            result = client.system_one(call.state, questions)
        except Exception as exc:  # noqa: BLE001 - any transport failure fails closed
            raise JevUnavailableError(f"TypeSafe Jev call failed: {exc}") from exc

        answers: dict[str, JevAnswer] = {}
        for key, question in call.questions.items():
            answer = JevAnswer(raw={})
            if question.primitive == Primitive.CHOICE:
                answer.choice = getattr(result.choices[key], "choice", None)
            elif question.primitive == Primitive.SCORE:
                answer.score = _normalize_score(getattr(result.scores[key], "score", None))
            else:
                value = getattr(result.nouls[key], "noul", None)
                answer.noul = _coerce_probability(value)
            answers[key] = answer
        return JevResult(
            answers=answers,
            request_id=getattr(result, "request_id", None),
            model_version=self.model,
        )


def _result_from_dict(payload: dict[str, Any], model_version: str) -> JevResult:
    """Build a :class:`JevResult` from a plain dict (used by tests)."""
    raw = payload.get("answers") or payload
    answers: dict[str, JevAnswer] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        answers[key] = JevAnswer(
            choice=value.get("choice"),
            noul=_coerce_probability(value.get("noul")),
            score=_normalize_score(value.get("score")),
            probability=_coerce_probability(value.get("probability")),
            raw=dict(value),
        )
    return JevResult(
        answers=answers,
        request_id=payload.get("request_id"),
        model_version=payload.get("model_version") or model_version,
    )


def _score_within_scale(definition: DecisionDefinition, value: Any) -> float | None:
    """The numeric score when it lies inside the definition's declared scale, else None.

    The scale is the definition's own: the numeric range its level keys span (`0..4`, `0..3`,
    `0..2`). A live answer inside that range is a legitimate answer and is carried as the
    provider's own number.

    Deliberately **not** done here: choosing which level the number is. `3.99` is only level `4`
    once the boundaries between levels have been calibrated on labelled data — the catalogue's own
    `thresholds` field says `UNSET_UNTIL_CALIBRATED_ON_LABELLED_DATA` — so this function returns the
    number and leaves `score` unset. A definition whose level keys are not numeric has no numeric
    scale, and a decimal for it is refused exactly as before.
    """
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not definition.score_levels:
        return None
    try:
        bounds = sorted(float(level) for level in definition.score_levels)
    except (TypeError, ValueError):
        return None
    low, high = bounds[0], bounds[-1]
    if low <= numeric <= high:
        return numeric
    return None


def _normalize_score(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        return str(value)
    return str(value)


def _coerce_probability(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class ReceiptStore(Protocol):
    def save(self, receipt: Receipt) -> None: ...

    def lookup(
        self,
        definition: DecisionDefinition,
        cache_scope: CacheScope,
        *,
        provider_model_version: str | None,
    ) -> dict[str, Any] | None: ...


class JevGateway:
    """The single entry point for semantic decisions."""

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        catalog: Catalog | None = None,
        modes: dict[str, str] | None = None,
        bounds: GatewayBounds | None = None,
        receipt_store: ReceiptStore | None = None,
        default_mode: str | None = None,
    ) -> None:
        self.catalog = catalog or load_catalog()
        # TypeSafe is no longer an automatic live fallback.  Deployments must
        # explicitly inject OpenJevTransport after pinning a local model.
        self.transport: Transport = transport or DisabledTransport()
        self.modes = modes or {}
        self.bounds = bounds or GatewayBounds()
        self.receipt_store = receipt_store
        self.default_mode = default_mode or self.catalog.default_runtime_mode
        self._executor = ThreadPoolExecutor(max_workers=self.bounds.max_concurrency)

    def mode_for(self, definition_key: str) -> str:
        mode = self.modes.get(definition_key, self.default_mode)
        if mode not in MODES:
            raise JevRequestError(f"Unknown Jev mode {mode!r} for {definition_key}")
        return mode

    # ------------------------------------------------------------------ evaluate

    def evaluate(self, request: DecisionRequest) -> Decision:
        definition = request.definition
        mode = self.mode_for(definition.key)
        # The input hash covers the authorized inputs AND the Choice criteria /
        # per-candidate instructions, so two different candidate sets can never
        # collide in the cache or the receipt ledger.
        digest = compute_input_hash(
            definition.key,
            {
                "state": request.state,
                "criteria": request.criteria,
                "instructions": request.instructions,
            },
        )
        scope = replace(request.cache_scope, input_hash=digest)
        if mode == "off":
            return Decision(
                definition_key=definition.key,
                mode=mode,
                outcome="off",
                suggestion=None,
                receipt_id=None,
                latency_ms=None,
                model_version=None,
                input_hash=digest,
            )
        question = self._build_question(definition, request)
        self._enforce_bounds(definition, request.state, [question], request.cancel_event)
        provider_model_version = (
            scope.provider_model_version or getattr(self.transport, "model_version", None)
        )
        if self.receipt_store is not None:
            cached = self.receipt_store.lookup(
                definition, scope, provider_model_version=provider_model_version
            )
            if cached is not None:
                suggestion: JevAnswer | None = self._suggestion_from_cache(
                    definition, cached
                )
                return Decision(
                    definition_key=definition.key,
                    mode=mode,
                    outcome="cache_hit",
                    suggestion=suggestion,
                    receipt_id=None,
                    latency_ms=None,
                    model_version=cached.get("model_version") or provider_model_version,
                    input_hash=digest,
                )
        started = perf_counter()
        call = JevCall(
            state=request.state,
            questions={question.key: question},
            metadata={
                "case_id": definition.key,
                "case_version": self.catalog.version,
                "owner_scope_hash": scope.owner_scope_hash,
                "course_id": scope.course_id,
                "workspace_id": scope.workspace_id,
                "material_revision": scope.material_revision,
                "node_id": scope.node_id,
                "spec_version": scope.spec_version,
                "question_hash": scope.question_hash,
                "input_hash": digest,
            },
        )
        try:
            result = self._run_call(call, request.cancel_event)
        except JevTimeoutError:
            return self._failed(
                definition, scope, request.caller_role, mode, "timeout", digest,
                perf_counter() - started,
            )
        except JevNotConfiguredError:
            return self._failed(
                definition, scope, request.caller_role, mode, "not_configured", digest,
                perf_counter() - started,
            )
        except JevError:
            return self._failed(
                definition, scope, request.caller_role, mode, "unavailable", digest,
                perf_counter() - started,
            )
        except Exception:  # noqa: BLE001 - unknown transport failure fails closed
            return self._failed(
                definition, scope, request.caller_role, mode, "unavailable", digest,
                perf_counter() - started,
            )

        latency_ms = (perf_counter() - started) * 1000
        answer = result.answers.get(question.key)
        try:
            suggestion = self._validate(definition, answer, request.criteria, question.key)
            outcome = "ok"
        except JevInvalidResponseError:
            suggestion = None
            outcome = "invalid_response"
        receipt_id = self._record(
            definition,
            scope,
            request.caller_role,
            mode,
            digest,
            suggestion,
            outcome,
            latency_ms,
            result.model_version,
            provider_request_id=result.request_id,
            provider_metadata=result.metadata,
        )
        return Decision(
            definition_key=definition.key,
            mode=mode,
            outcome=outcome,
            suggestion=suggestion,
            receipt_id=receipt_id,
            latency_ms=latency_ms,
            model_version=result.model_version,
            input_hash=digest,
        )

    def evaluate_batch(self, requests: Sequence[DecisionRequest]) -> list[Decision]:
        """Bound a batch of independent decisions; each item stays one call."""
        if len(requests) > self.bounds.max_batch_questions:
            raise JevRequestError(
                f"Jev batch of {len(requests)} exceeds max_batch_questions="
                f"{self.bounds.max_batch_questions}"
            )
        return [self.evaluate(request) for request in requests]

    # ------------------------------------------------------------------ internals

    def _build_question(
        self, definition: DecisionDefinition, request: DecisionRequest
    ) -> JevQuestion:
        instructions = request.instructions or definition.instructions
        if definition.primitive == Primitive.CHOICE:
            criteria = request.criteria
            if not criteria or not isinstance(criteria, dict):
                raise JevRequestError(
                    f"{definition.key}: Choice requires an id->label criteria dict"
                )
            return JevQuestion(
                key=request.definition.key,
                primitive=Primitive.CHOICE,
                instructions=instructions,
                criteria=dict(criteria),
            )
        if definition.primitive == Primitive.SCORE:
            score_criteria = definition.criteria or {}
            levels = [score_criteria[level] for level in definition.score_levels]
            return JevQuestion(
                key=request.definition.key,
                primitive=Primitive.SCORE,
                instructions=instructions,
                criteria=levels,
            )
        return JevQuestion(
            key=request.definition.key,
            primitive=Primitive.NOUL,
            instructions=instructions,
            criteria=None,
        )

    def _enforce_bounds(
        self,
        definition: DecisionDefinition,
        state: dict[str, Any],
        questions: Sequence[JevQuestion],
        cancel_event: Any,
    ) -> None:
        if len(questions) > self.bounds.max_batch_questions:
            raise JevRequestError("Jev batch exceeds max_batch_questions")
        size = len(json.dumps({"state": state, "questions": len(questions)}, default=str))
        if size > self.bounds.max_request_chars:
            raise JevRequestError(
                f"{definition.key}: request size {size} exceeds max_request_chars="
                f"{self.bounds.max_request_chars}"
            )
        if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
            raise JevRequestError(f"{definition.key}: call was cancelled")

    def _run_call(self, call: JevCall, cancel_event: Any) -> JevResult:
        future = self._executor.submit(
            self.transport.call, call, timeout_seconds=self.bounds.timeout_seconds
        )
        try:
            return future.result(timeout=self.bounds.timeout_seconds)
        except FutureTimeout:
            future.cancel()
            raise JevTimeoutError(
                f"Jev call exceeded timeout_seconds={self.bounds.timeout_seconds}"
            ) from None

    def _validate(
        self,
        definition: DecisionDefinition,
        answer: JevAnswer | None,
        criteria: dict[str, str] | list[str] | None,
        question_key: str,
    ) -> JevAnswer:
        if answer is None:
            raise JevInvalidResponseError(f"{definition.key}: transport returned no answer")
        if definition.primitive == Primitive.CHOICE:
            # The request layer already enforces an id -> label mapping for Choice
            # (``_build_question`` raises JevRequestError otherwise), so a mapping is
            # the only shape reachable here. Naming the mapping explicitly keeps the
            # invariant visible to the type checker; a non-mapping would degrade to
            # the typed invalid_response below rather than raise AttributeError.
            authorized = set(criteria) if isinstance(criteria, dict) else set()
            if not answer.choice or answer.choice not in authorized:
                raise JevInvalidResponseError(
                    f"{definition.key}: selected {answer.choice!r} is not an "
                    "authorized candidate id"
                )
            return JevAnswer(choice=answer.choice, raw=answer.raw)
        if definition.primitive == Primitive.SCORE:
            level = answer.score
            if level is None:
                raise JevInvalidResponseError(f"{definition.key}: missing score level")
            if level not in definition.score_levels:
                # The SDK's `.score` return type is unverified in two ways, and both were measured
                # against the live service rather than guessed at: it may return a level
                # *description* (mapped back to its ordered key below), or a **decimal on the
                # definition's own scale** — `3.99` for a 0..4 definition, `2.0` for a 0..2 one.
                by_description = {v: k for k, v in (definition.criteria or {}).items()}
                if level in by_description:
                    level = by_description[level]
                else:
                    value = _score_within_scale(definition, level)
                    if value is None:
                        raise JevInvalidResponseError(
                            f"{definition.key}: score level {level!r} not in "
                            f"{definition.score_levels}"
                        )
                    return JevAnswer(score=None, score_value=value, raw=answer.raw)
            return JevAnswer(score=level, raw=answer.raw)
        probability = answer.noul
        if probability is None or not (0.0 <= probability <= 1.0):
            raise JevInvalidResponseError(
                f"{definition.key}: noul {probability!r} is not a probability in [0, 1]"
            )
        return JevAnswer(noul=probability, probability=probability, raw=answer.raw)

    def _record(
        self,
        definition: DecisionDefinition,
        scope: CacheScope,
        caller_role: str,
        mode: str,
        digest: str,
        suggestion: JevAnswer | None,
        outcome: str,
        latency_ms: float,
        model_version: str | None,
        *,
        provider_request_id: str | None = None,
        provider_metadata: dict[str, Any] | None = None,
    ) -> str | None:
        if self.receipt_store is None:
            return None
        output = _suggestion_payload(
            suggestion,
            outcome=outcome,
            model_version=model_version,
            provider_request_id=provider_request_id,
            provider_metadata=provider_metadata,
        )
        receipt = Receipt(
            id=f"jev_{uuid4().hex}",
            definition_key=definition.key,
            primitive=definition.primitive,
            mode=mode,
            caller_role=caller_role,
            owner_scope_hash=scope.owner_scope_hash,
            course_id=scope.course_id,
            workspace_id=scope.workspace_id,
            material_revision=scope.material_revision,
            node_id=scope.node_id,
            spec_version=scope.spec_version,
            question_hash=scope.question_hash,
            input_hash=digest,
            output_json=json.dumps(output, ensure_ascii=False, sort_keys=True, default=str),
            outcome=outcome,
            latency_ms=round(latency_ms, 3),
            model_version=model_version,
        )
        self.receipt_store.save(receipt)
        return receipt.id

    def _failed(
        self,
        definition: DecisionDefinition,
        scope: CacheScope,
        caller_role: str,
        mode: str,
        outcome: str,
        digest: str,
        latency_ms: float,
    ) -> Decision:
        self._record(definition, scope, caller_role, mode, digest, None, outcome, latency_ms, None)
        return Decision(
            definition_key=definition.key,
            mode=mode,
            outcome=outcome,
            suggestion=None,
            receipt_id=None,
            latency_ms=round(latency_ms, 3),
            model_version=None,
            input_hash=digest,
        )

    def _suggestion_from_cache(
        self, definition: DecisionDefinition, cached: dict[str, Any]
    ) -> JevAnswer:
        if definition.primitive == Primitive.CHOICE:
            return JevAnswer(choice=cached.get("choice"), raw=cached)
        if definition.primitive == Primitive.SCORE:
            raw_value = cached.get("score_value")
            return JevAnswer(
                score=cached.get("score"),
                score_value=(
                    float(raw_value)
                    if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool)
                    else None
                ),
                raw=cached,
            )
        probability = _coerce_probability(cached.get("noul", cached.get("probability")))
        return JevAnswer(noul=probability, probability=probability, raw=cached)


def _suggestion_payload(
    suggestion: JevAnswer | None,
    *,
    outcome: str,
    model_version: str | None,
    provider_request_id: str | None = None,
    provider_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identity = {
        "outcome": outcome,
        "model_version": model_version,
        "provider_request_id": provider_request_id,
        "provider_metadata": provider_metadata or {},
    }
    if suggestion is None:
        return identity
    return identity | {
        "choice": suggestion.choice,
        "noul": suggestion.noul,
        "score": suggestion.score,
        "score_value": suggestion.score_value,
        "probability": suggestion.probability,
        "raw": suggestion.raw,
    }
