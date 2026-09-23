"""HTTP contract for the Canvas import routes.

These tests run the **real** application wiring (`app.main.create_app`): the real auth verifier,
the real error handler, the real registry, the real encrypted credential store and the real
`CanvasOAuthClient`. What is simulated is the school's HTTP surface — an `httpx.MockTransport`
standing in for Canvas — so the authorisation flow, the state handling, the identity binding, the
frozen job creation and the refusals are all production code paths.

The point of the suite is the list of things a route can get wrong that no amount of UI work
fixes: starting an authorisation for a school that has no key, accepting a callback whose state
it never issued, letting a callback attach a *different* Canvas account to an existing
connection, leaking a token into a response, letting one user read another user's connection or
job, and starting a second import of the same selection.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.canvas.credentials import generate_key
from app.canvas.oauth import CanvasOAuthClient, InMemoryStateStore
from app.canvas.registry import InstitutionConnectionRegistry
from app.config import Settings
from app.main import create_app

CITYU = "https://canvas.cityu.edu.hk"
CITYU_DG = "https://cityu-dg.instructure.com"
CALLBACK = "https://rag.coursejesus.com/api/integrations/canvas/oauth/callback"
USER = "user-1"
OTHER_USER = "user-2"
TOKEN = "canvas-access-token"
AUTH = {"Authorization": "Bearer test-session-token"}

COURSES_ACTIVE = [
    {
        "id": 560,
        "name": "Problem Solve & Programming",
        "course_code": "CS2312",
        "workflow_state": "available",
        "term": {"name": "Semester B 2025_26"},
        "enrollments": [
            {"type": "student", "role": "StudentEnrollment", "enrollment_state": "active"}
        ],
    }
]
COURSES_COMPLETED = [
    {
        "id": 240,
        "name": "Funda. of Internet App. Dev.",
        "course_code": "CS2204",
        "workflow_state": "completed",
        "term": {"name": "Semester A 2024_25"},
        "enrollments": [
            {"type": "student", "role": "StudentEnrollment", "enrollment_state": "completed"}
        ],
    }
]


@dataclass
class School:
    """A stand-in Canvas: the courses API, the profile, the token endpoint and a request log."""

    profile_id: int | None = 4242
    profile_name: str = "Student One"
    profile_status: int = 200
    courses_status: int = 200
    token_status: int = 200
    requests: list[tuple[str, str]] = field(default_factory=list)
    token_payloads: list[dict[str, str]] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path))
        if path == "/login/oauth2/token":
            self.token_payloads.append(dict(httpx.QueryParams(request.content.decode())))
            if self.token_status >= 400:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
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
            if self.profile_status >= 400:
                return httpx.Response(
                    self.profile_status, json={"errors": [{"message": "unauthorized"}]}
                )
            if self.profile_id is None:
                # A school that answers without an identity: the route must refuse to bind one.
                return httpx.Response(200, json={"name": self.profile_name})
            return httpx.Response(200, json={"id": self.profile_id, "name": self.profile_name})
        if path == "/api/v1/courses":
            if self.courses_status >= 400:
                return httpx.Response(self.courses_status, json={"errors": [{"message": "no"}]})
            completed = dict(request.url.params).get("enrollment_state") == "completed"
            return httpx.Response(200, json=COURSES_COMPLETED if completed else COURSES_ACTIVE)
        if path == "/login/oauth2/token/revoke" or path == "/login/oauth2/token":
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"errors": [{"message": "not found"}]})


@dataclass
class Harness:
    app: Any
    client: TestClient
    school: School
    settings: Settings
    store: Any
    states: InMemoryStateStore
    credentials: Any

    def connection_id(self) -> str:
        response = self.client.get("/api/integrations/canvas/connections", headers=AUTH)
        assert response.status_code == 200, response.text
        connections = response.json()["connections"]
        assert len(connections) == 1, connections
        return str(connections[0]["connectionId"])

    def start_state(
        self, institution: str = "cityu", *, headers: dict[str, str] | None = None
    ) -> str:
        response = self.client.get(
            f"/api/integrations/canvas/connect?institution={institution}",
            headers=headers or AUTH,
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text
        match = re.search(r"[?&]state=([^&]+)", response.headers["location"])
        assert match, response.headers["location"]
        return match.group(1)


def build(
    tmp_path: pathlib.Path,
    school: School,
    *,
    credential_key: str | None = None,
    v3_enabled: bool = True,
    return_path: str | None = None,
    task_credential: bool = False,
    task_credential_users: str = "",
) -> Harness:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        ui_web_dir=tmp_path / "no-web-build",
        app_env="test",
        rag_provider_mode="deterministic",
        auth_test_user_id=USER,
        admin_user_ids=USER,
        v3_enabled=v3_enabled,
        canvas_credential_dir=tmp_path / "canvas-credentials",
        canvas_credential_key=credential_key if credential_key is not None else generate_key(),
        canvas_return_path=return_path if return_path is not None else "/ui-extension/#/courses",
        canvas_task_credential_enabled=task_credential,
        canvas_task_credential_users=task_credential_users,
    )
    app = create_app(settings=settings)
    transport = httpx.MockTransport(school.handler)
    states = InMemoryStateStore()
    credentials = getattr(app.state, "canvas_credentials", None)
    # Replace the OAuth client with one that talks to the simulated school; everything else in
    # the flow (state issuing, the callback route, the identity binding, the store) is unchanged.
    # With no credential store the app deliberately wires no client at all, and neither do we.
    if credentials is not None:
        app.state.canvas_oauth = CanvasOAuthClient(
            registry=app.state.canvas_registry,
            state_store=states,
            credential_store=credentials,
            client=httpx.Client(transport=transport, follow_redirects=False),
        )
    from app.canvas.adapter import CanvasReadAdapter

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
    return Harness(
        app=app,
        client=TestClient(app),
        school=school,
        settings=settings,
        store=credentials,
        states=states,
        credentials=credentials,
    )


@pytest.fixture()
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANVAS_CITYU_CLIENT_ID", "12345")
    monkeypatch.setenv("CANVAS_CITYU_CLIENT_SECRET", "shhh")
    monkeypatch.setenv("CANVAS_CITYU_DG_CLIENT_ID", "67890")
    monkeypatch.setenv("CANVAS_CITYU_DG_CLIENT_SECRET", "shhh")


def authorise(harness: Harness, *, institution: str = "cityu", code: str = "abc123") -> str:
    """Run the whole flow once and return the connection id."""
    state = harness.start_state(institution)
    response = harness.client.get(
        f"/api/integrations/canvas/oauth/callback?code={code}&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/ui-extension/?canvas=connected#/courses"
    return harness.connection_id()


# --------------------------------------------------------------------------- availability
def test_every_route_requires_a_session(tmp_path) -> None:
    harness = build(tmp_path, School())
    body = {"connection_id": "conn-1", "course_ids": ["560"]}
    for method, path, payload in (
        ("get", "/api/integrations/canvas/institutions", None),
        ("get", "/api/integrations/canvas/connections", None),
        ("get", "/api/integrations/canvas/connect?institution=cityu", None),
        ("get", "/api/integrations/canvas/courses?connection_id=x", None),
        ("get", "/api/integrations/canvas/imports/job-1", None),
        ("post", "/api/integrations/canvas/imports", body),
        ("post", "/api/integrations/canvas/imports/job-1/cancel", None),
        ("delete", "/api/integrations/canvas/connections/x", None),
    ):
        request = getattr(harness.client, method)
        response = request(path, json=payload) if payload is not None else request(path)
        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_a_school_without_a_developer_key_is_reported_as_not_connectable(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "CANVAS_CITYU_CLIENT_ID",
        "CANVAS_CITYU_CLIENT_SECRET",
        "CANVAS_CITYU_DG_CLIENT_ID",
        "CANVAS_CITYU_DG_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    harness = build(tmp_path, School())

    body = harness.client.get("/api/integrations/canvas/institutions", headers=AUTH).json()

    assert [item["key"] for item in body["institutions"]] == ["cityu", "cityu-dg"]
    assert body["credentialsReady"] is True
    for item in body["institutions"]:
        assert item["connectable"] is False
        assert item["reason"] == "NO_DEVELOPER_KEY"
    # And starting an authorisation says so, rather than sending the user to a broken page.
    response = harness.client.get(
        "/api/integrations/canvas/connect?institution=cityu", headers=AUTH, follow_redirects=False
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CANVAS_NOT_CONFIGURED"


def test_a_deployment_without_a_credential_key_cannot_connect(tmp_path, keys) -> None:
    """A missing encryption key is a missing capability, never a plaintext fallback."""
    harness = build(tmp_path, School(), credential_key="")

    body = harness.client.get("/api/integrations/canvas/institutions", headers=AUTH).json()

    assert body["credentialsReady"] is False
    assert {item["reason"] for item in body["institutions"]} == {"NO_CREDENTIAL_KEY"}
    assert all(item["connectable"] is False for item in body["institutions"])
    response = harness.client.get(
        "/api/integrations/canvas/connect?institution=cityu", headers=AUTH, follow_redirects=False
    )
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "NO_CREDENTIAL_KEY"


def test_an_unknown_school_is_refused(tmp_path, keys) -> None:
    harness = build(tmp_path, School())
    response = harness.client.get(
        "/api/integrations/canvas/connect?institution=somewhere-else",
        headers=AUTH,
        follow_redirects=False,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "UNKNOWN_INSTITUTION"


def test_the_return_target_is_configuration_and_not_a_request_parameter(tmp_path, keys) -> None:
    """The product decides where a user lands; a query string must not be able to steer it.

    The UI is hash-routed, so the configured path carries a fragment and the outcome query has to
    go before it — which is exactly the sort of detail that would otherwise be discovered as a
    404 in production.
    """
    harness = build(tmp_path, School(), return_path="/app#/courses")
    state = harness.start_state()
    response = harness.client.get(
        f"/api/integrations/canvas/oauth/callback?code=abc&state={state}"
        "&return_url=https://evil.example.com/steal",
        follow_redirects=False,
    )
    assert response.headers["location"] == "/app?canvas=connected#/courses"

    # A configured path with no fragment is used as-is, and one that already carries a query
    # keeps it.
    plain = build(tmp_path / "plain", School(), return_path="/courses")
    state = plain.start_state()
    assert (
        plain.client.get(
            f"/api/integrations/canvas/oauth/callback?code=abc&state={state}",
            follow_redirects=False,
        ).headers["location"]
        == "/courses?canvas=connected"
    )
    queried = build(tmp_path / "queried", School(), return_path="/app?from=canvas#/courses")
    state = queried.start_state()
    assert (
        queried.client.get(
            f"/api/integrations/canvas/oauth/callback?code=abc&state={state}",
            follow_redirects=False,
        ).headers["location"]
        == "/app?from=canvas&canvas=connected#/courses"
    )


def test_every_callback_outcome_uses_the_configured_return_path(tmp_path, keys) -> None:
    harness = build(tmp_path, School(token_status=400), return_path="/app#/courses")
    state = harness.start_state()
    failed = harness.client.get(
        f"/api/integrations/canvas/oauth/callback?code=abc&state={state}", follow_redirects=False
    )
    denied_state = harness.start_state()
    denied = harness.client.get(
        f"/api/integrations/canvas/oauth/callback?error=access_denied&state={denied_state}",
        follow_redirects=False,
    )
    forged = harness.client.get(
        "/api/integrations/canvas/oauth/callback?code=abc&state=forged", follow_redirects=False
    )
    assert failed.headers["location"] == "/app?canvas=failed#/courses"
    assert denied.headers["location"] == "/app?canvas=denied#/courses"
    assert forged.headers["location"] == "/app?canvas=failed#/courses"


def test_a_wired_client_without_a_credential_store_is_treated_as_unconfigured(
    tmp_path, keys
) -> None:
    """A flow that cannot persist the credential must not report itself connected.

    This is the mis-wiring the route guards against: an OAuth client that exists but has no
    store would issue a state, complete the exchange, and then lose the token — leaving a
    connection that looks connected and a user who is not.
    """
    harness = build(tmp_path, School())
    harness.app.state.canvas_oauth = CanvasOAuthClient(
        registry=harness.app.state.canvas_registry,
        state_store=harness.states,
        credential_store=None,  # type: ignore[arg-type]
    )

    response = harness.client.get(
        "/api/integrations/canvas/connect?institution=cityu", headers=AUTH, follow_redirects=False
    )
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "NO_CREDENTIAL_KEY"

    callback = harness.client.get(
        "/api/integrations/canvas/oauth/callback?code=abc&state=whatever",
        follow_redirects=False,
    )
    assert callback.headers["location"] == "/ui-extension/?canvas=failed#/courses"
    assert harness.school.token_payloads == []


# ------------------------------------------------------------------------- authorisation
def test_connect_redirects_to_the_schools_own_authorisation_url(tmp_path, keys) -> None:
    harness = build(tmp_path, School())
    response = harness.client.get(
        "/api/integrations/canvas/connect?institution=cityu", headers=AUTH, follow_redirects=False
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith(f"{CITYU}/login/oauth2/auth?")
    query = httpx.QueryParams(location.split("?", 1)[1])
    assert query["client_id"] == "12345"
    assert query["response_type"] == "code"
    assert query["redirect_uri"] == CALLBACK, "the registered callback must be exact"
    assert query["state"] and USER not in query["state"]
    assert set(query) == {"client_id", "response_type", "state", "redirect_uri"}


def test_the_institution_is_taken_from_the_registry_not_the_caller(tmp_path, keys) -> None:
    """No route accepts a base_url, so one school's secret cannot be spent on another's origin."""
    harness = build(tmp_path, School())
    response = harness.client.get(
        "/api/integrations/canvas/connect?institution=cityu&base_url=https://evil.example.com",
        headers=AUTH,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith(f"{CITYU}/login/oauth2/auth?")
    # The second institution resolves to its own origin and its own client id.
    other = harness.client.get(
        "/api/integrations/canvas/connect?institution=cityu-dg",
        headers=AUTH,
        follow_redirects=False,
    )
    assert other.headers["location"].startswith(f"{CITYU_DG}/login/oauth2/auth?")
    assert "client_id=67890" in other.headers["location"]


def test_a_callback_with_a_state_we_never_issued_is_refused(tmp_path, keys) -> None:
    harness = build(tmp_path, School())

    response = harness.client.get(
        "/api/integrations/canvas/oauth/callback?code=abc&state=forged",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/ui-extension/?canvas=failed#/courses"
    assert harness.school.token_payloads == [], "no code may be exchanged for a forged state"
    assert (
        harness.client.get("/api/integrations/canvas/connections", headers=AUTH).json()[
            "connections"
        ]
        == []
    )


def test_a_state_cannot_be_replayed(tmp_path, keys) -> None:
    harness = build(tmp_path, School())
    state = harness.start_state()

    first = harness.client.get(
        f"/api/integrations/canvas/oauth/callback?code=abc&state={state}", follow_redirects=False
    )
    second = harness.client.get(
        f"/api/integrations/canvas/oauth/callback?code=abc&state={state}", follow_redirects=False
    )

    assert first.headers["location"] == "/ui-extension/?canvas=connected#/courses"
    assert second.headers["location"] == "/ui-extension/?canvas=failed#/courses"
    assert len(harness.school.token_payloads) == 1
    assert (
        len(
            harness.client.get("/api/integrations/canvas/connections", headers=AUTH).json()[
                "connections"
            ]
        )
        == 1
    )


def test_a_denied_authorisation_is_reported_as_denied_not_as_a_failure(tmp_path, keys) -> None:
    harness = build(tmp_path, School())
    state = harness.start_state()

    response = harness.client.get(
        f"/api/integrations/canvas/oauth/callback?error=access_denied"
        f"&error_description=The+user+denied+the+request&state={state}",
        follow_redirects=False,
    )

    assert response.headers["location"] == "/ui-extension/?canvas=denied#/courses"
    assert harness.school.token_payloads == []


def test_a_successful_callback_stores_an_encrypted_credential_and_no_token_in_the_response(
    tmp_path, keys
) -> None:
    harness = build(tmp_path, School())
    state = harness.start_state()

    response = harness.client.get(
        f"/api/integrations/canvas/oauth/callback?code=abc&state={state}", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/ui-extension/?canvas=connected#/courses"
    assert TOKEN not in response.text and TOKEN not in json.dumps(dict(response.headers))
    # The code was exchanged for the registered callback and the school's own client id.
    assert harness.school.token_payloads == [
        {
            "grant_type": "authorization_code",
            "client_id": "12345",
            "client_secret": "shhh",
            "redirect_uri": CALLBACK,
            "code": "abc",
        }
    ]

    connections = harness.client.get("/api/integrations/canvas/connections", headers=AUTH).json()[
        "connections"
    ]
    assert len(connections) == 1
    connection = connections[0]
    assert connection["institutionKey"] == "cityu"
    assert connection["origin"] == CITYU
    assert connection["canvasName"] == "Student One"
    assert connection["savedForReuse"] is False, "an ordinary import must not keep the credential"
    assert connection["scopes"] == ["url:GET|/api/v1/courses"]
    assert TOKEN not in json.dumps(connections)

    # The credential is on disk, encrypted, under a key id.
    files = list((tmp_path / "canvas-credentials").glob("*.canvascred"))
    assert len(files) == 1
    assert TOKEN.encode() not in files[0].read_bytes()
    assert json.loads(files[0].read_text(encoding="utf-8"))["key_id"]
    assert harness.credentials.load_token(connection["connectionId"]) == TOKEN


def test_reconnecting_the_same_canvas_account_updates_one_row(tmp_path, keys) -> None:
    harness = build(tmp_path, School())
    first = authorise(harness)
    second = authorise(harness, code="def456")

    connections = harness.client.get("/api/integrations/canvas/connections", headers=AUTH).json()[
        "connections"
    ]
    assert [item["connectionId"] for item in connections] == [first]
    assert first == second
    assert len(harness.school.token_payloads) == 2


def test_a_callback_for_a_different_canvas_account_does_not_replace_the_connection(
    tmp_path, keys
) -> None:
    """One person's courses must not be silently filed under another person's Canvas account."""
    school = School()
    harness = build(tmp_path, school)
    connection_id = authorise(harness)

    school.profile_id = 9999
    school.profile_name = "Someone Else"
    state = harness.start_state()
    response = harness.client.get(
        f"/api/integrations/canvas/oauth/callback?code=second&state={state}", follow_redirects=False
    )

    assert response.headers["location"] == "/ui-extension/?canvas=failed#/courses"
    connections = harness.client.get("/api/integrations/canvas/connections", headers=AUTH).json()[
        "connections"
    ]
    assert [item["connectionId"] for item in connections] == [connection_id]
    assert connections[0]["canvasName"] == "Student One", "the stored identity must not change"


def test_a_token_endpoint_failure_is_reported_without_echoing_the_school_message(
    tmp_path, keys
) -> None:
    school = School(token_status=400)
    harness = build(tmp_path, school)
    state = harness.start_state()

    response = harness.client.get(
        f"/api/integrations/canvas/oauth/callback?code=abc&state={state}", follow_redirects=False
    )

    assert response.headers["location"] == "/ui-extension/?canvas=failed#/courses"
    assert "invalid_grant" not in response.headers["location"]
    assert (
        harness.client.get("/api/integrations/canvas/connections", headers=AUTH).json()[
            "connections"
        ]
        == []
    )


# ------------------------------------------------------------------------------- courses
def test_courses_come_from_the_students_own_enrolments(tmp_path, keys) -> None:
    harness = build(tmp_path, School())
    connection_id = authorise(harness)

    response = harness.client.get(
        f"/api/integrations/canvas/courses?connection_id={connection_id}", headers=AUTH
    )

    assert response.status_code == 200
    courses = response.json()["courses"]
    assert {course["id"] for course in courses} == {"560", "240"}
    assert {(course["id"], course["readable"]) for course in courses} == {
        ("560", True),
        ("240", True),
    }


def test_another_users_connection_is_not_readable_and_not_even_confirmable(tmp_path, keys) -> None:
    harness = build(tmp_path, School())
    connection_id = authorise(harness)

    response = harness.client.get(
        f"/api/integrations/canvas/courses?connection_id={connection_id}",
        headers={"Authorization": "Bearer test-session-token"},
    )
    assert response.status_code == 200

    # The same connection id under a session that does not own it is absent, not forbidden.
    harness.app.state.auth_verifier.user_id = OTHER_USER
    try:
        other = harness.client.get(
            f"/api/integrations/canvas/courses?connection_id={connection_id}", headers=AUTH
        )
        assert other.status_code == 404
        assert other.json()["error"]["code"] == "CONNECTION_NOT_FOUND"
    finally:
        harness.app.state.auth_verifier.user_id = USER


def test_a_locked_course_list_is_reported_as_forbidden(tmp_path, keys) -> None:
    school = School(courses_status=403)
    harness = build(tmp_path, school)
    connection_id = authorise(harness)

    response = harness.client.get(
        f"/api/integrations/canvas/courses?connection_id={connection_id}", headers=AUTH
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CANVAS_FORBIDDEN"


# ------------------------------------------------------------------------------- imports
def test_creating_an_import_freezes_the_selection_and_is_idempotent(tmp_path, keys) -> None:
    harness = build(tmp_path, School())
    connection_id = authorise(harness)
    payload = {"connection_id": connection_id, "course_ids": ["560", "240"]}

    first = harness.client.post("/api/integrations/canvas/imports", json=payload, headers=AUTH)
    second = harness.client.post(
        "/api/integrations/canvas/imports",
        json={"connection_id": connection_id, "course_ids": ["240", "560"]},
        headers=AUTH,
    )

    assert first.status_code == 202
    assert first.json()["status"] == "QUEUED"
    assert first.json()["created"] is True
    assert second.json()["jobId"] == first.json()["jobId"], "the same selection is one job"
    assert second.json()["created"] is False

    status = harness.client.get(
        f"/api/integrations/canvas/imports/{first.json()['jobId']}", headers=AUTH
    ).json()
    assert status["status"] == "QUEUED"
    assert status["courses"] == 2
    assert status["files"] == 0


def test_an_import_selection_is_validated(tmp_path, keys) -> None:
    harness = build(tmp_path, School())
    connection_id = authorise(harness)

    for payload in (
        {"connection_id": connection_id, "course_ids": []},
        {"connection_id": connection_id, "course_ids": ["not-a-number"]},
        {"connection_id": "", "course_ids": ["560"]},
    ):
        response = harness.client.post(
            "/api/integrations/canvas/imports", json=payload, headers=AUTH
        )
        assert response.status_code == 422, payload


def test_saving_the_connection_for_reuse_is_explicit(tmp_path, keys) -> None:
    harness = build(tmp_path, School())
    connection_id = authorise(harness)
    assert (
        harness.client.get("/api/integrations/canvas/connections", headers=AUTH).json()[
            "connections"
        ][0]["savedForReuse"]
        is False
    )

    harness.client.post(
        "/api/integrations/canvas/imports",
        json={"connection_id": connection_id, "course_ids": ["560"], "save_connection": True},
        headers=AUTH,
    )

    assert (
        harness.client.get("/api/integrations/canvas/connections", headers=AUTH).json()[
            "connections"
        ][0]["savedForReuse"]
        is True
    )


def test_a_job_belonging_to_another_user_is_reported_as_absent(tmp_path, keys) -> None:
    harness = build(tmp_path, School())
    connection_id = authorise(harness)
    job_id = harness.client.post(
        "/api/integrations/canvas/imports",
        json={"connection_id": connection_id, "course_ids": ["560"]},
        headers=AUTH,
    ).json()["jobId"]

    harness.app.state.auth_verifier.user_id = OTHER_USER
    try:
        response = harness.client.get(f"/api/integrations/canvas/imports/{job_id}", headers=AUTH)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "JOB_NOT_FOUND"
    finally:
        harness.app.state.auth_verifier.user_id = USER


def test_cancelling_an_import_is_idempotent_and_keeps_the_files(tmp_path, keys) -> None:
    harness = build(tmp_path, School())
    connection_id = authorise(harness)
    job_id = harness.client.post(
        "/api/integrations/canvas/imports",
        json={"connection_id": connection_id, "course_ids": ["560", "240"]},
        headers=AUTH,
    ).json()["jobId"]

    first = harness.client.post(f"/api/integrations/canvas/imports/{job_id}/cancel", headers=AUTH)
    second = harness.client.post(f"/api/integrations/canvas/imports/{job_id}/cancel", headers=AUTH)

    assert first.json() == {"jobId": job_id, "status": "CANCELLED", "cancelled": True}
    assert second.json()["cancelled"] is False
    assert (
        harness.client.get(f"/api/integrations/canvas/imports/{job_id}", headers=AUTH).json()[
            "status"
        ]
        == "CANCELLED"
    )


def test_disconnecting_forgets_the_credential_and_marks_the_row(tmp_path, keys) -> None:
    harness = build(tmp_path, School())
    connection_id = authorise(harness)
    assert (tmp_path / "canvas-credentials").glob("*.canvascred")

    response = harness.client.delete(
        f"/api/integrations/canvas/connections/{connection_id}", headers=AUTH
    )

    assert response.status_code == 200
    assert response.json()["revoked"] is True
    assert (
        harness.client.get("/api/integrations/canvas/connections", headers=AUTH).json()[
            "connections"
        ]
        == []
    )
    assert list((tmp_path / "canvas-credentials").glob("*.canvascred")) == []
    assert harness.credentials.load_token(connection_id) is None


def test_a_disconnect_for_an_unknown_connection_is_a_404(tmp_path, keys) -> None:
    harness = build(tmp_path, School())
    response = harness.client.delete("/api/integrations/canvas/connections/not-mine", headers=AUTH)
    assert response.status_code == 404


def test_the_registry_the_app_wires_is_the_one_the_routes_use(tmp_path, keys) -> None:
    """The router must not build a private registry that disagrees with the deployment's."""
    harness = build(tmp_path, School())
    assert isinstance(harness.app.state.canvas_registry, InstitutionConnectionRegistry)
    assert harness.app.state.canvas_oauth.registry is harness.app.state.canvas_registry
    assert harness.app.state.canvas_oauth.credentials is harness.app.state.canvas_credentials


