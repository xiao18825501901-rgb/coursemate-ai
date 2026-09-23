"""The Local Canvas Bridge: a user's own machine importing into their own private course.

The OAuth route in `oauth.py` is how every user is meant to connect a school. This module exists for
the one case OAuth cannot cover while an institution has not issued a Developer Key: the user runs
the CourseJesus bridge on their own machine, where a Personal Access Token is read through a hidden
prompt and kept in the operating system's credential store.

The property that shapes every line here is that **the token never reaches CourseJesus**. The
server hands the user a short-lived, single-use code; their local bridge authenticates with the
user's own CourseJesus session *and* that code; from then on the server only ever receives course
metadata, file bytes and receipts. So there is deliberately no parameter, no column and no log line
anywhere in this module that could carry a credential — and a request that tries to send one is
refused by the request model rather than ignored.

What the server still owns, and never delegates to the bridge:

* the user the session belongs to (a second user with the code is refused);
* the institution the session was opened for (a bridge cannot point it at another school);
* which courses may be imported (only ones the bridge actually discovered, and then only ones the
  user selected — a file for any other course is refused);
* the bytes: the declared size and SHA-256 are recomputed from what arrived, so a manifest cannot
  claim content it did not send;
* the course and document writes, through the real `IngestionService`, with the real private-course
  quotas — no hand-written INSERT, no quota bypass.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from app.errors import ApiError
from app.models import CourseCreate, PublicationStatus
from app.services.ingestion import IngestionService

# How long a session stays usable. Short on purpose: the code is displayed once, in a page, and a
# user who does not paste it promptly should open a fresh one rather than leave a code alive.
SESSION_TTL_MINUTES: Final = 30

OPEN: Final = "OPEN"
CLAIMED: Final = "CLAIMED"
SELECTED: Final = "SELECTED"
IMPORTING: Final = "IMPORTING"
COMPLETED: Final = "COMPLETED"
COMPLETED_WITH_WARNINGS: Final = "COMPLETED_WITH_WARNINGS"
FAILED: Final = "FAILED"
CANCELLED: Final = "CANCELLED"
EXPIRED: Final = "EXPIRED"

TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {COMPLETED, COMPLETED_WITH_WARNINGS, FAILED, CANCELLED, EXPIRED}
)

# The file fates, the same vocabulary the OAuth worker uses so one report can describe both routes.
PENDING: Final = "PENDING"
INDEXED: Final = "INDEXED"
DOWNLOAD_ONLY: Final = "DOWNLOAD_ONLY"
SKIPPED_IDENTICAL: Final = "SKIPPED_IDENTICAL"
REJECTED: Final = "REJECTED"
FAILED_FILE: Final = "FAILED"

# Codes a bridge may see. They say what the caller must do next, and none of them reveals whether
# another user's session exists.
NOT_FOUND: Final = "LOCAL_SESSION_NOT_FOUND"
EXPIRED_CODE: Final = "LOCAL_SESSION_EXPIRED"
ALREADY_CLAIMED: Final = "LOCAL_SESSION_ALREADY_CLAIMED"
BAD_STATE: Final = "LOCAL_SESSION_WRONG_STATE"
UNKNOWN_COURSE: Final = "LOCAL_DISCOVERY_UNKNOWN_COURSE"
UNSELECTED_COURSE: Final = "LOCAL_COURSE_NOT_SELECTED"
HASH_MISMATCH: Final = "LOCAL_FILE_HASH_MISMATCH"
SIZE_MISMATCH: Final = "LOCAL_FILE_SIZE_MISMATCH"
UNSAFE_NAME: Final = "LOCAL_FILE_NAME_UNSAFE"


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse(moment: str) -> datetime:
    return datetime.strptime(moment, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def new_code() -> str:
    """A one-time code the user pastes into their terminal.

    `token_urlsafe` rather than a short numeric code: this string authorises a claim, so it must not
    be guessable, and it is compared by hash rather than by equality.
    """
    return secrets.token_urlsafe(24)


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def local_course_id(user_id: str, institution_origin: str, canvas_course_id: str) -> str:
    """A stable private-course id for one Canvas course belonging to one user.

    Derived from the user *and* the institution *and* the Canvas course id, so two users importing
    the same course get two separate private courses and the same user re-importing reuses theirs.
    """
    digest = hashlib.sha256(
        f"{user_id}|{institution_origin}|{canvas_course_id}".encode()
    ).hexdigest()[:12]
    return f"canvas-local-{digest}"


def course_storage_id(canvas_course_id: str) -> str:
    """The Canvas course id as a filesystem-safe fragment, for the display path of an original."""
    safe = "".join(character if character.isalnum() else "-" for character in canvas_course_id)
    return safe.strip("-")[:40] or "course"


def safe_display_name(name: str) -> str:
    """The one place a filename from the bridge is checked before it reaches the upload path.

    A name may not contain a path separator, a drive letter, a control character, or any of the
    traversal spellings — the upload layer checks again, but a refusal here names the actual problem
    instead of surfacing as a generic invalid-upload error.
    """
    if not name or len(name) > 200:
        raise ApiError(400, UNSAFE_NAME, "The file name is empty or too long to store safely.")
    if any(character in name for character in ("/", "\\", "\x00")):
        raise ApiError(400, UNSAFE_NAME, "The file name must not contain a path separator.")
    if any(ord(character) < 32 for character in name):
        raise ApiError(400, UNSAFE_NAME, "The file name must not contain control characters.")
    if name in {".", ".."} or name.startswith("~"):
        raise ApiError(400, UNSAFE_NAME, "The file name is not a file name.")
    if name.split(".")[0].casefold() in {"con", "prn", "aux", "nul"}:
        raise ApiError(400, UNSAFE_NAME, "The file name is reserved by the operating system.")
    return name


@dataclass(frozen=True)
class DiscoveredCourse:
    """One Canvas course the bridge found on the user's own account."""

    canvas_course_id: str
    name: str
    course_code: str = ""
    term: str = ""
    enrollment_state: str = ""
    workflow_state: str = ""
    file_count: int = 0
    size_bytes: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "canvasCourseId": self.canvas_course_id,
            "name": self.name,
            "courseCode": self.course_code,
            "term": self.term,
            "enrollmentState": self.enrollment_state,
            "workflowState": self.workflow_state,
            "fileCount": self.file_count,
            "sizeBytes": self.size_bytes,
        }


