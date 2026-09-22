"""Server-side Canvas OAuth2: state, code exchange, refresh and revocation.

Task B2 of the CourseJesus pack. The protocol facts here are the ones verified against
Instructure's documentation (see `docs/coursejesus/CANVAS_OAUTH_AND_SCOPES.md` §2):
`GET …/login/oauth2/auth?client_id&response_type=code&state&redirect_uri`, a callback
carrying `?code&state` or `?error&error_description&state`, `POST login/oauth2/token` with
`grant_type`/`client_id`/`client_secret`/`redirect_uri`/`code`, a response with
`access_token`/`refresh_token`/`expires_in` (3600 s in the documented example), and
revocation through `DELETE login/oauth2/token`. PKCE parameters are **not** documented for
this flow, so none are invented here.

The single most important property is that the `state` is a one-time token bound to
(signed-in subject, institution, nonce) and consumed on **both** success and failure —
otherwise a replayed callback could attach someone else's Canvas account to this account.
The second is that only the two documented token operations are non-`GET`; everything else
in this feature is a read.

Storage is injected. `InMemoryStateStore`/`InMemoryCredentialStore` are the test doubles and
the single-process default; a multi-worker deployment needs the shared implementations the
docstrings point at, which is called out rather than assumed.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from .adapter import EXPIRED_TOKEN, INVALID_RESPONSE, NETWORK, CanvasReadError
from .registry import Institution, InstitutionConnectionRegistry

AUTHORIZE_PATH = "/login/oauth2/auth"
TOKEN_PATH = "/login/oauth2/token"
GRANT_AUTHORIZATION_CODE = "authorization_code"
GRANT_REFRESH_TOKEN = "refresh_token"
STATE_TTL_SECONDS = 600
# A credential issued this recently is treated as "just refreshed": a second worker that
# waited on the per-connection lock reuses it instead of asking for another token.
REFRESH_REUSE_WINDOW_SECONDS = 300


class OAuthError(RuntimeError):
    """A refusal with a stable reason code."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class AuthorizationState:
    """One pending authorisation, bound to the user who started it."""

    state: str
    subject: str
    institution_key: str
    origin: str
    created_at: float
    return_path: str = "/app/canvas/import"
    consumed: bool = False

    def is_expired(self, now: float, ttl: int = STATE_TTL_SECONDS) -> bool:
        return (now - self.created_at) > ttl


class StateStore(Protocol):
    """One-time, short-lived authorisation states."""

    def issue(
        self, subject: str, institution: Institution, *, return_path: str = ""
    ) -> AuthorizationState: ...

    def consume(self, state: str, *, now: float | None = None) -> AuthorizationState: ...


class InMemoryStateStore:
    """Process-local state store.

    Adequate for a single-worker deployment and for tests. A multi-worker deployment must
    back this with shared storage (the same table that will hold connections), because a
    callback may land on a different worker than the one that issued the state.
    """

    def __init__(
        self, *, ttl: int = STATE_TTL_SECONDS, now: Callable[[], float] = time.time
    ) -> None:
        self._ttl = ttl
        self._now = now
        self._states: dict[str, AuthorizationState] = {}
        self._lock = threading.Lock()

    def issue(
        self, subject: str, institution: Institution, *, return_path: str = ""
    ) -> AuthorizationState:
        if not subject:
            raise OAuthError("NO_SUBJECT", "a signed-in user is required to start an authorisation")
        state = secrets.token_urlsafe(32)
        record = AuthorizationState(
            state=state,
            subject=subject,
            institution_key=institution.key,
            origin=institution.origin,
            created_at=self._now(),
            return_path=return_path or "/app/canvas/import",
        )
        with self._lock:
            self._states[state] = record
        return record

    def consume(self, state: str, *, now: float | None = None) -> AuthorizationState:
        """Validate and consume a state. Always consumes, even when it then refuses."""
        moment = self._now() if now is None else now
        with self._lock:
            record = self._states.pop(state, None)
        if record is None:
            raise OAuthError(
                "UNKNOWN_STATE", "this authorisation was already used or never existed"
            )
        if record.is_expired(moment, self._ttl):
            raise OAuthError("EXPIRED_STATE", "this authorisation expired before it was completed")
        record = AuthorizationState(**{**record.__dict__, "consumed": True})
        return record


