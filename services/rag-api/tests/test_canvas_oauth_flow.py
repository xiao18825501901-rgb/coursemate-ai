"""The Canvas OAuth flow: one-time state, exact callback, no silent account replacement.

Task B2 of the CourseJesus pack. The properties that matter, and that these tests pin:

* the `state` is one-time and short-lived, and is consumed on success **and** on failure —
  a replayed or expired callback must never attach an account;
* the flow is per institution, and the school's denial is a normal, recoverable outcome;
* a connection already bound to one Canvas account cannot be silently re-pointed at another;
* a refresh is serialised per connection, so two workers cannot invalidate each other;
* the two token operations are the only non-`GET` requests, and a token never appears in a
  URL or in the representation of the object that holds it.
"""

from __future__ import annotations

import threading
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.canvas.adapter import CanvasReadError
from app.canvas.oauth import (
    CanvasOAuthClient,
    InMemoryCredentialStore,
    InMemoryStateStore,
    OAuthError,
    TokenSet,
    callback_matches_institution,
    token_provider_for,
)
from app.canvas.registry import InstitutionConnectionRegistry

CITYU = "https://canvas.cityu.edu.hk"
CITYU_DG = "https://cityu-dg.instructure.com"


@pytest.fixture(autouse=True)
def configured_keys(monkeypatch):
    """Both institutions have a key pair, so the flow can be exercised."""
    monkeypatch.setenv("CANVAS_CITYU_CLIENT_ID", "cityu-client")
    monkeypatch.setenv("CANVAS_CITYU_CLIENT_SECRET", "cityu-secret")
    monkeypatch.setenv("CANVAS_CITYU_DG_CLIENT_ID", "dg-client")
    monkeypatch.setenv("CANVAS_CITYU_DG_CLIENT_SECRET", "dg-secret")


def token_response(*, access: str = "access-1", refresh: str = "refresh-1", expires: int = 3600):
    return httpx.Response(
        200,
        json={
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": expires,
            "token_type": "Bearer",
            "scope": "url:GET|/api/v1/courses",
        },
    )


class Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responses: list[httpx.Response] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0) if self.responses else token_response()
        return response

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler), follow_redirects=False)


def make_client(
    recorder: Recorder | None = None, *, now=None
) -> tuple[CanvasOAuthClient, Recorder]:
    recorder = recorder or Recorder()
    client = CanvasOAuthClient(
        registry=InstitutionConnectionRegistry(),
        state_store=InMemoryStateStore(now=now) if now else InMemoryStateStore(),
        credential_store=InMemoryCredentialStore(),
        client=recorder.client(),
        now=now or time.time,
    )
    return client, recorder


# ------------------------------------------------------------------ state rules
def test_start_builds_the_documented_authorization_url() -> None:
    client, _ = make_client()
    url = client.start("user-1", "cityu")
    parts = urlparse(url)
    query = parse_qs(parts.query)
    assert f"{parts.scheme}://{parts.netloc}" == CITYU
    assert parts.path == "/login/oauth2/auth"
    assert query["client_id"] == ["cityu-client"]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == [
        "https://rag.coursejesus.com/api/integrations/canvas/oauth/callback"
    ]
    assert len(query["state"][0]) >= 32
    # No token, no secret and no user data in the state.
    assert "secret" not in url
    assert "user-1" not in url


def test_start_refuses_an_institution_without_a_key(monkeypatch) -> None:
    monkeypatch.delenv("CANVAS_CITYU_CLIENT_ID", raising=False)
    client, _ = make_client()
    with pytest.raises(OAuthError) as error:
        client.start("user-1", "cityu")
    assert error.value.reason == "NOT_CONFIGURED"
    assert "Developer Key" in error.value.detail


def test_state_is_one_time() -> None:
    client, _ = make_client()
    url = client.start("user-1", "cityu")
    state = parse_qs(urlparse(url).query)["state"][0]
    completed = client.complete({"state": state, "code": "code-1"})
    assert completed.state.subject == "user-1"
    with pytest.raises(OAuthError) as error:
        client.complete({"state": state, "code": "code-1"})
    assert error.value.reason == "UNKNOWN_STATE"


