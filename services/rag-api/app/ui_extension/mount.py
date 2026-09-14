"""Mount the delivered new UI onto the existing RAG API application.

The host keeps every route, middleware and lifespan it already had. The UI is
mounted at a distinct sub-path and only in ``integrated`` + ``injected`` mode,
which is what stops a production deployment from accidentally running the
standalone reference store instead of the real V3 domain.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from app.config import Settings
from app.db import Database
from app.learning.orchestrator import LearningOrchestrator
from app.rag.retrieval import HybridRetriever
from app.services.ingestion import IngestionService
from app.ui_extension.domain import V3DomainAdapter
from app.ui_extension.identity import clerk_subject_resolver

MOUNT_PATH = "/ui-extension"


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
    origins = os.getenv("CMUI_ALLOWED_ORIGINS")
    ui.allowed_origins = (
        tuple(item.strip() for item in origins.split(",") if item.strip())
        if origins
        else (settings.web_origin,)
    )
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


def mount_ui_extension(host_app: FastAPI, *, mount_path: str = MOUNT_PATH) -> object | None:
    """Attach the new UI to an already-built host application.

    Callers gate this on ``Settings.ui_extension_enabled`` (env
    ``UI_EXTENSION_ENABLED``), which is off by default, so an operator must opt in
    explicitly before the new surface exists.

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
    )
    from app.cm_update.integration import install_ui_extension

    ui = install_ui_extension(
        host_app,
        _ui_settings(settings),
        adapter,
        clerk_subject_resolver(host_app),
        mount_path=mount_path,
    )
    # Exposed for tests and operational diagnostics; the adapter holds no secrets.
    host_app.state.ui_extension_adapter = adapter
    host_app.state.ui_extension_app = ui
    return ui
