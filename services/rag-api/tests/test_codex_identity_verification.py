"""Independent R16/R18 regressions. Synthetic isolated databases; no cloud calls."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_current_change_features import UI, auth, client  # noqa: F401


def test_issued_and_redeemed_code_never_persists_plaintext(client: TestClient) -> None:
    issued = client.post(f"{UI}/admin/verification-codes", headers=auth("admin-token"), json={"count": 1})
    assert issued.status_code == 201, issued.text
    secret = issued.json()["codes"][0]
    redeemed = client.post(f"{UI}/me/verification/redeem", headers=auth("token-a"),
                          json={"code": secret, "request_id": "audit-secret-code-01"})
    assert redeemed.status_code == 200, redeemed.text
    db = client.app.state.ui_extension_app.state.db
    # Inspect logical records, including audit/attempt notes, rather than relying
    # on one column name or a claimed HMAC implementation.
    for table in ("cmui_verification_codes", "cmui_redemption_attempts", "cmui_verification"):
        records = db.all(f"SELECT * FROM {table}")
        assert secret not in json.dumps(records), f"raw verification code persisted in {table}"


def test_admin_disables_code_by_opaque_id_and_redemption_is_rejected(client: TestClient) -> None:
    issued = client.post(f"{UI}/admin/verification-codes", headers=auth("admin-token"), json={"count": 1})
    assert issued.status_code == 201
    secret = issued.json()["codes"][0]
    listing = client.get(f"{UI}/admin/verification-codes", headers=auth("admin-token"))
    assert listing.status_code == 200
    item = listing.json()[0]
    assert item.get("code_id"), "admin list needs a non-secret stable management identifier"
    assert item["code_id"] != secret
    disabled = client.post(f"{UI}/admin/verification-codes/disable", headers=auth("admin-token"),
                           json={"code_id": item["code_id"]})
    assert disabled.status_code == 200, disabled.text
    listing = client.get(f"{UI}/admin/verification-codes", headers=auth("admin-token")).json()
    assert next(row for row in listing if row["code_id"] == item["code_id"])["status"] == "disabled"
    redeemed = client.post(f"{UI}/me/verification/redeem", headers=auth("token-a"),
                          json={"code": secret, "request_id": "audit-disabled-code-01"})
    assert redeemed.status_code == 400, redeemed.text


@pytest.mark.parametrize("query", ["", "Z", "Zed"])
def test_people_browsing_and_short_search_page_beyond_twenty(client: TestClient, query: str) -> None:
    client.get(f"{UI}/me", headers=auth("token-a"))
    db = client.app.state.ui_extension_app.state.db
    with db.connect(True) as conn:
        for index in range(25):
            conn.execute("INSERT INTO cmui_users(id,name,handle,created_at) VALUES(?,?,?,?)",
                         (f"directory-subject-{index:02}", f"Zed {index:02}", f"zed-{index:02}", "2026-01-01T00:00:00Z"))
    found = []
    for offset in (0, 10, 20):
        response = client.get(f"{UI}/people", headers=auth("token-a"),
                              params={"q": query, "limit": 10, "offset": offset})
        assert response.status_code == 200, response.text
        payload = response.json()
        rows = payload if isinstance(payload, list) else payload["items"]
        assert len(rows) <= 10, "page size must be enforced"
        found.extend(rows)
    assert len(found) == 25, "empty and one-character searches must include all directory pages"
    assert len({row["id"] for row in found}) == 25, "pages must not repeat the first page"
    assert {row["handle"] for row in found} == {f"zed-{index:02}" for index in range(25)}
    assert all(not any(key in row for key in ("email", "phone", "secret_hash")) for row in found)


def test_failed_grandfather_snapshot_can_recover_without_losing_old_user(tmp_path: Path) -> None:
    from app.cm_update.app import create_app
    from app.cm_update.auth import ensure_user
    from app.cm_update.config import Settings
    from app.cm_update.social import verification_status

    class SnapshotDomain:
        unavailable = True

        async def call(self, operation, subject, payload, request_id):
            assert operation == "verification.grandfather_candidates"
            if self.unavailable:
                raise RuntimeError("synthetic identity snapshot unavailable")
            return ["registered-before-cutoff"]

    async def subject_resolver(request):
        return "local-user"

    domain = SnapshotDomain()
    cfg = Settings(data_dir=tmp_path / "ui", environment="test", auth_mode="injected",
                   integration_mode="integrated", provider_mode="test", allow_billable=False,
                   auto_verify_new_users=False, web_dir=tmp_path / "no-web")
    first = create_app(cfg, domain=domain, subject_resolver=subject_resolver)
    with TestClient(first):
        pass
    # Retry after upstream recovery with the same DB. The protected upstream
    # ID need not already have opened the UI shell.
    domain.unavailable = False
    recovered = create_app(cfg, domain=domain, subject_resolver=subject_resolver)
    with TestClient(recovered):
        ensure_user(recovered.state.db, "registered-before-cutoff")
        old = verification_status(recovered.state.db, "registered-before-cutoff")
        assert old["verified"] is True, "failed snapshot must not permanently complete an empty boundary"
        assert old["method"] == "grandfathered"
        ensure_user(recovered.state.db, "registered-after-cutoff")
        assert verification_status(recovered.state.db, "registered-after-cutoff")["verified"] is False


def test_schema6_verification_upgrade_retains_tombstones_and_scrubs_secrets(tmp_path: Path) -> None:
    import sqlite3
    from app.cm_update.db import Database, SCHEMA, SCHEMA_VERSION
    from app.cm_update.config import Settings
    from app.cm_update import social

    db = Database(tmp_path / 'migration.sqlite3')
    cfg = Settings(environment='test', verification_secret='synthetic-migration-hmac-secret')
    with sqlite3.connect(db.path) as c:
        c.executescript(SCHEMA)
        c.execute("INSERT INTO cmui_meta VALUES('schema_version','6')")
        c.execute("INSERT INTO cmui_users(id,name,handle,created_at) VALUES('old','Old','old','2026-01-01')")
        for code, status, owner in [('0123456', 'issued', None), ('1234567', 'redeemed', 'old'), ('2345678', 'disabled', None)]:
            c.execute("INSERT INTO cmui_verification_codes(code,secret_hash,status,owner,issued_by,issued_at) VALUES(?,?,?,?,?,?)",
                      (code, social.code_secret_hash(cfg, code), status, owner, 'admin', '2026-01-01'))
        c.execute("INSERT INTO cmui_redemption_attempts VALUES('attempt','1234567','old',1,'2026-01-01')")
        c.execute("INSERT INTO cmui_verification VALUES('old',1,'code','2026-01-01','redeemed 1234567','2026-01-01')")
    with pytest.raises(ValueError, match='Configured verification secret'):
        db.initialize()
    assert db.one("SELECT value FROM cmui_meta WHERE key='schema_version'")['value'] == '6'
    db.initialize(verification_secret=cfg.verification_secret)
    db.initialize(verification_secret=cfg.verification_secret)
    assert db.one("SELECT value FROM cmui_meta WHERE key='schema_version'")['value'] == str(SCHEMA_VERSION)
    records = db.all('SELECT * FROM cmui_verification_codes')
    assert len(records) == 3
    assert next(r for r in records if r['status'] == 'redeemed')['owner'] == 'old'
    persisted = json.dumps(records + db.all('SELECT * FROM cmui_redemption_attempts') + db.all('SELECT * FROM cmui_verification'))
    assert all(code not in persisted for code in ('0123456','1234567','2345678'))
    assert social.redeem_code(db, cfg, 'old', '1234567', 'replay')['ok'] is True
    assert social.redeem_code(db, cfg, 'old', '2345678', 'disabled')['ok'] is False
    assert social.redeem_code(db, cfg, 'old', '0123456', 'leading-zero')['ok'] is True


def test_code_helpers_use_hmac_and_disable_opaque_id(tmp_path: Path) -> None:
    from app.cm_update.db import Database
    from app.cm_update.config import Settings
    from app.cm_update.auth import ensure_user
    from app.cm_update import social

    db = Database(tmp_path / 'helpers.sqlite3')
    db.initialize()
    cfg = Settings(environment='test', verification_secret='synthetic-helper-secret')
    ensure_user(db, 'student')
    secret = social.generate_codes(db, cfg, 1, 'admin')[0]
    listed = social.list_codes(db)
    assert set(listed[0]) == {'code_id', 'status', 'issued_at', 'redeemed_at'}
    assert social.disable_code(db, listed[0]['code_id'], 'admin') is True
    assert social.disable_code(db, listed[0]['code_id'], 'admin') is True
    assert social.disable_code(db, 'missing-code', 'admin') is False
    assert social.redeem_code(db, cfg, 'student', secret, 'disabled')['ok'] is False
    issued = social.generate_codes(db, cfg, 1, 'admin')[0]
    wrong = Settings(environment='test', verification_secret='wrong-synthetic-key')
    assert social.redeem_code(db, wrong, 'student', issued, 'wrong-key')['ok'] is False
    assert social.redeem_code(db, cfg, 'student', issued, 'right-key')['ok'] is True


def test_concurrent_redemption_has_single_owner_and_preserves_replay(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from app.cm_update.db import Database
    from app.cm_update.config import Settings
    from app.cm_update.auth import ensure_user
    from app.cm_update import social

    db = Database(tmp_path / 'concurrent.sqlite3')
    db.initialize()
    cfg = Settings(environment='test', verification_secret='synthetic-concurrent-secret')
    for owner in ('one', 'two'):
        ensure_user(db, owner)
    code = social.generate_codes(db, cfg, 1, 'admin')[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda owner: (owner, social.redeem_code(db, cfg, owner, code, owner)), ('one', 'two')))
    winners = [owner for owner, result in results if result['ok']]
    assert len(winners) == 1
    assert social.redeem_code(db, cfg, winners[0], code, 'replay')['ok'] is True
    assert db.one('SELECT owner FROM cmui_verification_codes')['owner'] == winners[0]


def test_grandfather_snapshot_atomic_and_one_time(tmp_path: Path) -> None:
    from app.cm_update.db import Database
    from app.cm_update.auth import ensure_user
    from app.cm_update import social

    db = Database(tmp_path / 'boundary.sqlite3')
    db.initialize()
    with pytest.raises(ValueError):
        social.grandfather_existing_users(db, ['', 'old'])
    assert db.one("SELECT value FROM cmui_meta WHERE key='verification_grandfather_boundary'") is None
    assert db.one("SELECT id FROM cmui_users WHERE id='old'") is None
    social.grandfather_existing_users(db, ['old'])
    assert social.verification_status(db, 'old')['method'] == 'grandfathered'
    ensure_user(db, 'new')
    social.grandfather_existing_users(db, ['old', 'new'])
    assert social.verification_status(db, 'new')['verified'] is False


def test_public_directory_id_can_block_and_unblock_messages(client):
    client.get(f'{UI}/me', headers=auth('token-a'))
    client.get(f'{UI}/me', headers=auth('token-b'))
    people=client.get(f'{UI}/people', headers=auth('token-a')).json()
    person=people[0]['id']
    assert person.startswith('person_')
    assert client.put(f'{UI}/people/{person}/block',headers=auth('token-a')).status_code==200
    assert client.post(f'{UI}/messages',headers=auth('token-a'),json={
        'recipient':person,'text':'blocked synthetic message','request_id':'blocked-directory'}).status_code==403
    assert client.delete(f'{UI}/people/{person}/block',headers=auth('token-a')).status_code==200
    assert client.post(f'{UI}/messages',headers=auth('token-a'),json={
        'recipient':person,'text':'synthetic message','request_id':'unblocked-directory'}).status_code==201


def test_inbox_notification_pagination_reaches_after_one_hundred(client):
    client.get(f'{UI}/me',headers=auth('token-a'))
    client.get(f'{UI}/me',headers=auth('token-b'))
    db=client.app.state.ui_extension_app.state.db
    with db.connect(True) as c:
        for i in range(101):
            c.execute('INSERT INTO cmui_notifications(id,owner,actor,kind,ref,text,created_at) VALUES(?,?,?,?,?,?,?)',
                (f'notice-page-{i:03}','user-a','user-b','synthetic',f'synthetic-{i}',f'Notice {i}','2026-01-01T00:00:00Z'))
    first=client.get(f'{UI}/notifications?limit=100&offset=0',headers=auth('token-a')).json()
    last=client.get(f'{UI}/notifications?limit=100&offset=100',headers=auth('token-a')).json()
    assert len(last)==1 and not {r['id'] for r in first}.intersection(r['id'] for r in last)