def test_a_deployment_without_the_private_course_schema_refuses_instead_of_failing(
    tmp_path, keys
) -> None:
    """Migration 031 ships with the V3 schema, so a V3-less deployment has no canvas tables.

    Mounting the routes regardless is deliberate — the UI must be able to ask — but every
    database-backed route has to say why it cannot work rather than raising a missing-table 500.
    """
    harness = build(tmp_path, School(), v3_enabled=False)

    body = harness.client.get("/api/integrations/canvas/institutions", headers=AUTH).json()
    assert body["tablesReady"] is False
    assert {item["reason"] for item in body["institutions"]} == {"SCHEMA_NOT_READY"}
    assert all(item["connectable"] is False for item in body["institutions"])

    for method, path, payload in (
        ("get", "/api/integrations/canvas/connections", None),
        ("get", "/api/integrations/canvas/imports/job-1", None),
        ("post", "/api/integrations/canvas/imports/job-1/cancel", None),
        ("delete", "/api/integrations/canvas/connections/x", None),
        ("get", "/api/integrations/canvas/courses?connection_id=x", None),
        (
            "post",
            "/api/integrations/canvas/imports",
            {"connection_id": "x", "course_ids": ["560"]},
        ),
    ):
        request = getattr(harness.client, method)
        if payload is None:
            response = request(path, headers=AUTH)
        else:
            response = request(path, json=payload, headers=AUTH)
        assert response.status_code == 503, f"{method} {path} -> {response.status_code}"
        assert response.json()["error"]["details"]["reason"] == "SCHEMA_NOT_READY"


