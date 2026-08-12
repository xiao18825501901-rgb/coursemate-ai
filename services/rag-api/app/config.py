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
    openai_chat_model: str = "gpt-5.6-luna"
    openai_embedding_model: str = "text-embedding-3-small"
    rag_provider_mode: Literal["openai", "deterministic"] = "openai"
    web_origin: str = "http://localhost:5173"
    clerk_secret_key: SecretStr | None = None
    clerk_jwt_key: SecretStr | None = None
    admin_user_ids: str = ""
    rag_qa_requests_per_minute: int = Field(default=10, ge=1, le=1_000)

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
    max_context_chars: int = Field(default=18_000, ge=1_000, le=100_000)

    @model_validator(mode="after")
    def validate_chunk_window(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self

    @property
    def admin_user_id_set(self) -> frozenset[str]:
        return frozenset(item.strip() for item in self.admin_user_ids.split(",") if item.strip())
