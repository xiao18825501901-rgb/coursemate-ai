from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated service configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    openai_chat_model: str = "gpt-5.6-luna"
    openai_embedding_model: str = "text-embedding-3-small"
    rag_chat_api_key: SecretStr | None = None
    rag_chat_base_url: str | None = None
    rag_chat_model: str = ""
    rag_embedding_api_key: SecretStr | None = None
    rag_embedding_base_url: str | None = None
    rag_embedding_model: str = ""
    rag_provider_mode: Literal["openai", "deterministic"] = "openai"
    web_origin: str = "http://localhost:5173"
    clerk_secret_key: SecretStr | None = None
    clerk_jwt_key: SecretStr | None = None
    admin_user_ids: str = ""
    rag_qa_requests_per_minute: int = Field(default=10, ge=1, le=1_000)
    app_env: Literal["development", "test", "production"] = "production"
    auth_test_user_id: str | None = None
    v3_enabled: bool = False
    v3_model: Literal["qwen3.8-max"] = "qwen3.8-max"
    v3_model_api_key: SecretStr | None = None
    v3_model_base_url: str | None = None
    v3_max_output_tokens: int = Field(default=4000, ge=500, le=8000)
    v3_model_timeout_seconds: int = Field(default=180, ge=30, le=600)
    v3_daily_operations: int = Field(default=30, ge=1, le=500)
    v3_daily_model_calls_per_user: int = Field(default=60, ge=1, le=1_000)
    v3_daily_model_calls_per_user_course: int = Field(default=60, ge=1, le=1_000)
    v3_problem_image_max_bytes: int = Field(
        default=10 * 1024 * 1024, ge=1_024, le=20 * 1024 * 1024
    )
    v3_preview_max_bytes: int = Field(default=2 * 1024 * 1024, ge=1_024, le=20 * 1024 * 1024)
    v3_preview_max_text_chars: int = Field(default=100_000, ge=1_000, le=1_000_000)
    v3_preview_max_csv_rows: int = Field(default=200, ge=1, le=5_000)
    v3_preview_max_csv_columns: int = Field(default=50, ge=1, le=500)
    v3_preview_max_cell_chars: int = Field(default=2_000, ge=10, le=20_000)
    v3_preview_max_notebook_cells: int = Field(default=100, ge=1, le=1_000)
    v3_preview_max_image_pixels: int = Field(default=40_000_000, ge=1, le=100_000_000)
    v3_preview_max_image_dimension: int = Field(default=16_384, ge=1, le=100_000)
    v3_office_max_archive_entries: int = Field(default=2_000, ge=1, le=20_000)
    v3_office_max_uncompressed_bytes: int = Field(
        default=50 * 1024 * 1024, ge=1_024, le=500 * 1024 * 1024
    )
    v3_office_max_compression_ratio: int = Field(default=100, ge=1, le=1_000)

    database_path: Path = Field(
        default=Path("../../data/rag.sqlite3"),
        validation_alias=AliasChoices("RAG_DATABASE_PATH", "DATABASE_PATH"),
    )
    upload_dir: Path = Field(
        default=Path("../../data/uploads"),
        validation_alias=AliasChoices("RAG_UPLOAD_DIR", "UPLOAD_DIR"),
    )
    chunk_size: int = Field(default=1_200, ge=200, le=12_000)
    chunk_overlap: int = Field(default=200, ge=0, le=4_000)
    top_k: int = Field(default=6, ge=1, le=30)
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1_024, le=100 * 1024 * 1024)
    user_course_max_courses: int = Field(default=10, ge=1, le=1_000)
    user_course_max_files: int = Field(default=50, ge=1, le=10_000)
    user_course_max_total_upload_bytes: int = Field(
        default=500 * 1024 * 1024,
        ge=1_024,
        le=100 * 1024 * 1024 * 1024,
    )
    max_context_chars: int = Field(default=18_000, ge=1_000, le=100_000)

    @model_validator(mode="after")
    def validate_chunk_window(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self.rag_chat_api_key = self.rag_chat_api_key or self.openai_api_key
        self.rag_chat_base_url = self.rag_chat_base_url or self.openai_base_url
        self.rag_chat_model = self.rag_chat_model or self.openai_chat_model
        self.rag_embedding_api_key = self.rag_embedding_api_key or self.openai_api_key
        self.rag_embedding_base_url = self.rag_embedding_base_url or self.openai_base_url
        self.rag_embedding_model = self.rag_embedding_model or self.openai_embedding_model
        return self

    @property
    def admin_user_id_set(self) -> frozenset[str]:
        return frozenset(item.strip() for item in self.admin_user_ids.split(",") if item.strip())