@dataclass(frozen=True)
class TokenSet:
    """Tokens, held only long enough to store them. Never logged, never returned to a UI."""

    access_token: str
    refresh_token: str
    expires_in: int
    scopes: tuple[str, ...] = ()

    @property
    def expires_at(self) -> float:
        return time.time() + max(self.expires_in, 0)

    def __repr__(self) -> str:  # pragma: no cover - defence in depth
        return (
            "TokenSet(access_token=<redacted>, refresh_token=<redacted>, "
            f"expires_in={self.expires_in})"
        )


@dataclass(frozen=True)
class StoredCredential:
    """What the credential store persists: ciphertext plus the key that can open it."""

    connection_id: str
    key_id: str
    ciphertext: bytes
    expires_at: float
    scopes: tuple[str, ...] = ()


class CredentialStore(Protocol):
    """Authenticated-encryption storage with a key id, separate from the database."""

    def save(self, connection_id: str, tokens: TokenSet) -> StoredCredential: ...

    def load_token(self, connection_id: str) -> str | None: ...

    def load_expiry(self, connection_id: str) -> float | None: ...

    def clear(self, connection_id: str) -> None: ...


class InMemoryCredentialStore:
    """Test double for the credential store.

    The production implementation must encrypt with a key held outside the database and
    record a `key_id` so a rotation can be performed without re-reading every token's
    plaintext. This class exists so the *flow* can be tested; it is not that implementation.
    """

    def __init__(self) -> None:
        self._tokens: dict[str, TokenSet] = {}
        self._lock = threading.Lock()

    def save(self, connection_id: str, tokens: TokenSet) -> StoredCredential:
        with self._lock:
            self._tokens[connection_id] = tokens
        return StoredCredential(
            connection_id=connection_id,
            key_id="test-key-1",
            ciphertext=b"<encrypted>",
            expires_at=tokens.expires_at,
            scopes=tokens.scopes,
        )

    def load_token(self, connection_id: str) -> str | None:
        with self._lock:
            tokens = self._tokens.get(connection_id)
        return tokens.access_token if tokens else None

    def load_expiry(self, connection_id: str) -> float | None:
        with self._lock:
            tokens = self._tokens.get(connection_id)
        return tokens.expires_at if tokens else None

    def clear(self, connection_id: str) -> None:
        with self._lock:
            self._tokens.pop(connection_id, None)


@dataclass(frozen=True)
class Connection:
    """A user's link to one Canvas account.

    The identity binding is `(subject, origin, canvas_user_id)`: names and e-mails are
    display-only and never merge two accounts.
    """

    connection_id: str
    subject: str
    institution_key: str
    origin: str
    canvas_user_id: str
    canvas_name: str = ""
    scopes: tuple[str, ...] = ()
    saved_for_reuse: bool = False
    created_at: float = field(default_factory=time.time)

    def matches_account(self, origin: str, canvas_user_id: str) -> bool:
        return self.origin == origin and self.canvas_user_id == str(canvas_user_id)


