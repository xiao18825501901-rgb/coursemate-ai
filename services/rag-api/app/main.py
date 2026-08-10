import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.ingestion import router as ingestion_router
from app.api.qa import router as qa_router
from app.config import Settings
from app.db import Database
from app.errors import ApiError
from app.rag.answers import AnswerProvider, MissingAnswerProvider, OpenAIAnswerProvider
from app.rag.embeddings import EmbeddingProvider, OpenAIEmbeddingProvider
from app.rag.retrieval import HybridRetriever
from app.repositories.chunks import ChunkRepository
from app.services.ingestion import IngestionService, MissingEmbeddingProvider
from app.services.qa import QaService

LOGGER = logging.getLogger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    answer_provider: AnswerProvider | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    database = Database(resolved_settings)
    database.initialize()
    secret = resolved_settings.openai_api_key
    api_key = secret.get_secret_value() if secret else ""
    if embedding_provider is None:
        embedding_provider = (
            OpenAIEmbeddingProvider(
                api_key=api_key,
                model=resolved_settings.openai_embedding_model,
            )
            if api_key
            else MissingEmbeddingProvider()
        )
    if answer_provider is None:
        answer_provider = (
            OpenAIAnswerProvider(api_key=api_key, model=resolved_settings.openai_chat_model)
            if api_key
            else MissingAnswerProvider()
        )

    application = FastAPI(title="CourseMate RAG API", version="0.1.0")
    application.state.ingestion_service = IngestionService(
        database,
        resolved_settings,
        embedding_provider,
    )
    application.state.database = database
    application.state.settings = resolved_settings
    application.state.qa_service = QaService(
        database,
        HybridRetriever(ChunkRepository(database), embedding_provider),
        answer_provider,
        top_k=resolved_settings.top_k,
        max_context_chars=resolved_settings.max_context_chars,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved_settings.web_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @application.middleware("http")
    async def security_headers(request: Request, call_next: object) -> object:
        response = await call_next(request)  # type: ignore[operator]
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
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
    return application


app = create_app()
