"""The Canvas credential store: real authenticated encryption, key ids, and no plaintext.

The task pack requires the access/refresh token to be stored under authenticated encryption with
a key id and kept apart from the database. These tests pin exactly that, and they are written so
that a weaker implementation fails them: the file on disk is inspected for the token, a second
key is shown not to open the record, a record moved to another connection is shown not to open,
and a corrupt file is shown to read as "no credential" rather than as a crash or as plaintext.
"""

from __future__ import annotations

import base64
import json
import pathlib

import pytest

from app.canvas.credentials import (
    KEY_BYTES,
    CredentialStoreUnavailable,
    FileCredentialStore,
    credential_store_from_settings,
    decode_key,
    generate_key,
    key_id_for,
    store_is_usable,
)
from app.canvas.oauth import InMemoryCredentialStore, TokenSet
from app.config import Settings

ACCESS = "canvas-access-token-9f2b"
REFRESH = "canvas-refresh-token-4c1a"


def tokens(**overrides) -> TokenSet:
    values = {"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 3600}
    values.update(overrides)
    return TokenSet(**values)  # type: ignore[arg-type]


def store(tmp_path: pathlib.Path, key: bytes | None = None) -> FileCredentialStore:
    return FileCredentialStore(tmp_path / "credentials", key or b"k" * KEY_BYTES)


def test_a_token_round_trips_and_the_file_holds_no_plaintext(tmp_path) -> None:
    credential_store = store(tmp_path)
    stored = credential_store.save("conn-1", tokens())

    assert credential_store.load_token("conn-1") == ACCESS
    expiry = credential_store.load_expiry("conn-1")
    assert expiry is not None and expiry > 0
    assert stored.key_id == key_id_for(b"k" * KEY_BYTES)
    assert stored.ciphertext != ACCESS.encode()

    written = list((tmp_path / "credentials").glob("*.canvascred"))
    assert len(written) == 1
    raw = written[0].read_bytes()
    for secret in (ACCESS, REFRESH):
        assert secret.encode() not in raw, "the token must not be readable in the file"
    record = json.loads(raw.decode("utf-8"))
    assert record["key_id"] == stored.key_id
    assert record["connection_id"] == "conn-1"
    assert set(record) == {
        "version",
        "key_id",
        "connection_id",
        "nonce",
        "ciphertext",
        "expires_at",
        "scopes",
    }


def test_the_filename_does_not_leak_the_connection_id(tmp_path) -> None:
    credential_store = store(tmp_path)
    credential_store.save("canvas-connection-abcdef", tokens())
    names = [path.name for path in (tmp_path / "credentials").iterdir()]
    assert names and all("canvas-connection-abcdef" not in name for name in names)


def test_a_different_key_cannot_open_the_record(tmp_path) -> None:
    store(tmp_path).save("conn-1", tokens())
    other = FileCredentialStore(tmp_path / "credentials", b"z" * KEY_BYTES)

    assert other.load_token("conn-1") is None
    assert other.load_expiry("conn-1") is not None, "the record is still identifiable by expiry"
    assert other.key_id != store(tmp_path).key_id


def test_a_record_moved_to_another_connection_does_not_open(tmp_path) -> None:
    """A copied credential file must not answer for the connection it was copied onto."""
    credential_store = store(tmp_path)
    credential_store.save("conn-1", tokens())
    source = next((tmp_path / "credentials").glob("*.canvascred"))
    original = source.read_bytes()

    credential_store.save("conn-2", tokens(access_token="other"))
    destination = next(
        path
        for path in (tmp_path / "credentials").glob("*.canvascred")
        if path.read_bytes() != original
    )
    destination.write_bytes(original)

    # The record still names conn-1, and it is refused for conn-2 rather than answering with
    # conn-1's token; conn-1's own record is the one that works.
    assert json.loads(destination.read_text(encoding="utf-8"))["connection_id"] == "conn-1"
    assert credential_store.load_token("conn-2") is None
    remaining = next(
        path for path in (tmp_path / "credentials").glob("*.canvascred") if path == source
    )
    assert json.loads(remaining.read_text(encoding="utf-8"))["connection_id"] == "conn-1"
    assert credential_store.load_token("conn-1") == ACCESS


def test_a_corrupt_record_reads_as_no_credential(tmp_path) -> None:
    credential_store = store(tmp_path)
    credential_store.save("conn-1", tokens())
    path = next((tmp_path / "credentials").glob("*.canvascred"))

    path.write_text("{ not json", encoding="utf-8")
    assert credential_store.load_token("conn-1") is None

    path.write_text(json.dumps({"version": 99, "key_id": "x"}), encoding="utf-8")
    assert credential_store.load_token("conn-1") is None

    path.write_bytes(b"")
    assert credential_store.load_token("conn-1") is None


def test_a_tampered_ciphertext_is_rejected_rather_than_returned(tmp_path) -> None:
    credential_store = store(tmp_path)
    credential_store.save("conn-1", tokens())
    path = next((tmp_path / "credentials").glob("*.canvascred"))
    record = json.loads(path.read_text(encoding="utf-8"))
    ciphertext = bytearray(base64.b64decode(record["ciphertext"]))
    ciphertext[0] ^= 0xFF
    record["ciphertext"] = base64.b64encode(bytes(ciphertext)).decode("ascii")
    path.write_text(json.dumps(record), encoding="utf-8")

    assert credential_store.load_token("conn-1") is None


def test_clearing_removes_the_file_and_a_missing_record_is_not_an_error(tmp_path) -> None:
    credential_store = store(tmp_path)
    credential_store.save("conn-1", tokens())
    credential_store.clear("conn-1")

    assert list((tmp_path / "credentials").glob("*.canvascred")) == []
    assert credential_store.load_token("conn-1") is None
    credential_store.clear("conn-1")  # idempotent


def test_saving_twice_replaces_the_record_rather_than_accumulating(tmp_path) -> None:
    credential_store = store(tmp_path)
    credential_store.save("conn-1", tokens())
    credential_store.save("conn-1", tokens(access_token="second"))

    assert credential_store.load_token("conn-1") == "second"
    assert len(list((tmp_path / "credentials").glob("*.canvascred"))) == 1


def test_the_store_refuses_a_key_of_the_wrong_size(tmp_path) -> None:
    with pytest.raises(CredentialStoreUnavailable):
        FileCredentialStore(tmp_path, b"short")
    with pytest.raises(CredentialStoreUnavailable):
        decode_key(base64.urlsafe_b64encode(b"short").decode("ascii"))
    with pytest.raises(CredentialStoreUnavailable):
        decode_key("!!!not base64!!!")


def test_a_generated_key_is_32_bytes_and_round_trips() -> None:
    raw = generate_key()
    assert len(decode_key(raw)) == KEY_BYTES
    assert decode_key(raw) != decode_key(generate_key())


def test_the_store_is_not_built_without_a_configured_key(tmp_path) -> None:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        app_env="test",
        rag_provider_mode="deterministic",
        canvas_credential_dir=tmp_path / "credentials",
    )
    assert credential_store_from_settings(settings) is None
    assert store_is_usable(None) is False

    configured = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        app_env="test",
        rag_provider_mode="deterministic",
        canvas_credential_dir=tmp_path / "credentials",
        canvas_credential_key=generate_key(),
    )
    built = credential_store_from_settings(configured)
    assert built is not None
    assert store_is_usable(built) is True
    # The probe the usability check writes must not be left behind.
    assert list((tmp_path / "credentials").glob("*.canvascred")) == []

    # A settings object assembled without pydantic still resolves the key rather than crashing.
    loose = settings.model_copy(update={"canvas_credential_key": generate_key()})
    assert credential_store_from_settings(loose) is not None


def test_an_unusable_store_is_reported_as_unusable(tmp_path) -> None:
    class Broken(InMemoryCredentialStore):
        def save(self, connection_id, tokens):  # type: ignore[override]
            raise OSError("the volume is read-only")

    assert store_is_usable(Broken()) is False


def test_representations_never_contain_a_token() -> None:
    assert ACCESS not in repr(tokens())
    assert REFRESH not in repr(tokens())
    stored = FileCredentialStore(pathlib.Path("unused"), b"k" * KEY_BYTES)
    assert ACCESS not in repr(stored)


def test_the_credential_directory_permissions_are_owner_only(tmp_path) -> None:
    """Only meaningful on POSIX; on Windows the ACL is the platform's business."""
    import os
    import stat

    if os.name != "posix":  # pragma: no cover - the suite runs on Windows
        pytest.skip("POSIX permission bits are not the Windows mechanism")
    credential_store = store(tmp_path)
    credential_store.save("conn-1", tokens())
    directory = tmp_path / "credentials"
    path = next(directory.glob("*.canvascred"))
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