def test_state_expires() -> None:
    clock = {"now": 1000.0}
    client, _ = make_client(now=lambda: clock["now"])
    url = client.start("user-1", "cityu")
    state = parse_qs(urlparse(url).query)["state"][0]
    clock["now"] += 601
    with pytest.raises(OAuthError) as error:
        client.complete({"state": state, "code": "code-1"})
    assert error.value.reason == "EXPIRED_STATE"


def test_an_unknown_state_never_reaches_the_code_exchange() -> None:
    client, recorder = make_client()
    with pytest.raises(OAuthError):
        client.complete({"state": "forged-state", "code": "code-1"})
    assert recorder.requests == [], "a forged state must not cause any outbound request"


def test_a_denied_authorization_is_consumed_and_reported_as_a_denial() -> None:
    client, recorder = make_client()
    url = client.start("user-1", "cityu")
    state = parse_qs(urlparse(url).query)["state"][0]
    with pytest.raises(OAuthError) as error:
        client.complete(
            {"state": state, "error": "access_denied", "error_description": "user said no"}
        )
    assert error.value.reason == "ACCESS_DENIED"
    assert recorder.requests == []
    # The state is burned even by a denial, so it cannot be replayed afterwards.
    with pytest.raises(OAuthError) as replay:
        client.complete({"state": state, "code": "code-1"})
    assert replay.value.reason == "UNKNOWN_STATE"


def test_a_callback_without_a_code_is_refused() -> None:
    client, _ = make_client()
    state = parse_qs(urlparse(client.start("user-1", "cityu")).query)["state"][0]
    with pytest.raises(OAuthError) as error:
        client.complete({"state": state})
    assert error.value.reason == "MISSING_CODE"


def test_start_requires_a_signed_in_user() -> None:
    client, _ = make_client()
    with pytest.raises(OAuthError) as error:
        client.start("", "cityu")
    assert error.value.reason == "NO_SUBJECT"


# ------------------------------------------------------------------ exchange
def test_completion_exchanges_the_code_with_the_exact_callback() -> None:
    client, recorder = make_client()
    state = parse_qs(urlparse(client.start("user-1", "cityu")).query)["state"][0]
    completed = client.complete({"state": state, "code": "code-abc"})
    assert completed.tokens.access_token == "access-1"
    assert completed.institution.origin == CITYU
    request = recorder.requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{CITYU}/login/oauth2/token"
    body = parse_qs(request.content.decode())
    assert body["grant_type"] == ["authorization_code"]
    assert body["code"] == ["code-abc"]
    assert body["redirect_uri"] == [
        "https://rag.coursejesus.com/api/integrations/canvas/oauth/callback"
    ]


def test_token_failures_are_classified() -> None:
    for status, expected in (
        (400, "EXPIRED_TOKEN"),
        (401, "EXPIRED_TOKEN"),
        (500, "INVALID_RESPONSE"),
    ):
        recorder = Recorder()
        recorder.responses = [httpx.Response(status, json={"error": "bad"})]
        client, _ = make_client(recorder)
        state = parse_qs(urlparse(client.start("user-1", "cityu")).query)["state"][0]
        with pytest.raises(CanvasReadError) as error:
            client.complete({"state": state, "code": "c"})
        assert error.value.category == expected, status


def test_a_token_response_without_an_access_token_is_invalid() -> None:
    recorder = Recorder()
    recorder.responses = [httpx.Response(200, json={"refresh_token": "r"})]
    client, _ = make_client(recorder)
    state = parse_qs(urlparse(client.start("user-1", "cityu")).query)["state"][0]
    with pytest.raises(CanvasReadError) as error:
        client.complete({"state": state, "code": "c"})
    assert error.value.category == "INVALID_RESPONSE"


# ------------------------------------------------------------------ binding
def test_binding_records_the_identity_triple() -> None:
    client, _ = make_client()
    state = parse_qs(urlparse(client.start("user-1", "cityu")).query)["state"][0]
    completed = client.complete({"state": state, "code": "c"})
    connection = completed.bind(
        canvas_user_id="4242",
        canvas_name="Student One",
        connection_id="conn-1",
        credential_store=client.credentials,
    )
    assert (connection.subject, connection.origin, connection.canvas_user_id) == (
        "user-1",
        CITYU,
        "4242",
    )
    assert connection.scopes == ("url:GET|/api/v1/courses",)
    assert callback_matches_institution(connection, completed.institution) is True


