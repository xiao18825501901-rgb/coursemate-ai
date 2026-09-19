"""Mount the delivered new UI onto the existing RAG API application.

The host keeps every route, middleware and lifespan it already had. The UI is
mounted at a distinct sub-path and only in ``integrated`` + ``injected`` mode,
which is what stops a production deployment from accidentally running the
standalone reference store instead of the real V3 domain.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.db import Database
from app.learning.orchestrator import LearningOrchestrator
from app.rag.retrieval import HybridRetriever
from app.services.ingestion import IngestionService
from app.ui_extension.domain import V3DomainAdapter
from app.ui_extension.identity import clerk_subject_resolver

MOUNT_PATH = "/ui-extension"


def ui_allowed_origins(settings: Settings) -> tuple[str, ...]:
    """The browser origins the mounted shell may be called from.

    Exposed so the host can build its own CORS middleware with these origins when
    the extension is enabled. The host's policy otherwise allows only
    `WEB_ORIGIN`, and a browser preflight from any other allowed site origin would
    be rejected with an opaque "Disallowed CORS origin" before the extension ever
    sees the request.
    """

    raw = os.getenv("CMUI_ALLOWED_ORIGINS", "")
    if raw:
        return tuple(item.strip() for item in raw.split(",") if item.strip())
    return (settings.web_origin,)


def _coverage_reviewer(settings: Settings) -> object:
    """Resolve the injected free-text coverage reviewer.

    ``none`` (default) never claims coverage; ``deterministic`` is local/test
    only and refused in production; ``model`` is the production reviewer: one
    independent, default-off third call over the site's single Qwen credential,
    enabled only when billing is authorized. The billable gate is checked
    before any request is built.
    """

    from app.learning.coverage_review import resolve_coverage_reviewer

    return resolve_coverage_reviewer(
        "production" if settings.app_env == "production" else "development",
        os.getenv("CMUI_COVERAGE_REVIEWER"),
        allow_billable=os.getenv("CMUI_ALLOW_BILLABLE", "false").lower() == "true",
        base_url=os.getenv("CMUI_QWEN_BASE_URL") or (settings.v3_model_base_url or ""),
        api_key=os.getenv("CMUI_QWEN_API_KEY")
        or (settings.v3_model_api_key.get_secret_value() if settings.v3_model_api_key else ""),
        model=os.getenv("CMUI_QWEN_MODEL") or settings.v3_model,
        timeout=float(
            os.getenv("CMUI_MODEL_TIMEOUT", str(settings.v3_model_timeout_seconds))
        ),
    )


def _ui_settings(settings: Settings) -> object:
    """Build the `cm_update` settings from the host configuration.

    Only non-secret values cross the boundary; the Qwen credential and base URL
    are read from the same variables the V3 learning provider already uses, so the
    site keeps exactly one deployed model credential.
    """

    from app.cm_update.config import Settings as UiSettings

    data_dir = os.getenv("CMUI_DATA_DIR") or str(
        settings.database_path.parent / "ui-extension"
    )
    ui = UiSettings(data_dir=Path(os.path.realpath(data_dir)))
    ui.environment = os.getenv(
        "CMUI_ENV", "production" if settings.app_env == "production" else "development"
    )
    ui.integration_mode = "integrated"
    ui.auth_mode = "injected"
    ui.allowed_origins = ui_allowed_origins(settings)
    ui.clerk_issuer = os.getenv("CLERK_ISSUER", "")
    ui.clerk_jwt_key = os.getenv("CLERK_JWT_KEY", "").replace("\\n", "\n")
    ui.clerk_audience = os.getenv("CLERK_AUDIENCE", "")
    ui.clerk_publishable_key = os.getenv("CLERK_PUBLISHABLE_KEY", "")
    ui.admin_ids = tuple(
        item.strip() for item in settings.admin_user_ids.split(",") if item.strip()
    )
    if os.getenv("CMUI_PROVIDER_MODE"):
        ui.provider_mode = os.environ["CMUI_PROVIDER_MODE"]
    ui.allow_billable = os.getenv("CMUI_ALLOW_BILLABLE", "false").lower() == "true"
    ui.qwen_model = settings.v3_model
    ui.qwen_base_url = os.getenv("CMUI_QWEN_BASE_URL") or (settings.v3_model_base_url or "")
    ui.qwen_key = os.getenv("CMUI_QWEN_API_KEY") or (
        settings.v3_model_api_key.get_secret_value() if settings.v3_model_api_key else ""
    )
    ui.qwen_protocol = os.getenv("CMUI_QWEN_PROTOCOL", "chat_completions")
    ui.timeout = float(
        os.getenv("CMUI_MODEL_TIMEOUT", str(settings.v3_model_timeout_seconds))
    )
    ui.prompt_tokens = int(os.getenv("CMUI_PROMPT_TOKENS", "2500"))
    ui.answer_tokens = int(
        os.getenv("CMUI_ANSWER_TOKENS", str(max(settings.v3_max_output_tokens, 6500)))
    )
    ui.api_base = MOUNT_PATH + "/api/ui/v1"
    ui.web_dir = settings.ui_web_dir
    # A non-existent web_dir is intentional: the host does not serve the
    # offline-verified bundle, and the production gate still rejects it if present.
    ui.validate()
    return ui


def mount_ui_extension(
    host_app: FastAPI,
    *,
    mount_path: str = MOUNT_PATH,
    provider: object = None,
    coverage_reviewer: object = None,
) -> object | None:
    """Attach the new UI to an already-built host application.

    Callers gate this on ``Settings.ui_extension_enabled`` (env
    ``UI_EXTENSION_ENABLED``), which is off by default, so an operator must opt in
    explicitly before the new surface exists.

    `provider` is a test seam only; production mounts pass none and the extension
    selects the real Qwen/disabled provider from its own settings.

    One adapter instance is shared: it is stateless apart from a context variable
    that is reset at the start of every `DomainPort.call`, so concurrent requests
    never see each other's memoised rows.
    """

    settings: Settings = host_app.state.settings
    database: Database = host_app.state.database
    ingestion: IngestionService = host_app.state.ingestion_service
    learning: LearningOrchestrator | None = getattr(host_app.state, "learning", None)
    retriever: HybridRetriever = host_app.state.qa_service.retriever

    adapter = V3DomainAdapter(
        database=database,
        settings=settings,
        ingestion=ingestion,
        learning=learning,
        retriever=retriever,
        task_agent_url=os.getenv("UI_TASK_AGENT_URL", settings.ui_task_agent_url),
        coverage_reviewer=coverage_reviewer or _coverage_reviewer(settings),
    )
    ui_settings = _ui_settings(settings)
    from app.cm_update.integration import install_ui_extension

    ui = install_ui_extension(
        host_app,
        ui_settings,
        adapter,
        clerk_subject_resolver(host_app),
        mount_path=mount_path,
        provider=provider,
    )
    _allow_browser_credentials(host_app, mount_path, ui_settings.allowed_origins)
    _prepend_legacy_history(ui, adapter)
    # Exposed for tests and operational diagnostics; the adapter holds no secrets.
    host_app.state.ui_extension_adapter = adapter
    host_app.state.ui_extension_app = ui
    from app.errors import ApiError
    def authorize_content(course, subject, is_admin=False):
        if is_admin or subject in settings.admin_user_id_set:
            return
        fields=set(course.keys())
        required=('requires_student_verification' in fields and course['requires_student_verification']) or ('display_type' in fields and course['display_type']=='campus') or ('course_type' in fields and course['course_type']=='official')
        if required:
            verification=ui.state.db.one('SELECT verified FROM cmui_verification WHERE owner=?',(subject,))
            if not verification or not verification['verified']:
                raise ApiError(403,'STUDENT_VERIFICATION_REQUIRED','请先完成学生认证')
    database.course_content_authorizer=authorize_content
    return ui


def _prepend_legacy_history(ui: object, adapter: V3DomainAdapter) -> None:
    """Add read-only routes for the pre-existing V3 conversations.

    The delivered module has no route for them, and copying the old rows into the
    refreshed shell's history would create two histories that drift apart. These
    routes therefore project the original `conversations`/`messages` tables through
    the same adapter, so the caller's verified identity and course authorization
    still apply and nothing becomes unreachable when the new navigation replaces
    the old one.

    The routes are inserted ahead of the sub-application's existing routes: when a
    built frontend is present, `cm_update` registers a catch-all static mount that
    would otherwise answer every unmatched path, including these.
    """

    from fastapi import APIRouter, HTTPException

    from app.cm_update.auth import current_user

    router = APIRouter()

    async def _call(operation: str, payload: dict[str, object], request: Request) -> object:
        user = await current_user(request)
        try:
            return await adapter.call(
                operation, user["id"], payload, request.headers.get("authorization", "")
            )
        except HTTPException:
            raise

    @router.get(
        "/api/ui/v1/courses/{course_id}/legacy-conversations",
        response_model=None,
    )
    async def legacy_conversations(course_id: str, request: Request):
        rows = await _call("legacy.conversations", {"course": course_id}, request)
        return JSONResponse(content=rows)

    @router.get(
        "/api/ui/v1/courses/{course_id}/legacy-conversations/{conversation_id}",
        response_model=None,
    )
    async def legacy_conversation(
        course_id: str,
        conversation_id: str,
        request: Request,
    ):
        body = await _call(
            "legacy.conversation",
            {"course": course_id, "id": conversation_id},
            request,
        )
        return JSONResponse(content=body)

    ui.routes[:0] = router.routes  # type: ignore[attr-defined]


def _allow_browser_credentials(
    host_app: FastAPI, mount_path: str, allowed_origins: tuple[str, ...]
) -> None:
    """Complete the CORS and caching contract the delivered browser client requires.

    Two gaps appear only once the UI is *mounted* rather than run standalone:

    * `apps/web/src/ui/api.js` always sends `credentials: 'include'`, so a browser
      demands `Access-Control-Allow-Credentials: true` on the preflight *and* on the
      response. Starlette's middleware answers the preflight for the mounted
      sub-application without that header.
    * the delivered no-store middleware keys off a literal `/api/` path prefix,
      which the mounted path `/ui-extension/api/...` does not match.

    Both are fixed here, scoped strictly to the extension's own paths. Only a
    response header is added - never a cookie, token or secret - and an origin the
    extension does not already allow still receives no allow-origin header.
    """

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as StarletteRequest

    prefix = mount_path.rstrip("/") + "/"

    class ExtensionResponseHeaders(BaseHTTPMiddleware):
        async def dispatch(self, request: StarletteRequest, call_next: object) -> object:
            response = await call_next(request)  # type: ignore[operator]
            if not request.url.path.startswith(prefix):
                return response
            # Every extension response is per-user data and must never be stored.
            response.headers["Cache-Control"] = "private, no-store"
            origin = request.headers.get("origin", "")
            if origin in allowed_origins and "access-control-allow-origin" in response.headers:
                response.headers["Access-Control-Allow-Credentials"] = "true"
            else:
                try:
                    del response.headers["Access-Control-Allow-Credentials"]
                except KeyError:
                    pass
            return response

    host_app.add_middleware(ExtensionResponseHeaders)