# --------------------------------------------------------- the one-off task credential
PASTED = "1~pastedCanvasPersonalAccessTokenValue000000000000000"


def open_task_credential(harness: Harness, *, institution_key: str = "cityu") -> dict[str, Any]:
    response = harness.client.post(
        "/api/integrations/canvas/task-credentials",
        headers=AUTH,
        json={"institution_key": institution_key, "personal_access_token": PASTED},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_the_task_credential_path_is_off_until_a_deployment_offers_it_to_an_account(
    tmp_path, keys
) -> None:
    """The owner's testing path must not be a public multi-user feature by accident.

    Three separate gates are asserted: the deployment flag, the listed account, and the reason
    the UI is told. A deployment that never enables it answers exactly as it does today.
    """
    closed = build(tmp_path, School(), task_credential=False)
    body = closed.client.get("/api/integrations/canvas/institutions", headers=AUTH).json()
    assert body["taskCredential"] == {
        "available": False,
        "reason": "TASK_CREDENTIAL_DISABLED",
        "ownerOnly": True,
    }
    refusal = closed.client.post(
        "/api/integrations/canvas/task-credentials",
        headers=AUTH,
        json={"institution_key": "cityu", "personal_access_token": PASTED},
    )
    assert refusal.status_code == 403
    assert refusal.json()["error"]["code"] == "CANVAS_TASK_CREDENTIAL_FORBIDDEN"
    assert refusal.json()["error"]["details"]["reason"] == "TASK_CREDENTIAL_DISABLED"

    listed_elsewhere = build(
        tmp_path, School(), task_credential=True, task_credential_users="someone-else"
    )
    body = listed_elsewhere.client.get(
        "/api/integrations/canvas/institutions", headers=AUTH
    ).json()
    assert body["taskCredential"]["available"] is False
    assert body["taskCredential"]["reason"] == "NOT_LISTED_FOR_TASK_CREDENTIAL"

    open_here = build(tmp_path, School(), task_credential=True, task_credential_users=USER)
    body = open_here.client.get("/api/integrations/canvas/institutions", headers=AUTH).json()
    assert body["taskCredential"]["available"] is True
    assert body["taskCredential"]["ownerOnly"] is True
    assert body["taskCredential"]["idleMinutes"] == 30
    assert body["taskCredential"]["maxHours"] == 24


def test_a_pasted_credential_is_held_transiently_and_written_down_nowhere(tmp_path, keys) -> None:
    """The owner's central requirement, checked against the database rather than asserted.

    Every column of every Canvas table is searched for the pasted value. Nothing may contain it,
    and the connection row must show that no encrypted credential was written for this task.
    """
    harness = build(tmp_path, School(), task_credential=True)

    body = open_task_credential(harness)

    assert body["state"] == "PRESENT_TRANSIENTLY"
    assert body["canvasUserId"] == "4242"
    assert body["canvasName"] == "Student One"
    assert PASTED not in json.dumps(body)
    assert json.dumps(body).lower().count("token") == 0

    with harness.app.state.database.connect() as connection:
        tables = [
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'canvas%'"
            )
        ]
        assert tables
        for table in tables:
            rows = connection.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608 - own tables
            for row in rows:
                assert PASTED not in json.dumps([dict(entry) for entry in [row]], default=str)
        connection_row = connection.execute(
            "SELECT credential_key_id, credential_expires_at, saved_for_reuse "
            "FROM canvas_connections WHERE id=?",
            (body["connectionId"],),
        ).fetchone()
        # No key id and no expiry: nothing was encrypted on this task's behalf.
        assert not connection_row["credential_key_id"]
        assert connection_row["credential_expires_at"] is None
        assert int(connection_row["saved_for_reuse"]) == 0
        events = connection.execute(
            "SELECT state, reason, subject FROM canvas_credential_lifecycle_events "
            "WHERE credential_ref=?",
            (body["credentialRef"],),
        ).fetchall()
    assert [str(event["state"]) for event in events] == ["PRESENT_TRANSIENTLY"]
    assert str(events[0]["subject"]) == USER
    # The credential is in this process, and asking about it says so without returning it.
    state = harness.client.get(
        f"/api/integrations/canvas/task-credentials/{body['credentialRef']}", headers=AUTH
    )
    assert state.status_code == 200
    assert state.json()["state"] == "PRESENT_TRANSIENTLY"
    assert PASTED not in state.text