class CanvasOAuthClient:
    """The authorisation-code flow for one institution.

    Nothing here is reachable from the model or from a front-end `GET`: the caller is the
    server-side route that a signed-in user triggers, and the only non-`GET` requests are the
    two documented token operations.
    """

    def __init__(
        self,
        *,
        registry: InstitutionConnectionRegistry,
        state_store: StateStore,
        credential_store: CredentialStore,
        client: httpx.Client | None = None,
        refresh_locks: dict[str, threading.Lock] | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.registry = registry
        self.states = state_store
        self.credentials = credential_store
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=False)
        # One lock per connection: two workers must not refresh the same connection
        # concurrently and overwrite each other's freshly issued refresh token.
        self._refresh_locks = refresh_locks if refresh_locks is not None else {}
        self._locks_guard = threading.Lock()
        self._now = now

    # ------------------------------------------------------------------ step 1
    def start(self, subject: str, institution_key: str, *, return_path: str = "") -> str:
        """Build the school authorisation URL for a signed-in user."""
        institution = self.registry.by_key(institution_key)
        record = self.states.issue(subject, institution, return_path=return_path)
        query = urlencode(
            {
                "client_id": self._client_id(institution),
                "response_type": "code",
                "state": record.state,
                "redirect_uri": institution.callback_url,
            }
        )
        return f"{institution.origin}{AUTHORIZE_PATH}?{query}"

    def _client_id(self, institution: Institution) -> str:
        import os

        client_id = os.environ.get(institution.client_id_ref)
        if not client_id:
            raise OAuthError(
                "NOT_CONFIGURED",
                f"{institution.label} has no Developer Key configured; no authorisation can start",
            )
        return client_id

    def _client_secret(self, institution: Institution) -> str:
        import os

        secret = os.environ.get(institution.client_secret_ref)
        if not secret:
            raise OAuthError(
                "NOT_CONFIGURED", f"{institution.label} has no client secret configured"
            )
        return secret

    # ------------------------------------------------------------------ step 2
    def complete(self, params: dict[str, str]) -> CompletedAuthorization:
        """Handle the callback: validate the state, then exchange the code.

        The state is consumed before anything else happens, so a denial and a success both
        burn it, and an unknown or expired state is refused without touching the code.
        """
        state = params.get("state", "")
        record = self.states.consume(state)
        institution = self.registry.by_key(record.institution_key)
        if error := params.get("error"):
            # A denial is a normal outcome: the user declined, and it is reported as such
            # rather than as a failure of the product.
            raise OAuthError("ACCESS_DENIED", params.get("error_description") or error)
        code = params.get("code", "")
        if not code:
            raise OAuthError("MISSING_CODE", "the callback carried no authorization code")
        tokens = self._token_request(
            institution,
            {
                "grant_type": GRANT_AUTHORIZATION_CODE,
                "client_id": self._client_id(institution),
                "client_secret": self._client_secret(institution),
                "redirect_uri": institution.callback_url,
                "code": code,
            },
        )
        return CompletedAuthorization(state=record, institution=institution, tokens=tokens)

    # -------------------------------------------------------------- token calls
    def _token_request(self, institution: Institution, payload: dict[str, str]) -> TokenSet:
        """The only non-GET request in the Canvas integration."""
        try:
            response = self._client.post(f"{institution.origin}{TOKEN_PATH}", data=payload)
        except httpx.HTTPError as error:
            raise CanvasReadError(NETWORK, f"{type(error).__name__}: {error}") from error
        if response.status_code >= 400:
            raise CanvasReadError(
                EXPIRED_TOKEN if response.status_code in (400, 401) else INVALID_RESPONSE,
                f"token endpoint answered {response.status_code}",
                status=response.status_code,
            )
        try:
            body: Any = response.json()
        except ValueError as error:
            raise CanvasReadError(
                INVALID_RESPONSE, f"token endpoint returned non-JSON: {error}"
            ) from error
        if not isinstance(body, dict) or not body.get("access_token"):
            raise CanvasReadError(INVALID_RESPONSE, "token response carried no access_token")
        expires = body.get("expires_in", 0)
        scopes = body.get("scope")
        return TokenSet(
            access_token=str(body["access_token"]),
            refresh_token=str(body.get("refresh_token", "")),
            expires_in=int(expires) if str(expires).isdigit() else 0,
            scopes=tuple(scopes.split()) if isinstance(scopes, str) else (),
        )

    def refresh(self, connection: Connection, *, force: bool = False) -> TokenSet | None:
        """Renew the access token, at most once per connection at a time.

        Returns `None` when no refresh was performed — either the stored token is still
        valid, or another worker renewed it while this caller waited for the lock. That
        second case is the point: holding a per-connection lock and then refreshing anyway
        would issue two tokens and let them overwrite each other, which is exactly the
        failure the pack names. Callers read the stored token when this returns `None`.
        """
        with self._lock_for(connection.connection_id):
            if not force:
                return None
            expiry = self.credentials.load_expiry(connection.connection_id)
            clock = time.time
            if expiry is not None and (expiry - clock()) > REFRESH_REUSE_WINDOW_SECONDS:
                # Someone else just refreshed: reuse it rather than issuing a second token.
                return None
            institution = self.registry.by_key(connection.institution_key)
            refresh_token = self._refresh_token(connection.connection_id)
            if not refresh_token:
                raise CanvasReadError(
                    EXPIRED_TOKEN, "no refresh token is stored for this connection"
                )
            tokens = self._token_request(
                institution,
                {
                    "grant_type": GRANT_REFRESH_TOKEN,
                    "client_id": self._client_id(institution),
                    "client_secret": self._client_secret(institution),
                    "redirect_uri": institution.callback_url,
                    "refresh_token": refresh_token,
                },
            )
            self.credentials.save(connection.connection_id, tokens)
            return tokens

    def _refresh_token(self, connection_id: str) -> str | None:
        loader = getattr(self.credentials, "load_refresh_token", None)
        return loader(connection_id) if callable(loader) else None

    def _lock_for(self, connection_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._refresh_locks.setdefault(connection_id, threading.Lock())

    def revoke(self, connection: Connection) -> bool:
        """Revoke this application's token for this connection (user-initiated)."""
        institution = self.registry.by_key(connection.institution_key)
        token = self.credentials.load_token(connection.connection_id)
        if not token:
            self.credentials.clear(connection.connection_id)
            return False
        try:
            response = self._client.request(
                "DELETE",
                f"{institution.origin}{TOKEN_PATH}",
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as error:
            raise CanvasReadError(NETWORK, f"{type(error).__name__}: {error}") from error
        # The local credential is cleared regardless: refusing to forget a token because the
        # school's endpoint was unreachable would leave a disconnect that does not disconnect.
        self.credentials.clear(connection.connection_id)
        return response.status_code < 400


@dataclass(frozen=True)
class CompletedAuthorization:
    """A successful callback, before the connection is bound to an identity."""

    state: AuthorizationState
    institution: Institution
    tokens: TokenSet

    def bind(
        self,
        *,
        canvas_user_id: str,
        canvas_name: str = "",
        connection_id: str,
        credential_store: CredentialStore,
        previous: Connection | None = None,
        confirmed_replacement: bool = False,
    ) -> Connection:
        """Bind the tokens to an identity, refusing a silent account replacement.

        If this connection already pointed at a different Canvas account, the caller must
        show that identity and pass `confirmed_replacement=True`; otherwise one person's
        courses would be silently filed under another.
        """
        if (
            previous is not None
            and not previous.matches_account(self.institution.origin, canvas_user_id)
            and not confirmed_replacement
        ):
            raise OAuthError(
                "ACCOUNT_REPLACEMENT_NOT_CONFIRMED",
                f"this connection is bound to Canvas user {previous.canvas_user_id!r}; "
                f"attaching {canvas_user_id!r} needs explicit confirmation",
            )
        credential_store.save(connection_id, self.tokens)
        return Connection(
            connection_id=connection_id,
            subject=self.state.subject,
            institution_key=self.institution.key,
            origin=self.institution.origin,
            canvas_user_id=str(canvas_user_id),
            canvas_name=canvas_name,
            scopes=self.tokens.scopes,
        )


def callback_matches_institution(connection: Connection, institution: Institution) -> bool:
    """A connection may only be used against the institution that issued it."""
    return connection.origin == institution.origin and connection.institution_key == institution.key


def token_provider_for(
    connection: Connection,
    client: CanvasOAuthClient,
    *,
    refresh_margin_seconds: int = 120,
    now: Callable[[], float] = time.time,
) -> Callable[[], str | None]:
    """A `token_provider` for `CanvasReadAdapter` that refreshes only when it must.

    A token that is present and more than `refresh_margin_seconds` from expiry is used as
    is. Otherwise a refresh is attempted, and when that returns `None` (another worker just
    renewed the credential) the freshly stored token is read instead.
    """

    def provider() -> str | None:
        token = client.credentials.load_token(connection.connection_id)
        expiry = client.credentials.load_expiry(connection.connection_id)
        if token and (expiry is None or (expiry - now()) > refresh_margin_seconds):
            return token
        client.refresh(connection, force=True)
        return client.credentials.load_token(connection.connection_id)

    return provider


def scopes_for(institutions: Sequence[Institution]) -> dict[str, tuple[str, ...]]:
    """Granted scopes per institution, for display. Never includes a token."""
    return {institution.key: institution.scopes for institution in institutions}
