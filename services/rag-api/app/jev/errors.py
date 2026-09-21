"""Typed errors for the Jev semantic-decision layer.

The four codes required by the governing plan are the concrete subclasses
below; callers catch :class:`JevError` (or a specific subclass) and fall back
to the deterministic path. Nothing in this module ever retries or writes state.
"""

from __future__ import annotations


class JevError(Exception):
    """Base class for every Jev decision error."""

    code = "JEV_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class JevNotConfiguredError(JevError):
    """No live TypeSafe credential/transport is configured."""

    code = "JEV_NOT_CONFIGURED"


class JevUnavailableError(JevError):
    """The transport could not complete the call (network/SDK failure)."""

    code = "JEV_UNAVAILABLE"


class JevTimeoutError(JevError):
    """The call exceeded the configured timeout bound."""

    code = "JEV_TIMEOUT"


class JevInvalidResponseError(JevError):
    """The transport returned a response the catalog definition cannot accept."""

    code = "JEV_INVALID_RESPONSE"


class JevRequestError(JevError):
    """The request itself violated a bound (size/batch/concurrency/cancel)."""

    code = "JEV_INVALID_REQUEST"
