from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated service configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: SecretStr | None = None
    openai_chat_model: str = "gpt-5.6-luna"
    openai_embedding_model: str = "text-embedding-3-small"
    web_origin: str = "http://localhost:5173"

    database_path: Path = Path("../../data/rag.sqlite3")
    upload_dir: Path = Path("../../data/uploads")
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
