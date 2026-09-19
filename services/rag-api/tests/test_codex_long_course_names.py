"""Real integrated API + isolated SQLite/uploads; no paid or external providers."""
from concurrent.futures import ThreadPoolExecutor
import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.errors import ApiError
from app.ui_extension.domain import V3DomainAdapter
from test_current_change_features import (
    UI, auth, make_settings, FakeAuthVerifier, FakeEmbeddingProvider,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CMUI_PROVIDER_MODE", "test")
    monkeypatch.setenv("CMUI_AUTO_VERIFY_NEW_USERS", "false")
    app = create_app(settings=make_settings(tmp_path),
                     embedding_provider=FakeEmbeddingProvider(),
                     auth_verifier=FakeAuthVerifier())
    with TestClient(app, raise_server_exceptions=False) as value:
        yield value


def create(client, name, token="token-a"):
    return client.post(f"{UI}/courses", headers=auth(token), json={"name": name})


def counts(client):
    with client.app.state.database.connect() as db:
        courses = db.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
    pins = client.app.state.ui_extension_app.state.db.one(
        "SELECT COUNT(*) AS n FROM cmui_pins")["n"]
    return courses, pins


@pytest.mark.parametrize("name", [
    "x", "CS3481", "GE2324", "Python 3", "A" * 99, "B" * 100,
    "课" * 99, "学" * 100, "CS3481 数据🙂é" * 9 + "X",
])
def test_direct_legal_name_preserved_and_private(client, name):
    response = create(client, name)
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["name"] == name
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]{1,49}", row["id"])
    detail = client.get(f"{UI}/courses/{row['id']}", headers=auth("token-a"))
    assert detail.status_code == 200
    assert detail.json()["name"] == name
    listed = client.get(f"{UI}/courses", headers=auth("token-a")).json()
    assert any(c["id"] == row["id"] and c["name"] == name and c["pinned"] for c in listed)
    assert client.get(f"{UI}/courses/{row['id']}", headers=auth("token-b")).status_code == 404


@pytest.mark.parametrize("name", ["", "   ", "A" * 101, "课" * 101, None, 123])
def test_invalid_name_is_422_without_course_or_pin(client, name):
    before = counts(client)
    response = create(client, name)
    assert response.status_code == 422, response.text
    assert counts(client) == before


def test_same_names_and_prefixes_concurrent_and_two_users(client):
    names = ["A" * 100, "A" * 100, "A" * 99 + "B", "A" * 100]
    tokens = ["token-a", "token-a", "token-a", "token-b"]
    # Pre-register synthetic identities before the concurrent course requests.
    for token in set(tokens):
        assert client.get(f"{UI}/me", headers=auth(token)).status_code == 200
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda args: create(client, *args), zip(names, tokens)))
    assert [r.status_code for r in responses] == [201] * 4
    rows = [r.json() for r in responses]
    assert len({r["id"] for r in rows}) == 4
    assert [r["name"] for r in rows] == names
    for row, token in zip(rows, tokens):
        other = "token-b" if token == "token-a" else "token-a"
        assert client.get(f"{UI}/courses/{row['id']}", headers=auth(other)).status_code == 404


def test_collision_retries_preserve_existing_and_exhaust_without_partial_data(client, monkeypatch):
    existing = create(client, "Existing")
    assert existing.status_code == 201
    old_id = existing.json()["id"]
    generated = iter([old_id, "course-unique-after-collision"])
    monkeypatch.setattr(V3DomainAdapter, "_new_course_id", staticmethod(lambda: next(generated)))
    response = create(client, "课" * 100)
    assert response.status_code == 201, response.text
    assert response.json()["id"] == "course-unique-after-collision"
    calls = []
    def collide():
        calls.append(old_id)
        return old_id
    monkeypatch.setattr(V3DomainAdapter, "_new_course_id", staticmethod(collide))
    before = counts(client)
    failure = create(client, "B" * 100, "token-b")
    assert failure.status_code == 409, failure.text
    assert len(calls) == 3
    assert counts(client) == before
    assert client.get(f"{UI}/courses/{old_id}", headers=auth("token-a")).json()["name"] == "Existing"
    assert client.get(f"{UI}/courses/{old_id}", headers=auth("token-b")).status_code == 404


def test_non_collision_failure_is_not_retried_or_pinned(client, monkeypatch):
    calls = []
    def reject(*args, **kwargs):
        calls.append(1)
        raise ApiError(429, "COURSE_QUOTA_EXCEEDED", "Synthetic quota boundary")
    monkeypatch.setattr(client.app.state.ingestion_service, "create_course", reject)
    before = counts(client)
    response = create(client, "课" * 100)
    assert response.status_code == 429, response.text
    assert len(calls) == 1
    assert counts(client) == before


def test_long_name_file_and_frozen_share_join_replay(client):
    name = "课程CS3481" * 12 + "数据分析"
    assert len(name) == 100
    for token in ("token-a", "token-b"):
        assert client.get(f"{UI}/me", headers=auth(token)).status_code == 200
    response = create(client, name)
    assert response.status_code == 201, response.text
    source = response.json()["id"]
    uploaded = client.post(f"{UI}/courses/{source}/files", headers=auth("token-a"),
        files={"file": ("lesson.txt", b"LONG_NAME_UNIQUE frozen lesson evidence", "text/plain")})
    assert uploaded.status_code == 201, uploaded.text
    original_file = uploaded.json()["id"]
    sent = client.post(f"{UI}/shares", headers=auth("token-a"), json={
        "course": source, "recipients": ["user-b"], "history_scope": "none", "request_id": "long-name-share"})
    assert sent.status_code == 201, sent.text
    url = f"{UI}/shares/{sent.json()['id']}/join"
    first = client.post(url, headers=auth("token-b"))
    assert first.status_code == 200, first.text
    target = first.json()["joined_course_id"]
    assert target != source and re.fullmatch(r"[a-z0-9][a-z0-9-]{1,49}", target)
    before = counts(client)
    assert client.post(url, headers=auth("token-b")).json()["joined_course_id"] == target
    assert counts(client) == before
    assert client.get(f"{UI}/courses/{target}", headers=auth("token-b")).json()["name"] == name
    copied = client.get(f"{UI}/courses/{target}/files", headers=auth("token-b")).json()
    assert len(copied) == 1 and copied[0]["id"] != original_file
    original = client.get(f"{UI}/courses/{source}/files", headers=auth("token-a")).json()
    assert len(original) == 1 and original[0]["id"] == original_file
    for course, file_id, token in ((source, original_file, "token-a"), (target, copied[0]["id"], "token-b")):
        for suffix in ("", "?download=true"):
            response = client.get(f"{UI}/courses/{course}/files/{file_id}/content{suffix}", headers=auth(token))
            assert response.status_code == 200
            assert response.content == b"LONG_NAME_UNIQUE frozen lesson evidence"
    assert client.get(f"{UI}/courses/{source}", headers=auth("token-b")).status_code == 404
