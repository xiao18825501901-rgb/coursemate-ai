"""Settings validation: fail fast on a misconfigured service."""

from __future__ import annotations

import pytest
from app.settings import PINNED_MODEL_REVISION, Settings
from pydantic import ValidationError


def test_fake_backend_needs_no_secret_or_model_dir() -> None:
    s = Settings(model_backend="fake", app_env="test")
    assert s.model_backend == "fake"
    assert s.service_token_plain is None


def test_real_backend_requires_service_token() -> None:
    with pytest.raises(ValidationError):
        Settings(model_backend="real", model_dir="/tmp/laya")


def test_real_backend_requires_model_dir() -> None:
    with pytest.raises(ValidationError):
        Settings(model_backend="real", service_token="s")


def test_real_backend_with_both_is_valid() -> None:
    s = Settings(model_backend="real", service_token="s", model_dir="/tmp/laya")
    assert s.model_revision == PINNED_MODEL_REVISION


def test_head_max_len_must_be_smaller_than_max_len() -> None:
    with pytest.raises(ValidationError):
        Settings(model_backend="fake", max_len=256, head_max_len=256)


def test_defaults_match_node_budget() -> None:
    s = Settings(model_backend="fake")
    assert s.concurrency == 1
    assert s.queue_size == 8
    assert s.torch_threads == 8
    assert s.torch_interop_threads == 1
    assert s.max_deadline_ms == 30_000