def test_the_task_credential_reads_courses_and_stops_being_usable_once_forgotten(
    tmp_path, keys
) -> None:
    """The lifecycle the owner asked for: usable for the reads it was given, then unusable."""
    harness = build(tmp_path, School(), task_credential=True)
    opened = open_task_credential(harness)
    ref = opened["credentialRef"]
    connection_id = opened["connectionId"]

    listed = harness.client.get(
        f"/api/integrations/canvas/courses?connection_id={connection_id}&credential_ref={ref}",
        headers=AUTH,
    )
    assert listed.status_code == 200, listed.text
    assert [course["id"] for course in listed.json()["courses"]] == ["560", "240"]

    forgotten = harness.client.post(
        f"/api/integrations/canvas/task-credentials/{ref}/forget",
        headers=AUTH,
        json={"reason": "canvas_reads_complete"},
    )
    assert forgotten.status_code == 200, forgotten.text
    assert forgotten.json() == {
        "credentialRef": ref,
        "state": "DESTROYED",
        "cleared": True,
        # Two reads: the active enrolments and the completed-history page, which is exactly what
        # listing the student's readable courses costs.
        "readCalls": 2,
    }

    after = harness.client.get(
        f"/api/integrations/canvas/courses?connection_id={connection_id}&credential_ref={ref}",
        headers=AUTH,
    )
    # A reference to a credential that no longer exists is answered as such, with the state in
    # the details, rather than as a school authorisation error: "this credential is gone" and
    # "the school refused the token" are different problems and the screen says different things.
    assert after.status_code == 404, after.text
    assert after.json()["error"]["code"] == "TASK_CREDENTIAL_NOT_FOUND"
    assert after.json()["error"]["details"]["state"] == "DESTROYED"

    state = harness.client.get(
        f"/api/integrations/canvas/task-credentials/{ref}", headers=AUTH
    ).json()
    assert state["state"] == "DESTROYED"
    assert state["reason"] == "canvas_reads_complete"

    with harness.app.state.database.connect() as connection:
        states = [
            str(row["state"])
            for row in connection.execute(
                "SELECT state FROM canvas_credential_lifecycle_events WHERE credential_ref=? "
                "ORDER BY created_at, id",
                (ref,),
            )
        ]
    assert states == ["PRESENT_TRANSIENTLY", "DESTROYED"]