@dataclass(frozen=True)
class LocalSession:
    """One short-lived import session, as the API is allowed to describe it.

    There is no code field: the plaintext code exists in the response that created the session and
    nowhere else, so it cannot be fetched again by anything that later reads a session.
    """

    id: str
    owner_user_id: str
    institution_key: str
    institution_origin: str
    status: str
    claimed_by: str
    canvas_user_id: str
    canvas_display_name: str
    discovery: tuple[DiscoveredCourse, ...]
    selection: tuple[str, ...]
    error_code: str
    error_message: str
    created_at: str
    expires_at: str
    claimed_at: str
    selection_at: str
    completed_at: str

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    def as_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.id,
            "institutionKey": self.institution_key,
            "institutionOrigin": self.institution_origin,
            "status": self.status,
            "claimedBy": self.claimed_by,
            "canvasUserId": self.canvas_user_id,
            "canvasDisplayName": self.canvas_display_name,
            "courses": [course.as_dict() for course in self.discovery],
            "selectedCourseIds": list(self.selection),
            "errorCode": self.error_code,
            "errorMessage": self.error_message,
            "createdAt": self.created_at,
            "expiresAt": self.expires_at,
            "claimedAt": self.claimed_at,
            "selectionAt": self.selection_at,
            "completedAt": self.completed_at,
        }


@dataclass(frozen=True)
class FileRecord:
    """What happened to one uploaded file. Returned to the bridge as its receipt."""

    canvas_course_id: str
    canvas_file_id: str
    display_name: str
    size_bytes: int
    content_sha256: str
    status: str
    reason: str
    document_id: str
    target_course_id: str
    duplicate: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "canvasCourseId": self.canvas_course_id,
            "canvasFileId": self.canvas_file_id,
            "displayName": self.display_name,
            "sizeBytes": self.size_bytes,
            "sha256": self.content_sha256,
            "status": self.status,
            "reason": self.reason,
            "documentId": self.document_id,
            "targetCourseId": self.target_course_id,
            "duplicate": self.duplicate,
        }


