"""Typed errors for the Laya semantic-decision adapter.

The Laya layer never retries and never falls back to Jev or Qwen: every failure is
surfaced as a typed :class:`LayaError` that :class:`~app.laya.adapter.LayaGateway`
maps to a deterministic fallback with a ``fallback_reason`` string.
"""

from __future__ import annotations


class LayaError(Exception):
    """Base class for every Laya decision error."""

    code = "LAYA_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class LayaUnavailableError(LayaError):
    """The self-hosted Laya inference service could not be reached or returned an error."""

    code = "LAYA_UNAVAILABLE"


class LayaTimeoutError(LayaError):
    """The Laya inference call exceeded its timeout."""

    code = "LAYA_TIMEOUT"


class LayaInvalidResponseError(LayaError):
    """The Laya service returned a response that fails the catalog validation rules."""

    code = "LAYA_INVALID_RESPONSE"


class LayaOversizedError(LayaError):
    """The request exceeded a client-side size bound and was never sent."""

    code = "LAYA_OVERSIZED"


class LayaUnsupportedError(LayaError):
    """The request used a question kind or shape Laya cannot serve."""

    code = "LAYA_UNSUPPORTED"