def test_an_import_that_borrows_a_task_credential_says_so_and_reports_its_state(
    tmp_path, keys
) -> None:
    """The job records the kind and the reference; the credential stays out of the row."""
    harness = build(tmp_path, School(), task_credential=True)
    opened = open_task_credential(harness)
    ref = opened["credentialRef"]

    created = harness.client.post(
        "/api/integrations/canvas/imports",
        headers=AUTH,
        json={
            "connection_id": opened["connectionId"],
            "course_ids": ["560"],
            "credential_ref": ref,
        },
    )
    assert created.status_code == 202, created.text
    body = created.json()
    assert body["credentialKind"] == "transient_task"
    assert body["credentialState"] == "PRESENT_TRANSIENTLY"

    with harness.app.state.database.connect() as connection:
        row = connection.execute(
            "SELECT credential_ref, credential_kind, credential_state, owner_user_id "
            "FROM canvas_import_jobs WHERE id=?",
            (body["jobId"],),
        ).fetchone()
    assert str(row["credential_ref"]) == ref
    assert str(row["credential_kind"]) == "transient_task"
    assert str(row["credential_state"]) == "PRESENT_TRANSIENTLY"

    status = harness.client.get(
        f"/api/integrations/canvas/imports/{body['jobId']}", headers=AUTH
    ).json()
    assert status["credentialState"] == "PRESENT_TRANSIENTLY"
    assert status["needsCredential"] is False

    harness.client.post(
        f"/api/integrations/canvas/task-credentials/{ref}/forget",
        headers=AUTH,
        json={"reason": "canvas_reads_complete"},
    )

    after = harness.client.get(
        f"/api/integrations/canvas/imports/{body['jobId']}", headers=AUTH
    ).json()
    assert after["credentialState"] == "DESTROYED"
    # The job has not finished, so it cannot proceed without a new credential — and it says so.
    assert after["needsCredential"] is True


