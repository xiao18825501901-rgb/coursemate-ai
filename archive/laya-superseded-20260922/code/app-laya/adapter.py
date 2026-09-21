"""The Laya gateway: transport, modes, validation, receipts, deadline and breaker.

This is the client-side adapter for the self-hosted Laya inference service (the
official entry point is ``RLAgent.system_one(state, questions)``). It is the
successor to the retired TypeSafe "Jev" transport and never falls back to Jev or
Qwen.

Responsibilities (nothing else):

* injectable transport — :class:`FakeLayaTransport` for tests, :class:`HttpLayaTransport`
  for the live self-hosted path (a plain HTTP POST to our private Alibaba Cloud CPU
  node; it never logs payloads or keys);
* ``off | shadow | on | advisory`` per definition id, with ``shadow`` the default
  (nothing becomes ``on`` until the calibration gate passes);
* strict validation of the official output shape (choice ids from server criteria,
  finite probabilities in [0, 1] with probability mass ~ 1, noul = P(true) only,
  score = expected index in ``0..K-1`` with a legend);
* one call per decision — no retry, no Jev/Qwen fallback;
* an absolute ``deadline_ms`` (late replies are discarded) and a circuit breaker
  that fails fast for a bounded cooldown;
* a persisted receipt recording ``provider="laya"``, model revision, definition
  id + version, calibration version, latency, outcome and the cache-scope keys.
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Any, Protocol
from uuid import uuid4

from app.jev.catalog import Catalog, DecisionDefinition, Primitive
from app.laya.errors import (
    LayaError,
    LayaInvalidResponseError,
    LayaTimeoutError,
    LayaUnavailableError,
    LayaUnsupportedError,
)
from app.laya.models import (
    DEFAULT_COMPILER_VERSION,
    DEFAULT_MODEL_REVISION,
    Kind,
    LayaAnswer,
    LayaDiagnostics,
    LayaQuestion,
    LayaReply,
    LayaRequest,
    LayaScope,
    request_content_hash,
)

PROBABILITY_MASS_TOLERANCE = 1e-2
ENDPOINT_PATH = "/system_one"


# --------------------------------------------------------------------------- config
@dataclass(frozen=True)
class LayaConfig:
    """Client-side configuration for the Laya adapter.

    ``temperature`` / ``temperature_by_options`` record the model's own scaling
    (multilingual ships ``[1.0, 1.0, 1.0]`` and ``{}``). The client never applies
    or re-applies temperature — it passes probabilities through unmodified, so a
    calibration temperature can never be double-applied here.
    """

    base_url: str | None = None
    api_key: str | None = None
    model_revision: str = DEFAULT_MODEL_REVISION
    compiler_version: str = DEFAULT_COMPILER_VERSION
    timeout_seconds: float = 10.0
    max_request_chars: int = 40_000
    default_mode: str = "shadow"
    temperature: tuple[float, float, float] = (1.0, 1.0, 1.0)
    temperature_by_options: dict[str, float] = field(default_factory=dict)
    calibration_version: str | None = None
    breaker_failure_threshold: int = 3
    breaker_cooldown_ms: int = 30_000

    @classmethod
    def from_settings(cls, settings: Any) -> LayaConfig:
        """Build a :class:`LayaConfig` from a Settings-like object (duck-typed)."""
        return cls(
            base_url=getattr(settings, "laya_base_url", None),
            api_key=_secret_value(getattr(settings, "laya_api_key", None)),
            model_revision=getattr(settings, "laya_model_revision", DEFAULT_MODEL_REVISION),
            compiler_version=getattr(settings, "laya_compiler_version", DEFAULT_COMPILER_VERSION),
            timeout_seconds=float(getattr(settings, "laya_timeout_seconds", 10.0)),
            max_request_chars=int(getattr(settings, "laya_max_request_chars", 40_000)),
            default_mode=getattr(settings, "laya_default_mode", "shadow"),
            temperature=tuple(getattr(settings, "laya_temperature", (1.0, 1.0, 1.0))),
            temperature_by_options=dict(getattr(settings, "laya_temperature_by_options", {})),
            calibration_version=getattr(settings, "laya_calibration_version", None),
            breaker_failure_threshold=int(getattr(settings, "laya_breaker_failure_threshold", 3)),
            breaker_cooldown_ms=int(getattr(settings, "laya_breaker_cooldown_ms", 30_000)),
        )


def _secret_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "get_secret_value", lambda: value)())


# ----------------------------------------------------------------------------- clock
class Clock(Protocol):
    def now_ms(self) -> int:
        """Return the current wall-clock epoch in milliseconds."""


class SystemClock:
    def now_ms(self) -> int:
        return int(time.time() * 1000)


# ------------------------------------------------------------------------- transport
class LayaTransport(Protocol):
    def decide(self, request: LayaRequest) -> LayaReply:
        """Run one call; raise a :class:`LayaError` subclass on failure."""


class HttpLayaTransport:
    """POSTs the request to our internal Laya node (never logs payloads or keys)."""

    def __init__(self, config: LayaConfig, *, opener: Any = None) -> None:
        self.config = config
        self._opener = opener  # injectable for the zero-egress / unit spies
        self.requests: list[LayaRequest] = []

    def decide(self, request: LayaRequest) -> LayaReply:
        if not self.config.base_url:
            raise LayaUnavailableError("Laya base_url is not configured")
        self.requests.append(request)
        payload = self._payload(request)
        url = self.config.base_url.rstrip("/") + ENDPOINT_PATH
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST", headers={"Content-Type": "application/json"}
        )
        if self.config.api_key:
            req.add_header("Authorization", "Bearer " + self.config.api_key)
        started = perf_counter()
        try:
            if self._opener is not None:
                with self._opener.open(req, timeout=self.config.timeout_seconds) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
            else:
                with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise LayaUnavailableError(f"Laya inference call failed: {type(exc).__name__}") from exc
        latency_ms = (perf_counter() - started) * 1000
        return self._parse_reply(request, raw, latency_ms)

    def _payload(self, request: LayaRequest) -> dict[str, Any]:
        questions: dict[str, Any] = {}
        for qid, question in request.questions.items():
            questions[qid] = {
                "type": question.kind,
                "instructions": question.instructions,
                "criteria": question.criteria,
            }
        return {"state": request.state, "questions": questions}

    def _parse_reply(self, request: LayaRequest, raw: Any, latency_ms: float) -> LayaReply:
        if not isinstance(raw, dict):
            raise LayaUnavailableError("Laya service returned a non-object payload")
        raw_answers = raw.get("answers") if isinstance(raw.get("answers"), dict) else {}
        answers: dict[str, LayaAnswer] = {}
        for qid, question in request.questions.items():
            answers[qid] = _answer_from_raw(question.kind, raw_answers.get(qid))
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        diagnostics = LayaDiagnostics(
            input_tokens=int(usage.get("input_tokens") or 0),
            truncated_state=False,
            truncated_head=False,
            options_shortened=False,
            per_option_tokens=[],
            option_count=sum(q.option_count() for q in request.questions.values()),
            retained_chars=len(json.dumps(request.state, ensure_ascii=False, default=str)),
            content_hash=request_content_hash(
                request.definition_id,
                request.definition_version,
                request.state,
                request.questions,
            ),
            deadline_ms=request.deadline_ms,
            model_revision=request.model_revision,
            compiler_version=request.compiler_version,
        )
        return LayaReply(
            answers=answers,
            diagnostics=diagnostics,
            latency_ms=latency_ms,
            model_revision=request.model_revision,
            status="ok",
        )


class FakeLayaTransport:
    """Deterministic offline transport for tests (no network, no keys)."""

    def __init__(self, responder: Any = None) -> None:
        self.responder = responder
        self.requests: list[LayaRequest] = []

    def decide(self, request: LayaRequest) -> LayaReply:
        self.requests.append(request)
        if self.responder is None:
            raise LayaUnavailableError("FakeLayaTransport has no responder configured")
        result = self.responder(request)
        if isinstance(result, LayaReply):
            return result
        if isinstance(result, Exception):
            raise result
        if isinstance(result, dict):
            return _reply_from_dict(request, result)
        raise LayaInvalidResponseError("FakeLayaTransport responder returned an unknown type")


# ---------------------------------------------------------------------- circuit breaker
class CircuitBreaker:
    """A small failure-count breaker that fails fast for a bounded cooldown."""

    def __init__(self, *, failure_threshold: int, cooldown_ms: int) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_ms = cooldown_ms
        self.failure_count = 0
        self.opened_until_ms: int | None = None

    @property
    def state(self) -> str:
        return "open" if self.opened_until_ms is not None else "closed"

    def allow(self, now_ms: int) -> bool:
        if self.opened_until_ms is not None:
            if now_ms < self.opened_until_ms:
                return False
            self.opened_until_ms = None
            self.failure_count = 0
        return True

    def record_success(self) -> None:
        self.failure_count = 0
        self.opened_until_ms = None

    def record_failure(self, now_ms: int) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.opened_until_ms = now_ms + self.cooldown_ms


# --------------------------------------------------------------------------- receipts
@dataclass
class LayaReceipt:
    """One persisted Laya call record (neutral provider field = "laya")."""

    id: str
    definition_id: str
    definition_version: str
    model_revision: str
    compiler_version: str
    calibration_version: str | None
    temperature: str | None
    mode: str
    outcome: str
    owner_scope_hash: str | None
    course_id: str | None
    workspace_id: str | None
    material_revision: str | None
    node_id: str | None
    spec_version: str | None
    question_hash: str | None
    input_hash: str
    output_json: str
    latency_ms: float


class LayaReceiptStore(Protocol):
    def save(self, receipt: LayaReceipt) -> None: ...

    def lookup(
        self, definition_id: str, scope: LayaScope, *, model_revision: str
    ) -> dict[str, Any] | None: ...


# ---------------------------------------------------------------------------- decision
@dataclass(frozen=True)
class LayaDecision:
    """The gateway result for one decision.

    ``value`` is the value to use: the Laya value when ``used_laya`` is True,
    otherwise the caller-supplied deterministic fallback (or ``None`` when the caller
    did not supply one). ``answer`` (additive field) carries the validated suggestion
    in ``advisory``/``on`` modes; in ``shadow`` it is recorded in the receipt only.
    """

    definition_id: str
    value: Any
    used_laya: bool
    mode: str
    receipt_id: str | None
    confidence: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    fallback_reason: str | None = None
    latency_ms: float = 0.0
    answer: LayaAnswer | None = None


# ---------------------------------------------------------------------------- gateway
class LayaGateway:
    """The single entry point for Laya semantic decisions."""

    MODES = frozenset({"off", "shadow", "on", "advisory"})

    def __init__(
        self,
        *,
        transport: LayaTransport,
        catalog: Catalog,
        modes: dict[str, str] | None = None,
        receipt_store: LayaReceiptStore | None = None,
        clock: Clock | None = None,
        config: LayaConfig | None = None,
    ) -> None:
        self.transport = transport
        self.catalog = catalog
        self.modes = dict(modes or {})
        self.receipt_store = receipt_store
        self._clock = clock or SystemClock()
        self.config = config or LayaConfig()
        self._breaker = CircuitBreaker(
            failure_threshold=self.config.breaker_failure_threshold,
            cooldown_ms=self.config.breaker_cooldown_ms,
        )

    @property
    def breaker_state(self) -> str:
        return self._breaker.state

    def mode_for(self, definition_id: str) -> str:
        mode = self.modes.get(definition_id, self.config.default_mode)
        if mode not in self.MODES:
            raise LayaError(f"Unknown Laya mode {mode!r} for {definition_id}")
        return mode

    def decide(
        self, request: LayaRequest, *, scope: LayaScope, fallback: Any = None
    ) -> LayaDecision:
        definition = self.catalog.get(request.definition_id)
        mode = self.mode_for(request.definition_id)

        if mode == "off":
            return LayaDecision(
                definition_id=request.definition_id,
                value=fallback,
                used_laya=False,
                mode=mode,
                receipt_id=None,
                confidence=None,
                probabilities={},
                fallback_reason=None,
                latency_ms=0.0,
            )

        question = self._single_question(request)
        digest = request_content_hash(
            request.definition_id, request.definition_version, request.state, request.questions
        )
        scoped = replace(scope, input_hash=digest)

        preflight = self._preflight(request, question)
        if preflight is not None:
            return self._failure(
                request, definition, mode, scoped, preflight, digest, 0.0, fallback
            )

        now = self._clock.now_ms()
        if request.deadline_ms > 0 and now >= request.deadline_ms:
            return self._failure(
                request, definition, mode, scoped, "deadline_exceeded", digest, 0.0, fallback
            )
        if not self._breaker.allow(now):
            return self._failure(
                request, definition, mode, scoped, "circuit_open", digest, 0.0, fallback
            )

        if self.receipt_store is not None:
            cached = self.receipt_store.lookup(
                request.definition_id, scoped, model_revision=request.model_revision
            )
            if cached is not None:
                return self._from_cache(request, question, definition, mode, cached, fallback)

        started = perf_counter()
        try:
            reply = self.transport.decide(request)
        except LayaTimeoutError:
            self._breaker.record_failure(self._clock.now_ms())
            return self._failure(
                request, definition, mode, scoped, "timeout", digest, 0.0, fallback
            )
        except LayaError:
            self._breaker.record_failure(self._clock.now_ms())
            return self._failure(
                request, definition, mode, scoped, "unavailable", digest, 0.0, fallback
            )
        except Exception:  # noqa: BLE001 - unknown transport failure fails closed
            self._breaker.record_failure(self._clock.now_ms())
            return self._failure(
                request, definition, mode, scoped, "unavailable", digest, 0.0, fallback
            )

        latency_ms = (perf_counter() - started) * 1000

        if request.deadline_ms > 0 and self._clock.now_ms() > request.deadline_ms:
            # A late reply must never be applied; it also signals a slow service.
            self._breaker.record_failure(self._clock.now_ms())
            return self._failure(
                request, definition, mode, scoped, "deadline_exceeded", digest, latency_ms, fallback
            )

        raw_answer = reply.answers.get(question_key(request, question))
        try:
            answer = _validate_answer(question, raw_answer)
        except LayaInvalidResponseError as exc:
            self._breaker.record_failure(self._clock.now_ms())
            return self._failure(
                request, definition, mode, scoped, "invalid_response", digest, latency_ms,
                fallback, detail=str(exc),
            )

        self._breaker.record_success()
        value = _value_for(question.kind, answer)
        receipt_id = self._record(
            request, definition, mode, scoped, answer=answer, outcome="ok",
            latency_ms=latency_ms, fallback_reason=None,
        )
        used_laya = mode == "on"
        return LayaDecision(
            definition_id=request.definition_id,
            value=value if used_laya else fallback,
            used_laya=used_laya,
            mode=mode,
            receipt_id=receipt_id,
            confidence=None if question.kind == "noul" else answer.confidence,
            probabilities=answer.probabilities,
            fallback_reason=None,
            latency_ms=latency_ms,
            answer=None if mode == "shadow" else answer,
        )

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _single_question(request: LayaRequest) -> LayaQuestion:
        if request.definition_id in request.questions:
            return request.questions[request.definition_id]
        if len(request.questions) == 1:
            return next(iter(request.questions.values()))
        raise LayaError("LayaRequest must carry exactly one question for its definition_id")

    def _preflight(self, request: LayaRequest, question: LayaQuestion) -> str | None:
        size = len(
            json.dumps({"state": request.state, "questions": len(request.questions)}, default=str)
        )
        if size > self.config.max_request_chars:
            return "oversized"
        if question.kind not in {"choice", "score", "noul"}:
            return "unsupported"
        if question.kind == "score" and not question.criteria:
            return "unsupported"
        return None

    def _failure(
        self,
        request: LayaRequest,
        definition: DecisionDefinition,
        mode: str,
        scope: LayaScope,
        reason: str,
        digest: str,
        latency_ms: float,
        fallback: Any,
        *,
        detail: str | None = None,
    ) -> LayaDecision:
        self._record(
            request, definition, mode, scope, answer=None, outcome=reason,
            latency_ms=latency_ms, fallback_reason=detail or reason,
        )
        return LayaDecision(
            definition_id=request.definition_id,
            value=fallback,
            used_laya=False,
            mode=mode,
            receipt_id=None,
            confidence=None,
            probabilities={},
            fallback_reason=reason,
            latency_ms=latency_ms,
        )

    def _from_cache(
        self,
        request: LayaRequest,
        question: LayaQuestion,
        definition: DecisionDefinition,
        mode: str,
        cached: dict[str, Any],
        fallback: Any,
    ) -> LayaDecision:
        answer = _validate_answer(question, _answer_from_raw(question.kind, cached))
        used_laya = mode == "on"
        value = _value_for(question.kind, answer) if used_laya else fallback
        return LayaDecision(
            definition_id=request.definition_id,
            value=value,
            used_laya=used_laya,
            mode=mode,
            receipt_id=None,
            confidence=None if question.kind == "noul" else answer.confidence,
            probabilities=answer.probabilities,
            fallback_reason=None,
            latency_ms=0.0,
            answer=None if mode == "shadow" else answer,
        )

    def _record(
        self,
        request: LayaRequest,
        definition: DecisionDefinition,
        mode: str,
        scope: LayaScope,
        *,
        answer: LayaAnswer | None,
        outcome: str,
        latency_ms: float,
        fallback_reason: str | None,
    ) -> str | None:
        if self.receipt_store is None:
            return None
        output = _output_payload(
            answer,
            outcome=outcome,
            fallback_reason=fallback_reason,
            model_revision=request.model_revision,
        )
        receipt = LayaReceipt(
            id=f"laya_{uuid4().hex}",
            definition_id=definition.key,
            definition_version=request.definition_version,
            model_revision=request.model_revision,
            compiler_version=request.compiler_version,
            calibration_version=self.config.calibration_version,
            temperature=_temperature_payload(self.config),
            mode=mode,
            outcome=outcome,
            owner_scope_hash=scope.owner_scope_hash,
            course_id=scope.course_id,
            workspace_id=scope.workspace_id,
            material_revision=scope.material_revision,
            node_id=scope.node_id,
            spec_version=scope.spec_version,
            question_hash=scope.question_hash,
            input_hash=scope.input_hash or "",
            output_json=json.dumps(output, ensure_ascii=False, sort_keys=True, default=str),
            latency_ms=round(latency_ms, 3),
        )
        self.receipt_store.save(receipt)
        return receipt.id


# ------------------------------------------------------------------------ validation
def _answer_from_raw(kind: Kind, raw: Any) -> LayaAnswer:
    raw = raw if isinstance(raw, dict) else {}
    rl_agent = raw.get("rl_agent") if isinstance(raw.get("rl_agent"), dict) else {}
    return LayaAnswer(
        kind=kind,
        choice=raw.get("choice") if kind == "choice" else None,
        score=_finite_float(raw.get("score")) if kind == "score" else None,
        noul=_finite_float(raw.get("noul")) if kind == "noul" else None,
        probabilities={str(k): v for k, v in (raw.get("probabilities") or {}).items()},
        confidence=_finite_float(raw.get("confidence")) or 0.0,
        confidence_kind="distribution_concentration",
        legend=_string_map(raw.get("legend")),
        act_probability=_finite_float(
            rl_agent.get("act_probability", raw.get("act_probability"))
        ),
    )


def _validate_answer(question: LayaQuestion, answer: LayaAnswer | None) -> LayaAnswer:
    if answer is None:
        raise LayaInvalidResponseError("transport returned no answer")
    if answer.kind != question.kind:
        raise LayaInvalidResponseError(
            f"answer kind {answer.kind!r} != question kind {question.kind!r}"
        )
    if question.kind == "choice":
        return _validate_choice(question, answer)
    if question.kind == "score":
        return _validate_score(question, answer)
    return _validate_noul(answer)


def _validate_choice(question: LayaQuestion, answer: LayaAnswer) -> LayaAnswer:
    criteria = question.criteria if isinstance(question.criteria, dict) else {}
    authorized = set(criteria.keys())
    if not answer.choice or answer.choice not in authorized:
        raise LayaInvalidResponseError(
            f"selected {answer.choice!r} is not an authorized candidate id"
        )
    probabilities = _validate_probabilities(answer.probabilities, allowed_keys=authorized)
    mass = sum(probabilities.values())
    if abs(mass - 1.0) > PROBABILITY_MASS_TOLERANCE:
        raise LayaInvalidResponseError(f"choice probability mass {mass} is not ~1")
    return LayaAnswer(
        kind="choice",
        choice=answer.choice,
        probabilities=probabilities,
        confidence=_confidence(answer.confidence, list(probabilities.values())),
        confidence_kind="distribution_concentration",
        act_probability=answer.act_probability,
    )


def _validate_score(question: LayaQuestion, answer: LayaAnswer) -> LayaAnswer:
    criteria = question.criteria
    if isinstance(criteria, dict):
        legend = {str(k): str(v) for k, v in criteria.items()}
        k = len(criteria)
    elif isinstance(criteria, list):
        legend = {str(i): str(c) for i, c in enumerate(criteria)}
        k = len(criteria)
    else:
        raise LayaUnsupportedError("score question requires criteria")
    score = answer.score
    if score is None or not (0.0 <= score <= k - 1):
        raise LayaInvalidResponseError(f"score {score!r} is not an expected index in 0..{k - 1}")
    probabilities = _validate_probabilities(
        answer.probabilities, allowed_keys={str(i) for i in range(k)}
    )
    mass = sum(probabilities.values())
    if abs(mass - 1.0) > PROBABILITY_MASS_TOLERANCE:
        raise LayaInvalidResponseError(f"score probability mass {mass} is not ~1")
    return LayaAnswer(
        kind="score",
        score=score,
        probabilities=probabilities,
        confidence=_confidence(answer.confidence, list(probabilities.values())),
        confidence_kind="distribution_concentration",
        legend=answer.legend or legend,
        act_probability=answer.act_probability,
    )


def _validate_noul(answer: LayaAnswer) -> LayaAnswer:
    noul = answer.noul
    if noul is None or not (0.0 <= noul <= 1.0):
        raise LayaInvalidResponseError(f"noul {noul!r} is not a probability in [0, 1]")
    # P(true) is the answer; it is never converted to max(p, 1-p) and never a confidence.
    return LayaAnswer(
        kind="noul",
        noul=noul,
        probabilities={},
        confidence=0.0,
        confidence_kind="distribution_concentration",
    )


def _validate_probabilities(
    probabilities: dict[str, float], *, allowed_keys: set[str]
) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in probabilities.items():
        key_s = str(key)
        if key_s not in allowed_keys:
            raise LayaInvalidResponseError(f"probability key {key_s!r} is not a server option")
        f = _finite_float(value)
        if f is None or not (0.0 <= f <= 1.0):
            raise LayaInvalidResponseError(
                f"probability {value!r} for {key_s!r} not finite in [0, 1]"
            )
        out[key_s] = f
    return out


def _confidence(confidence: float, probabilities: list[float]) -> float:
    if math.isfinite(confidence) and 0.0 < confidence <= 1.0:
        return confidence
    return _concentration(probabilities)


def _concentration(probabilities: list[float]) -> float:
    """1 - normalized entropy (distribution concentration), mirroring the service."""
    k = len(probabilities)
    if k < 2:
        return 1.0
    p = [max(x, 1e-12) for x in probabilities[:k]]
    entropy = -sum(x * math.log(x) for x in p)
    return float(1.0 - entropy / math.log(k))


def _finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _string_map(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    return {str(k): str(v) for k, v in value.items()}


# --------------------------------------------------------------------------- helpers
def _primitive_to_kind(primitive: str) -> Kind:
    return {
        Primitive.CHOICE: "choice",
        Primitive.NOUL: "noul",
        Primitive.SCORE: "score",
    }[primitive]


def laya_question(
    definition: DecisionDefinition,
    *,
    criteria: dict[str, str] | list[str] | None = None,
    instructions: str | None = None,
) -> LayaQuestion:
    """Build a :class:`LayaQuestion` from a catalog definition (for wiring code)."""
    kind = _primitive_to_kind(definition.primitive)
    text = instructions or definition.instructions
    if kind == "choice":
        return LayaQuestion(kind="choice", instructions=text, criteria=dict(criteria or {}))
    if kind == "score":
        levels = [definition.criteria[level] for level in definition.score_levels]
        return LayaQuestion(kind="score", instructions=text, criteria=levels)
    return LayaQuestion(kind="noul", instructions=text, criteria=None)


def _value_for(kind: Kind, answer: LayaAnswer) -> Any:
    if kind == "choice":
        return answer.choice
    if kind == "score":
        return answer.score
    return answer.noul


def question_key(request: LayaRequest, question: LayaQuestion) -> str:
    if request.definition_id in request.questions:
        return request.definition_id
    return next(iter(request.questions.keys()))


def _output_payload(
    answer: LayaAnswer | None,
    *,
    outcome: str,
    fallback_reason: str | None,
    model_revision: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "outcome": outcome,
        "model_revision": model_revision,
        "confidence_kind": "distribution_concentration",
    }
    if fallback_reason is not None:
        payload["fallback_reason"] = fallback_reason
    if answer is not None:
        payload.update(
            {
                "kind": answer.kind,
                "choice": answer.choice,
                "score": answer.score,
                "noul": answer.noul,
                "probabilities": answer.probabilities,
                "probability_mass": round(sum(answer.probabilities.values()), 6),
                "confidence": answer.confidence,
                "legend": answer.legend,
                "act_probability": answer.act_probability,
            }
        )
    return payload


_IDENTITY_TEMPERATURE = (1.0, 1.0, 1.0)


def _temperature_payload(config: LayaConfig) -> str | None:
    # Multilingual ships the identity temperature (all 1.0, empty by_options), so a
    # calibration temperature is only "applied" when it differs. None means "no
    # calibration temperature is in effect" and is what gets recorded by default.
    has_calibration = (
        tuple(config.temperature) != _IDENTITY_TEMPERATURE
        or bool(config.temperature_by_options)
    )
    if not has_calibration:
        return None
    return json.dumps(
        {
            "temperature": list(config.temperature),
            "temperature_by_options": config.temperature_by_options,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _reply_from_dict(request: LayaRequest, payload: dict[str, Any]) -> LayaReply:
    raw_answers = payload.get("answers") if isinstance(payload.get("answers"), dict) else {}
    answers: dict[str, LayaAnswer] = {}
    for qid, question in request.questions.items():
        answers[qid] = _answer_from_raw(question.kind, raw_answers.get(qid))
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    diagnostics = LayaDiagnostics(
        input_tokens=int(usage.get("input_tokens") or 0),
        truncated_state=False,
        truncated_head=False,
        options_shortened=False,
        per_option_tokens=[],
        option_count=sum(q.option_count() for q in request.questions.values()),
        retained_chars=len(json.dumps(request.state, ensure_ascii=False, default=str)),
        content_hash=request_content_hash(
            request.definition_id, request.definition_version, request.state, request.questions
        ),
        deadline_ms=request.deadline_ms,
        model_revision=request.model_revision,
        compiler_version=request.compiler_version,
    )
    return LayaReply(
        answers=answers,
        diagnostics=diagnostics,
        latency_ms=float(payload.get("latency_ms") or 0.0),
        model_revision=request.model_revision,
        status=str(payload.get("status") or "ok"),
    )
