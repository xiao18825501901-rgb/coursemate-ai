"""Service-token auth: constant-time comparison, no browser identity."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.auth import ServiceTokenVerifier, build_verifier


def _request(headers: dict[str, str]) -> MagicMock:
    req = MagicMock()
    req.headers = headers
    return req


def test_bearer_token_accepted() -> None:
    v = ServiceTokenVerifier("secret")
    assert v.verify(_request({"authorization": "Bearer secret"})) is True


def test_wrong_token_rejected() -> None:
    v = ServiceTokenVerifier("secret")
    assert v.verify(_request({"authorization": "Bearer wrong"})) is False


def test_explicit_header_accepted() -> None:
    v = ServiceTokenVerifier("secret")
    assert v.verify(_request({"x-laya-service-token": "secret"})) is True


def test_missing_token_rejected() -> None:
    v = ServiceTokenVerifier("secret")
    assert v.verify(_request({})) is False


def test_unset_token_is_noop() -> None:
    v = build_verifier(None)
    assert v.verify(_request({})) is True


def test_browser_clerk_token_not_accepted() -> None:
    # A Clerk session token must not authenticate this service.
    v = ServiceTokenVerifier("secret")
    assert v.verify(_request({"authorization": "Bearer eyJhbGciOiJSUzI1NiJ9.clerk"}) ) is False
