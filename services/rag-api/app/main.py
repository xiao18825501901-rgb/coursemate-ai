import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.ingestion import router as ingestion_router
from app.api.learning import router as learning_router
from app.api.publication import router as publication_router
from app.api.qa import router as qa_router
from app.api.teaching_profiles import router as teaching_profiles_router
from app.auth import AuthVerifier, ClerkAuthVerifier, TestAuthVerifier
from app.config import Settings
from app.db import Database
from app.errors import ApiError
from app.learning.orchestrator import LearningOrchestrator
from app.rag.answers import (
    AnswerProvider,
    ExtractiveAnswerProvider,
    MissingAnswerProvider,
    OpenAIAnswerProvider,
)
from app.rag.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from app.rag.retrieval import HybridRetriever
from app.repositories.chunks import ChunkRepository
from app.services.ingestion import IngestionService, MissingEmbeddingProvider
from app.services.knowledge_publication import KnowledgePublicationService
from app.services.overlay_publication import OverlayPublicationService
from app.services.publication import PublicationService
from app.services.qa import QaService
from app.services.teaching_profiles import TeachingProfileService

LOGGER = logging.getLogger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    answer_provider: AnswerProvider | None = None,
    auth_verifier: AuthVerifier | None = None,
    ui_provider: object | None = None,
    ui_coverage_reviewer: object | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    if resolved_settings.auth_test_user_id and (
        resolved_settings.app_env != "test"
        or resolved_settings.rag_provider_mode != "deterministic"
    ):
        raise RuntimeError("AUTH_TEST_USER_ID is allowed only in test deterministic mode.")
    if (
        auth_verifier is None
        and not resolved_settings.auth_test_user_id
        and not (resolved_settings.clerk_secret_key or resolved_settings.clerk_jwt_key)
    ):
        raise RuntimeError("CLERK_SECRET_KEY or CLERK_JWT_KEY is required.")
    database = Database(resolved_settings)
    database.initialize()
    embedding_secret = resolved_settings.rag_embedding_api_key
    embedding_api_key = embedding_secret.get_secret_value() if embedding_secret else ""
    chat_secret = resolved_settings.rag_chat_api_key
    chat_api_key = chat_secret.get_secret_value() if chat_secret else ""
    if embedding_provider is None:
        if resolved_settings.rag_provider_mode == "deterministic":
            embedding_provider = DeterministicEmbeddingProvider()
        else:
            embedding_provider = (
                OpenAIEmbeddingProvider(
                    api_key=embedding_api_key,
                    model=resolved_settings.rag_embedding_model,
                    base_url=resolved_settings.rag_embedding_base_url,
                )
                if embedding_api_key
                else MissingEmbeddingProvider()
            )
    if answer_provider is None:
        if resolved_settings.rag_provider_mode == "deterministic":
            answer_provider = ExtractiveAnswerProvider()
        else:
            answer_provider = (
                OpenAIAnswerProvider(
                    api_key=chat_api_key,
                    model=resolved_settings.rag_chat_model,
                    base_url=resolved_settings.rag_chat_base_url,
                )
                if chat_api_key
                else MissingAnswerProvider()
            )

    application = FastAPI(title="CourseMate RAG API", version="0.1.0")
    application.state.ingestion_service = IngestionService(
        database,
        resolved_settings,
        embedding_provider,
    )
    application.state.database = database
    if resolved_settings.v3_enabled:
        application.state.learning = LearningOrchestrator(
            database, resolved_settings,
            HybridRetriever(ChunkRepository(database), embedding_provider)
        )
    teaching_profile_service = TeachingProfileService(database)
    application.state.teaching_profile_service = teaching_profile_service
    application.state.publication_service = PublicationService(database)
    application.state.knowledge_publication_service = KnowledgePublicationService(database)
    application.state.overlay_publication_service = OverlayPublicationService(database)
    application.state.settings = resolved_settings
    application.state.auth_verifier = (
        auth_verifier
        or (
            TestAuthVerifier(resolved_settings.auth_test_user_id)
            if resolved_settings.auth_test_user_id
            else ClerkAuthVerifier(resolved_settings)
        )
    )
    application.state.qa_service = QaService(
        database,
        HybridRetriever(ChunkRepository(database), embedding_provider),
        answer_provider,
        top_k=resolved_settings.top_k,
        max_context_chars=resolved_settings.max_context_chars,
        teaching_profiles=teaching_profile_service,
    )
    cors_origins = [resolved_settings.web_origin]
    cors_methods = ["GET", "HEAD", "POST", "PATCH", "DELETE", "OPTIONS"]
    if resolved_settings.ui_extension_enabled:
        from app.ui_extension.mount import ui_allowed_origins

        for origin in ui_allowed_origins(resolved_settings):
            if origin not in cors_origins:
                cors_origins.append(origin)
        # The refreshed shell pins courses with PUT, which the host policy did not
        # previously need. Only added when the extension is actually mounted.
        cors_methods.insert(2, "PUT")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=cors_methods,
        allow_headers=["Authorization", "Content-Type"],
    )

    @application.middleware("http")
    async def security_headers(request: Request, call_next: object) -> object:
        response = await call_next(request)  # type: ignore[operator]
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'"
        )
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if (
            request.url.path.startswith("/api/learning")
            or request.url.path.startswith("/api/admin")
            or request.url.path.startswith("/api/shared-overlays")
            or "publication-requests" in request.url.path
        ):
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Vary"] = "Authorization"
        return response

    @application.exception_handler(ApiError)
    async def api_error_handler(request: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": error.details,
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "The request did not pass validation.",
                    "details": {"issues": jsonable_encoder(error.errors())},
                }
            },
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, error: Exception) -> JSONResponse:
        LOGGER.exception("Unhandled RAG API error", exc_info=error)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An internal error occurred.",
                    "details": {},
                }
            },
        )

    application.include_router(ingestion_router)
    application.include_router(qa_router)
    application.include_router(teaching_profiles_router)
    application.include_router(publication_router)
    if resolved_settings.v3_enabled:
        application.include_router(learning_router)
    if resolved_settings.ui_extension_enabled:
        from app.ui_extension.mount import mount_ui_extension

        mount_ui_extension(application, provider=ui_provider, coverage_reviewer=ui_coverage_reviewer)
    return application