def test_another_canvas_account_cannot_replace_a_connection_silently() -> None:
    client, _ = make_client()
    state = parse_qs(urlparse(client.start("user-1", "cityu")).query)["state"][0]
    completed = client.complete({"state": state, "code": "c"})
    first = completed.bind(
        canvas_user_id="4242", connection_id="conn-1", credential_store=client.credentials
    )
    state = parse_qs(urlparse(client.start("user-1", "cityu")).query)["state"][0]
    second = client.complete({"state": state, "code": "c2"})
    with pytest.raises(OAuthError) as error:
        second.bind(
            canvas_user_id="9999",
            connection_id="conn-1",
            credential_store=client.credentials,
            previous=first,
        )
    assert error.value.reason == "ACCOUNT_REPLACEMENT_NOT_CONFIRMED"
    assert "4242" in error.value.detail and "9999" in error.value.detail
    # With an explicit confirmation the rebinding is allowed.
    rebound = second.bind(
        canvas_user_id="9999",
        connection_id="conn-1",
        credential_store=client.credentials,
        previous=first,
        confirmed_replacement=True,
    )
    assert rebound.canvas_user_id == "9999"


def test_two_users_are_bound_to_their_own_connections() -> None:
    client, _ = make_client()
    connections = []
    for subject, canvas_id, connection_id in (
        ("user-a", "1", "conn-a"),
        ("user-b", "2", "conn-b"),
    ):
        state = parse_qs(urlparse(client.start(subject, "cityu")).query)["state"][0]
        completed = client.complete({"state": state, "code": "c"})
        connections.append(
            completed.bind(
                canvas_user_id=canvas_id,
                connection_id=connection_id,
                credential_store=client.credentials,
            )
        )
    assert {(c.subject, c.canvas_user_id) for c in connections} == {
        ("user-a", "1"),
        ("user-b", "2"),
    }
    assert client.credentials.load_token("conn-a") == "access-1"
    assert client.credentials.load_token("conn-b") == "access-1"


# ------------------------------------------------------------------ refresh
class RefreshStore(InMemoryCredentialStore):
    """A credential store that can also return the refresh token, as production must."""

    def __init__(self) -> None:
        super().__init__()
        self._refresh: dict[str, str] = {}

    def save(self, connection_id: str, tokens: TokenSet):
        stored = super().save(connection_id, tokens)
        self._refresh[connection_id] = tokens.refresh_token
        return stored

    def load_refresh_token(self, connection_id: str) -> str | None:
        return self._refresh.get(connection_id)

    def clear(self, connection_id: str) -> None:
        super().clear(connection_id)
        self._refresh.pop(connection_id, None)


