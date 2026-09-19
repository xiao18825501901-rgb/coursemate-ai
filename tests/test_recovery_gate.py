"""Bounded publication handling; real OS/CLI coverage remains separate."""
import importlib.util
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location('recovery_gate', Path(__file__).parents[1] / 'ops/restore_v2.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def denied(number=5):
    error = PermissionError('synthetic Windows denial')
    error.winerror = number
    return error


def test_transient_publication_completes_in_same_invocation(module, monkeypatch, tmp_path, capsys):
    partial, target = tmp_path / '.partial', tmp_path / 'target'
    partial.mkdir()
    attempts, sleeps = [], []
    def rename(source, destination):
        attempts.append((source, destination))
        if len(attempts) < 3:
            raise denied()
        source.rename(destination)
    monkeypatch.setattr(module, '_rename_no_replace', rename)
    monkeypatch.setattr(module, 'time', SimpleNamespace(sleep=sleeps.append), raising=False)
    assert module._publish_partial(partial, target) == target
    assert len(attempts) == 3 and sleeps == [0.1, 0.2]
    assert 'attempt=1 winerror=5' in capsys.readouterr().err


def test_persistent_denial_is_bounded_and_keeps_staging(module, monkeypatch, tmp_path):
    partial, target = tmp_path / '.partial', tmp_path / 'target'
    partial.mkdir()
    (partial / 'proof').write_bytes(b'untouched')
    attempts, sleeps = [], []
    def rename(*args):
        attempts.append(args)
        raise denied(32)
    monkeypatch.setattr(module, '_rename_no_replace', rename)
    monkeypatch.setattr(module, 'time', SimpleNamespace(sleep=sleeps.append), raising=False)
    with pytest.raises(RuntimeError, match='RESTORE_RESUME_PARTIAL'):
        module._publish_partial(partial, target)
    assert len(attempts) == 5 and sum(sleeps) == pytest.approx(1.5)
    assert (partial / 'proof').read_bytes() == b'untouched' and not target.exists()


def test_racing_target_after_denial_is_never_overwritten(module, monkeypatch, tmp_path):
    partial, target = tmp_path / '.partial', tmp_path / 'target'
    partial.mkdir()
    attempts = []
    def rename(*args):
        attempts.append(args)
        raise denied()
    def race(delay):
        target.mkdir()
        (target / 'proof').write_bytes(b'existing')
    monkeypatch.setattr(module, '_rename_no_replace', rename)
    monkeypatch.setattr(module, 'time', SimpleNamespace(sleep=race), raising=False)
    with pytest.raises(FileExistsError):
        module._publish_partial(partial, target)
    assert len(attempts) == 1
    assert partial.exists() and (target / 'proof').read_bytes() == b'existing'


def test_non_windows_error_never_retried(module, monkeypatch, tmp_path):
    attempts = []
    def rename(*args):
        attempts.append(args)
        raise OSError(28, 'synthetic disk error')
    monkeypatch.setattr(module, '_rename_no_replace', rename)
    with pytest.raises(OSError):
        module._publish_partial(tmp_path / '.partial', tmp_path / 'target')
    assert len(attempts) == 1


@pytest.mark.parametrize('include_ui', [False, True])
def test_application_resources_closed_before_publication(module, monkeypatch, tmp_path, include_ui):
    from test_codex_backup_publication import backup_fixture
    backup_fixture(tmp_path, monkeypatch, include_ui=include_ui)
    connections, files, archives = [], [], []
    connect, opened, archive_open = sqlite3.connect, Path.open, module.tarfile.open
    def tracked_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection
    def tracked_open(*args, **kwargs):
        handle = opened(*args, **kwargs)
        files.append(handle)
        return handle
    def tracked_archive(*args, **kwargs):
        archive = archive_open(*args, **kwargs)
        archives.append(archive)
        return archive
    original = module._rename_no_replace
    def audit_and_publish(source, target):
        assert connections and archives and files
        assert all(handle.closed for handle in files)
        assert all(archive.closed for archive in archives)
        for connection in connections:
            with pytest.raises(sqlite3.ProgrammingError, match='closed'):
                connection.execute('SELECT 1')
        original(source, target)
    monkeypatch.setattr(module.sqlite3, 'connect', tracked_connect)
    monkeypatch.setattr(Path, 'open', tracked_open)
    monkeypatch.setattr(module.tarfile, 'open', tracked_archive)
    monkeypatch.setattr(module, '_rename_no_replace', audit_and_publish)
    assert module.restore_backup().is_dir()


@pytest.mark.parametrize('include_ui', [False, True])
def test_fresh_top_level_command_records_real_publication_attempts(tmp_path, monkeypatch, include_ui):
    from test_codex_backup_publication import backup_fixture
    _, target = backup_fixture(tmp_path, monkeypatch, include_ui=include_ui)
    result = subprocess.run([sys.executable, str(Path(__file__).parents[1] / 'ops/restore_v2.py')],
                            capture_output=True, text=True, timeout=15)
    (tmp_path / 'restore-stdout.txt').write_text(result.stdout, encoding='utf-8')
    (tmp_path / 'restore-stderr.txt').write_text(result.stderr, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    assert target.is_dir() and not list(tmp_path.glob('.restored.*.partial'))
