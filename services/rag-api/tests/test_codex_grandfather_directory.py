"""Protected full-registration cutoff grants; all HTTP and identities synthetic."""
import asyncio
import json

import httpx
import pytest

from app.cm_update import directory
from app.cm_update.auth import ensure_user
from app.cm_update.db import Database
from app.cm_update.social import set_verified, verification_status


def record(subject, created=1000, **extra):
    return {'id': subject, 'created_at': created, 'updated_at': 3000, **extra}


def test_snapshot_candidates_exclude_new_unknown_and_disabled_identities():
    helper = getattr(directory, 'grandfather_candidates', None)
    assert helper is not None, 'protected full registered snapshot candidate helper missing'
    result = helper([record('old'), record('at-cutoff', 2000), record('new', 2001),
                     record('unknown', None), {'id': 'missing', 'updated_at': 3000},
                     record('banned', banned=True), record('deleted', deleted=True)], cutoff_ms=2000, complete=True)
    assert result['candidates'] == ['at-cutoff', 'old']
    assert result['evidence']['unknown_created_at'] == 2
    assert result['evidence']['snapshot_sha256']
    with pytest.raises(ValueError, match='complete'):
        helper([record('old')], cutoff_ms=2000, complete=False)


def test_snapshot_grants_never_visited_old_users_preserves_existing_and_is_one_time(tmp_path):
    helper = getattr(directory, 'apply_grandfather_snapshot', None)
    assert helper is not None, 'protected snapshot application missing'
    db = Database(tmp_path / 'ui.sqlite3'); db.initialize()
    ensure_user(db, 'qualified'); set_verified(db, 'qualified', 'code', 'existing qualification')
    db.execute("INSERT INTO cmui_meta VALUES('verification_grandfather_boundary',?)", (json.dumps({'legacy': True}),))
    helper(db, [record('old-never-visited'), record('qualified'), record('new', 3000)], cutoff_ms=2000, complete=True)
    assert verification_status(db, 'old-never-visited')['method'] == 'grandfathered'
    assert verification_status(db, 'qualified')['method'] == 'code'
    assert verification_status(db, 'new')['verified'] is False
    assert json.loads(db.one("SELECT value FROM cmui_meta WHERE key='verification_grandfather_boundary'")['value']) == {'legacy': True}
    helper(db, [record('late-added-old-id')], cutoff_ms=2000, complete=True)
    assert verification_status(db, 'late-added-old-id')['verified'] is False
    receipt = json.loads(db.one("SELECT value FROM cmui_meta WHERE key='verification_grandfather_registered_snapshot'")['value'])
    assert receipt['status'] == 'COMPLETED'
    with pytest.raises(ValueError, match='cutoff'):
        helper(db, [], cutoff_ms=4000, complete=True)


def test_failed_http_snapshot_is_retryable_without_partial_grants(tmp_path):
    helper = getattr(directory, 'approved_grandfather', None)
    assert helper is not None, 'approved registered snapshot client path missing'
    db = Database(tmp_path / 'ui.sqlite3'); db.initialize()

    async def attempt(fail):
        def handle(request):
            offset = int(request.url.params.get('offset', 0))
            if fail and offset:
                return httpx.Response(503, json={'error': 'synthetic unavailable'})
            users = [record(f'old-{i}') for i in range(100)] if fail else [record('old-final')]
            return httpx.Response(200, json=users)
        async with httpx.AsyncClient(base_url='https://clerk.example.invalid/v1/', transport=httpx.MockTransport(handle)) as http:
            return await helper(db, 'synthetic-secret', cutoff_ms=2000, http_client=http)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(attempt(True))
    assert db.all('SELECT * FROM cmui_verification') == []
    receipt = json.loads(db.one("SELECT value FROM cmui_meta WHERE key='verification_grandfather_registered_snapshot'")['value'])
    assert receipt['status'] == 'FAILED_RETRYABLE'
    asyncio.run(attempt(False))
    assert verification_status(db, 'old-final')['method'] == 'grandfathered'


def test_incomplete_snapshot_never_grants_and_cutoff_is_pinned(tmp_path):
    db = Database(tmp_path / 'ui.sqlite3'); db.initialize()
    with pytest.raises(ValueError, match='complete'):
        directory.apply_grandfather_snapshot(db, [record('old')], cutoff_ms=2000, complete=False)
    assert db.all('SELECT * FROM cmui_verification') == []
    receipt = json.loads(db.one("SELECT value FROM cmui_meta WHERE key='verification_grandfather_registered_snapshot'")['value'])
    assert receipt['status'] == 'FAILED_RETRYABLE'
    with pytest.raises(ValueError, match='cutoff'):
        directory.apply_grandfather_snapshot(db, [record('new', 3000)], cutoff_ms=4000, complete=True)
    directory.apply_grandfather_snapshot(db, [record('old')], cutoff_ms=2000, complete=True)
    assert verification_status(db, 'old')['verified'] is True
