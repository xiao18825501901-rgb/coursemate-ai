"""Service-credential auth for the CourseMate-internal Laya API.

The only accepted credential is a pre-shared service token read from
``LAYA_SERVICE_TOKEN`` (never a browser Clerk token). The token is compared with
a constant-time primitive. In the fake backend (local dev/test) an unset token
is allowed and auth is a no-op; the real backend refuses to start without one
(see Settings).

mTLS is terminated at the private reverse proxy in front of this service (see
deploy/laya for the nginx sketch); this module is intentionally narrow so the
service never depends on a browser/Clerk identity.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Protocol

from fastapi import Request


class AuthVerifier(Protocol):
    def verify(self, request: Request) -> bool: ...


class ServiceTokenVerifier:
    """Constant-time comparison against the pre-shared service token."""

    def __init__(self, token: str | None) -> None:
        self._token = token

    def verify(self, request: Request) -> bool:
        if self._token is None:
            return True  # fake/test backend only; real backend refuses to start unset
        supplied = self._extract(request)
        if supplied is None:
            return False
        return hmac.compare_digest(supplied.encode("utf-8"), self._token.encode("utf-8"))

    @staticmethod
    def _extract(request: Request) -> str | None:
        authz = request.headers.get("authorization")
        if authz and authz.startswith("Bearer "):
            token = authz[len("Bearer ") :].strip()
            return token or None
        # Alternative explicit header, for clients that cannot set Authorization.
        return request.headers.get("x-laya-service-token")


@dataclass(frozen=True)
class _NoopVerifier:
    def verify(self, request: Request) -> bool:  # noqa: ARG002
        return True


def build_verifier(token: str | None) -> AuthVerifier:
    if token is None:
        return _NoopVerifier()
    return ServiceTokenVerifier(token)
