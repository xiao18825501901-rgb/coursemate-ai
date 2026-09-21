"""FastAPI application for the CourseMate-internal Laya decision service.

Endpoints:
    GET  /health/live            -> process liveness (independent of model)
    GET  /health/ready           -> model loaded + warmed up
    GET  /internal/v1/model-info -> resident model identity
    POST /internal/v1/decisions  -> evaluate one decision

The model is loaded exactly once, on a background thread started at app
creation, so ``/health/live`` is reachable before the model is ready. Inference
runs in the dedicated :class:`InferenceEngine` (never on the event loop).
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.auth import AuthVerifier, build_verifier
from app.definitions import DefinitionsRegistry, validate_questions_against
from app.engine import InferenceEngine
from app.logging import configure_logging, log_request, safe_id
from app.model import DecisionModel, build_model
from app.schema import (
    DecisionRequest,
    DecisionResponse,
    ErrorDetail,
    HealthResponse,
    ModelInfoResponse,
)
from app.settings import Settings

_HTTP_STATUS = {
    "OK": 200,
    "MODEL_NOT_READY": 503,
    "QUEUE_FULL": 503,
    "DEADLINE_EXCEEDED": 408,
    "UNSUPPORTED_DEFINITION": 422,
    "INPUT_TOO_LONG": 422,
    "INVALID_REQUEST": 422,
    "INFERENCE_ERROR": 500,
}

_AUTH_HEADER = "x-laya-service-token"


def new_receipt_id(request_id: str) -> str:
    nonce = secrets.token_hex(8)
    return hashlib.sha256(f"{request_id}|{nonce}".encode()).hexdigest()


class MaxBodySizeMiddleware:
    """Reject oversized bodies before the app parses them (Content-Length fast
    path) and truncate a lying/streaming body as defense-in-depth."""

    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        content_length = self._content_length(scope)
        if content_length is not None and content_length > self.max_bytes:
            await self._respond(send, 413, {"error": {"code": "PAYLOAD_TOO_LARGE"}})
            return

        state = {"received": 0}

        async def guarded_receive() -> dict:
            message = await receive()
            if message.get("type") == "http.request":
                state["received"] += len(message.get("body", b""))
                if state["received"] > self.max_bytes:
                    # Truncate: the app sees an empty body and fails validation,
                    # so an oversized stream can never reach the model.
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        await self.app(scope, guarded_receive, send)

    @staticmethod
    def _content_length(scope: dict) -> int | None:
        for name, value in scope.get("headers") or []:
            if name == b"content-length":
                try:
                    return int(value)
                except ValueError:
                    return None
        return None

    @staticmethod
    async def _respond(send: Any, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class SecurityHeadersMiddleware:
    """Private, non-browser API: no CORS, no caching, no framing."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def wrapped_send(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.extend(
                    [
                        (b"cache-control", b"private, no-store"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, wrapped_send)


def create_app(
    *,
    settings: Settings | None = None,
    model: DecisionModel | None = None,
    registry: DefinitionsRegistry | None = None,
    engine: InferenceEngine | None = None,
    auth_verifier: AuthVerifier | None = None,
) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level, settings.log_format)

    if model is None:
        model = build_model(settings)
    if registry is None:
        registry = DefinitionsRegistry.from_json_file(settings.definitions_path)
    if engine is None:
        engine = InferenceEngine(
            model,
            concurrency=settings.concurrency,
            queue_size=settings.queue_size,
        )

    application = FastAPI(title="CourseMate Laya Inference", version="0.1.0")
    application.state.settings = settings
    application.state.model = model
    application.state.engine = engine
    application.state.registry = registry
    application.state.auth_verifier = auth_verifier or build_verifier(settings.service_token_plain)
    application.state.ready = False
    application.state.load_error = None

    engine.start()

    # Single load at startup, on a dedicated thread, so /health/live is up
    # before the model is ready and nothing blocks the loop.
    def _load_model() -> None:
        try:
            model.load()
            model.warmup()
            application.state.ready = True
            logging.getLogger("laya").info("model loaded and warmed up")
        except Exception as exc:  # noqa: BLE001 - startup failure is surfaced via /ready
            application.state.load_error = type(exc).__name__
            application.state.ready = False
            logging.getLogger("laya").error(
                "model load failed", extra={"data": {"exc_type": type(exc).__name__}}
            )

    threading.Thread(target=_load_model, name="laya-model-load", daemon=True).start()

    application.add_middleware(MaxBodySizeMiddleware, max_bytes=settings.max_body_bytes)
    application.add_middleware(SecurityHeadersMiddleware)

    # --- auth dependency -------------------------------------------------
    def require_service(request: Request) -> None:
        verifier: AuthVerifier = request.app.state.auth_verifier
        if not verifier.verify(request):
            raise _unauthorized()

    def _unauthorized() -> HTTPException:
        return HTTPException(
            status_code=401,
            detail={"error": {"code": "UNAUTHENTICATED", "message": "service credential required"}},
        )

    # --- health ----------------------------------------------------------
    @application.get("/health/live", response_model=HealthResponse)
    async def health_live() -> HealthResponse:
        return HealthResponse(status="alive")

    @application.get("/health/ready", response_model=HealthResponse)
    async def health_ready() -> JSONResponse:
        if application.state.ready:
            return JSONResponse(
                status_code=200,
                content=HealthResponse(
                    status="ready", backend=settings.model_backend
                ).model_dump(),
            )
        return JSONResponse(
            status_code=503,
            content=HealthResponse(
                status="not_ready",
                backend=settings.model_backend,
                error=application.state.load_error,
            ).model_dump(),
        )

    # --- model info ------------------------------------------------------
    @application.get("/internal/v1/model-info", response_model=ModelInfoResponse)
    async def model_info(request: Request) -> ModelInfoResponse:
        require_service(request)
        info = model.model_info()
        return ModelInfoResponse(
            model=info,
            ready=application.state.ready,
            calibration_version=settings.calibration_version,
            real_inference=settings.model_backend == "real",
            load_error=application.state.load_error,
        )

    # --- decisions -------------------------------------------------------
    @application.post("/internal/v1/decisions")
    async def decisions(request: Request) -> JSONResponse:
        t0 = time.monotonic()

        # Auth first: nothing about the request (even its size) is echoed to an
        # unauthenticated caller beyond the 401 itself.
        require_service(request)

        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            return _error(request_id="-", receipt_id="-", status="INVALID_REQUEST",
                           http_status=422, message="body is not valid JSON")

        try:
            body = DecisionRequest.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            return _validation_error(exc, payload)

        request_id = body.request_id
        receipt_id = new_receipt_id(request_id)
        state_len = _state_len(body.compiled_state)

        # 1. readiness
        if not application.state.ready or not engine.started:
            return _error(request_id, receipt_id, "MODEL_NOT_READY", 503,
                          "model not ready", load_error=application.state.load_error,
                          state_len=state_len, t0=t0)

        # 2. server-managed definition allowlist
        entry = registry.resolve(body.decision_definition_id, body.definition_version)
        if entry is None:
            return _error(request_id, receipt_id, "UNSUPPORTED_DEFINITION", 422,
                          "unknown decision_definition_id/definition_version",
                          definition_id=body.decision_definition_id,
                          definition_version=body.definition_version,
                          state_len=state_len, t0=t0)
        if entry.compiler_versions and body.compiler_version not in entry.compiler_versions:
            return _error(request_id, receipt_id, "UNSUPPORTED_DEFINITION", 422,
                          "compiler_version not supported for this definition",
                          definition_id=body.decision_definition_id,
                          definition_version=body.definition_version,
                          state_len=state_len, t0=t0)

        # 3. schema must match the canonical definition exactly
        questions = {qid: q.model_dump() for qid, q in body.questions.items()}
        problems = validate_questions_against(entry, questions)
        if problems:
            return _error(request_id, receipt_id, "INVALID_REQUEST", 422,
                          "; ".join(problems),
                          definition_id=body.decision_definition_id,
                          definition_version=body.definition_version,
                          state_len=state_len, t0=t0)

        # 4. anti-abuse token measurement (real tokenizer at load time)
        diag = model.token_diagnostics(body.compiled_state, questions)
        if diag.options_not_fit:
            return _error(request_id, receipt_id, "INPUT_TOO_LONG", 422,
                          "options do not fit head budget",
                          definition_id=body.decision_definition_id,
                          definition_version=body.definition_version,
                          state_len=state_len, tokens=diag.total_tokens, t0=t0)
        if diag.total_tokens > settings.max_request_tokens:
            return _error(request_id, receipt_id, "INPUT_TOO_LONG", 422,
                          "request exceeds token budget",
                          definition_id=body.decision_definition_id,
                          definition_version=body.definition_version,
                          state_len=state_len, tokens=diag.total_tokens, t0=t0)

        # 5. deadline clamp (the server is the authority on resource use)
        deadline_ms = min(body.deadline_ms, settings.max_deadline_ms)
        deadline_clamped = body.deadline_ms > settings.max_deadline_ms

        # 6. run inference (off the event loop)
        outcome = await engine.decide(
            body.compiled_state, questions, deadline_ms, request_id
        )
        diagnostics = {
            "input_tokens": diag.total_tokens,
            "state_tokens": diag.state_tokens,
            "questions_seen": len(questions),
            "max_len": diag.max_len,
            "head_max_len": diag.head_max_len,
            "truncated": diag.truncated,
            "options_not_fit": list(diag.options_not_fit),
            "deadline_clamped": deadline_clamped,
        }
        timings = outcome.timings or {}

        if outcome.status == "OK":
            payload_out = DecisionResponse(
                request_id=request_id,
                receipt_id=receipt_id,
                status="OK",
                answers=outcome.answers,
                diagnostics=diagnostics,
                model=model.model_info(),
                timings=timings,
                calibration_version=settings.calibration_version,
            )
            _log(request_id, receipt_id, body, "OK", 200, diag.total_tokens, state_len,
                 (time.monotonic() - t0) * 1000.0, None)
            return JSONResponse(status_code=200, content=payload_out.model_dump())

        status = outcome.status
        message = outcome.error_message or outcome.status
        http_status = _HTTP_STATUS.get(status, 500)
        payload_out = DecisionResponse(
            request_id=request_id,
            receipt_id=receipt_id,
            status=status,
            error=ErrorDetail(code=outcome.error_code or status, message=message),
            diagnostics=diagnostics,
            model=model.model_info(),
            timings=timings,
            calibration_version=settings.calibration_version,
        )
        _log(request_id, receipt_id, body, status, http_status, diag.total_tokens, state_len,
             (time.monotonic() - t0) * 1000.0, outcome.error_code)
        return JSONResponse(status_code=http_status, content=payload_out.model_dump())

    # --- error handlers --------------------------------------------------
    @application.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "request_id": "-",
                "receipt_id": "-",
                "status": "INVALID_REQUEST",
                "error": {"code": "INVALID_REQUEST", "message": "request did not pass validation"},
            },
        )

    @application.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger("laya").error(
            "unhandled error", extra={"data": {"exc_type": type(exc).__name__}}
        )
        return JSONResponse(
            status_code=500,
            content={
                "request_id": "-",
                "receipt_id": "-",
                "status": "INFERENCE_ERROR",
                "error": {"code": "INFERENCE_ERROR", "message": "internal error"},
            },
        )

    return application


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _state_len(state: Any) -> int:
    if isinstance(state, str):
        return len(state)
    try:
        return len(repr(state))
    except Exception:  # noqa: BLE001
        return -1