class LocalSessionRepository:
    """All SQL for the local-bridge tables. No caller runs a statement against them directly."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row

    # ------------------------------------------------------------------ sessions
    def insert(
        self,
        *,
        session_id: str,
        owner_user_id: str,
        institution_key: str,
        institution_origin: str,
        code_hash: str,
        expires_at: str,
    ) -> None:
        self._connection.execute(
            "INSERT INTO canvas_local_sessions(id, owner_user_id, institution_key, "
            "institution_origin, code_hash, status, expires_at) VALUES(?,?,?,?,?,?,?)",
            (
                session_id,
                owner_user_id,
                institution_key,
                institution_origin,
                code_hash,
                OPEN,
                expires_at,
            ),
        )

    def get(self, session_id: str) -> LocalSession | None:
        row = self._connection.execute(
            "SELECT * FROM canvas_local_sessions WHERE id=?", (session_id,)
        ).fetchone()
        return None if row is None else self._to_session(row)

    def by_code_hash(self, code_hash: str) -> LocalSession | None:
        row = self._connection.execute(
            "SELECT * FROM canvas_local_sessions WHERE code_hash=?", (code_hash,)
        ).fetchone()
        return None if row is None else self._to_session(row)

    def claim(
        self,
        session_id: str,
        *,
        canvas_user_id: str,
        canvas_display_name: str,
        claimed_by: str,
        claimed_at: str,
    ) -> int:
        """Mark the session claimed. Returns the number of rows changed.

        The `status='OPEN'` and `claimed_at IS NULL` conditions are the replay guard: two bridges
        racing the same code both run this statement, and the database lets exactly one of them win.
        """
        cursor = self._connection.execute(
            "UPDATE canvas_local_sessions SET status=?, claimed_at=?, canvas_user_id=?, "
            "canvas_display_name=?, claimed_by=?, updated_at=? "
            "WHERE id=? AND status=? AND claimed_at IS NULL",
            (
                CLAIMED,
                claimed_at,
                canvas_user_id,
                canvas_display_name,
                claimed_by,
                claimed_at,
                session_id,
                OPEN,
            ),
        )
        return int(cursor.rowcount)

    def update(
        self,
        session_id: str,
        *,
        status: str | None = None,
        discovery: Sequence[DiscoveredCourse] | None = None,
        selection: Sequence[str] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        touch_selection: bool = False,
        touch_completed: bool = False,
        now: str,
    ) -> None:
        sets = ["updated_at=?"]
        values: list[Any] = [now]
        if status is not None:
            sets.append("status=?")
            values.append(status)
        if discovery is not None:
            sets.append("discovery_json=?")
            values.append(json.dumps([course.as_dict() for course in discovery]))
        if selection is not None:
            sets.append("selection_json=?")
            values.append(json.dumps(list(selection)))
        if error_code is not None or error_message is not None:
            sets.append("error_code=?")
            values.append(error_code)
            sets.append("error_message=?")
            values.append(error_message)
        if touch_selection:
            sets.append("selection_at=?")
            values.append(now)
        if touch_completed:
            sets.append("completed_at=?")
            values.append(now)
        values.append(session_id)
        self._connection.execute(
            f"UPDATE canvas_local_sessions SET {', '.join(sets)} WHERE id=?", values
        )

    # ------------------------------------------------------------------ files
    def file_by_identity(
        self, session_id: str, canvas_course_id: str, canvas_file_id: str, content_sha256: str
    ) -> FileRecord | None:
        row = self._connection.execute(
            "SELECT * FROM canvas_local_files WHERE session_id=? AND canvas_course_id=? "
            "AND canvas_file_id=? AND content_sha256=?",
            (session_id, canvas_course_id, canvas_file_id, content_sha256),
        ).fetchone()
        return None if row is None else self._to_file(row)

    def insert_file(
        self,
        *,
        session_id: str,
        canvas_course_id: str,
        canvas_file_id: str,
        display_name: str,
        size_bytes: int,
        content_sha256: str,
        source_updated_at: str,
        status: str,
        reason: str,
        target_course_id: str,
        document_id: str | None,
    ) -> FileRecord:
        row_id = f"clf_{uuid.uuid4().hex}"
        self._connection.execute(
            "INSERT INTO canvas_local_files(id, session_id, canvas_course_id, canvas_file_id, "
            "display_name, size_bytes, content_sha256, source_updated_at, target_course_id, "
            "local_document_id, status, reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row_id,
                session_id,
                canvas_course_id,
                canvas_file_id,
                display_name,
                size_bytes,
                content_sha256,
                source_updated_at,
                target_course_id,
                document_id,
                status,
                reason,
            ),
        )
        return FileRecord(
            canvas_course_id=canvas_course_id,
            canvas_file_id=canvas_file_id,
            display_name=display_name,
            size_bytes=size_bytes,
            content_sha256=content_sha256,
            status=status,
            reason=reason,
            document_id=document_id or "",
            target_course_id=target_course_id,
        )

    def files(self, session_id: str) -> list[FileRecord]:
        rows = self._connection.execute(
            "SELECT * FROM canvas_local_files WHERE session_id=? "
            "ORDER BY canvas_course_id, display_name",
            (session_id,),
        ).fetchall()
        return [self._to_file(row) for row in rows]

    def counts(self, session_id: str) -> dict[str, int]:
        rows = self._connection.execute(
            "SELECT status, COUNT(*) AS files FROM canvas_local_files WHERE session_id=? "
            "GROUP BY status",
            (session_id,),
        ).fetchall()
        return {str(row["status"]): int(row["files"]) for row in rows}

    # ------------------------------------------------------------------ mapping
    @staticmethod
    def _to_session(row: sqlite3.Row) -> LocalSession:
        discovery = json.loads(row["discovery_json"] or "[]")
        return LocalSession(
            id=str(row["id"]),
            owner_user_id=str(row["owner_user_id"]),
            institution_key=str(row["institution_key"]),
            institution_origin=str(row["institution_origin"]),
            status=str(row["status"]),
            claimed_by=str(row["claimed_by"] or ""),
            canvas_user_id=str(row["canvas_user_id"] or ""),
            canvas_display_name=str(row["canvas_display_name"] or ""),
            discovery=tuple(
                DiscoveredCourse(
                    canvas_course_id=str(item.get("canvasCourseId", "")),
                    name=str(item.get("name", "")),
                    course_code=str(item.get("courseCode", "")),
                    term=str(item.get("term", "")),
                    enrollment_state=str(item.get("enrollmentState", "")),
                    workflow_state=str(item.get("workflowState", "")),
                    file_count=int(item.get("fileCount", 0) or 0),
                    size_bytes=int(item.get("sizeBytes", 0) or 0),
                )
                for item in discovery
            ),
            selection=tuple(str(item) for item in json.loads(row["selection_json"] or "[]")),
            error_code=str(row["error_code"] or ""),
            error_message=str(row["error_message"] or ""),
            created_at=str(row["created_at"]),
            expires_at=str(row["expires_at"]),
            claimed_at=str(row["claimed_at"] or ""),
            selection_at=str(row["selection_at"] or ""),
            completed_at=str(row["completed_at"] or ""),
        )

    @staticmethod
    def _to_file(row: sqlite3.Row) -> FileRecord:
        return FileRecord(
            canvas_course_id=str(row["canvas_course_id"]),
            canvas_file_id=str(row["canvas_file_id"]),
            display_name=str(row["display_name"]),
            size_bytes=int(row["size_bytes"]),
            content_sha256=str(row["content_sha256"]),
            status=str(row["status"]),
            reason=str(row["reason"]),
            document_id=str(row["local_document_id"] or ""),
            target_course_id=str(row["target_course_id"]),
        )


class LocalBridgeService:
    """The rules of the bridge: who may do what, in which order, with which evidence."""

    def __init__(
        self,
        repository: LocalSessionRepository,
        *,
        ingestion: IngestionService | None = None,
        ttl_minutes: int = SESSION_TTL_MINUTES,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._repository = repository
        self._ingestion = ingestion
        self._ttl = timedelta(minutes=ttl_minutes)
        self._clock = clock

    # ------------------------------------------------------------------ opening
    def open_session(
        self, *, user_id: str, institution_key: str, institution_origin: str
    ) -> tuple[LocalSession, str]:
        """Create a session and return it with the one-time code.

        The caller shows the code once. It is stored as a hash and can never be read back.
        """
        moment = self._clock()
        code = new_code()
        session_id = f"cls_{uuid.uuid4().hex}"
        self._repository.insert(
            session_id=session_id,
            owner_user_id=user_id,
            institution_key=institution_key,
            institution_origin=institution_origin,
            code_hash=hash_code(code),
            expires_at=_stamp(moment + self._ttl),
        )
        session = self._repository.get(session_id)
        if session is None:  # pragma: no cover - the insert above cannot be invisible
            raise ApiError(500, NOT_FOUND, "The local import session could not be created.")
        return session, code

    # ------------------------------------------------------------------ claiming
    def claim(
        self,
        *,
        user_id: str,
        code: str,
        canvas_user_id: str,
        canvas_display_name: str = "",
        claimed_by: str = "",
    ) -> LocalSession:
        """Claim a session with the code. One claim only, for the session's own user only."""
        if not code:
            raise ApiError(400, NOT_FOUND, "A local import code is required.")
        session = self._repository.by_code_hash(hash_code(code))
        if session is None or session.owner_user_id != user_id:
            # The same answer for "no such code" and "someone else's code": a bridge must not
            # be able to probe which codes exist.
            raise ApiError(404, NOT_FOUND, "That local import code is not valid.")
        if session.claimed_at:
            raise ApiError(409, ALREADY_CLAIMED, "That local import code has already been used.")
        if self._expired(session):
            self._repository.update(
                session.id,
                status=EXPIRED,
                error_code=EXPIRED_CODE,
                error_message="",
                now=_stamp(self._clock()),
            )
            raise ApiError(410, EXPIRED_CODE, "That local import code has expired.")
        if not canvas_user_id:
            raise ApiError(400, NOT_FOUND, "The Canvas user id is required to claim a session.")
        changed = self._repository.claim(
            session.id,
            canvas_user_id=canvas_user_id,
            canvas_display_name=canvas_display_name,
            claimed_by=claimed_by[:120],
            claimed_at=_stamp(self._clock()),
        )
        if changed != 1:
            # Two bridges raced; the database refused the second.
            raise ApiError(409, ALREADY_CLAIMED, "That local import code has already been used.")
        return self._must(session.id, user_id)

    # ------------------------------------------------------------------ discovery
    def record_discovery(
        self, *, user_id: str, session_id: str, courses: Sequence[DiscoveredCourse]
    ) -> LocalSession:
        session = self._must(session_id, user_id)
        self._live(session)
        if session.status not in {CLAIMED, SELECTED}:
            raise ApiError(409, BAD_STATE, "The session is not waiting for a course list.")
        seen: set[str] = set()
        unique: list[DiscoveredCourse] = []
        for course in courses:
            if not course.canvas_course_id or course.canvas_course_id in seen:
                continue
            seen.add(course.canvas_course_id)
            unique.append(course)
        self._repository.update(
            session_id,
            discovery=unique,
            status=CLAIMED,
            error_code="",
            error_message="",
            now=_stamp(self._clock()),
        )
        return self._must(session_id, user_id)

    # ------------------------------------------------------------------ selection
    def select(
        self, *, user_id: str, session_id: str, canvas_course_ids: Sequence[str]
    ) -> LocalSession:
        session = self._must(session_id, user_id)
        self._live(session)
        discovered = {course.canvas_course_id for course in session.discovery}
        if not session.discovery:
            raise ApiError(409, BAD_STATE, "The bridge has not reported any courses yet.")
        wanted = list(dict.fromkeys(canvas_course_ids))
        unknown = [course_id for course_id in wanted if course_id not in discovered]
        if unknown:
            raise ApiError(
                400,
                UNKNOWN_COURSE,
                "A selected course is not one this bridge discovered.",
                details={"unknown": unknown[:5]},
            )
        if not wanted:
            raise ApiError(
                400, UNKNOWN_COURSE, "Select at least one course, or cancel the session."
            )
        self._repository.update(
            session_id,
            selection=wanted,
            status=SELECTED,
            touch_selection=True,
            error_code="",
            error_message="",
            now=_stamp(self._clock()),
        )
        return self._must(session_id, user_id)

    # ------------------------------------------------------------------ files
    def upload_file(
        self,
        *,
        user_id: str,
        session_id: str,
        canvas_course_id: str,
        canvas_file_id: str,
        display_name: str,
        content: bytes,
        declared_size: int,
        declared_sha256: str,
        source_updated_at: str = "",
    ) -> FileRecord:
        """Store one file the bridge downloaded, through the real ingestion path.

        Everything checkable is checked before the write: the file must belong to a course the user
        selected, the name must be a name, and the declared size and digest must match the bytes
        that actually arrived. A file that fails any of those is refused rather than recorded.
        """
        session = self._must(session_id, user_id)
        self._live(session)
        if session.status not in {SELECTED, IMPORTING}:
            raise ApiError(409, BAD_STATE, "The session has no selected courses to import into.")
        if canvas_course_id not in session.selection:
            raise ApiError(
                403,
                UNSELECTED_COURSE,
                "That Canvas course was not selected for this import.",
            )
        if not canvas_file_id:
            raise ApiError(400, UNSAFE_NAME, "A Canvas file id is required.")
        name = safe_display_name(display_name)
        digest = hashlib.sha256(content).hexdigest()
        if declared_sha256 and declared_sha256.casefold() != digest:
            raise ApiError(
                409,
                HASH_MISMATCH,
                "The uploaded bytes do not match the digest the bridge declared.",
                details={"declared": declared_sha256, "actual": digest},
            )
        if declared_size and int(declared_size) != len(content):
            raise ApiError(
                409,
                SIZE_MISMATCH,
                "The uploaded bytes do not match the size the bridge declared.",
                details={"declared": int(declared_size), "actual": len(content)},
            )
        existing = self._repository.file_by_identity(
            session_id, canvas_course_id, canvas_file_id, digest
        )
        if existing is not None:
            # The same file, the same bytes, a retried upload: the first receipt is the answer.
            return FileRecord(
                canvas_course_id=existing.canvas_course_id,
                canvas_file_id=existing.canvas_file_id,
                display_name=existing.display_name,
                size_bytes=existing.size_bytes,
                content_sha256=existing.content_sha256,
                status=existing.status,
                reason=existing.reason,
                document_id=existing.document_id,
                target_course_id=existing.target_course_id,
                duplicate=True,
            )
        target = local_course_id(user_id, session.institution_origin, canvas_course_id)
        if self._ingestion is None:  # pragma: no cover - the API always wires the real service
            raise ApiError(503, BAD_STATE, "The ingestion layer is not available.")
        self._repository.update(session_id, status=IMPORTING, now=_stamp(self._clock()))
        self._ensure_course(
            target, user_id=user_id, session=session, canvas_course_id=canvas_course_id
        )
        status, reason, document_id = self._ingest(
            target, user_id=user_id, name=name, content=content
        )
        return self._repository.insert_file(
            session_id=session_id,
            canvas_course_id=canvas_course_id,
            canvas_file_id=canvas_file_id,
            display_name=name,
            size_bytes=len(content),
            content_sha256=digest,
            source_updated_at=source_updated_at,
            status=status,
            reason=reason,
            target_course_id=target,
            document_id=document_id,
        )

    # ------------------------------------------------------------------ closing
    def finish(self, *, user_id: str, session_id: str) -> dict[str, Any]:
        session = self._must(session_id, user_id)
        if session.status in TERMINAL_STATES:
            raise ApiError(409, BAD_STATE, "That session has already finished.")
        counts = self._repository.counts(session_id)
        failed = int(counts.get(FAILED_FILE, 0)) + int(counts.get(REJECTED, 0))
        state = COMPLETED_WITH_WARNINGS if failed else COMPLETED
        self._repository.update(
            session_id, status=state, touch_completed=True, now=_stamp(self._clock())
        )
        return {"sessionId": session_id, "status": state, "counts": counts}

    def cancel(self, *, user_id: str, session_id: str) -> dict[str, Any]:
        """Stop a session. Files already ingested stay — they are the user's own private course."""
        session = self._must(session_id, user_id)
        if session.status in TERMINAL_STATES:
            return {
                "sessionId": session_id,
                "status": session.status,
                "counts": self._repository.counts(session_id),
            }
        self._repository.update(
            session_id, status=CANCELLED, touch_completed=True, now=_stamp(self._clock())
        )
        return {
            "sessionId": session_id,
            "status": CANCELLED,
            "counts": self._repository.counts(session_id),
        }

    def status(self, *, user_id: str, session_id: str) -> dict[str, Any]:
        session = self._must(session_id, user_id)
        if self._expired(session) and session.status == OPEN:
            self._repository.update(
                session_id, status=EXPIRED, error_code=EXPIRED_CODE, now=_stamp(self._clock())
            )
            session = self._must(session_id, user_id)
        payload = session.as_dict()
        payload["counts"] = self._repository.counts(session_id)
        payload["files"] = [record.as_dict() for record in self._repository.files(session_id)]
        return payload

    # ------------------------------------------------------------------ internals
    def _must(self, session_id: str, user_id: str) -> LocalSession:
        session = self._repository.get(session_id)
        if session is None or session.owner_user_id != user_id:
            raise ApiError(404, NOT_FOUND, "No such local import session.")
        return session

    def _expired(self, session: LocalSession) -> bool:
        return _parse(session.expires_at) <= self._clock()

    def _live(self, session: LocalSession) -> None:
        if self._expired(session):
            self._repository.update(
                session.id,
                status=EXPIRED,
                error_code=EXPIRED_CODE,
                error_message="",
                now=_stamp(self._clock()),
            )
            raise ApiError(410, EXPIRED_CODE, "That local import session has expired.")
        if session.status in TERMINAL_STATES:
            raise ApiError(409, BAD_STATE, "That local import session has already finished.")

    def _ensure_course(
        self,
        target: str,
        *,
        user_id: str,
        session: LocalSession,
        canvas_course_id: str,
    ) -> None:
        assert self._ingestion is not None  # narrowed by the caller
        existing = None
        with self._ingestion.database.connect() as connection:
            existing = connection.execute(
                "SELECT id, course_type, visibility, publication_status, owner_user_id "
                "FROM courses WHERE id=?",
                (target,),
            ).fetchone()
        if existing is not None:
            # Never write into a course this user does not own, and never into a published one: a
            # published course is a reviewed release (migration 019), not an import target.
            if (
                str(existing["owner_user_id"] or "") != user_id
                or str(existing["course_type"]) != "user"
            ):
                raise ApiError(409, BAD_STATE, "That private course belongs to someone else.")
            if str(existing["publication_status"]) != "private":
                raise ApiError(409, BAD_STATE, "That course is no longer a private draft.")
            return
        discovered = next(
            (course for course in session.discovery if course.canvas_course_id == canvas_course_id),
            None,
        )
        label = (discovered.course_code or discovered.name) if discovered else ""
        self._ingestion.create_course(
            CourseCreate(
                id=target,
                name=(label or f"Canvas {canvas_course_id}")[:120],
                description=(
                    f"由本地 Canvas Bridge 从 {session.institution_origin} 的课程 "
                    f"{canvas_course_id} 导入；仅本人可见。"
                ),
            ),
            owner_user_id=user_id,
            is_admin=False,
            publication_status=PublicationStatus.PRIVATE,
        )

    def _ingest(
        self, target: str, *, user_id: str, name: str, content: bytes
    ) -> tuple[str, str, str]:
        """Queue and process one document through the real service, and say what happened."""
        assert self._ingestion is not None
        try:
            accepted = self._ingestion.queue_document(
                course_id=target,
                filename=name,
                media_type=_media_type_for(name),
                content=content,
                owner_user_id=user_id,
                is_admin=False,
            )
        except ApiError as error:
            if error.code == "DUPLICATE_DOCUMENT":
                existing = error.details.get("documentId")
                return (
                    SKIPPED_IDENTICAL,
                    "an identical file is already in this course",
                    str(existing or ""),
                )
            return REJECTED, f"{error.code}: {error.message}", ""
        self._ingestion.process_document(accepted.document.id, accepted.job.id)
        # The owner must be named on the read: this course is a *private user course*, and an
        # ownerless admin read refuses it (`_require_course` answers "not found" rather than leaking
        # that it exists), which is how this line was found — the upload succeeded and the receipt
        # lookup then reported the job missing.
        job = self._ingestion.get_job(
            accepted.job.id, owner_user_id=user_id, is_admin=False
        )
        document = self._ingestion.get_document(accepted.document.id)
        if str(job.status.value) == "completed" and document.chunk_count > 0:
            return INDEXED, "indexed", accepted.document.id
        # Stored but not readable: kept as an original, never counted as learnable material.
        return (
            DOWNLOAD_ONLY,
            str(job.error_message or "the file produced no extractable text"),
            accepted.document.id,
        )


def _media_type_for(name: str) -> str:
    """The media type the upload layer expects, from the same table it validates against."""
    from app.learning.uploads import MEDIA_TYPES

    suffix = "." + name.rsplit(".", 1)[-1].casefold() if "." in name else ""
    allowed = MEDIA_TYPES.get(suffix)
    if not allowed:
        # The upload layer owns the final word; this is the best guess for a format it will refuse
        # with a typed error rather than a crash.
        return "application/octet-stream"
    preferred = sorted(entry for entry in allowed if entry != "application/octet-stream")
    return preferred[0] if preferred else sorted(allowed)[0]
