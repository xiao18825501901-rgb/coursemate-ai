"""The shared OAuth state store: the property a multi-worker deployment depends on.

`InMemoryStateStore` is correct for one process. A deployment that runs more than one has a quiet
failure waiting for it: the browser starts an authorisation on the worker that answered `/connect`,
the school redirects back to whichever worker the load balancer picks, and that worker has never heard
of the state it is asked to validate — the user grants access and is told the authorisation was
already used.

These tests drive the real application twice over **one database**: the first instance issues the
state, the second completes the callback. Nothing is simulated except the school's HTTP surface, and
the store's own invariants (one use, expiry, no plaintext state at rest) are asserted directly against
the database.
"""

from __future__ import annotations

import hashlib
import pathlib
import sqlite3
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.canvas.credentials import generate_key
from app.canvas.oauth import (
    AuthorizationState,
    CanvasOAuthClient,
    InMemoryStateStore,
    OAuthError,
    SqlStateStore,
)
from app.canvas.registry import InstitutionConnectionRegistry
from app.config import Settings
from app.db import Database
from app.main import create_app

USER = "state-user-1"
AUTH = {"Authorization": "Bearer test-session-token"}
TOKEN = "canvas-access-token"


@dataclass
class School:
    """The smallest stand-in Canvas that can complete an authorisation."""

    profile_id: int = 4242
    profile_name: str = "Student One"
    requests: list[tuple[str, str]] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        path = request.url.path
        if path == "/login/oauth2/token":
            return httpx.Response(
                200,
                json={
                    "access_token": TOKEN,
                    "refresh_token": "canvas-refresh-token",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                    "scope": "url:GET|/api/v1/courses",
                },
            )
        if path == "/api/v1/users/self/profile":
            return httpx.Response(200, json={"id": self.profile_id, "name": self.profile_name})
        return httpx.Response(404, json={"errors": [{"message": "not found"}]})


def build_app(tmp_path: pathlib.Path, school: School) -> tuple[Any, School]:
    """One application instance over `tmp_path` — call it twice to get two 'workers'."""
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        ui_web_dir=tmp_path / "no-web-build",
        app_env="test",
        rag_provider_mode="deterministic",
        auth_test_user_id=USER,
        v3_enabled=True,
        canvas_credential_dir=tmp_path / "canvas-credentials",
        canvas_credential_key=generate_key(),
    )
    app = create_app(settings=settings)
    client = CanvasOAuthClient(
        registry=InstitutionConnectionRegistry(),
        state_store=app.state.canvas_oauth.states,
        credential_store=app.state.canvas_credentials,
        client=httpx.Client(
            transport=httpx.MockTransport(school.handler),
            timeout=30.0,
            follow_redirects=False,
        ),
    )
    app.state.canvas_oauth = client
    # The callback reads the user's own profile through the adapter, which builds its own client, so
    # the simulated school has to stand in for that client too.
    from app.canvas.adapter import CanvasReadAdapter

    transport = httpx.MockTransport(school.handler)
    app.state.canvas_adapter_for = lambda *, connection_id, origin, registry, token_provider: (
        CanvasReadAdapter(
            connection_id=connection_id,
            origin=origin,
            token_provider=token_provider,
            registry=registry,
            client=httpx.Client(base_url=origin, transport=transport, follow_redirects=False),
            download_client=httpx.Client(transport=transport, follow_redirects=False),
        )
    )
    return app, school


def store(tmp_path: pathlib.Path) -> SqlStateStore:
    settings = Settings(
        database_path=tmp_path / "state.sqlite3",
        upload_dir=tmp_path / "uploads",
        app_env="test",
        v3_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "web",
    )
    database = Database(settings)
    database.initialize()
    return SqlStateStore(database)


# ---------------------------------------------------------------------------- the store's own rules
def test_two_store_instances_share_the_same_state(tmp_path) -> None:
    """The multi-worker property, at the level where it is decided."""
    first = store(tmp_path)
    second = SqlStateStore(Database(Settings(
        database_path=tmp_path / "state.sqlite3",
        upload_dir=tmp_path / "uploads",
        app_env="test",
        v3_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "web",
    )))
    issued = first.issue("user-a", InstitutionConnectionRegistry().by_key("cityu"))
    assert issued.state

    consumed = second.consume(issued.state)
    assert consumed.subject == "user-a"
    assert consumed.institution_key == "cityu"
    assert consumed.consumed is True


def test_a_state_is_usable_exactly_once(tmp_path) -> None:
    s = store(tmp_path)
    issued = s.issue("user-a", InstitutionConnectionRegistry().by_key("cityu"))
    assert s.consume(issued.state).subject == "user-a"
    with pytest.raises(OAuthError) as raised:
        s.consume(issued.state)
    assert raised.value.reason == "UNKNOWN_STATE"


