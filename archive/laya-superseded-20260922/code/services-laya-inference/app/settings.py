"""Validated service configuration loaded from environment variables.

Every Laya setting is prefixed ``LAYA_`` (for example ``LAYA_MODEL_BACKEND``,
``LAYA_SERVICE_TOKEN``). Values are validated up front so a misconfigured
service fails fast at startup rather than misbehaving under load.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The one multilingual checkpoint CourseMate deploys. The revision is pinned so
# the server never drifts onto a newer (or ``latest``) snapshot it has not
# reviewed. Never change these without a new model-manifest and a re-review.
PINNED_MODEL_REPO = "convaiinnovations/laya"
PINNED_MODEL_SUBFOLDER = "multilingual"
PINNED_MODEL_REVISION = "1c5edc17a7acd8701df6fc341c0d179f1c62c982"


class Settings(BaseSettings):
    """Laya service settings. Env vars use the ``LAYA_`` prefix."""

    model_config = SettingsConfigDict(
        env_prefix="LAYA_",
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- process ---------------------------------------------------------
    app_env: Literal["development", "test", "production"] = "production"
    host: str = "127.0.0.1"  # loopback only; see the runbook for the VPC rules
    port: int = Field(default=8105, ge=1, le=65535)
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    # --- auth ------------------------------------------------------------
    # Pre-shared service credential. Required for the real backend; optional
    # only for the fake backend (local dev/test). Never a browser Clerk token.
    service_token: SecretStr | None = None

    # --- model -----------------------------------------------------------
    # "real" loads the pinned Laya snapshot; "fake" runs a deterministic in-process
    # stand-in with NO torch/network/model download (tests + local smoke only).
    model_backend: Literal["real", "fake"] = "real"
    model_repo: str = PINNED_MODEL_REPO
    model_subfolder: str = PINNED_MODEL_SUBFOLDER
    model_revision: str = PINNED_MODEL_REVISION
    # Local snapshot directory produced by scripts/fetch_laya_model.py --dest.
    # The server only ever loads from here; it never reaches the hub at runtime.
    model_dir: Path | None = None
    # Runtime HF hub is offline: the snapshot is the only source of weights.
    offline: bool = True

    # torch thread budget. Defaults derived from the 8 vCPU / 16 GiB node:
    #   intra-op = 8  (one thread per vCPU for the single resident model)
    #   inter-op = 1  (concurrency is 1, so parallel op overlap only thrashes)
    torch_threads: int = Field(default=8, ge=1, le=64)
    torch_interop_threads: int = Field(default=1, ge=1, le=8)

    # Model geometry (must match the multilingual checkpoint's rl_agent_config).
    max_len: int = Field(default=1024, ge=1, le=8192)
    head_max_len: int = Field(default=256, ge=16, le=4096)

    # --- engine ----------------------------------------------------------
    concurrency: int = Field(default=1, ge=1, le=8)
    queue_size: int = Field(default=8, ge=1, le=1000)
    # Server-side ceiling on the client's deadline. A client may ask for less,
    # never more; this keeps one request from pinning the single worker.
    max_deadline_ms: float = Field(default=30_000, gt=0)

    # --- validation / anti-abuse ----------------------------------------
    max_body_bytes: int = Field(default=2 * 1024 * 1024, ge=1024)
    max_questions: int = Field(default=10, ge=1, le=100)
    max_options_per_question: int = Field(default=20, ge=2, le=256)
    max_instruction_chars: int = Field(default=2_000, ge=1)
    max_state_chars: int = Field(default=200_000, ge=1)
    # Measured with the real tokenizer at request time; ~8 questions at full
    # 1024-token budget. The headroom is deliberate: a single CPU forward pass
    # over a 10k-token batch is already far beyond the intended decision size.
    max_request_tokens: int = Field(default=8192, ge=1)

    # The multilingual checkpoint ships with NO fitted temperatures, so its
    # probabilities are raw/uncalibrated. We surface this instead of pretending.
    calibration_version: str = "none"

    # Server-managed allowlist of (decision_definition_id, definition_version)
    # -> canonical question schemas. Empty/absent => every definition is unknown
    # (fail closed). See README for the registry JSON shape.
    definitions_path: Path | None = None

    @model_validator(mode="after")
    def _validate_consistency(self) -> Settings:
        if self.model_backend == "real":
            if self.service_token is None:
                raise ValueError(
                    "LAYA_SERVICE_TOKEN is required when LAYA_MODEL_BACKEND=real"
                )
            if self.model_dir is None:
                raise ValueError(
                    "LAYA_MODEL_DIR is required when LAYA_MODEL_BACKEND=real "
                    "(the pinned snapshot produced by fetch_laya_model.py)"
                )
        if self.head_max_len >= self.max_len:
            raise ValueError("LAYA_HEAD_MAX_LEN must be smaller than LAYA_MAX_LEN")
        return self

    @property
    def service_token_plain(self) -> str | None:
        """The service token as plaintext, or None when unset (fake/test only)."""
        if self.service_token is None:
            return None
        return self.service_token.get_secret_value()
