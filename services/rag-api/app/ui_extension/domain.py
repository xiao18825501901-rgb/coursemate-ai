"""Real CourseMate V3 implementation of the delivered UI ``DomainPort``.

Every operation is served by the existing V3 database, ingestion service,
`HybridRetriever`, learning orchestrator and Node task agent. This module adds
no second course/file/task/knowledge store: it only projects the live V3 rows
into the canonical DTOs that the new UI expects, and re-checks authorization
from the server-derived ``subject`` on every call.

Authorisation rules that are deliberately preserved:

* course visibility uses :func:`app.course_access.require_course_access`, so a
  private course is hidden (404) rather than merely read-only;
* retrieval is always scoped with :class:`RetrievalAccess`, so another user's
  workspace-private chunks can never enter a prompt;
* attachments are read through the documented version authorizer, so an id
  belonging to somebody else is a 404 and never reaches the model.
"""

from __future__ import annotations

import base64
import hashlib
import sqlite3
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response

from app.config import Settings
from app.course_access import require_course_access
from app.db import Database
from app.errors import ApiError
from app.learning.orchestrator import LearningOrchestrator
from app.learning.previews import IMAGE_MEDIA_TYPES
from app.learning.problems import ProblemRepository
from app.learning.workspaces import (
    current_document_version,
    document_for,
    join_course,
    original_path,
)
from app.rag.retrieval import HybridRetriever
from app.repositories.chunks import RetrievalAccess
from app.services.ingestion import IngestionService

# The UI palette is a presentation concern; V3 courses have no colour column, so
# a stable value is derived from the course id instead of inventing a schema field.
_PALETTE = ("#38585b", "#756480", "#2f6f4f", "#8a5a2b", "#3f5d9c", "#7a3f5d")

# Default display timezone for a date-only agent task. The Node agent stores
# YYYY-MM-DD without a zone, so the UI is told the zone this project already
# defaults to for Hong Kong timetables rather than pretending the value is UTC.
_DEFAULT_TASK_TIMEZONE = "Asia/Hong_Kong"

_UI_SCHEMA_LOCK = "ui-extension-schema"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _colour(course_id: str) -> str:
    return _PALETTE[sum(course_id.encode()) % len(_PALETTE)]


class _RequestCache:
    """Per-request memo so one UI action does not re-read the same course N times."""

    __slots__ = ("courses", "snapshots", "workspaces")

    def __init__(self) -> None:
        self.courses: dict[str, dict[str, Any]] = {}
        self.workspaces: dict[str, dict[str, Any]] = {}
        self.snapshots: dict[str, dict[str, Any]] = {}


_CACHE: ContextVar[_RequestCache | None] = ContextVar("cmui_request_cache", default=None)


def _cache() -> _RequestCache:
    current = _CACHE.get()
    if current is None:
        current = _RequestCache()
        _CACHE.set(current)
    return current


