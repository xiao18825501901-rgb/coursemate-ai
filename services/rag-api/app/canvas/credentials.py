"""Authenticated-encryption storage for Canvas credentials, kept out of the database.

The task pack is specific about this: an access/refresh token must be stored with a key id
under authenticated encryption, *separate from the database*, and the import job must reference
only a `connection_id`. A dump of the application database therefore cannot contain a Canvas
token, and neither can a log line, an error report or a backup of the DB.

Three properties are the reason this is a module:

1. **Real authenticated encryption.** AES-256-GCM (`cryptography`, already a dependency) with a
   random 96-bit nonce per write and the connection id plus key id as associated data, so a
   ciphertext cannot be moved to another connection or another key generation without failing
   to open. Nothing here hand-rolls a construction.
2. **The key is never in the database and never in the response path.** It comes from
   `CANVAS_CREDENTIAL_KEY` (base64, 32 bytes) or a key file outside the repository. If neither
   is present the store reports itself unavailable and the integration says so — it does *not*
   silently fall back to plaintext, which is the failure this whole module exists to prevent.
3. **A rotation is visible.** Every record carries the `key_id` (a digest of the key, not the
   key), so a store written under an old key is detectable instead of silently unreadable.

Files are written with owner-only permissions where the platform supports it, via a temporary
file and an atomic replace, so a crash cannot leave a half-written credential.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import os
import pathlib
import secrets
import tempfile
import threading
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import Settings

from .oauth import CredentialStore, StoredCredential, TokenSet

LOGGER = logging.getLogger(__name__)

KEY_BYTES = 32
NONCE_BYTES = 12
# The envelope version, so a future change to the record shape is a migration rather than a
# guess about what an existing file contains.
ENVELOPE_VERSION = 1


class CredentialStoreUnavailable(RuntimeError):
    """No key material: the integration must report itself unconfigured, not store plaintext."""


@dataclass(frozen=True)
class _Envelope:
    version: int
    key_id: str
    connection_id: str
    nonce: bytes
    ciphertext: bytes
    expires_at: float
    scopes: tuple[str, ...]


def key_id_for(key: bytes) -> str:
    """A short, non-secret name for a key generation.

    A digest of the key is safe to record and compare; it says which key wrote a record
    without being usable to open one.
    """
    return hashlib.sha256(key).hexdigest()[:16]


def decode_key(raw: str) -> bytes:
    """Decode a configured key, refusing anything that is not exactly 32 bytes."""
    try:
        key = base64.urlsafe_b64decode(raw.strip() + "=" * (-len(raw.strip()) % 4))
    except (ValueError, TypeError) as error:
        raise CredentialStoreUnavailable("CANVAS_CREDENTIAL_KEY is not valid base64") from error
    if len(key) != KEY_BYTES:
        raise CredentialStoreUnavailable(
            f"CANVAS_CREDENTIAL_KEY must decode to {KEY_BYTES} bytes, got {len(key)}"
        )
    return key


def generate_key() -> str:
    """A fresh key, for an operator to place in a protected environment variable."""
    return base64.urlsafe_b64encode(secrets.token_bytes(KEY_BYTES)).decode("ascii")


class FileCredentialStore:
    """`CredentialStore` backed by one encrypted file per connection.

    Deliberately not a database table: the pack requires the credential to live apart from the
    rows it authorises, so a restored database alone is not enough to reach a school.
    """

    def __init__(self, directory: pathlib.Path, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise CredentialStoreUnavailable(f"the key must be {KEY_BYTES} bytes")
        self.directory = pathlib.Path(directory)
        self._key = key
        self.key_id = key_id_for(key)
        self._aes = AESGCM(key)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ protocol
    def save(self, connection_id: str, tokens: TokenSet) -> StoredCredential:
        envelope = _Envelope(
            version=ENVELOPE_VERSION,
            key_id=self.key_id,
            connection_id=connection_id,
            nonce=secrets.token_bytes(NONCE_BYTES),
            ciphertext=b"",
            expires_at=tokens.expires_at,
            scopes=tokens.scopes,
        )
        payload = json.dumps(
            {"access_token": tokens.access_token, "refresh_token": tokens.refresh_token},
            separators=(",", ":"),
        ).encode("utf-8")
        ciphertext = self._aes.encrypt(envelope.nonce, payload, self._associated_data(envelope))
        record = {
            "version": ENVELOPE_VERSION,
            "key_id": self.key_id,
            "connection_id": connection_id,
            "nonce": base64.b64encode(envelope.nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "expires_at": tokens.expires_at,
            "scopes": list(tokens.scopes),
        }
        self._write(self._path(connection_id), record)
        return StoredCredential(
            connection_id=connection_id,
            key_id=self.key_id,
            ciphertext=ciphertext,
            expires_at=tokens.expires_at,
            scopes=tokens.scopes,
        )

    def load_token(self, connection_id: str) -> str | None:
        opened = self._open(connection_id)
        if opened is None:
            return None
        return opened.access_token

    def load_expiry(self, connection_id: str) -> float | None:
        envelope = self._read(connection_id)
        return envelope.expires_at if envelope is not None else None

    def clear(self, connection_id: str) -> None:
        with self._lock:
            try:
                self._path(connection_id).unlink(missing_ok=True)
            except OSError as error:  # pragma: no cover - a leftover file is not a security bug
                LOGGER.warning("could not remove a Canvas credential file: %s", error)

    # ------------------------------------------------------------------ internals
    def _path(self, connection_id: str) -> pathlib.Path:
        # The filename is a digest of the connection id: no Canvas id, no subject and no
        # school name appears in a directory listing.
        digest = hashlib.sha256(connection_id.encode("utf-8")).hexdigest()[:32]
        return self.directory / f"{digest}.canvascred"

    def _associated_data(self, envelope: _Envelope) -> bytes:
        """Bind a ciphertext to its record: a file moved between connections will not open."""
        return f"{envelope.version}:{envelope.key_id}:{envelope.connection_id}".encode()

    def _write(self, path: pathlib.Path, record: dict[str, object]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._restrict(self.directory, 0o700)
        with self._lock:
            descriptor, name = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
            temporary = pathlib.Path(name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(record, handle, separators=(",", ":"))
                    handle.flush()
                    os.fsync(handle.fileno())
                self._restrict(temporary, 0o600)
                os.replace(temporary, path)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise

    def _read(self, connection_id: str) -> _Envelope | None:
        path = self._path(connection_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            # A corrupt record is treated as "no credential": the user reconnects. It is never
            # treated as "unencrypted": nothing here reads a plaintext token.
            LOGGER.warning("unreadable Canvas credential record: %s", type(error).__name__)
            return None
        if not isinstance(raw, dict) or raw.get("version") != ENVELOPE_VERSION:
            return None
        try:
            return _Envelope(
                version=ENVELOPE_VERSION,
                key_id=str(raw["key_id"]),
                connection_id=str(raw["connection_id"]),
                nonce=base64.b64decode(str(raw["nonce"])),
                ciphertext=base64.b64decode(str(raw["ciphertext"])),
                expires_at=float(raw["expires_at"]),
                scopes=tuple(str(scope) for scope in raw.get("scopes") or ()),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _open(self, connection_id: str) -> _TokenPair | None:
        envelope = self._read(connection_id)
        if envelope is None:
            return None
        if envelope.connection_id != connection_id:
            # The record names a different connection than the one asked for. The associated data
            # binds the ciphertext to the connection it was written for, so this file was copied
            # or renamed: refusing is the only answer that cannot hand over another
            # connection's credential.
            LOGGER.warning("Canvas credential record does not belong to the requested connection")
            return None
        if envelope.key_id != self.key_id:
            # Written under a different key generation. Reporting "no token" makes the user
            # reconnect, which is the honest outcome; the alternative would be a silent
            # refusal that looks like a school outage.
            LOGGER.warning(
                "Canvas credential for key %s cannot be opened with key %s",
                envelope.key_id,
                self.key_id,
            )
            return None
        try:
            payload = self._aes.decrypt(
                envelope.nonce, envelope.ciphertext, self._associated_data(envelope)
            )
        except InvalidTag:
            LOGGER.warning("Canvas credential failed authentication and was ignored")
            return None
        try:
            body = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):  # pragma: no cover - authenticated plaintext
            return None
        if not isinstance(body, dict):
            return None
        access = body.get("access_token")
        refresh = body.get("refresh_token")
        if not isinstance(access, str) or not access:
            return None
        return _TokenPair(
            access_token=access, refresh_token=refresh if isinstance(refresh, str) else ""
        )

    @staticmethod
    def _restrict(path: pathlib.Path, mode: int) -> None:
        """Owner-only permissions where the platform enforces them (Windows ACLs are separate)."""
        with contextlib.suppress(OSError, NotImplementedError):
            path.chmod(mode)


@dataclass(frozen=True)
class _TokenPair:
    access_token: str
    refresh_token: str = ""

    def __repr__(self) -> str:  # pragma: no cover - defence in depth
        return "_TokenPair(access_token=<redacted>, refresh_token=<redacted>)"


def _key_material(value: object) -> str:
    """The configured key as text, accepting either a `SecretStr` or a plain string.

    Configuration is normally a `SecretStr`, but a caller that assembles settings another way
    must not make the integration crash on its way to reporting "not configured".
    """
    if value is None:
        return ""
    getter = getattr(value, "get_secret_value", None)
    return str(getter()) if callable(getter) else str(value)


def credential_store_from_settings(settings: Settings) -> FileCredentialStore | None:
    """Build the store from configuration, or return None when no key material exists.

    Returning None is the point: a deployment with no key gets the "school connection is not
    open yet" state rather than a plaintext token file or a hard crash on the import screen.
    """
    raw = _key_material(settings.canvas_credential_key)
    if not raw:
        return None
    return FileCredentialStore(settings.canvas_credential_dir, decode_key(raw))


def store_is_usable(store: CredentialStore | None) -> bool:
    """True when a credential can actually be persisted and read back."""
    if store is None:
        return False
    try:
        probe = "probe-connection"
        store.save(
            probe,
            TokenSet(access_token="probe", refresh_token="probe", expires_in=60),
        )
        ok = store.load_token(probe) == "probe"
        store.clear(probe)
    except Exception:  # noqa: BLE001 - a broken store must read as unusable, never as ready
        LOGGER.exception("the Canvas credential store failed a write probe")
        return False
    return ok
