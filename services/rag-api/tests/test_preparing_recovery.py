"""Abrupt exit of our own synthetic HTTP worker, not a production process."""
import json
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest


@pytest.mark.parametrize('phase', ['freeze', 'partial', 'complete', 'committed'])
def test_process_exit_recovery_uses_only_frozen_archive(tmp_path, phase):
    from app.cm_update.share_recovery import recover
    from app.cm_update.db import Database
    root = tmp_path / phase
    root.mkdir()
    result = subprocess.run([sys.executable, __file__, str(root), phase], capture_output=True, text=True,
                            env={**os.environ, 'CMUI_PROVIDER_MODE': 'test', 'CMUI_ALLOW_BILLABLE': 'false',
                                 'CMUI_ENV': 'test', 'CMUI_DATA_DIR': '', 'CMUI_AUTO_VERIFY_NEW_USERS': 'false'}, timeout=45)
    assert result.returncode == 73, result.stdout + result.stderr
    database = next(root.rglob('ui.sqlite3'))
    db = Database(database)
    share = db.one('SELECT * FROM cmui_shares WHERE request_id=?', ('abrupt-send',))
    assert share is not None
    # Sender's later live content must never enter controlled recovery.
    for path in (root / 'uploads').rglob('*'):
        if path.is_file(): path.write_bytes(b'LATER_SOURCE_MUST_NOT_BE_READ')
    preview = recover(database, share['id'], apply=False)
    assert preview['action'] == ('ready' if phase in ('complete', 'committed') else 'failed')
    before = db.one('SELECT status FROM cmui_shares WHERE id=?', (share['id'],))
    assert before['status'] == ('ready' if phase == 'committed' else 'preparing')
    outcome = recover(database, share['id'], apply=True)
    assert outcome['action'] == preview['action']
    recover(database, share['id'], apply=True)
    expected = 1 if phase in ('complete', 'committed') else 0
    assert len(db.all('SELECT * FROM cmui_notifications WHERE ref=?', (share['id'],))) == expected
    assert len(db.all('SELECT * FROM cmui_share_recipients WHERE share=?', (share['id'],))) == expected
    assert not db.all('SELECT * FROM cmui_share_imports')  # Recovery never creates a course.


def test_recovery_refuses_active_sender(tmp_path):
    from app.cm_update.share_recovery import send_lock, RecoveryBusy
    with send_lock(tmp_path):
        with pytest.raises(RecoveryBusy):
            with send_lock(tmp_path):
                pytest.fail('A second worker acquired the active send lock')


def test_repeated_cancellation_does_not_release_send_lock_early(tmp_path):
    from app.cm_update.share_recovery import send_lock, RecoveryBusy, settle
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        async def copy():
            started.set()
            await release.wait()
        async def send():
            with send_lock(tmp_path):
                await settle(asyncio.create_task(copy()))
        task = asyncio.create_task(send())
        await started.wait()
        for _ in range(2):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done()
        with pytest.raises(RecoveryBusy):
            with send_lock(tmp_path): pytest.fail('lock released during copy')
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        with send_lock(tmp_path): pass
    asyncio.run(scenario())


@pytest.mark.parametrize('shutdown_all_owned_tasks', [False, True])
def test_cancelled_copy_drains_real_owned_thread_before_unlock(tmp_path, shutdown_all_owned_tasks):
    from app.cm_update.share_recovery import file_io, send_lock, RecoveryBusy
    started, release = threading.Event(), threading.Event()
    def write():
        started.set()
        assert release.wait(10), 'Test must explicitly release its own thread'
        (tmp_path / 'finished').write_bytes(b'complete')
    async def scenario():
        baseline = asyncio.all_tasks()
        async def sender():
            with send_lock(tmp_path):
                await file_io(write)
        task = asyncio.create_task(sender())
        try:
            assert await asyncio.to_thread(started.wait, 5)
            for _ in range(2):
                for owned in (asyncio.all_tasks() - baseline if shutdown_all_owned_tasks else {task}):
                    owned.cancel()
                await asyncio.sleep(0)
            # Let cancellation propagate through shields/wrappers, not just the
            # first scheduled callback; the actual writer remains held by us.
            for _ in range(8): await asyncio.sleep(0)
            assert not task.done()
            with pytest.raises(RecoveryBusy):
                with send_lock(tmp_path): pytest.fail('writer still active')
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError): await task
        assert (tmp_path / 'finished').read_bytes() == b'complete'
    asyncio.run(scenario())