class V3DomainAdapter:
    """``DomainPort`` over the existing CourseMate V3 services."""

    def __init__(
        self,
        *,
        database: Database,
        settings: Settings,
        ingestion: IngestionService,
        learning: LearningOrchestrator | None,
        retriever: HybridRetriever,
        task_agent_url: str = "",
        task_agent_timeout: float = 60.0,
        task_agent_credential: str = "",
    ) -> None:
        self.database = database
        self.settings = settings
        self.ingestion = ingestion
        self.learning = learning
        self.retriever = retriever
        self.problems = ProblemRepository(database)
        self.task_agent_url = task_agent_url.rstrip("/")
        self.task_agent_timeout = task_agent_timeout
        self.task_agent_credential = task_agent_credential

    # ------------------------------------------------------------------ helpers

    def _begin_request(self) -> None:
        _CACHE.set(_RequestCache())

    def _is_admin(self, subject: str) -> bool:
        return subject in self.settings.admin_user_id_set

    def _workspace_row(self, course_id: str, subject: str) -> sqlite3.Row | None:
        """Return the caller's workspace for a course, creating it on first use.

        Creating the workspace is what gives the user a private corpus course for
        their own uploads; it is the same call the V3 learning page makes, so no
        second storage model is introduced.
        """

        cached = _cache().workspaces.get(course_id)
        if cached is not None:
            return cast(sqlite3.Row, cached) if cached else None
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM learning_workspaces WHERE course_id=? AND owner_user_id=?",
                (course_id, subject),
            ).fetchone()
        if row is not None:
            _cache().workspaces[course_id] = dict(row)
            return row
        workspace = join_course(
            self.database, course_id, subject, self.settings.user_course_max_courses
        )
        _cache().workspaces[course_id] = workspace
        with self.database.connect() as connection:
            fresh = connection.execute(
                "SELECT * FROM learning_workspaces WHERE id=?", (workspace["id"],)
            ).fetchone()
        return fresh

    @staticmethod
    def _course_dto(row: sqlite3.Row | dict[str, Any], *, requirements: str = "") -> dict[str, Any]:
        official = row["course_type"] == "official"
        return {
            "id": row["id"],
            "code": str(row["id"]).upper(),
            "name": row["name"],
            "description": row["description"] or "",
            "color": _colour(str(row["id"])),
            "visibility": row["visibility"],
            "official": bool(official),
            "owner": row["owner_user_id"],
            "course_type": row["course_type"],
            "publication_status": row["publication_status"] if "publication_status" in row.keys() else "private",
            "preferred_language": row["preferred_language"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "requirements": requirements,
        }

    def _requirements(self, course_id: str, subject: str) -> str:
        """Return the newest teaching profile's requirements for this caller.

        V3 keeps the student's course requirements in `course_teaching_profiles`
        (`custom_requirements` + `learning_goal`), which is the real source the
        Qwen planner already reads. A course without a profile has none.
        """

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT learning_goal,custom_requirements FROM course_teaching_profiles "
                "WHERE course_id=? AND created_by_user_id=? ORDER BY version DESC LIMIT 1",
                (course_id, subject),
            ).fetchone()
        if row is None:
            return ""
        goal = (row["learning_goal"] or "").strip()
        custom = (row["custom_requirements"] or "").strip()
        return "\n".join(part for part in (goal, custom) if part)

    def _course_row(self, course_id: str, subject: str, *, write: bool = False) -> sqlite3.Row:
        row = require_course_access(
            self.database,
            course_id,
            owner_user_id=subject,
            is_admin=self._is_admin(subject),
            write=write,
        )
        return row

    def _course_dto_for(self, course_id: str, subject: str, *, write: bool = False) -> dict[str, Any]:
        cached = _cache().courses.get(course_id)
        if cached is not None and not write:
            return cached
        row = self._course_row(course_id, subject, write=write)
        dto = self._course_dto(row, requirements=self._requirements(course_id, subject))
        _cache().courses[course_id] = dto
        return dto

    # ------------------------------------------------------------------- courses

    def _list_courses(self, subject: str) -> list[dict[str, Any]]:
        where = "(visibility='public' OR owner_user_id=?)"
        if self.settings.v3_enabled:
            where += (
                " AND NOT EXISTS (SELECT 1 FROM learning_workspaces "
                "WHERE private_course_id=courses.id)"
            )
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM courses WHERE "
                + where
                + " ORDER BY CASE course_type WHEN 'official' THEN 0 ELSE 1 END,"
                " updated_at DESC, id",
                (subject,),
            ).fetchall()
        return [self._course_dto(row, requirements="") for row in rows]

    def _create_course(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ApiError(422, "INVALID_COURSE", "A course name is required.")
        course_id = self._new_course_id(name)
        record = self.ingestion.create_course(
            _course_create_model(course_id, name, str(payload.get("description") or "")),
            owner_user_id=subject,
            is_admin=False,
        )
        dto = self._course_dto_for(course_id, subject, write=True)
        dto["name"] = record.name
        dto["description"] = record.description
        description = str(payload.get("description") or "")
        if dto["description"] != description:
            dto["description"] = description
        return dto

    @staticmethod
    def _new_course_id(name: str) -> str:
        slug = "".join(
            character if character.isalnum() else "-" for character in name.casefold()
        ).strip("-")
        slug = "-".join(part for part in slug.split("-") if part)[:40]
        if not slug or not slug[0].isalnum() or len(slug) < 2:
            slug = ("course-" + slug)[:40]
        return f"{slug}-{datetime.now(UTC).strftime('%y%m%d%H%M%S')}"

    def _update_course(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        course_id = str(payload["id"])
        self._course_row(course_id, subject, write=True)
        record = self.ingestion.update_course(
            course_id,
            _course_update_model(
                payload.get("name"), payload.get("description")
            ),
            owner_user_id=subject,
            is_admin=self._is_admin(subject),
        )
        requirements = str(payload.get("requirements") or "").strip()
        if requirements:
            self._save_requirements(course_id, subject, requirements)
        _cache().courses.pop(course_id, None)
        dto = self._course_dto_for(course_id, subject, write=True)
        dto["name"] = record.name
        dto["description"] = record.description
        return dto

    def _save_requirements(self, course_id: str, subject: str, requirements: str) -> None:
        """Store updated course requirements on the caller's newest teaching profile.

        V3 owns the schemas of `course_teaching_profiles` and `teaching_specs`; the
        UI's free-text "course requirements" box is the student's own requirement
        statement, which is exactly what the profile carries. When the caller has
        no profile yet, the requirement is remembered in the UI database by
        `cm_update` instead, so nothing is invented here.
        """

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id,version FROM course_teaching_profiles "
                "WHERE course_id=? AND created_by_user_id=? ORDER BY version DESC LIMIT 1",
                (course_id, subject),
            ).fetchone()
            if row is None:
                return
            connection.execute(
                "UPDATE course_teaching_profiles SET custom_requirements=?, updated_at=? "
                "WHERE id=?",
                (requirements, _now(), row["id"]),
            )

    def _delete_course(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        course_id = str(payload["id"])
        confirm = str(payload.get("confirm") or "")
        row = self._course_row(course_id, subject, write=True)
        if confirm != row["name"]:
            raise ApiError(422, "CONFIRM_MISMATCH", "The confirmation name does not match.")
        self.ingestion.delete_course(
            course_id, owner_user_id=subject, is_admin=self._is_admin(subject)
        )
        _cache().courses.pop(course_id, None)
        return {"deleted": True, "inaccessible_files_pending_cleanup": 0}

    # --------------------------------------------------------------------- files

    def _file_rows(self, course_id: str, subject: str) -> list[dict[str, Any]]:
        """Project the caller's accessible V3 documents into UI file DTOs.

        `official` documents come from the course corpus; the caller's own uploads
        live in their workspace-private corpus course, which is why both sources
        are unioned here. No `stored_path` ever leaves the server.
        """

        workspace = self._workspace_row(course_id, subject)
        private_course = workspace["private_course_id"] if workspace is not None else None
        official = (
            "(version.course_id=? AND (version.source_scope='OFFICIAL' OR "
            "(version.source_scope='OWNER_COURSE' AND (version.owner_user_id=? OR EXISTS("
            "SELECT 1 FROM courses AS source_course WHERE source_course.id=version.course_id "
            "AND source_course.visibility='public' "
            "AND source_course.publication_status='published')))))"
        )
        private = (
            "(version.course_id=? AND version.source_scope='WORKSPACE_PRIVATE' "
            "AND version.owner_user_id=?)"
        )
        parameters: tuple[object, ...]
        if private_course is None:
            clause = official
            parameters = (course_id, subject)
        else:
            clause = f"({official} OR {private})"
            parameters = (course_id, subject, private_course, subject)
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT documents.id,documents.status,documents.chunk_count,"
                "documents.created_at,version.filename,version.extension,version.byte_size,"
                "version.sha256,version.source_scope,version.course_id,version.id AS version_id "
                "FROM documents JOIN document_versions AS version "
                "ON version.document_id=documents.id AND version.version=("
                "  SELECT MAX(latest.version) FROM document_versions AS latest "
                "  WHERE latest.document_id=documents.id) "
                f"WHERE {clause} ORDER BY version.filename COLLATE NOCASE,documents.id",
                parameters,
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            path = original_path(
                self.database,
                self._version_row(row["version_id"]) or row,
            )
            items.append(
                {
                    "id": row["id"],
                    "name": row["filename"],
                    "folder": _folder_for(row["filename"], row["source_scope"]),
                    "size": row["byte_size"],
                    "mime": _media_type(row["extension"]),
                    "scope": "private" if row["source_scope"] == "WORKSPACE_PRIVATE" else "public",
                    "status": _file_status(row["status"], path is not None),
                    "version_id": row["version_id"],
                    "sha256": row["sha256"],
                    "error": None if path is not None else "原件暂不可用",
                }
            )
        return items

    def _version_row(self, version_id: str) -> sqlite3.Row | None:
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT * FROM document_versions WHERE id=?", (version_id,)
            ).fetchone()

    def _file_upload(
        self, subject: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        course_id = str(payload["course"])
        self._course_row(course_id, subject, write=False)
        workspace = self._workspace_row(course_id, subject)
        if workspace is None:
            raise ApiError(
                409,
                "WORKSPACE_UNAVAILABLE",
                "This course cannot accept private uploads for the current account.",
            )
        content = payload.get("content")
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise ApiError(422, "EMPTY_UPLOAD", "The uploaded file is empty.")
        accepted = self.ingestion.queue_document(
            course_id=workspace["private_course_id"],
            filename=str(payload.get("name") or ""),
            media_type=str(payload.get("mime") or "application/octet-stream"),
            content=bytes(content),
            owner_user_id=subject,
            is_admin=False,
        )
        # Ingestion runs here, synchronously and bounded, so the response reports the
        # real post-ingestion status rather than the 'pending' row handed back by
        # `queue_document`. Re-read afterwards instead of trusting that stale copy.
        self.ingestion.process_document(accepted.document.id, accepted.job.id)
        document = self._document_row(accepted.document.id)
        if document is None:
            raise ApiError(500, "UPLOAD_LOST", "The uploaded file could not be confirmed.")
        version = current_document_version(self.database, document["id"], subject)
        path = original_path(self.database, version)
        return {
            "id": document["id"],
            "name": document["filename"],
            "folder": _folder_for(document["filename"], "WORKSPACE_PRIVATE"),
            "size": document["byte_size"],
            "mime": document["media_type"],
            "scope": "private",
            "status": _file_status(document["status"], path is not None),
            "version_id": version["id"],
            "error": document["error_message"],
        }

    def _document_row(self, document_id: str) -> sqlite3.Row | None:
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT * FROM documents WHERE id=?", (document_id,)
            ).fetchone()

    def _file_content(self, subject: str, payload: dict[str, Any]) -> Response:
        course_id = str(payload["course"])
        self._course_row(course_id, subject)
        version = current_document_version(self.database, str(payload["id"]), subject)
        path = original_path(self.database, version)
        if path is None:
            raise ApiError(410, "ORIGINAL_UNAVAILABLE", "The original file is unavailable.")
        download = bool(payload.get("download"))
        media = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".txt": "text/plain; charset=utf-8",
            ".md": "text/plain; charset=utf-8",
        }
        inline_ok = version["extension"] in media
        return FileResponse(
            path,
            media_type=media.get(version["extension"], "application/octet-stream"),
            filename=version["filename"],
            content_disposition_type=(
                "attachment" if download or not inline_ok else "inline"
            ),
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    def _file_text(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        course_id = str(payload["course"])
        self._course_row(course_id, subject)
        document = document_for(self.database, str(payload["id"]), subject)
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT locator_type,locator_value,content FROM chunks "
                "WHERE document_id=? ORDER BY ordinal LIMIT 150",
                (document["id"],),
            ).fetchall()
        pages = [
            {
                "page": _page_number(row["locator_type"], row["locator_value"]),
                "text": row["content"],
            }
            for row in rows
        ]
        return {"pages": pages}

    def _file_delete(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        course_id = str(payload["course"])
        self._course_row(course_id, subject)
        document = document_for(self.database, str(payload["id"]), subject)
        if document["course_id"] == course_id:
            raise ApiError(
                403,
                "SHARED_DOCUMENT",
                "Shared course materials cannot be deleted from the new interface.",
            )
        self.ingestion.delete_document(
            document["course_id"],
            document["id"],
            owner_user_id=subject,
            is_admin=self._is_admin(subject),
        )
        return {"deleted": True}

    # ---------------------------------------------------------------- retrieval

    def _retrieve(self, subject: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        course_id = str(payload["course"])
        self._course_row(course_id, subject)
        query = str(payload.get("query") or "").strip()
        if not query:
            return []
        workspace = self._workspace_row(course_id, subject)
        top_k = self.settings.top_k
        sources: list[dict[str, Any]] = []
        hit_rows = self.retriever.retrieve(
            course_id=course_id,
            query=query,
            top_k=top_k,
            access=RetrievalAccess(owner_user_id=subject, scope="official"),
        )
        if workspace is not None:
            hit_rows = [
                *hit_rows,
                *self.retriever.retrieve(
                    course_id=workspace["private_course_id"],
                    query=query,
                    top_k=top_k,
                    access=RetrievalAccess(owner_user_id=subject, scope="mine"),
                ),
            ]
        seen: set[str] = set()
        for index, hit in enumerate(hit_rows[: top_k * 2], start=1):
            if hit.chunk_id in seen:
                continue
            seen.add(hit.chunk_id)
            sources.append(
                {
                    "id": f"S{len(sources) + 1}",
                    "document_id": hit.document_id,
                    "name": hit.filename,
                    "page": _page_number(hit.locator_type, hit.locator_value),
                    "locator": f"{hit.locator_type}:{hit.locator_value}",
                    "section": hit.section,
                    "text": hit.content[: self.settings.max_context_chars // max(index, 1)][:4000],
                }
            )
            if len(sources) >= top_k:
                break
        return sources

    def _attachments(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        course_id = str(payload["course"])
        self._course_row(course_id, subject)
        workspace = self._workspace_row(course_id, subject)
        images: list[dict[str, Any]] = []
        metadata: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        for raw in payload.get("ids") or []:
            file_id = str(raw)
            try:
                document = document_for(self.database, file_id, subject)
            except ApiError:
                raise ApiError(404, "ATTACHMENT_NOT_FOUND", "The attachment was not found.") from None
            version = current_document_version(self.database, file_id, subject)
            metadata.append(
                {
                    "id": file_id,
                    "name": version["filename"],
                    "mime": version["media_type"],
                    "version_id": version["id"],
                }
            )
            media_type = IMAGE_MEDIA_TYPES.get(version["extension"])
            if media_type not in {"image/png", "image/jpeg"}:
                continue
            if workspace is None:
                raise ApiError(
                    404, "ATTACHMENT_NOT_FOUND", "The attachment was not found."
                )
            if version["byte_size"] > self.settings.v3_problem_image_max_bytes:
                raise ApiError(
                    413,
                    "IMAGE_MODEL_LIMIT",
                    "The image exceeds the bounded model-input size.",
                    details={"limitBytes": self.settings.v3_problem_image_max_bytes},
                )
            # Authorised through the documented version gate above; the bytes are
            # returned to the provider layer only and never persisted or logged.
            image, descriptor = self.problems.image_input(
                workspace["id"],
                subject,
                version["id"],
                max_bytes=self.settings.v3_problem_image_max_bytes,
            )
            images.append(
                {
                    "id": file_id,
                    "media_type": image.media_type,
                    "data_url": "data:"
                    + image.media_type
                    + ";base64,"
                    + base64.b64encode(image.content).decode("ascii"),
                }
            )
            sources.append(
                {
                    "id": f"S{len(sources) + 1}",
                    "document_id": document["id"],
                    "name": descriptor["filename"],
                    "page": None,
                    "locator": "image",
                    "section": None,
                    "text": f"随题目上传的图片附件：{descriptor['filename']}",
                }
            )
        return {"images": images, "metadata": metadata, "sources": sources}

    # -------------------------------------------------------------------- tasks

    def _agent_headers(self, credential: str) -> dict[str, str]:
        token = credential or self.task_agent_credential
        if token and not token.lower().startswith("bearer "):
            token = "Bearer " + token
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = token
        return headers

    def _agent_request(
        self,
        method: str,
        path: str,
        credential: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        if not self.task_agent_url:
            raise ApiError(
                503,
                "TASK_AGENT_UNAVAILABLE",
                "The study-plan agent is not configured for this deployment.",
            )
        url = self.task_agent_url + path
        try:
            with httpx.Client(timeout=self.task_agent_timeout, follow_redirects=False) as client:
                response = client.request(
                    method, url, headers=self._agent_headers(credential), json=json_body
                )
        except httpx.TimeoutException as error:
            raise ApiError(
                504, "TASK_AGENT_TIMEOUT", "The study-plan agent did not answer in time."
            ) from error
        except httpx.HTTPError as error:
            raise ApiError(
                502, "TASK_AGENT_UNREACHABLE", "The study-plan agent could not be reached."
            ) from error
        if response.status_code == 401:
            raise ApiError(401, "UNAUTHENTICATED", "A valid sign-in session is required.")
        if response.status_code == 204:
            return None
        try:
            body = response.json()
        except ValueError as error:
            raise ApiError(
                502, "TASK_AGENT_INVALID", "The study-plan agent returned an invalid response."
            ) from error
        if response.status_code >= 400:
            detail = body.get("error") if isinstance(body, dict) else None
            message = (
                detail.get("message")
                if isinstance(detail, dict) and isinstance(detail.get("message"), str)
                else "The study-plan agent rejected the request."
            )
            raise ApiError(response.status_code, "TASK_AGENT_ERROR", message)
        return body

    @staticmethod
    def _task_dto(task: dict[str, Any]) -> dict[str, Any]:
        due = task.get("dueDate")
        due_at = f"{due}T09:00:00.000Z" if isinstance(due, str) and due else None
        status = task.get("status")
        return {
            "id": task.get("id"),
            "title": task.get("title") or "",
            "notes": task.get("notes"),
            "due_at": due_at,
            "timezone": _DEFAULT_TASK_TIMEZONE,
            "course": task.get("courseId"),
            "status": "done" if status == "completed" else "todo",
            "priority": task.get("priority"),
            "version": _task_version(task),
            "created_at": task.get("createdAt"),
            "updated_at": task.get("updatedAt"),
            "completed_at": task.get("completedAt"),
        }

    def _task_list(self, credential: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while page <= 10:
            body = self._agent_request(
                "GET", f"/api/tasks?page={page}&pageSize=100", credential
            )
            rows = body.get("items") if isinstance(body, dict) else None
            if not isinstance(rows, list):
                break
            items.extend(self._task_dto(row) for row in rows if isinstance(row, dict))
            total = body.get("total") if isinstance(body, dict) else None
            if not isinstance(total, int) or len(items) >= total:
                break
            page += 1
        return items

    def _task_create(self, credential: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = {
            "title": payload.get("title"),
            "notes": None,
            "courseId": payload.get("course"),
            "priority": None,
            "dueDate": _date_only(payload.get("due_at")),
            "sourceCitation": None,
        }
        return self._task_dto(
            self._agent_request("POST", "/api/tasks", credential, json_body=body)
        )

    def _task_update(self, credential: str, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = str(payload["id"])
        current = self._agent_request("GET", f"/api/tasks?page=1&pageSize=100", credential)
        existing = _find_task(current, task_id)
        if existing is None:
            raise ApiError(404, "TASK_NOT_FOUND", "The task was not found.")
        expected = payload.get("version")
        if expected is not None and int(expected) != _task_version_int(existing):
            raise ApiError(
                409,
                "VERSION_CONFLICT",
                "This task was changed elsewhere; reload before editing it.",
            )
        body: dict[str, Any] = {}
        if payload.get("title") is not None:
            body["title"] = payload["title"]
        if payload.get("due_at") is not None:
            body["dueDate"] = _date_only(payload["due_at"])
        if payload.get("status") is not None:
            body["status"] = "completed" if payload["status"] == "done" else "todo"
        if not body:
            return self._task_dto(existing)
        return self._task_dto(
            self._agent_request(
                "PATCH", f"/api/tasks/{task_id}", credential, json_body=body
            )
        )

    def _task_delete(self, credential: str, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = str(payload["id"])
        current = self._agent_request("GET", "/api/tasks?page=1&pageSize=100", credential)
        existing = _find_task(current, task_id)
        if existing is None:
            raise ApiError(404, "TASK_NOT_FOUND", "The task was not found.")
        expected = payload.get("version")
        if expected is not None and int(expected) != _task_version_int(existing):
            raise ApiError(
                409,
                "VERSION_CONFLICT",
                "This task was changed elsewhere; reload before deleting it.",
            )
        self._agent_request("DELETE", f"/api/tasks/{task_id}", credential)
        return {"deleted": True}

    def _task_plan(self, credential: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Run the existing Node tool-calling agent; never a regex or canned answer."""

        body = self._agent_request(
            "POST",
            "/api/agent/chat",
            credential,
            json_body={"message": payload.get("text")},
        )
        if not isinstance(body, dict) or not isinstance(body.get("message"), str):
            raise ApiError(
                502, "TASK_AGENT_INVALID", "The study-plan agent returned an invalid response."
            )
        return {"text": body["message"], "tool_results": body.get("toolResults") or []}

    # ---------------------------------------------------------------- knowledge

    def _knowledge(self, subject: str, course_id: str) -> dict[str, Any]:
        cached = _cache().snapshots.get(course_id)
        if cached is not None:
            return cached
        if self.learning is None or not self.settings.v3_enabled:
            snapshot: dict[str, Any] = {"registry": [], "members": []}
            _cache().snapshots[course_id] = snapshot
            return snapshot
        workspace = self._workspace_row(course_id, subject)
        if workspace is None:
            snapshot = {"registry": [], "members": []}
            _cache().snapshots[course_id] = snapshot
            return snapshot
        state = self.learning.knowledge_state(workspace["id"], subject)
        selected = (
            state.get("personalized_tree")
            if state.get("selected_tree") == "PERSONALIZED"
            else state.get("official_tree")
        ) or {}
        snapshot = {
            "registry": state.get("registry") or [],
            "members": selected.get("members") or [],
            "selected_tree": state.get("selected_tree"),
        }
        _cache().snapshots[course_id] = snapshot
        return snapshot

    def _knowledge_tree(self, subject: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        course_id = str(payload["course"])
        self._course_row(course_id, subject)
        snapshot = self._knowledge(subject, course_id)
        registry = {
            node["id"]: node
            for node in snapshot["registry"]
            if isinstance(node, dict) and node.get("id")
        }
        tree: list[dict[str, Any]] = []
        ordered = sorted(
            (member for member in snapshot["members"] if isinstance(member, dict)),
            key=lambda member: (member.get("parent_node_id") or "", member.get("ordinal") or 0),
        )
        for member in ordered:
            node_id = member.get("node_id")
            if not node_id:
                continue
            node = registry.get(node_id) or {}
            state = member.get("state") or node.get("state") or {}
            learning = state.get("learning") or {}
            assessment = state.get("assessment") or {}
            tree.append(
                {
                    "id": node_id,
                    "parent": member.get("parent_node_id"),
                    "title": node.get("title") or member.get("title") or node_id,
                    "description": node.get("description") or "",
                    "kind": node.get("kind"),
                    "position": member.get("ordinal") or 0,
                    "progress": learning.get("status") or "NOT_STARTED",
                    "grade": assessment.get("grade_label"),
                    "assessment": assessment,
                    "learning": learning,
                }
            )
        return tree

    def _knowledge_assessment(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        course_id = str(payload["course"])
        node_id = str(payload["node"])
        self._course_row(course_id, subject)
        snapshot = self._knowledge(subject, course_id)
        for node in snapshot["registry"]:
            if node.get("id") == node_id:
                assessment = (node.get("state") or {}).get("assessment") or {}
                return {
                    "node": node_id,
                    "status": assessment.get("status") or "NOT_ASSESSED",
                    "grade": assessment.get("grade_label"),
                    "score": assessment.get("raw_score"),
                    "session": assessment.get("session_id"),
                    "mode": assessment.get("mode"),
                    "assistance": assessment.get("assistance_status"),
                    "source": "V3 assessment engine",
                }
        raise ApiError(404, "NODE_NOT_FOUND", "The knowledge node was not found.")

    # ------------------------------------------------------------------ dispatch

    async def call(
        self, operation: str, subject: str, payload: dict[str, Any], credential: str = ""
    ) -> Any:
        try:
            return await self._dispatch(operation, subject, payload, credential)
        except ApiError as error:
            # FastAPI does not hand a mounted sub-application's exceptions to the
            # host's exception handlers, so the adapter translates the documented
            # V3 error envelope into the response contract `cm_update` expects.
            raise HTTPException(status_code=error.status_code, detail=error.message) from None

    async def _dispatch(
        self, operation: str, subject: str, payload: dict[str, Any], credential: str = ""
    ) -> Any:
        self._begin_request()
        course_operations = {
            "course.list",
            "course.get",
            "course.create",
            "course.update",
            "course.delete",
            "file.list",
            "file.upload",
            "file.content",
            "file.text",
            "file.delete",
            "context.retrieve",
            "attachments.prepare",
            "knowledge.tree",
            "knowledge.assessment",
        }
        if operation in course_operations:
            course_id = str(payload.get("course") or payload.get("id") or "")
            if course_id and operation not in {"course.list", "course.create"}:
                self._course_row(course_id, subject)

        if operation == "course.list":
            return self._list_courses(subject)
        if operation == "course.get":
            return self._course_dto_for(str(payload["id"]), subject)
        if operation == "course.create":
            return self._create_course(subject, payload)
        if operation == "course.update":
            return self._update_course(subject, payload)
        if operation == "course.delete":
            return self._delete_course(subject, payload)
        if operation == "file.list":
            query = str(payload.get("q") or "").strip().casefold()
            folder = payload.get("folder")
            items = self._file_rows(str(payload["course"]), subject)
            if query:
                items = [item for item in items if query in item["name"].casefold()]
            if folder:
                items = [item for item in items if item["folder"] == folder]
            return items
        if operation == "file.upload":
            return self._file_upload(subject, payload)
        if operation == "file.content":
            return self._file_content(subject, payload)
        if operation == "file.text":
            return self._file_text(subject, payload)
        if operation == "file.delete":
            return self._file_delete(subject, payload)
        if operation == "context.retrieve":
            return self._retrieve(subject, payload)
        if operation == "attachments.prepare":
            return self._attachments(subject, payload)
        if operation == "task.list":
            return self._task_list(credential)
        if operation == "task.create":
            return self._task_create(credential, payload)
        if operation == "task.update":
            return self._task_update(credential, payload)
        if operation == "task.delete":
            return self._task_delete(credential, payload)
        if operation == "task.plan":
            return self._task_plan(credential, payload)
        if operation == "knowledge.tree":
            return self._knowledge_tree(subject, payload)
        if operation == "knowledge.assessment":
            return self._knowledge_assessment(subject, payload)
        raise ApiError(
            501,
            "DOMAIN_OPERATION_UNSUPPORTED",
            f"The V3 adapter does not implement '{operation}'.",
        )


# ------------------------------------------------------------------ module helpers


def _course_create_model(course_id: str, name: str, description: str) -> Any:
    from app.models import CourseCreate

    return CourseCreate(id=course_id, name=name, description=description[:1000])


def _course_update_model(name: Any, description: Any) -> Any:
    from app.models import CourseUpdate

    return CourseUpdate(
        name=str(name).strip() if isinstance(name, str) and name.strip() else None,
        description=str(description)[:1000] if isinstance(description, str) else None,
    )


def _media_type(extension: str) -> str:
    return {
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".csv": "text/csv",
        ".ipynb": "application/x-ipynb+json",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
    }.get(extension, "application/octet-stream")


def _file_status(status: str, original_available: bool) -> str:
    if not original_available:
        return "unavailable"
    return {
        "ready": "indexed",
        "processing": "processing",
        "pending": "processing",
        "failed": "failed",
        "unsupported": "preview_only",
    }.get(status, "processing")


def _folder_for(filename: str, source_scope: str) -> str:
    lowered = filename.casefold()
    if "tutorial" in lowered:
        return "Tutorial"
    if source_scope == "WORKSPACE_PRIVATE":
        return "我的上传"
    return "Lecture Slides"


def _page_number(locator_type: str, locator_value: str) -> int | None:
    if locator_type not in {"page", "slide"}:
        return None
    try:
        return int(str(locator_value).strip())
    except (TypeError, ValueError):
        return None


def _date_only(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC)
    return parsed.date().isoformat()


def _task_version(task: dict[str, Any]) -> int:
    return _task_version_int(task)


def _task_version_int(task: dict[str, Any]) -> int:
    """Derive an optimistic-concurrency token from the agent's `updatedAt`.

    The Node task store has no integer version column, so the row's own
    `updatedAt` is used as the comparable revision. It is stable across reads and
    changes on every accepted write, which is all the UI needs to detect a
    concurrent edit; the agent remains the single source of truth either way.
    """

    stamp = str(task.get("updatedAt") or task.get("createdAt") or task.get("id") or "")
    digest = hashlib.sha256(stamp.encode()).hexdigest()
    # Keep it inside a 32-bit range so it round-trips through the UI's JSON number.
    return int(digest[:8], 16) % 2_000_000_000


def _find_task(body: Any, task_id: str) -> dict[str, Any] | None:
    rows = body.get("items") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and row.get("id") == task_id:
            return row
    return None


def build_adapter(
    request: Request,
    *,
    task_agent_url: str = "",
    task_agent_timeout: float = 60.0,
    task_agent_credential: str = "",
) -> V3DomainAdapter:
    """Build an adapter bound to the live host application state."""

    settings: Settings = request.app.state.settings
    database: Database = request.app.state.database
    ingestion: IngestionService = request.app.state.ingestion_service
    learning: LearningOrchestrator | None = getattr(request.app.state, "learning", None)
    retriever: HybridRetriever = request.app.state.qa_service.retriever
    return V3DomainAdapter(
        database=database,
        settings=settings,
        ingestion=ingestion,
        learning=learning,
        retriever=retriever,
        task_agent_url=task_agent_url or settings.ui_task_agent_url,
        task_agent_timeout=task_agent_timeout or settings.ui_task_agent_timeout_seconds,
        task_agent_credential=task_agent_credential,
    )
