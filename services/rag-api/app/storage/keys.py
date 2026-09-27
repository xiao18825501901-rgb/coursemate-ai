import hashlib
import re

_EXTENSION = re.compile(r"^\.[a-z0-9]{1,12}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def _scope(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _safe_extension(extension: str) -> str:
    normalized = extension.casefold()
    if not _EXTENSION.fullmatch(normalized):
        raise ValueError("Storage object extension is invalid")
    return normalized


def _opaque_id(value: str, *, label: str) -> str:
    if not _OPAQUE_ID.fullmatch(value):
        raise ValueError(f"{label} is invalid")
    return value


def canonical_object_key(
    *,
    owner_user_id: str,
    course_id: str,
    document_id: str,
    sha256: str,
    extension: str,
) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", sha256):
        raise ValueError("sha256 must be lowercase hexadecimal")
    return "/".join(
        (
            "canonical",
            _scope(owner_user_id),
            _scope(course_id),
            _opaque_id(document_id, label="document_id"),
            f"{sha256}{_safe_extension(extension)}",
        )
    )


def quarantine_object_key(*, owner_user_id: str, upload_id: str, extension: str) -> str:
    return "/".join(
        (
            "quarantine",
            _scope(owner_user_id),
            f"{_opaque_id(upload_id, label='upload_id')}{_safe_extension(extension)}",
        )
    )