def test_a_job_created_with_a_reference_that_is_not_held_is_refused(tmp_path, keys) -> None:
    """A stale reference must not become a job that can never read anything."""
    harness = build(tmp_path, School(), task_credential=True)
    opened = open_task_credential(harness)

    response = harness.client.post(
        "/api/integrations/canvas/imports",
        headers=AUTH,
        json={
            "connection_id": opened["connectionId"],
            "course_ids": ["560"],
            "credential_ref": "not-a-held-ref",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_CREDENTIAL_NOT_FOUND"
    assert response.json()["error"]["details"]["state"] == "NEVER_STORED"


def test_a_pasted_credential_that_the_school_refuses_is_never_held(tmp_path, keys) -> None:
    """A token the school will not accept must fail at the door, not become a task.

    Two refusals are exercised: the school rejecting the token outright, and the school answering
    without an identity to bind. Neither may leave a held credential or a lifecycle row behind.
    """
    refused = build(tmp_path, School(profile_status=401), task_credential=True)
    response = refused.client.post(
        "/api/integrations/canvas/task-credentials",
        headers=AUTH,
        json={"institution_key": "cityu", "personal_access_token": PASTED},
    )
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "CANVAS_NEEDS_REAUTH"
    assert refused.app.state.canvas_task_credentials.live_count() == 0

    anonymous = build(tmp_path, School(profile_id=None), task_credential=True)
    response = anonymous.client.post(
        "/api/integrations/canvas/task-credentials",
        headers=AUTH,
        json={"institution_key": "cityu", "personal_access_token": PASTED},
    )
    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"] == "CANVAS_IDENTITY_UNAVAILABLE"

    for harness in (refused, anonymous):
        assert harness.app.state.canvas_task_credentials.live_count() == 0
        with harness.app.state.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM canvas_credential_lifecycle_events"
            ).fetchone()
            connections = connection.execute(
                "SELECT COUNT(*) AS total FROM canvas_connections"
            ).fetchone()
        assert int(row["total"]) == 0, "a refused token must not be recorded as a held credential"
        assert int(connections["total"]) == 0, "nothing may be stored for a token that failed"


def test_a_token_pasted_for_an_unknown_school_is_refused_before_any_read(tmp_path, keys) -> None:
    """The school comes from the registry, so an arbitrary address cannot be reached."""
    harness = build(tmp_path, School(), task_credential=True)
    for payload in (
        {"institution_key": "not-a-school", "personal_access_token": PASTED},
        {"canvas_base_url": "https://evil.example.com", "personal_access_token": PASTED},
        {"personal_access_token": PASTED},
    ):
        response = harness.client.post(
            "/api/integrations/canvas/task-credentials", headers=AUTH, json=payload
        )
        assert response.status_code in (409, 422), response.text
    assert harness.school.requests == []
    assert harness.app.state.canvas_task_credentials.live_count() == 0


def test_the_token_field_is_rejected_on_every_other_route(tmp_path, keys) -> None:
    """`extra="forbid"` is what keeps the exception to exactly one route.

    The service accepts a credential in one body, for one owner, on one path. Everywhere else a
    body carrying one is a 422 rather than a silently ignored field.
    """
    harness = build(tmp_path, School(), task_credential=True)
    for path, payload in (
        ("/api/integrations/canvas/imports", {"connection_id": "x", "course_ids": ["560"]}),
        (
            "/api/integrations/canvas/imports",
            {"connection_id": "x", "course_ids": ["560"], "personal_access_token": PASTED},
        ),
        ("/api/integrations/canvas/local-sessions", {"institution_key": "cityu"}),
        (
            "/api/integrations/canvas/local-sessions",
            {"institution_key": "cityu", "personal_access_token": PASTED},
        ),
    ):
        response = harness.client.post(path, headers=AUTH, json=payload)
        carries_credential = "personal_access_token" in payload
        if carries_credential:
            assert response.status_code == 422, f"{path} accepted a credential"
        else:
            # Without the field the request reaches the route's own logic, which is what proves
            # the credential is not merely an optional field these models quietly ignore.
            assert response.status_code != 422, f"{path} -> {response.status_code}"
