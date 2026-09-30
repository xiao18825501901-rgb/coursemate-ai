from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).parents[3]
MONITOR_SCRIPT = REPOSITORY_ROOT / "ops" / "monitor_v2.py"


def _monitor_module() -> ModuleType:
    specification = importlib.util.spec_from_file_location("monitor_v2", MONITOR_SCRIPT)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def _completed_backup(root: Path, created_at: datetime) -> Path:
    backup = root / "coursemate-v2-test"
    backup.mkdir(parents=True)
    for name in {
        "SHA256SUMS",
        "agent.sqlite3",
        "rag.sqlite3",
        "sqlite-check.txt",
        "uploads.tar.gz",
    }:
        backup.joinpath(name).write_bytes(b"test")
    backup.joinpath("manifest.json").write_text(
        json.dumps({"createdAt": created_at.isoformat()}), encoding="utf-8"
    )
    return backup


def test_backup_monitor_accepts_fresh_complete_backup_and_ignores_partial(tmp_path: Path) -> None:
    monitor = _monitor_module()
    now = datetime(2026, 8, 14, tzinfo=UTC)
    _completed_backup(tmp_path, now - timedelta(hours=1))
    partial = tmp_path / ".coursemate-v2-newer.partial"
    partial.mkdir()

    result = monitor.check_backup(tmp_path, timedelta(hours=26), now)

    assert result.ok is True
    # The detail now also reports the size the next backup would need and the
    # space available, so the check states a capacity fact instead of only an age.
    assert result.detail.startswith("latest backup age is 3600s")


def test_backup_monitor_fails_closed_for_stale_or_incomplete_backup(tmp_path: Path) -> None:
    monitor = _monitor_module()
    now = datetime(2026, 8, 14, tzinfo=UTC)
    _completed_backup(tmp_path, now - timedelta(hours=27))

    stale = monitor.check_backup(tmp_path, timedelta(hours=26), now)
    assert stale.ok is False
    assert "stale" in stale.detail

    (tmp_path / "coursemate-v2-test" / "agent.sqlite3").unlink()
    incomplete = monitor.check_backup(tmp_path, timedelta(hours=26), now)
    assert incomplete.ok is False
    assert incomplete.detail == "no completed backup was found"


def _free_space(monkeypatch: pytest.MonkeyPatch, monitor: ModuleType, free: int) -> None:
    class _Usage:
        def __init__(self, free_bytes: int) -> None:
            self.free = free_bytes

    monkeypatch.setattr(monitor.shutil, "disk_usage", lambda _path: _Usage(free))


def test_backup_monitor_fails_when_the_next_backup_does_not_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An absolute free-space floor does not express this failure.

    On the deployment this check was written for, the floor is 1 GiB while one
    backup occupies 1.7 GiB: the disk passes its own check and still has no room
    for the next backup.  Comparing free space with the last backup's real size
    turns that into a reported condition instead of a silent cliff.
    """
    monitor = _monitor_module()
    now = datetime(2026, 8, 14, tzinfo=UTC)
    backup = _completed_backup(tmp_path, now - timedelta(hours=1))
    backup.joinpath("big.bin").write_bytes(b"x" * 4096)
    _free_space(monkeypatch, monitor, 1024)

    result = monitor.check_backup(tmp_path, timedelta(hours=26), now)

    assert result.ok is False
    assert "does not fit" in result.detail
    assert "occupies" in result.detail
    assert "1024 bytes are free" in result.detail


def test_backup_monitor_accepts_a_backup_that_still_fits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor = _monitor_module()
    now = datetime(2026, 8, 14, tzinfo=UTC)
    _completed_backup(tmp_path, now - timedelta(hours=1))
    _free_space(monkeypatch, monitor, 10**12)

    result = monitor.check_backup(tmp_path, timedelta(hours=26), now)

    assert result.ok is True
    assert "bytes free" in result.detail


def test_backup_monitor_ignores_symlinked_completed_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor = _monitor_module()
    now = datetime(2026, 8, 14, tzinfo=UTC)
    backup_root = tmp_path / "backups"
    completed = _completed_backup(backup_root, now - timedelta(hours=1))
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == completed or original_is_symlink(path),
    )

    result = monitor.check_backup(backup_root, timedelta(hours=26), now)

    assert result.ok is False
    assert result.detail == "no completed backup was found"


def test_health_monitor_requires_https_without_leaking_url() -> None:
    monitor = _monitor_module()

    result = monitor.check_health("rag", "http://secret-host/health", "rag-api", 1)

    assert result.ok is False
    assert result.detail == "health URL must use HTTPS"
    assert "secret-host" not in result.detail


def test_health_monitor_rejects_malformed_url_without_leaking_it() -> None:
    monitor = _monitor_module()

    for url in ("https://secret-host/\x00", "https://[secret-host/health"):
        result = monitor.check_health("rag", url, "rag-api", 1)

        assert result.ok is False
        assert result.detail == "health URL format is invalid"
        assert "secret-host" not in result.detail


def test_backup_monitor_ignores_symlinked_required_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor = _monitor_module()
    now = datetime(2026, 8, 14, tzinfo=UTC)
    completed = _completed_backup(tmp_path, now - timedelta(hours=1))
    linked_artifact = completed / "manifest.json"
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == linked_artifact or original_is_symlink(path),
    )

    result = monitor.check_backup(tmp_path, timedelta(hours=26), now)

    assert result.ok is False
    assert result.detail == "no completed backup was found"


def test_main_fails_closed_when_monitoring_paths_and_urls_are_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monitor = _monitor_module()
    for name in (
        "RAG_HEALTH_URL",
        "AGENT_HEALTH_URL",
        "BACKUP_ROOT",
        "RAG_UPLOAD_DIR",
    ):
        monkeypatch.delenv(name, raising=False)

    assert monitor.main() == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failing"
    assert [check["name"] for check in payload["checks"]] == [
        "rag",
        "agent",
        "backup",
        "disk",
    ]
