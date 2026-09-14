"""The mounted shell must be callable from the site's own origin.

The delivered `api.js` sends `credentials: 'include'`, which makes the browser
require `Access-Control-Allow-Credentials: true` on the preflight as well as the
response. Without it every call from the browser fails with an opaque
"Failed to fetch" that no server-side test would ever surface.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

UI = "/ui-extension/api/ui/v1"
ORIGIN = "http://127.0.0.1:5273"
OTHER_ORIGIN = "https://not-the-site.example"
SUBJECTS = {"Bearer token-a": "user-a"}


class FakeAuthVerifier:
    def authenticate(self, request: Request) -> str | None:
        return SUBJECTS.get(request.headers.get("authorization", ""))


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> Iterator[TestClient]:
    # The mounted extension allows the site origin; CMUI_ALLOWED_ORIGINS defaults to
    # the standalone dev ports, so set it the way a deployment does.
    monkeypatch.setenv("CMUI_ALLOWED_ORIGINS", ORIGIN)
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        admin_user_ids="user-admin",
        app_env="test",
        v3_enabled=True,
        ui_extension_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )
    application = create_app(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )
    with TestClient(application) as test_client:
        yield test_client


def _preflight(client: TestClient, path: str, method: str = "GET", origin: str = ORIGIN):
    return client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type,authorization",
        },
    )


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", f"{UI}/config"),
        ("GET", f"{UI}/me"),
        ("GET", f"{UI}/courses"),
        ("GET", f"{UI}/notifications"),
        ("PUT", f"{UI}/courses/cs3481/pin"),
        ("DELETE", f"{UI}/courses/cs3481/pin"),
        ("POST", f"{UI}/courses/cs3481/comments"),
        ("POST", f"{UI}/courses/cs3481/files"),
        ("PATCH", f"{UI}/me"),
        ("PUT", f"{UI}/courses/cs3481/layout"),
    ],
)
def test_preflight_allows_the_site_origin_with_credentials(
    client: TestClient, method: str, path: str
) -> None:
    response = _preflight(client, path, method)
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    allow_headers = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allow_headers
    assert "content-type" in allow_headers
    assert method in response.headers["access-control-allow-methods"]


def test_actual_request_carries_the_credentials_header(client: TestClient) -> None:
    response = client.get(f"{UI}/config", headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


def test_an_unlisted_origin_is_not_granted_access(client: TestClient) -> None:
    response = _preflight(client, f"{UI}/config", "GET", OTHER_ORIGIN)
    assert response.status_code == 400
    # The extension helper must not hand credentials to an origin it does not allow,
    # even though Starlette still advertises the method set on the rejection.
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers


def test_api_responses_stay_no_store(client: TestClient) -> None:
    response = client.get(f"{UI}/config", headers={"Origin": ORIGIN})
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
