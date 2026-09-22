"""The Jev gateway: transport, modes, bounds, receipts and typed errors.

Responsibilities (nothing else):

* injectable transport — :class:`FakeTransport` for tests, :class:`SdkTransport`
  for the live path (a real adapter over the verified ``typesafe-sdk`` signature
  that raises :class:`JevNotConfiguredError` when no credential exists);
* ``off | shadow | on`` per definition key, with ``shadow`` the default;
* request size / batch / timeout / concurrency / cancel bounds;
* one call per decision, never an automatic paid retry;
* a persisted call receipt (model/version, definition, input hash, caller role,
  latency, outcome) — the transport suggestion is recorded, never auto-applied;
* typed errors only: the four required codes plus a request-bound error.

The SDK is imported lazily inside :class:`SdkTransport` so the package has no
third-party runtime import, and only the fields verified against
``docs.typesafe.ai`` are used (``TypeSafeClient(model=...).system_one(state,
questions)`` with ``Choice(instructions, criteria=dict)``,
``Score(instructions, criteria=list)``, ``Noul(instructions)`` and the
``.choices/.nouls/.scores`` accessors). No endpoint, model id, timeout or limit
is invented.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Any, Protocol, Sequence
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
    input_hash as compute_input_hash,
)


@dataclass(frozen=True)
class GatewayBounds:
    """Centralized call bounds (the plan's "centralised thresholds" are separate)."""

    max_request_chars: int = 40_000
    max_batch_questions: int = 24
    timeout_seconds: float = 10.0
    max_concurrency: int = 4


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


class SdkTransport:
    """Live adapter over ``typesafe-sdk`` (verified signature only).

    Unconfigured (no ``TYPESAFE_API_KEY`` in the environment and none passed in)
    or missing SDK raises :class:`JevNotConfiguredError` before any network access,
    so the live path is a real adapter that fails typed and never invents a
    request. ``TYPESAFE_MODEL`` overrides the verified default model id when the
    account needs a different one.
    """

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        # The SDK resolves its own credential from the environment, so this
        # guard has to look in the same place: the service builds
        # ``SdkTransport()`` with no arguments, while the ablation CLI passes a
        # key explicitly and that still wins. Before this, the guard always
        # fired in the service, so putting the key in the protected env -- the
        # documented owner action -- could not enable the live path at all.
        self.api_key = (
            api_key if api_key is not None else os.environ.get("TYPESAFE_API_KEY")
        )
        resolved_model = model or os.environ.get("TYPESAFE_MODEL") or "jev"
        self.model = resolved_model
        self.model_version = resolved_model

    def call(self, call: JevCall, *, timeout_seconds: float) -> JevResult:
        if not self.api_key:
            raise JevNotConfiguredError(
                "TypeSafe API key is not configured; the live Jev path is unavailable."
            )
        try:
            from typesafe_sdk import Choice, Noul, Score, TypeSafeClient
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
            client = TypeSafeClient(model=self.model)
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
        self.transport: Transport = transport or SdkTransport()
        self.modes = modes or {}
        self.bounds = bounds or GatewayBounds()
        self.receipt_store = receipt_store
        self.default_mode = default_mode or self.catalog.default_runtime_mode
        self._executor = ThreadPoolExecutor(max_workers=self.bounds.max_concurrency)

    def mode_for(self, definition_key: str) -> str:
        mode = self.modes.get(definition_key, self.default_mode)
        if mode not in {"off", "shadow", "on"}:
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
        call = JevCall(state=request.state, questions={question.key: question})
        try:
            result = self._run_call(call, request.cancel_event)
        except JevTimeoutError:
            return self._failed(definition, scope, request.caller_role, mode, "timeout", digest, perf_counter() - started)
        except JevNotConfiguredError:
            return self._failed(definition, scope, request.caller_role, mode, "not_configured", digest, perf_counter() - started)
        except JevError:
            return self._failed(definition, scope, request.caller_role, mode, "unavailable", digest, perf_counter() - started)
        except Exception:  # noqa: BLE001 - unknown transport failure fails closed
            return self._failed(definition, scope, request.caller_role, mode, "unavailable", digest, perf_counter() - started)

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

    def _build_question(self, definition: DecisionDefinition, request: DecisionRequest) -> JevQuestion:
        instructions = request.instructions or definition.instructions
        if definition.primitive == Primitive.CHOICE:
            criteria = request.criteria
            if not criteria or not isinstance(criteria, dict):
                raise JevRequestError(f"{definition.key}: Choice requires an id->label criteria dict")
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
        future = self._executor.submit(self.transport.call, call, timeout_seconds=self.bounds.timeout_seconds)
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
                    f"{definition.key}: selected {answer.choice!r} is not an authorized candidate id"
                )
            return JevAnswer(choice=answer.choice, raw=answer.raw)
        if definition.primitive == Primitive.SCORE:
            level = answer.score
            if level is None:
                raise JevInvalidResponseError(f"{definition.key}: missing score level")
            if level not in definition.score_levels:
                # The SDK's `.score` return type is unverified; tolerate a level
                # description by mapping it back to its ordered key.
                by_description = {v: k for k, v in (definition.criteria or {}).items()}
                if level in by_description:
                    level = by_description[level]
                else:
                    raise JevInvalidResponseError(
                        f"{definition.key}: score level {level!r} not in {definition.score_levels}"
                    )
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
    ) -> str | None:
        if self.receipt_store is None:
            return None
        output = _suggestion_payload(suggestion, outcome=outcome, model_version=model_version)
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

    def _suggestion_from_cache(self, definition: DecisionDefinition, cached: dict[str, Any]) -> JevAnswer:
        if definition.primitive == Primitive.CHOICE:
            return JevAnswer(choice=cached.get("choice"), raw=cached)
        if definition.primitive == Primitive.SCORE:
            return JevAnswer(score=cached.get("score"), raw=cached)
        probability = _coerce_probability(cached.get("noul", cached.get("probability")))
        return JevAnswer(noul=probability, probability=probability, raw=cached)


def _suggestion_payload(
    suggestion: JevAnswer | None, *, outcome: str, model_version: str | None
) -> dict[str, Any]:
    if suggestion is None:
        return {"outcome": outcome, "model_version": model_version}
    return {
        "choice": suggestion.choice,
        "noul": suggestion.noul,
        "score": suggestion.score,
        "probability": suggestion.probability,
        "model_version": model_version,
    }