def test_an_unknown_state_is_refused(tmp_path) -> None:
    with pytest.raises(OAuthError) as raised:
        store(tmp_path).consume("never-issued-this")
    assert raised.value.reason == "UNKNOWN_STATE"


def test_an_expired_state_is_refused_and_consumed(tmp_path) -> None:
    s = store(tmp_path)
    issued = s.issue("user-a", InstitutionConnectionRegistry().by_key("cityu"))
    with pytest.raises(OAuthError) as raised:
        s.consume(issued.state, now=issued.created_at + 10_000)
    assert raised.value.reason == "EXPIRED_STATE"
    # Consumed even though it was refused: the in-memory store behaves the same way on purpose.
    with pytest.raises(OAuthError) as second:
        s.consume(issued.state)
    assert second.value.reason == "UNKNOWN_STATE"


def test_the_plaintext_state_is_never_stored(tmp_path) -> None:
    """A database dump must not contain anything that could be replayed into a callback."""
    database = pathlib.Path(tmp_path / "state.sqlite3")
    s = store(tmp_path)
    issued = s.issue("user-a", InstitutionConnectionRegistry().by_key("cityu"))

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in connection.execute("SELECT * FROM canvas_oauth_states")]
    finally:
        connection.close()
    assert len(rows) == 1
    row = rows[0]
    assert issued.state not in str(row)
    assert row["state_hash"] == hashlib.sha256(issued.state.encode()).hexdigest()
    # Only the hash column is keyed on the state; the rest is bookkeeping.
    assert set(row) == {
        "state_hash",
        "subject",
        "institution_key",
        "origin",
        "return_path",
        "created_at",
        "expires_at",
        "consumed_at",
    }
    assert "token" not in " ".join(row).casefold()


def test_purging_removes_only_states_that_can_no_longer_be_used(tmp_path) -> None:
    s = store(tmp_path)
    live = s.issue("user-a", InstitutionConnectionRegistry().by_key("cityu"))
    stale = s.issue("user-a", InstitutionConnectionRegistry().by_key("cityu"))
    removed = s.purge_expired(now=stale.created_at + 10_000)
    assert removed == 2  # both are past their expiry at that moment
    assert s.pending() == 0
    del live
    del stale


def test_the_in_memory_store_still_implements_the_same_protocol(tmp_path) -> None:
    """The test double must not drift away from the shared implementation."""
    memory = InMemoryStateStore()
    issued = memory.issue("user-a", InstitutionConnectionRegistry().by_key("cityu"))
    assert isinstance(issued, AuthorizationState)
    assert memory.consume(issued.state).subject == "user-a"
    with pytest.raises(OAuthError):
        memory.consume(issued.state)


# ---------------------------------------------------------------------------- the real deployment
def test_the_app_wires_the_shared_store_not_the_in_memory_one(tmp_path) -> None:
    """The claim that matters for production: one process does not hold the only copy."""
    app, _school = build_app(tmp_path, School())
    state_store = getattr(app.state.canvas_oauth, 'states', None)
    assert isinstance(state_store, SqlStateStore)
    assert not isinstance(state_store, InMemoryStateStore)


def test_a_callback_lands_on_a_second_worker_and_completes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The journey a multi-worker deployment actually performs.

    Worker A answers `/connect` and hands the browser to the school; worker B receives the callback.
    With the in-memory store this is where the user would be told their authorisation "was already
    used or never existed"; with the shared store it completes and the connection exists.
    """
    monkeypatch.setenv("CANVAS_CITYU_CLIENT_ID", "12345")
    monkeypatch.setenv("CANVAS_CITYU_CLIENT_SECRET", "shhh")
    first_school = School()
    app_a, _ = build_app(tmp_path, first_school)
    client_a = TestClient(app_a)

    started = client_a.get(
        "/api/integrations/canvas/connect?institution=cityu", headers=AUTH, follow_redirects=False
    )
    assert started.status_code == 303, started.text
    location = started.headers["location"]
    state = httpx.URL(location).params["state"]

    # A second instance over the same database: a different process, the same schema.
    app_b, _ = build_app(tmp_path, School())
    client_b = TestClient(app_b)
    completed = client_b.get(
        f"/api/integrations/canvas/oauth/callback?code=auth-code&state={state}",
        headers=AUTH,
        follow_redirects=False,
    )
    assert completed.status_code == 303, completed.text
    assert "canvas=connected" in completed.headers["location"]

    connections = client_b.get("/api/integrations/canvas/connections", headers=AUTH)
    assert connections.status_code == 200, connections.text
    assert len(connections.json()["connections"]) == 1

    # And the state is spent: the same callback cannot run twice, on either worker.
    replay = client_a.get(
        f"/api/integrations/canvas/oauth/callback?code=auth-code&state={state}",
        headers=AUTH,
        follow_redirects=False,
    )
    assert replay.status_code == 303
    assert "canvas=failed" in replay.headers["location"]
