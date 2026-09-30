"""The hybrid reviewer chain has to survive being switched on.

`HYBRID_QUALITY_ENABLED` is off by default, and that default hid a defect: the
reviewer factory referenced `LearningProvider` without importing it, so the
service started normally with the flag unset and raised `NameError` on the first
deployment that turned the gate on.  Every other test exercised the gate through
scripts and direct service construction, which never runs this factory.

These tests build the chain the way `create_app` does, in both positions of the
flag, so "off" and "on" are both covered before a deployment discovers the
difference.
"""
from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.db import Database
from app.learning.hybrid_quality import HybridQualityService
from app.main import hybrid_reviewer_from_settings


def _settings(tmp_path: Path, *, hybrid: bool) -> Settings:
    return Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        hybrid_quality_enabled=hybrid,
    )


def test_the_hybrid_reviewer_is_absent_unless_the_deployment_opts_in(
    tmp_path: Path,
) -> None:
    """Unset means no paid call is ever made, so the chain must not be built."""
    settings = _settings(tmp_path, hybrid=False)
    assert hybrid_reviewer_from_settings(settings, Database(settings)) is None


def test_the_hybrid_reviewer_builds_when_the_flag_is_on(tmp_path: Path) -> None:
    """The enabled path is real code and must be constructed at least once."""
    settings = _settings(tmp_path, hybrid=True)
    service = hybrid_reviewer_from_settings(settings, Database(settings))
    assert isinstance(service, HybridQualityService)