def _log(
    request_id, receipt_id, body, status, http_status, tokens, state_len, duration_ms, error_code
):
    try:
        safe_id(request_id)
    except ValueError:
        request_id = "invalid-id"
    log_request(
        request_id=request_id,
        receipt_id=receipt_id,
        definition_id=body.decision_definition_id if body is not None else None,
        definition_version=body.definition_version if body is not None else None,
        status=status,
        http_status=http_status,
        tokens=tokens,
        state_len=state_len,
        duration_ms=duration_ms,
        error_code=error_code,
    )


def _validation_error(exc: Exception, payload: Any) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "request_id": _safe_payload_id(payload),
            "receipt_id": "-",
            "status": "INVALID_REQUEST",
            "error": {"code": "INVALID_REQUEST", "message": "request did not pass validation"},
        },
    )


def _safe_payload_id(payload: Any) -> str:
    if isinstance(payload, dict):
        raw = payload.get("request_id")
        if isinstance(raw, str):
            try:
                return safe_id(raw)
            except ValueError:
                return "invalid-id"
    return "-"


def _error(request_id, receipt_id, status, http_status, message, **kwargs) -> JSONResponse:
    t0 = kwargs.pop("t0", None)
    definition_id = kwargs.pop("definition_id", None)
    definition_version = kwargs.pop("definition_version", None)
    state_len = kwargs.pop("state_len", None)
    tokens = kwargs.pop("tokens", None)
    load_error = kwargs.pop("load_error", None)
    diagnostics = {
        "input_tokens": tokens,
        "state_tokens": None,
        "questions_seen": None,
    }
    if load_error:
        diagnostics["load_error"] = load_error
    payload = DecisionResponse(
        request_id=request_id,
        receipt_id=receipt_id,
        status=status,
        error=ErrorDetail(code=status, message=message),
        diagnostics=diagnostics,
    )
    duration = (time.monotonic() - t0) * 1000.0 if t0 is not None else 0.0
    log_request(
        request_id=request_id if request_id != "-" else "invalid-id",
        receipt_id=receipt_id,
        definition_id=definition_id,
        definition_version=definition_version,
        status=status,
        http_status=http_status,
        tokens=tokens,
        state_len=state_len,
        duration_ms=duration,
        error_code=status,
    )
    return JSONResponse(status_code=http_status, content=payload.model_dump())
