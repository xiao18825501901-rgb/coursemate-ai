"""The integrated UI extension must serve a resolvable OpenAPI schema.

Release blocker regression: `GET /ui-extension/openapi.json` used to answer
HTTP 500 with a Pydantic ``class-not-fully-defined`` error for
``ForwardRef('JSONResponse')``. The legacy-history routes are prepended to the
sub-application's routes and their return annotations must resolve inside the
sub-application's own OpenAPI generation.

These tests drive the same integrated host configuration as the legacy-history
tests (real V3 tables + mounted extension + fake auth verifier).
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
SUBJECTS = {
    "Bearer token-a": "user-a",
    "Bearer token-b": "user-b",
    "Bearer admin-token": "user-admin",
}


class FakeAuthVerifier:
    def authenticate(self, request: Request) -> str | None:
        return SUBJECTS.get(request.headers.get("authorization", ""))


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
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


@pytest.fixture
def schema(client: TestClient) -> dict:
    response = client.get("/ui-extension/openapi.json")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert isinstance(body, dict)
    return body


def test_openapi_schema_is_served_as_valid_openapi_json(schema: dict) -> None:
    assert schema.get("openapi", "").startswith("3.")
    assert isinstance(schema.get("info"), dict)
    paths = schema.get("paths")
    assert isinstance(paths, dict) and paths
    # Every path must be a well-formed operation map, not a schema-generation stub.
    for path, operations in paths.items():
        assert path.startswith("/"), path
        assert isinstance(operations, dict), path


def test_openapi_schema_keeps_the_real_ui_routes(schema: dict) -> None:
    paths = schema["paths"]
    for expected in (
        "/api/ui/v1/config",
        "/api/ui/v1/me",
        "/api/ui/v1/courses",
        "/api/ui/v1/courses/{cid}",
        "/api/ui/v1/tasks",
        "/api/ui/v1/conversations",
        "/api/ui/v1/conversations/{conv_id}",
        "/api/ui/v1/conversations/{conv_id}/runs",
        "/api/ui/v1/runs/{rid}",
        "/api/ui/v1/courses/{cid}/knowledge",
        "/api/ui/v1/courses/{cid}/bridges",
        "/health",
    ):
        assert expected in paths, f"missing UI route in OpenAPI schema: {expected}"


def test_openapi_schema_includes_the_legacy_history_routes(schema: dict) -> None:
    paths = schema["paths"]
    legacy_list = "/api/ui/v1/courses/{course_id}/legacy-conversations"
    legacy_detail = "/api/ui/v1/courses/{course_id}/legacy-conversations/{conversation_id}"
    assert legacy_list in paths
    assert legacy_detail in paths
    assert "get" in paths[legacy_list]
    assert "get" in paths[legacy_detail]


def test_legacy_history_auth_is_unchanged(client: TestClient) -> None:
    # Same fail-closed behavior the release gate already asserted: no
    # verified session -> 401, never a schema error leaking through.
    response = client.get(f"{UI}/courses/cs3481/legacy-conversations")
    assert response.status_code == 401


def test_openapi_schema_survives_repeated_generation(client: TestClient) -> None:
    # Schema generation is cached on the sub-app; a second hit must stay 200
    # and identical (no one-shot fallback or mutated schema object).
    first = client.get("/ui-extension/openapi.json")
    second = client.get("/ui-extension/openapi.json")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