def test_complete_archive_tampering_cannot_publish(tmp_path):
    from app.cm_update.share_recovery import recover
    from app.cm_update.db import Database
    result = subprocess.run([sys.executable, __file__, str(tmp_path), 'complete'], capture_output=True, text=True,
        env={**os.environ, 'CMUI_PROVIDER_MODE': 'test', 'CMUI_ALLOW_BILLABLE': 'false',
             'CMUI_ENV': 'test', 'CMUI_DATA_DIR': '', 'CMUI_AUTO_VERIFY_NEW_USERS': 'false'}, timeout=45)
    assert result.returncode == 73, result.stderr
    database = next(tmp_path.rglob('ui.sqlite3'))
    db = Database(database)
    share = db.one('SELECT * FROM cmui_shares WHERE request_id=?', ('abrupt-send',))
    index = next((database.parent / 'shares').rglob('*.index.json'))
    index.write_bytes(b'changed index')
    assert recover(database, share['id'], apply=True)['action'] == 'failed'
    assert not db.all('SELECT * FROM cmui_notifications WHERE ref=?', (share['id'],))


def worker(root, phase):
    (root / 'owned-worker.json').write_text(json.dumps({'pid': os.getpid(), 'parent_pid': os.getppid(),
        'phase': phase, 'root': str(root), 'exit_code': 73}), encoding='utf-8')
    sys.path.insert(0, str(Path(__file__).parents[1]))
    sys.path.insert(0, str(Path(__file__).parent))
    from fastapi.testclient import TestClient
    from test_current_change_features import make_settings, FakeEmbeddingProvider, FakeAuthVerifier, auth, UI
    from app.main import create_app
    from app.cm_update import share_recovery
    from app.ui_extension.domain import V3DomainAdapter
    application = create_app(settings=make_settings(root), embedding_provider=FakeEmbeddingProvider(), auth_verifier=FakeAuthVerifier())
    original_export = V3DomainAdapter._snapshot_export
    count = 0
    def export(self, subject, payload):
        nonlocal count
        count += 1
        if (phase == 'freeze' and count == 1) or (phase == 'partial' and count == 2):
            os._exit(73)
        return original_export(self, subject, payload)
    V3DomainAdapter._snapshot_export = export
    original_publish = share_recovery.publish
    def publish(*args, **kwargs):
        if phase == 'complete': os._exit(73)
        result = original_publish(*args, **kwargs)
        if phase == 'committed': os._exit(73)
        return result
    share_recovery.publish = publish
    with TestClient(application) as client:
        for token in ('token-a', 'token-b'):
            assert client.get(f'{UI}/me', headers=auth(token)).status_code == 200
        course = client.post(f'{UI}/courses', headers=auth('token-a'), json={'name': 'Abrupt synthetic'}).json()['id']
        for index in range(2):
            response = client.post(f'{UI}/courses/{course}/files', headers=auth('token-a'),
                                   files={'file': (f'{index}.txt', f'frozen synthetic {index}'.encode(), 'text/plain')})
            assert response.status_code == 201, response.text
        client.post(f'{UI}/shares', headers=auth('token-a'), json={'course': course, 'recipients': ['user-b'],
                    'history_scope': 'none', 'request_id': 'abrupt-send'})
    raise AssertionError('Fault boundary was not reached')


if __name__ == '__main__':
    worker(Path(sys.argv[1]), sys.argv[2])