def test_refresh_is_serialised_per_connection() -> None:
    """Two workers cannot both refresh: the second reuses the first worker's new token.

    The initial exchange issues a token that is already near expiry, so a refresh really
    does happen; the refresh itself returns a long-lived token, so the worker waiting on
    the per-connection lock must reuse it instead of asking for a second one.
    """
    calls: list[float] = []
    gate = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(time.time())
        grant = parse_qs(request.content.decode()).get("grant_type", [""])[0]
        gate.wait(timeout=5)
        if grant == "refresh_token":
            return token_response(access="access-refreshed", refresh="refresh-2", expires=3600)
        return token_response(access="access-initial", refresh="refresh-1", expires=10)

    store = RefreshStore()
    client = CanvasOAuthClient(
        registry=InstitutionConnectionRegistry(),
        state_store=InMemoryStateStore(),
        credential_store=store,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    state = parse_qs(urlparse(client.start("user-1", "cityu")).query)["state"][0]
    completed = client.complete({"state": state, "code": "c"})
    connection = completed.bind(canvas_user_id="1", connection_id="conn-1", credential_store=store)
    results: list[object] = []

    def worker() -> None:
        try:
            results.append(client.refresh(connection, force=True))
        except Exception as error:  # noqa: BLE001 - recorded, asserted below
            results.append(error)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    time.sleep(0.05)
    gate.set()
    for thread in threads:
        thread.join(timeout=10)
    assert len(calls) == 2, "the exchange plus exactly one refresh"
    assert all(not isinstance(result, Exception) for result in results), results


def test_refresh_without_force_does_not_call_the_endpoint() -> None:
    client, recorder = make_client()
    state = parse_qs(urlparse(client.start("user-1", "cityu")).query)["state"][0]
    completed = client.complete({"state": state, "code": "c"})
    connection = completed.bind(
        canvas_user_id="1", connection_id="conn-1", credential_store=client.credentials
    )
    calls_before = len(recorder.requests)
    assert client.refresh(connection) is None
    assert len(recorder.requests) == calls_before


def test_refresh_without_a_stored_refresh_token_is_expired_token() -> None:
    """A near-expiry credential with no refresh token is the NEEDS_REAUTH case."""
    recorder = Recorder()
    recorder.responses = [token_response(expires=10)]
    client, _ = make_client(recorder)
    state = parse_qs(urlparse(client.start("user-1", "cityu")).query)["state"][0]
    completed = client.complete({"state": state, "code": "c"})
    connection = completed.bind(
        canvas_user_id="1", connection_id="conn-1", credential_store=client.credentials
    )
    with pytest.raises(CanvasReadError) as error:
        client.refresh(connection, force=True)
    assert error.value.category == "EXPIRED_TOKEN"


def test_token_provider_prefers_the_stored_token() -> None:
    client, _ = make_client()
    state = parse_qs(urlparse(client.start("user-1", "cityu")).query)["state"][0]
    completed = client.complete({"state": state, "code": "c"})
    connection = completed.bind(
        canvas_user_id="1", connection_id="conn-1", credential_store=client.credentials
    )
    provider = token_provider_for(connection, client)
    assert provider() == "access-1"


# ------------------------------------------------------------------ revocation
def test_revoke_calls_delete_and_clears_the_local_credential() -> None:
    client, recorder = make_client()
    state = parse_qs(urlparse(client.start("user-1", "cityu")).query)["state"][0]
    completed = client.complete({"state": state, "code": "c"})
    connection = completed.bind(
        canvas_user_id="1", connection_id="conn-1", credential_store=client.credentials
    )
    recorder.responses = [httpx.Response(200, json={})]
    assert client.revoke(connection) is True
    request = recorder.requests[-1]
    assert request.method == "DELETE"
    assert str(request.url) == f"{CITYU}/login/oauth2/token"
    assert request.headers["authorization"] == "Bearer access-1"
    assert client.credentials.load_token("conn-1") is None


def test_revoke_clears_locally_even_when_the_school_endpoint_fails() -> None:
    client, recorder = make_client()
    state = parse_qs(urlparse(client.start("user-1", "cityu")).query)["state"][0]
    completed = client.complete({"state": state, "code": "c"})
    connection = completed.bind(
        canvas_user_id="1", connection_id="conn-1", credential_store=client.credentials
    )
    recorder.responses = [httpx.Response(503, json={})]
    assert client.revoke(connection) is False
    assert client.credentials.load_token("conn-1") is None


# ------------------------------------------------------------------ redaction
def test_tokens_are_never_in_a_url_or_a_repr() -> None:
    client, recorder = make_client()
    state = parse_qs(urlparse(client.start("user-1", "cityu")).query)["state"][0]
    completed = client.complete({"state": state, "code": "code-abc"})
    for request in recorder.requests:
        assert "access-1" not in str(request.url)
        assert "refresh-1" not in str(request.url)
        assert "secret" not in str(request.url)
    rendered = repr(completed.tokens)
    assert "access-1" not in rendered and "refresh-1" not in rendered
    assert "<redacted>" in rendered
    stored = client.credentials.save("conn-x", completed.tokens)
    assert "access-1" not in repr(stored)


def test_the_only_non_get_requests_are_the_documented_token_operations() -> None:
    client, recorder = make_client()
    state = parse_qs(urlparse(client.start("user-1", "cityu")).query)["state"][0]
    completed = client.complete({"state": state, "code": "c"})
    connection = completed.bind(
        canvas_user_id="1", connection_id="conn-1", credential_store=client.credentials
    )
    recorder.responses = [httpx.Response(200, json={})]
    client.revoke(connection)
    methods = {(request.method, urlparse(str(request.url)).path) for request in recorder.requests}
    assert methods == {
        ("POST", "/login/oauth2/token"),
        ("DELETE", "/login/oauth2/token"),
    }
