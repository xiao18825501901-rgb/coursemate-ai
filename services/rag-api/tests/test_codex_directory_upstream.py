"""R16 production-client contracts with HTTP transport replaced, never live Clerk.

The proposed client seam is intentionally explicit: a missing implementation is
a failing requirement, not an import-time collection error or a skipped test.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json

import httpx

from test_current_change_features import UI, auth, client  # noqa: F401


def directory_module():
    name = 'app.cm_update.directory'
    assert importlib.util.find_spec(name) is not None, 'R16 missing production identity-directory HTTP client and synchronization module'
    module = importlib.import_module(name)
    assert hasattr(module, 'ClerkDirectoryClient'), 'R16 requires a client testable with injected HTTP transport'
    assert hasattr(module, 'sync_directory'), 'R16 requires persisted registered-user projection, not first-visit-only users'
    return module


def registered_user(index: int, *, updated_at: int = 2000, **overrides):
    return {
        'id': f'user_clerk_subject_{index:03}', 'username': f'registered-{index:03}',
        'first_name': f'Registered {index:03}', 'last_name': 'Student',
        'image_url': f'https://images.example.invalid/{index}.png',
        'created_at': 1000, 'updated_at': updated_at, 'banned': False,
        'email_addresses': [{'email_address': f'private-{index}@example.invalid'}],
        'phone_numbers': [{'phone_number': '+15550000000'}],
        'private_metadata': {'private_canary': 'DO_NOT_PUBLISH'},
        **overrides,
    }


def fetch_from_fake_http(module, pages):
    seen = []

    def handler(request):
        assert request.url.host == 'clerk.example.invalid'
        assert request.url.path == '/v1/users'
        assert request.headers['authorization'] == 'Bearer synthetic-test-only'
        offset = int(request.url.params.get('offset', '0'))
        limit = int(request.url.params['limit'])
        assert 1 <= limit <= 500
        seen.append(offset)
        if offset == 0:
            return httpx.Response(200, json=pages[0])
        if offset == len(pages[0]):
            return httpx.Response(200, json=pages[1])
        return httpx.Response(200, json=[])

    async def fetch():
        async with httpx.AsyncClient(base_url='https://clerk.example.invalid/v1/',
                                    headers={'Authorization': 'Bearer synthetic-test-only'},
                                    transport=httpx.MockTransport(handler)) as upstream:
            return await module.ClerkDirectoryClient(upstream).fetch_users()

    return asyncio.run(fetch()), seen


def test_registered_directory_http_pagination_deduplicates_newest_record():
    module = directory_module()
    # More than one upstream page, repeated subject, newest page first: the
    # older later duplicate must not restore the old public name.
    first = [registered_user(index) for index in range(100)]
    first[0] = registered_user(0, updated_at=3000, first_name='Newest profile')
    second = [registered_user(0, updated_at=1000, first_name='Stale profile')] + [registered_user(index) for index in range(100, 125)]
    users, seen = fetch_from_fake_http(module, [first, second])
    assert len(users) == 125
    assert len({row['id'] for row in users}) == 125
    assert next(row for row in users if row['id'] == first[0]['id'])['first_name'] == 'Newest profile'
    assert 0 in seen and 100 in seen, 'must request every page, including registered users absent from local UI'


def test_registered_nonvisitors_are_browsable_with_public_only_addresses(client):
    module = directory_module()
    db = client.app.state.ui_extension_app.state.db
    client.get(f'{UI}/me', headers=auth('token-a'))
    registrations = [registered_user(index) for index in range(25)]
    module.sync_directory(db, registrations)
    rows = []
    for offset in (0, 10, 20):
        response = client.get(f'{UI}/people', headers=auth('token-a'), params={'offset': offset, 'limit': 10})
        assert response.status_code == 200, response.text
        payload = response.json()
        rows.extend(payload if isinstance(payload, list) else payload['items'])
    assert len(rows) == 25
    assert len({row['id'] for row in rows}) == 25
    assert {row['handle'] for row in rows} == {u['username'] for u in registrations}
    serialized = json.dumps(rows)
    for private in ('user_clerk_subject_', 'private-', '+15550000000', 'DO_NOT_PUBLISH', 'email_addresses', 'phone_numbers', 'private_metadata'):
        assert private not in serialized, f'directory leaked {private}'


def test_registered_directory_excludes_banned_deleted_hidden_and_blocked(client):
    module = directory_module()
    db = client.app.state.ui_extension_app.state.db
    client.get(f'{UI}/me', headers=auth('token-a'))
    registrations = [registered_user(index) for index in range(5)]
    module.sync_directory(db, registrations)
    # Existing local privacy settings and active blocks survive a later sync.
    db.execute('UPDATE cmui_users SET discoverable=0 WHERE id=?', (registrations[2]['id'],))
    db.execute('INSERT INTO cmui_blocks(owner,blocked) VALUES(?,?)', ('user-a', registrations[3]['id']))
    module.sync_directory(db, [registered_user(0, updated_at=4000, banned=True),
                               registered_user(1, updated_at=4000, deleted=True),
                               registered_user(2, updated_at=4000), registered_user(3, updated_at=4000)])
    response = client.get(f'{UI}/people', headers=auth('token-a'))
    assert response.status_code == 200
    payload = response.json()
    rows = payload if isinstance(payload, list) else payload['items']
    assert [row['handle'] for row in rows] == [registrations[4]['username']]


def test_out_of_order_sync_cannot_resurrect_deleted_registration(client):
    module = directory_module()
    db = client.app.state.ui_extension_app.state.db
    client.get(f'{UI}/me', headers=auth('token-a'))
    module.sync_directory(db, [registered_user(0, updated_at=1000)])
    module.sync_directory(db, [registered_user(0, updated_at=3000, deleted=True)])
    module.sync_directory(db, [registered_user(0, updated_at=1000)])
    response = client.get(f'{UI}/people', headers=auth('token-a'))
    assert response.status_code == 200
    payload = response.json()
    rows = payload if isinstance(payload, list) else payload['items']
    assert rows == [], 'an old duplicate must not resurrect a deleted identity'


def test_complete_snapshot_absence_blocks_later_stale_record(client):
    module = directory_module()
    db = client.app.state.ui_extension_app.state.db
    module.sync_directory(db, [registered_user(0, updated_at=1000)])
    module.sync_directory(db, [], complete=True, snapshot_at_ms=3000)
    assert db.one('SELECT active FROM cmui_directory')['active'] == 0
    module.sync_directory(db, [registered_user(0, updated_at=2000)])
    assert db.one('SELECT active FROM cmui_directory')['active'] == 0, 'snapshot absence needs an update watermark, not only active=0'
    assert db.one('SELECT updated_ms FROM cmui_directory')['updated_ms'] == 3000
    module.sync_directory(db, [registered_user(0, updated_at=4000)])
    assert db.one('SELECT active FROM cmui_directory')['active'] == 1
    module.sync_directory(db, [], complete=True, snapshot_at_ms=3500)
    assert db.one('SELECT active FROM cmui_directory')['active'] == 1, 'older snapshots cannot deactivate newer records'


def test_complete_snapshot_presence_blocks_stale_profile_overwrite(client):
    module = directory_module()
    db = client.app.state.ui_extension_app.state.db
    module.sync_directory(db, [registered_user(0, updated_at=1000, first_name='Snapshot')], complete=True, snapshot_at_ms=3000)
    module.sync_directory(db, [registered_user(0, updated_at=2000, first_name='Stale replay')])
    assert db.one('SELECT name FROM cmui_users')['name'] == 'Snapshot Student'


def test_fresh_profile_updates_preserve_local_privacy_and_qualification(client):
    from app.cm_update.social import set_verified, verification_status
    module = directory_module()
    db = client.app.state.ui_extension_app.state.db
    module.sync_directory(db, [registered_user(0), registered_user(1)])
    owner = registered_user(0)['id']
    db.execute('UPDATE cmui_users SET discoverable=0 WHERE id=?', (owner,))
    db.execute('INSERT INTO cmui_blocks(owner,blocked) VALUES(?,?)', (owner, registered_user(1)['id']))
    set_verified(db, owner, 'admin', 'synthetic explicit qualification')
    original_address = db.one('SELECT public_id FROM cmui_directory WHERE subject=?', (owner,))['public_id']
    module.sync_directory(db, [registered_user(0, updated_at=4000, first_name='Updated', last_name='Profile', username='updated-public-handle')])
    profile = db.one('SELECT * FROM cmui_users WHERE id=?', (owner,))
    assert profile['name'] == 'Updated Profile'
    assert profile['handle'] == 'updated-public-handle'
    assert profile['discoverable'] == 0
    assert db.one('SELECT blocked FROM cmui_blocks WHERE owner=?', (owner,))['blocked'] == registered_user(1)['id']
    assert verification_status(db, owner)['method'] == 'admin'
    assert db.one('SELECT public_id FROM cmui_directory WHERE subject=?', (owner,))['public_id'] == original_address
