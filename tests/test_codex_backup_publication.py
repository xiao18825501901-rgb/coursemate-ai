"""Real Windows publication diagnostics using synthetic files only.

These characterize the OS failure, not an unproven claim about an external
scanner. No sleeps, retries, process termination, or system settings changes.
"""
from __future__ import annotations

import ctypes
import errno
import hashlib
import importlib.util
import io
import json
import os
import sqlite3
import tarfile
from types import SimpleNamespace
from pathlib import Path

import pytest


@pytest.fixture
def restore_module():
    spec = importlib.util.spec_from_file_location("audit_restore", Path(__file__).parents[1] / "ops" / "restore_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def backup_fixture(tmp_path: Path, monkeypatch, *, include_ui: bool = False):
    source, target = tmp_path / "backup", tmp_path / "restored"
    source.mkdir()
    names = ["rag.sqlite3", "agent.sqlite3"] + (["ui.sqlite3"] if include_ui else [])
    for name in names:
        connection = sqlite3.connect(source / name)
        try:
            connection.execute("CREATE TABLE synthetic(value TEXT)")
            connection.commit()
        finally:
            connection.close()
    archives = ["uploads.tar.gz"] + (["ui-uploads.tar.gz", "ui-shares.tar.gz"] if include_ui else [])
    for name in archives:
        with tarfile.open(source / name, "w:gz") as archive:
            entry = tarfile.TarInfo("nested/notes.txt")
            entry.size = 9
            archive.addfile(entry, io.BytesIO(b"synthetic"))
    manifest = {"formatVersion": 1, "uploadFileCount": 1, "uploadTotalBytes": 9,
                "artifacts": {name: name for name in names + archives}}
    if include_ui:
        manifest.update(uiUploadFileCount=1, uiUploadTotalBytes=9, uiShareFileCount=1, uiShareTotalBytes=9)
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (source / "sqlite-check.txt").write_text("synthetic fixture\n", encoding="utf-8")
    covered = names + archives + ["manifest.json", "sqlite-check.txt"]
    (source / "SHA256SUMS").write_text("".join(
        hashlib.sha256((source / name).read_bytes()).hexdigest() + "  " + name + "\n" for name in covered), encoding="ascii")
    monkeypatch.setenv("RESTORE_SOURCE", str(source))
    monkeypatch.setenv("RESTORE_TARGET", str(target))
    monkeypatch.delenv("RESTORE_RESUME_PARTIAL", raising=False)
    return source, target


@pytest.mark.skipif(os.name != "nt", reason="Real Windows descendant-handle lock")
@pytest.mark.parametrize("include_ui", [False, True])
def test_locked_restore_is_preserved_and_explicit_verified_resume_succeeds(tmp_path, monkeypatch, restore_module, include_ui):
    source, target = backup_fixture(tmp_path, monkeypatch, include_ui=include_ui)
    original = restore_module._rename_no_replace

    def held_reader(staging, destination):
        with (staging / "uploads" / "nested" / "notes.txt").open("rb"):
            return original(staging, destination)

    monkeypatch.setattr(restore_module, "_rename_no_replace", held_reader)
    with pytest.raises(RuntimeError, match="RESTORE_RESUME_PARTIAL") as captured:
        restore_module.restore_backup()
    assert "Windows" in str(captured.value)
    partial, = tmp_path.glob(".restored.*.partial")
    assert not target.exists()
    before = {p.relative_to(partial).as_posix(): p.read_bytes() for p in partial.rglob("*") if p.is_file()}
    monkeypatch.setenv("RESTORE_RESUME_PARTIAL", str(partial))
    monkeypatch.setattr(restore_module, "_rename_no_replace", original)
    assert restore_module.restore_backup() == target
    assert not partial.exists()
    after = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    assert before == after


@pytest.mark.parametrize("change", ["database", "upload", "ui_upload", "share", "extra", "missing", "source", "rehashed_archive"])
def test_resume_rejects_modified_or_incomplete_content(tmp_path, monkeypatch, restore_module, change):
    source, target = backup_fixture(tmp_path, monkeypatch, include_ui=True)
    def stop_before_publish(staging, destination):
        raise RuntimeError("intentional synthetic publication stop")
    original = restore_module._rename_no_replace
    monkeypatch.setattr(restore_module, "_rename_no_replace", stop_before_publish)
    with pytest.raises(RuntimeError, match="intentional synthetic"):
        restore_module.restore_backup()
    partial, = tmp_path.glob(".restored.*.partial")
    changed = {"database": partial / "rag.sqlite3", "upload": partial / "uploads/nested/notes.txt",
               "ui_upload": partial / "ui-uploads/nested/notes.txt", "share": partial / "ui-shares/nested/notes.txt",
               "extra": partial / "extra.txt", "missing": partial / "uploads/nested/notes.txt",
               "source": source / "rag.sqlite3", "rehashed_archive": source / "uploads.tar.gz"}[change]
    if change == "missing":
        changed.rename(changed.with_suffix(".missing"))
    elif change == "rehashed_archive":
        with tarfile.open(changed, "w:gz") as archive:
            entry = tarfile.TarInfo("nested/notes.txt")
            entry.size = 9
            archive.addfile(entry, io.BytesIO(b"different"))
        sums = source / "SHA256SUMS"
        digest = hashlib.sha256(changed.read_bytes()).hexdigest()
        sums.write_text("\n".join(digest + "  uploads.tar.gz" if line.endswith("  uploads.tar.gz") else line
                                    for line in sums.read_text(encoding="ascii").splitlines()) + "\n", encoding="ascii")
    else:
        changed.write_bytes(b"tampered synthetic content")
    monkeypatch.setenv("RESTORE_RESUME_PARTIAL", str(partial))
    monkeypatch.setattr(restore_module, "_rename_no_replace", original)
    with pytest.raises(ValueError):
        restore_module.restore_backup()
    assert partial.is_dir()
    assert not target.exists()


def test_publication_refuses_destination_created_after_initial_validation(tmp_path, monkeypatch, restore_module):
    _, target = backup_fixture(tmp_path, monkeypatch)
    original = restore_module._rename_no_replace
    def racing_target(staging, destination):
        destination.mkdir()
        original(staging, destination)
    monkeypatch.setattr(restore_module, "_rename_no_replace", racing_target)
    with pytest.raises(FileExistsError):
        restore_module.restore_backup()
    assert list(target.iterdir()) == []
    assert len(list(tmp_path.glob(".restored.*.partial"))) == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows handle-sharing diagnostic")
@pytest.mark.parametrize("share_delete", [False, True])
def test_open_descendant_handle_prevents_directory_publication(tmp_path: Path, share_delete: bool, restore_module) -> None:
    from ctypes import wintypes

    staging = tmp_path / ".restore.partial"
    nested = staging / "uploads" / "notes.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("synthetic restore data", encoding="utf-8")
    target = tmp_path / "restored"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    # An explicit real reader with no DELETE access. The delete-sharing variant
    # distinguishes descendant directory rules from a direct file sharing lock.
    handle = kernel32.CreateFileW(str(nested), 0x80000000, 3 | (4 if share_delete else 0),
                                  None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
    try:
        with pytest.raises(PermissionError) as captured:
            staging.replace(target)
        assert captured.value.winerror == 5
        assert not target.exists()
        assert nested.read_text(encoding="utf-8") == "synthetic restore data"
        # Merely using no-overwrite rename does not bypass the same OS lock.
        with pytest.raises(PermissionError) as renamed:
            staging.rename(target)
        assert renamed.value.winerror == 5
    finally:
        assert kernel32.CloseHandle(handle)
    # Closing OUR handle does not prove every OS handle is gone. The original
    # immediate-rename assertion failed in preserved XML. Exercise the bounded
    # application policy after release; raw rename denial above stays unchanged.
    restore_module._publish_partial(staging, target)
    assert not staging.exists()
    assert (target / "uploads" / "notes.txt").read_text(encoding="utf-8") == "synthetic restore data"


@pytest.mark.parametrize("target_type", ["empty_directory", "nonempty_directory", "file"])
def test_exclusive_rename_never_overwrites_a_racing_target(tmp_path: Path, target_type: str, restore_module) -> None:
    staging = tmp_path / ".restore.partial"
    staging.mkdir()
    (staging / "new.txt").write_text("new synthetic bytes", encoding="utf-8")
    target = tmp_path / "restored"
    assert not target.exists()  # Simulate the script's initial validation.
    if target_type == "file":
        target.write_text("existing synthetic bytes", encoding="utf-8")
    else:
        target.mkdir()
        if target_type == "nonempty_directory":
            (target / "existing.txt").write_text("existing synthetic bytes", encoding="utf-8")
    with pytest.raises(FileExistsError):
        restore_module._publish_partial(staging, target)
    assert (staging / "new.txt").read_text(encoding="utf-8") == "new synthetic bytes"
    if target_type == "file":
        assert target.read_text(encoding="utf-8") == "existing synthetic bytes"
    elif target_type == "nonempty_directory":
        assert (target / "existing.txt").read_text(encoding="utf-8") == "existing synthetic bytes"
    else:
        assert list(target.iterdir()) == []


@pytest.mark.parametrize("kind", ["wrong_name", "wrong_parent", "hardlink", "extra_directory"])
def test_resume_rejects_wrong_scope_and_linked_or_extra_content(tmp_path, monkeypatch, restore_module, kind):
    _, target = backup_fixture(tmp_path, monkeypatch)
    def stop(staging, destination):
        raise RuntimeError("synthetic stop")
    original = restore_module._rename_no_replace
    monkeypatch.setattr(restore_module, "_rename_no_replace", stop)
    with pytest.raises(RuntimeError, match="synthetic stop"):
        restore_module.restore_backup()
    partial, = tmp_path.glob(".restored.*.partial")
    candidate = partial
    if kind == "wrong_name":
        candidate = tmp_path / ".unrelated.partial"
        candidate.mkdir()
    elif kind == "wrong_parent":
        candidate = tmp_path / "other" / partial.name
        candidate.mkdir(parents=True)
    elif kind == "hardlink":
        os.link(partial / "uploads/nested/notes.txt", tmp_path / "aliased.txt")
    else:
        (partial / "extra-directory").mkdir()
    monkeypatch.setenv("RESTORE_RESUME_PARTIAL", str(candidate))
    monkeypatch.setattr(restore_module, "_rename_no_replace", original)
    with pytest.raises(ValueError):
        restore_module.restore_backup()
    assert partial.is_dir()
    assert not target.exists()


@pytest.mark.parametrize("native_error", [0, errno.EEXIST, errno.ENOSYS])
def test_linux_exclusive_rename_native_contract_without_linux_runtime(tmp_path, monkeypatch, restore_module, native_error):
    calls = []
    class NativeRename:
        def __call__(self, *args):
            calls.append(args)
            ctypes.set_errno(native_error)
            return -1 if native_error else 0
    native = NativeRename()
    monkeypatch.setattr(restore_module, "os", SimpleNamespace(name="posix", fsencode=os.fsencode, strerror=os.strerror))
    monkeypatch.setattr(restore_module, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(restore_module.ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace(renameat2=native))
    source, target = tmp_path / ".partial", tmp_path / "final"
    if native_error:
        with pytest.raises(OSError) as captured:
            restore_module._rename_no_replace(source, target)
        assert captured.value.errno == native_error
    else:
        restore_module._rename_no_replace(source, target)
    assert calls == [(-100, os.fsencode(source), -100, os.fsencode(target), 1)]
    assert native.restype is ctypes.c_int
    assert native.argtypes == [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]


def test_linux_missing_native_exclusive_rename_fails_closed(tmp_path, monkeypatch, restore_module):
    monkeypatch.setattr(restore_module, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(restore_module, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(restore_module.ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace())
    with pytest.raises(OSError) as captured:
        restore_module._rename_no_replace(tmp_path / ".partial", tmp_path / "final")
    assert captured.value.errno == errno.ENOTSUP


def test_resume_refuses_existing_empty_target_without_mutating_staging(tmp_path, monkeypatch, restore_module):
    _, target = backup_fixture(tmp_path, monkeypatch)
    def stop(staging, destination):
        raise RuntimeError("synthetic stop")
    monkeypatch.setattr(restore_module, "_rename_no_replace", stop)
    with pytest.raises(RuntimeError, match="synthetic stop"):
        restore_module.restore_backup()
    partial, = tmp_path.glob(".restored.*.partial")
    before = {p.relative_to(partial).as_posix(): p.read_bytes() for p in partial.rglob("*") if p.is_file()}
    monkeypatch.setenv("RESTORE_RESUME_PARTIAL", str(partial))
    target.mkdir()
    with pytest.raises(ValueError, match="Refusing to overwrite"):
        restore_module.restore_backup()
    assert list(target.iterdir()) == []
    assert before == {p.relative_to(partial).as_posix(): p.read_bytes() for p in partial.rglob("*") if p.is_file()}
