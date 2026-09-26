from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.auth import ClerkAuthVerifier
from app.config import Settings
from app.main import create_app

PRIMARY_ORIGIN = "https://qqttai.com"
NEW_ORIGIN = "https://coursejesus.com"
UNKNOWN_ORIGIN = "https://evil.example"


class FakeAuthVerifier:
    def authenticate(self, request: Request) -> str | None:
        return None


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_path": tmp_path / "rag.sqlite3",
        "upload_dir": tmp_path / "uploads",
        "app_env": "test",
        "rag_provider_mode": "deterministic",
        "web_origin": PRIMARY_ORIGIN,
        "web_allowed_origins": "",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def _preflight(client: TestClient, origin: str):
    return client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )


def test_web_allowed_origins_falls_back_to_primary_origin(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    assert settings.web_allowed_origin_tuple == (PRIMARY_ORIGIN,)


def test_web_allowed_origins_loads_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WEB_ORIGIN", PRIMARY_ORIGIN)
    monkeypatch.setenv("WEB_ALLOWED_ORIGINS", f"{PRIMARY_ORIGIN},{NEW_ORIGIN}")

    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        app_env="test",
        rag_provider_mode="deterministic",
    )

    assert settings.web_allowed_origin_tuple == (PRIMARY_ORIGIN, NEW_ORIGIN)


def test_web_allowed_origins_trims_deduplicates_and_keeps_primary(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        web_allowed_origins=(
            f" {NEW_ORIGIN},, {NEW_ORIGIN} "
        ),
    )

    assert settings.web_allowed_origin_tuple == (NEW_ORIGIN, PRIMARY_ORIGIN)


def test_rag_cors_accepts_both_configured_origins_and_rejects_unknown(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        web_allowed_origins=f"{PRIMARY_ORIGIN},{NEW_ORIGIN}",
    )
    app = create_app(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )

    with TestClient(app) as client:
        primary = _preflight(client, PRIMARY_ORIGIN)
        new = _preflight(client, NEW_ORIGIN)
        unknown = _preflight(client, UNKNOWN_ORIGIN)

    assert primary.status_code == 200
    assert primary.headers["access-control-allow-origin"] == PRIMARY_ORIGIN
    assert new.status_code == 200
    assert new.headers["access-control-allow-origin"] == NEW_ORIGIN
    assert unknown.status_code == 400
    assert "access-control-allow-origin" not in unknown.headers


def test_rag_cors_fallback_allows_only_primary_origin(tmp_path: Path) -> None:
    app = create_app(
        settings=_settings(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )

    with TestClient(app) as client:
        primary = _preflight(client, PRIMARY_ORIGIN)
        new = _preflight(client, NEW_ORIGIN)

    assert primary.status_code == 200
    assert primary.headers["access-control-allow-origin"] == PRIMARY_ORIGIN
    assert new.status_code == 400
    assert "access-control-allow-origin" not in new.headers


def test_clerk_authorized_parties_use_all_allowed_origins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def capture_options(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("app.auth.AuthenticateRequestOptions", capture_options)
    settings = _settings(
        tmp_path,
        web_allowed_origins=f"{PRIMARY_ORIGIN},{NEW_ORIGIN}",
        clerk_jwt_key="test-public-key",
    )

    ClerkAuthVerifier(settings)

    assert captured["authorized_parties"] == [PRIMARY_ORIGIN, NEW_ORIGIN]


def test_production_rejects_non_https_non_loopback_origin(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        _settings(
            tmp_path,
            app_env="production",
            web_allowed_origins="http://public.example",
        )
