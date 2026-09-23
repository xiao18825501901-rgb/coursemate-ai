"""The owner's small-sample live Canvas read: one real school, a few real files, no storage.

This is the code the owner runs against their own Canvas account to prove that the transient
credential path works against a real school rather than a simulated one. It exists as a module
rather than a script so the same logic is covered by a test against a simulated school — the live
run then differs from a tested run only in the transport.

What it does, in order, and nothing more:

1. reads the account identity with the pasted credential (`profile`), so the receipt names the
   Canvas account the import would be bound to;
2. lists the student's own readable courses (`student_courses`);
3. picks one course — named by the caller, or the first readable one — and lists its files;
4. downloads at most `max_files` files, skipping anything above `max_bytes`, hashing what it
   received so the receipt can be compared against the file the school serves;
5. destroys the credential and reports what the store says happened to it.

The receipt never contains the credential, and no file it downloads is kept: the bytes are hashed
and discarded, because this is a measurement of the read path, not an import.

Nothing here parses, indexes or stores anything, so a live run cannot create a course or a document
in the product.
"""

from __future__ import annotations

import hashlib
import pathlib
import time
from dataclasses import dataclass, field
from typing import Any

from .adapter import CanvasReadAdapter, CanvasReadError
from .transient_credential import (
    REASON_READS_COMPLETE,
    TransientCanvasCredentialStore,
)

DEFAULT_MAX_FILES = 3
DEFAULT_MAX_BYTES = 2 * 1024 * 1024


@dataclass
class FileReceipt:
    """One file read: its identity, its size and the hash of the bytes actually received."""

    file_id: str
    display_name: str
    declared_size: int
    received_bytes: int = 0
    sha256: str = ""
    skipped_reason: str = ""
    error: str = ""


@dataclass
class SmokeReceipt:
    """What the live run observed. Contains no credential, by construction."""

    institution_origin: str
    canvas_user_id: str = ""
    canvas_name: str = ""
    readable_courses: int = 0
    course_id: str = ""
    course_name: str = ""
    listed_files: int = 0
    files: list[FileReceipt] = field(default_factory=list)
    read_calls: int = 0
    credential_state: str = ""
    destroy_reason: str = ""
    zeroed_bytes: int = 0
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "institution_origin": self.institution_origin,
            "canvas_user_id": self.canvas_user_id,
            "canvas_name": self.canvas_name,
            "readable_courses": self.readable_courses,
            "course_id": self.course_id,
            "course_name": self.course_name,
            "listed_files": self.listed_files,
            "files": [
                {
                    "file_id": item.file_id,
                    "display_name": item.display_name,
                    "declared_size": item.declared_size,
                    "received_bytes": item.received_bytes,
                    "sha256": item.sha256,
                    "skipped_reason": item.skipped_reason,
                    "error": item.error,
                }
                for item in self.files
            ],
            "read_calls": self.read_calls,
            "credential_state": self.credential_state,
            "destroy_reason": self.destroy_reason,
            "zeroed_bytes": self.zeroed_bytes,
            "seconds": round(self.seconds, 3),
            "errors": list(self.errors),
        }

    @property
    def ok(self) -> bool:
        """True only when a real file was read and the credential ended destroyed."""
        return (
            not self.errors
            and any(item.sha256 for item in self.files)
            and self.credential_state == "DESTROYED"
        )


def _hash_of(path: pathlib.Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def run_smoke(
    *,
    adapter: CanvasReadAdapter,
    store: TransientCanvasCredentialStore,
    credential_ref: str,
    sink_dir: pathlib.Path,
    course_id: str = "",
    max_files: int = DEFAULT_MAX_FILES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> SmokeReceipt:
    """Read a small sample from the school, then destroy the credential. Never raises."""
    receipt = SmokeReceipt(institution_origin=adapter.origin)
    started = time.monotonic()
    sink_dir = pathlib.Path(sink_dir)
    sink_dir.mkdir(parents=True, exist_ok=True)
    try:
        profile = adapter.profile()
        receipt.canvas_user_id = str(profile.id or "")
        receipt.canvas_name = profile.name or ""
        if not receipt.canvas_user_id:
            receipt.errors.append("the school returned no account identity for this credential")
            return _finish(receipt, store, credential_ref, started, sink_dir)

        courses = [course for course in adapter.student_courses() if course.is_readable_history]
        receipt.readable_courses = len(courses)
        if not courses:
            receipt.errors.append("this account has no readable courses")
            return _finish(receipt, store, credential_ref, started, sink_dir)

        chosen = next((course for course in courses if course.id == course_id), None)
        if chosen is None:
            if course_id:
                receipt.errors.append(
                    f"course {course_id} is not among this account's readable courses"
                )
                return _finish(receipt, store, credential_ref, started, sink_dir)
            chosen = courses[0]
        receipt.course_id = chosen.id
        receipt.course_name = chosen.name

        entries = adapter.course_files(chosen.id)
        receipt.listed_files = len(entries)
        smallest = sorted(entries, key=lambda entry: entry.size)[: max(0, max_files)]
        for entry in smallest:
            item = FileReceipt(
                file_id=entry.id,
                display_name=entry.display_name,
                declared_size=entry.size,
            )
            if entry.size > max_bytes:
                item.skipped_reason = (
                    f"declared size {entry.size} is above the {max_bytes}-byte cap"
                )
                receipt.files.append(item)
                continue
            sink = sink_dir / f"smoke-{entry.id}"
            try:
                url = adapter.course_file_download_url(chosen.id, entry.id)
                result = adapter.download(url, sink)
                size, digest = _hash_of(sink)
                item.received_bytes = size
                item.sha256 = digest
                if result.bytes_written and result.bytes_written != size:
                    item.error = (
                        f"the adapter reported {result.bytes_written} bytes and {size} were read"
                    )
            except CanvasReadError as error:
                item.error = f"{error.category}: {error.detail}"
            finally:
                sink.unlink(missing_ok=True)
            receipt.files.append(item)
    except CanvasReadError as error:
        receipt.errors.append(f"{error.category}: {error.detail}")
    except Exception as error:  # noqa: BLE001
        # Anything else is recorded by name rather than swallowed. It is caught here and the
        # receipt is returned below, so the credential is always destroyed — and a failure cannot
        # make a live run report "the school had no files", which is what a silent exception looks
        # like from the outside. (This is not a `finally: return`, which ruff's B012 is right to
        # flag: that construct swallows exceptions instead of recording them.)
        receipt.errors.append(f"{type(error).__name__}: {error}")
    return _finish(receipt, store, credential_ref, started, sink_dir)


def _finish(
    receipt: SmokeReceipt,
    store: TransientCanvasCredentialStore,
    credential_ref: str,
    started: float,
    sink_dir: pathlib.Path,
) -> SmokeReceipt:
    """Always destroy the credential and report what the store recorded."""
    destroyed = store.destroy(credential_ref, reason=REASON_READS_COMPLETE)
    if destroyed is not None:
        receipt.read_calls = destroyed.read_calls
        receipt.destroy_reason = destroyed.destroy_reason
        receipt.zeroed_bytes = destroyed.zeroed_bytes
    receipt.credential_state = store.state(credential_ref)
    receipt.seconds = time.monotonic() - started
    # The downloaded sample is a measurement, not material: nothing is kept.
    for leftover in sink_dir.glob("smoke-*"):
        leftover.unlink(missing_ok=True)
    return receipt
