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

import asyncio
import base64
import hashlib
import json
import sqlite3
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response

from app.config import Settings
from app.course_access import require_course_access
from app.db import Database
from app.errors import ApiError
from app.jev import callsites
from app.jev.entity_resolution import CourseEntityResolver, EntityObject
from app.jev.evidence_consistency import (
    COMPATIBLE,
    VERSION_OR_TASK_DIFFERENCE,
    check_evidence_consistency,
)
from app.jev.reference_verification import verify_query_reference
from app.jev.service import SemanticDecisionService
from app.learning.coverage_review import CoverageReviewer, NullCoverageReviewer
from app.learning.models import (
    AssessmentAbandonInput,
    AssessmentAnswer,
    AssessmentAttachment,
    AssessmentDraftInput,
    AssessmentExplanationInput,
    AssessmentPreparationStartInput,
    AssessmentStartInput,
    AssessmentSubmitInput,
)
from app.learning.orchestrator import LearningOrchestrator
from app.learning.previews import IMAGE_MEDIA_TYPES
from app.learning.problems import ProblemRepository
from app.learning.question_runtime import (
    QuestionEngineRuntime,
    QuestionEngineRuntimeError,
)
from app.learning.retrieval_orchestrator import (
    ScopedCandidates,
    budget_text,
    citation_id,
    exact_targets_from_query,
    fuse_scoped_candidates,
)
from app.learning.shell_delivery import submit_shell_delivery
from app.learning.shell_problems import record_shell_problem
from app.learning.workspaces import (
    current_document_version,
    document_for,
    join_course,
    original_path,
)
from app.rag.answers import evidence_bundle_support
from app.rag.retrieval import HybridRetriever
from app.repositories.chunks import RetrievalAccess
from app.services.ingestion import IngestionService
from app.tutor.references import parse_query_reference
from app.tutor.rewrite import rewrite_retrieval_query

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


def _assessment_display(assessment: dict[str, Any]) -> str | None:
    """Ready-to-render assessment label for the node panel.

    ``None`` means "no assessment yet" (the UI renders 未测评). A raw score is
    always shown when it exists — including when the school publishes no grade
    mapping — and is explicitly marked as an AI-graded self-assessment so it is
    never mistaken for an official grade. A running attempt keeps the previous
    valid result visible instead of blanking the panel.
    """

    if not assessment:
        return None
    status = str(assessment.get("status") or "")
    raw = assessment.get("raw_score")
    label = assessment.get("grade_label")
    score = f"{round(float(raw), 1)}/100" if isinstance(raw, (int, float)) else None
    if status == "GRADED":
        if label and score:
            return f"{label} · {score}"
        if label:
            return str(label)
        if score:
            return f"{score} · AI自测"
        return "已评分"
    if status == "PARTIALLY_ASSESSED":
        return f"{score} · 部分测评（AI自测）" if score else "部分测评"
    if status == "IN_PROGRESS":
        return f"测评进行中 · 上次 {score}" if score else "测评进行中"
    if status == "NEEDS_REVIEW":
        return "待复核"
    return None


def _consistency_signal(report: Any) -> dict[str, str]:
    """Deterministic per-candidate relation from the version/task narrowing only.

    Semantic relations (contradiction / different-assumptions / insufficient) are
    decided by the Jev mode, so they never enter this map. The map is therefore
    byte-identical under ``off``/``shadow``/unavailable and with no Jev at all.
    """
    signals: dict[str, str] = {}
    for finding in report.findings:
        if finding.relation == VERSION_OR_TASK_DIFFERENCE:
            signals[finding.left_id] = VERSION_OR_TASK_DIFFERENCE
            signals[finding.right_id] = VERSION_OR_TASK_DIFFERENCE
    return signals


def _contradiction_partners(report: Any) -> dict[str, list[str]]:
    """Map candidate id -> counterpart ids for genuine contradictions only.

    A genuine ``SAME_CONTEXT_CONTRADICTION`` only ever surfaces in mode ``on``, so
    this map is empty (and the conflict note absent) under off/shadow/unavailable.
    A ``DIFFERENT_ASSUMPTIONS`` or ``VERSION_OR_TASK_DIFFERENCE`` pair never enters
    it, so it is never described as a conflict.
    """
    partners: dict[str, list[str]] = {}
    for finding in report.contradictions:
        partners.setdefault(finding.left_id, []).append(finding.right_id)
        partners.setdefault(finding.right_id, []).append(finding.left_id)
    return partners


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
        coverage_reviewer: CoverageReviewer | None = None,
        jev: SemanticDecisionService | None = None,
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
        self.coverage_reviewer = coverage_reviewer or NullCoverageReviewer()
        # Non-authoritative semantic-decision layer. None (the default) disables
        # Jev entirely; the deterministic path is byte-identical to before.
        self.jev = jev
        self.question_engine = (
            QuestionEngineRuntime(
                database=database,
                provider=learning.provider,
                semantic_decisions=jev,
            )
            if learning is not None
            else None
        )
        # Course-scope entity resolution over already-authorized fused candidates.
        # Query expansion is deterministic (never reaches Jev); relation resolution
        # goes through the shared gateway and is returned, never applied.
        self.entity_resolver = CourseEntityResolver(
            self.jev.gateway if self.jev is not None else None
        )

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
        keys = row.keys()
        # display_type is a PRESENTATION label; access rules stay in
        # course_type/ownership plus the independent verification flag.
        if "display_type" in keys and row["display_type"]:
            display_type = row["display_type"]
        else:
            display_type = "campus" if official else "private"
        requires_verification = (
            bool(row["requires_student_verification"])
            if "requires_student_verification" in keys
            else official
        )
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
            "display_type": display_type,
            "requires_student_verification": requires_verification,
            "publication_status": row["publication_status"] if "publication_status" in keys else "private",
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

    def _course_row(self, course_id: str, subject: str, *, write: bool = False, content: bool = True) -> sqlite3.Row:
        row = require_course_access(
            self.database,
            course_id,
            owner_user_id=subject,
            is_admin=self._is_admin(subject),
            write=write,
            content=content,
        )
        return row

    def _course_dto_for(self, course_id: str, subject: str, *, write: bool = False) -> dict[str, Any]:
        cached = _cache().courses.get(course_id)
        if cached is not None and not write:
            return cached
        row = self._course_row(course_id, subject, write=write, content=write)
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
        for attempt in range(3):
            course_id = self._new_course_id()
            try:
                record = self.ingestion.create_course(
                    _course_create_model(course_id, name, str(payload.get("description") or "")),
                    owner_user_id=subject,
                    is_admin=False,
                )
                break
            except ApiError as exc:
                # The transactional INSERT arbitrates collisions, not a racy pre-check.
                if exc.code != "COURSE_EXISTS" or attempt == 2:
                    raise
        dto = self._course_dto_for(course_id, subject, write=True)
        dto["name"] = record.name
        dto["description"] = record.description
        description = str(payload.get("description") or "")
        if dto["description"] != description:
            dto["description"] = description
        return dto

    @staticmethod
    def _new_course_id() -> str:
        # Display names are Unicode; domain IDs are independent ASCII (max 50).
        return f"course-{uuid4().hex}"

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

    def _create_shared_course(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Receiver-side copy of a shared course snapshot: a real V3 course
        owned by the recipient, display_type='shared', with the snapshot's
        verification requirement preserved independently of its display label."""
        name = str(payload.get("name") or "共享课程")[:120]
        description = str(payload.get("description") or "")[:1000]
        course_id = "share-" + hashlib.sha256(
            f"{payload.get('share_id')}:{subject}".encode()
        ).hexdigest()[:20]
        with self.database.connect() as connection:
            existing = connection.execute('SELECT owner_user_id FROM courses WHERE id=?', (course_id,)).fetchone()
        if existing is None:
            try:
                self.ingestion.create_course(
                    _course_create_model(course_id, name, description),
                    owner_user_id=subject, is_admin=False)
            except ApiError as error:
                if error.code!='COURSE_EXISTS': raise
                # Another worker can win the deterministic creation race.
                # Re-authorize the winner instead of trusting a conflicting ID.
                self._course_row(course_id,subject,write=True)
        elif existing['owner_user_id'] != subject:
            raise ApiError(404, 'COURSE_NOT_FOUND', 'Course not found.')
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE courses SET display_type='shared', "
                "requires_student_verification=? WHERE id=?",
                (1 if payload.get("requires_student_verification") else 0, course_id),
            )
        _cache().courses.pop(course_id, None)
        return self._course_dto_for(course_id, subject, write=True)

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
        if str(payload['id']) not in {item['id'] for item in self._file_rows(course_id,subject)}:
            raise ApiError(404,'DOCUMENT_NOT_FOUND','Document not found in this course.')
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

    def _snapshot_export(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Only the authenticated share service calls this internal operation."""
        course_id = str(payload['course'])
        self._course_row(course_id, subject)
        allowed = {item['version_id']: item for item in self._file_rows(course_id, subject)}
        version_id = str(payload['version_id'])
        if version_id not in allowed:
            raise ApiError(404, 'DOCUMENT_NOT_FOUND', 'Document not found.')
        with self.database.connect() as connection:
            version = dict(connection.execute('SELECT * FROM document_versions WHERE id=?', (version_id,)).fetchone())
            document = connection.execute('SELECT status FROM documents WHERE id=?', (version['document_id'],)).fetchone()
            chunks = [dict(row) for row in connection.execute(
                'SELECT chunks.* FROM chunks JOIN chunk_source_versions v ON v.chunk_id=chunks.id WHERE v.document_version_id=? ORDER BY ordinal', (version_id,))]
        path = original_path(self.database, version)
        if path is None or document['status'] != 'ready':
            raise ApiError(409, 'SNAPSHOT_SOURCE_NOT_READY', 'File is not ready for a complete snapshot.')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != version['sha256']:
            raise ApiError(409, 'SNAPSHOT_HASH_MISMATCH', 'Snapshot integrity check failed.')
        return {'content': content, 'index': {key: version[key] for key in
                ('document_id','id','filename','media_type','sha256','source_scope')}
                | {'chunks': chunks, 'embedding_model': self.settings.rag_embedding_model}}

    def _snapshot_import(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._course_row(str(payload['course']), subject, write=True)
        workspace = self._workspace_row(str(payload['course']), subject)
        # Keep the source's two authorized corpora distinct. Equal bytes in
        # course materials and personal notes are still distinct file entries.
        scope=payload['index']['source_scope']
        if scope not in {'OFFICIAL','OWNER_COURSE','WORKSPACE_PRIVATE'}:
            raise ApiError(409,'INVALID_SNAPSHOT_SCOPE','Invalid snapshot source scope.')
        destination=workspace['private_course_id'] if scope=='WORKSPACE_PRIVATE' else str(payload['course'])
        return self.ingestion.import_snapshot(course_id=destination,
            owner_user_id=subject, content=payload['content'], snapshot=payload['index'])

    def _file_text(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        course_id = str(payload["course"])
        self._course_row(course_id, subject)
        if str(payload['id']) not in {item['id'] for item in self._file_rows(course_id,subject)}:
            raise ApiError(404,'DOCUMENT_NOT_FOUND','Document not found in this course.')
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
        if str(payload['id']) not in {item['id'] for item in self._file_rows(course_id,subject)}:
            raise ApiError(404,'DOCUMENT_NOT_FOUND','Document not found in this course.')
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

    def _accepted_name_groups(self, course_id: str, subject: str) -> tuple[tuple[str, ...], ...]:
        """Accepted names per concept, as the deterministic backend owns them.

        One group per knowledge node: its canonical title first, then its
        already-accepted aliases. Query expansion uses a group only when the query
        itself names one of its members, so a Chinese question about "密度聚类" can
        gain "DBSCAN" while an unrelated question in the same course gains nothing —
        a course-wide alias list is never injected into every query. Returns ``()``
        when the registry is unavailable (or the course has no accepted names),
        which keeps the retrieval query byte-identical to the un-expanded form.
        """
        try:
            with self.database.connect() as connection:
                rows = connection.execute(
                    "SELECT node.title AS title, alias.alias AS alias "
                    "FROM knowledge_node_aliases AS alias "
                    "JOIN knowledge_nodes AS node ON node.id = alias.node_id "
                    "WHERE node.course_id = ? AND ("
                    "(node.owner_user_id = ? AND node.status = 'PRIVATE') OR "
                    "(node.owner_user_id IS NULL AND node.status = 'PUBLISHED')) "
                    "ORDER BY node.title, alias.normalized_alias, alias.locale",
                    (course_id, subject),
                ).fetchall()
        except Exception:  # pragma: no cover - registry is optional for retrieval
            return ()
        groups: dict[str, list[str]] = {}
        for row in rows:
            title = str(row["title"] or "").strip()
            alias = str(row["alias"] or "").strip()
            if not title or not alias:
                continue
            names = groups.setdefault(title, [])
            if alias not in names:
                names.append(alias)
        return tuple((title, *names) for title, names in groups.items())

    def _persist_relation_proposals(
        self,
        report: Any,
        *,
        objects: list[EntityObject],
        course_id: str,
        material_revision: str,
    ) -> int:
        """Record the resolved relations as PROPOSED rows for the backend to review.

        This is the one write the contract allows here, and it is proposal-only:
        the row's ``status`` is ``PROPOSED`` and the semantic layer can never write
        ``ACCEPTED``/``REJECTED``, so nothing is merged, deleted, renamed or
        reordered. ``INSERT OR IGNORE`` against ``UNIQUE(left_id, right_id,
        relation)`` makes a repeated retrieval idempotent. A missing table or a
        locked database degrades to "no proposal recorded" — bookkeeping must never
        break retrieval.
        """
        relations = list(getattr(report, "relations", ()) or ())
        if not relations:
            return 0
        versions = {obj.object_id: obj.source_version for obj in objects}
        recorded = 0
        try:
            with self.database.connect() as connection:
                for relation in relations:
                    left_id = str(getattr(relation, "left_id", "") or "")
                    right_id = str(getattr(relation, "right_id", "") or "")
                    label = str(getattr(relation, "relation", "") or "")
                    if not left_id or not right_id or not label:
                        continue
                    cursor = connection.execute(
                        "INSERT OR IGNORE INTO entity_relations("
                        "id,left_id,right_id,left_source_version,right_source_version,"
                        "course_id,material_revision,relation,evidence,status,"
                        "receipt_id,used_jev) "
                        "VALUES(?,?,?,?,?,?,?,?,?,'PROPOSED',?,?)",
                        (
                            uuid4().hex,
                            left_id,
                            right_id,
                            versions.get(left_id),
                            versions.get(right_id),
                            course_id,
                            material_revision,
                            label,
                            str(getattr(relation, "reason", "") or ""),
                            getattr(relation, "receipt_id", None),
                            1 if getattr(relation, "used_jev", False) else 0,
                        ),
                    )
                    recorded += 1 if cursor.rowcount == 1 else 0
        except sqlite3.Error:  # pragma: no cover - proposal bookkeeping is best effort
            return recorded
        return recorded

    def _resolve_entity_relations(
        self,
        subject: str,
        course_id: str,
        workspace: sqlite3.Row | None,
        fused: list[Any],
    ) -> Any:
        """Resolve pairwise relations over already-authorized fused candidates.

        The report is returned (a proposal set) and never applied: it cannot
        reorder, merge, delete or rename anything on the path. The only write is
        the proposal row described in :meth:`_persist_relation_proposals`. Under
        off/shadow/unavailable every semantic relation is UNCERTAIN and the
        deterministic fused order is untouched.
        """
        if self.jev is None or not fused:
            return None
        revision = str(workspace["revision"]) if workspace is not None else "0"
        objects = [
            EntityObject(
                object_id=entry.chunk_id,
                kind="evidence",
                course_id=course_id,
                material_revision=revision,
                label=str(getattr(entry.hit, "filename", "") or entry.chunk_id),
                content=str(getattr(entry.hit, "content", "") or ""),
                source_version=str(getattr(entry.hit, "document_id", "") or ""),
                aliases=(),
            )
            for entry in fused
        ]
        scope = self.jev.scope(
            owner_user_id=subject,
            authorization_scope="entity_resolution",
            course_id=course_id,
            workspace_id=str(workspace["id"]) if workspace is not None else None,
            material_revision=revision if workspace is not None else None,
        )
        report = self.entity_resolver.resolve(
            objects,
            course_id=course_id,
            material_revision=revision,
            cache_scope=scope,
        )
        self._persist_relation_proposals(
            report,
            objects=objects,
            course_id=course_id,
            material_revision=revision,
        )
        return report

    def _retrieve(self, subject: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Authorized multi-scope recall with ONE global ranking.

        Order (deterministic, no model): authorize course/workspace -> rewrite the
        query from bounded history -> recall keyword/vector/structured candidates
        per authorized scope -> merge scopes and fuse ranks (official and private
        compete on the same scale; append order is not a score) -> protect
        explicit file/page/question references -> budget the text -> assign the
        public S1..Sn ids.
        """

        course_id = str(payload["course"])
        self._course_row(course_id, subject)
        raw_query = str(payload.get("query") or "").strip()
        if not raw_query:
            return []
        history = payload.get("history") or []
        query = raw_query
        if history:
            try:
                # `rewrite_retrieval_query` returns a RewriteResult (see
                # app/services/qa.py), not a bare string.
                rewritten = rewrite_retrieval_query(raw_query, history)
                candidate_query = getattr(rewritten, "query", None) or (
                    rewritten if isinstance(rewritten, str) else None
                )
                if isinstance(candidate_query, str) and candidate_query.strip():
                    query = candidate_query.strip()
            except Exception:  # pragma: no cover - rewrite is best effort
                query = raw_query
        workspace = self._workspace_row(course_id, subject)
        # Conservative alias expansion (deterministic, never reaches Jev): a concept
        # the query already names may contribute its other accepted names, which can
        # only ADD recall. The user's original query is always the prefix, an
        # unrelated query is never expanded, and an explicit file/page/question
        # target skips expansion entirely so it can never be displaced or outranked.
        exact_targets = exact_targets_from_query(raw_query)
        expanded = self.entity_resolver.expand_query(
            query,
            name_groups=self._accepted_name_groups(course_id, subject),
            explicit_targets=[target.raw for target in exact_targets],
        )
        query = expanded.expanded_query
        top_k = int(self.settings.top_k)
        candidates = int(getattr(self.settings, "retrieval_candidates", 40) or 40)
        access = RetrievalAccess(owner_user_id=subject, scope="official")
        official_hits = self.retriever.retrieve(
            course_id=course_id, query=query, top_k=candidates, access=access
        )
        groups: list[ScopedCandidates] = [ScopedCandidates(scope="official", hits=official_hits)]
        # Structured exact retrieval reuses the legacy QA locator parser so an
        # explicit "file.pdf page 3 question 2" reference is recalled precisely
        # instead of being left to similarity search. That reference is a HARD
        # filter on chunk metadata in both the official and the private scope, so
        # the label it carries is verified first (module A): deterministic checks
        # over the label and its locator, then Jev over the learner's own words.
        # Only an affirmative defect removes a label, and removing one can only
        # ever take a filter away. With Jev off/shadow/unavailable the
        # deterministic reference is used unchanged and a receipt is recorded.
        try:
            parsed_reference = parse_query_reference(raw_query)
        except Exception:  # pragma: no cover - parser is defensive
            parsed_reference = None
        reference_verification: dict[str, Any] | None = None
        reference = parsed_reference
        if parsed_reference is not None:
            verified = verify_query_reference(
                raw_query,
                parsed_reference,
                service=self.jev,
                owner_user_id=subject,
                authorization_scope="official",
                course_id=course_id,
            )
            reference = verified.reference
            reference_verification = verified.as_dict()
        if reference is not None:
            structured: list[Any] = []
            if workspace is not None:
                structured = self.retriever.retrieve_structured(
                    course_id=workspace["private_course_id"],
                    reference=reference,
                    top_k=top_k,
                    access=RetrievalAccess(owner_user_id=subject, scope="mine"),
                )
            official_structured = self.retriever.retrieve_structured(
                course_id=course_id,
                reference=reference,
                top_k=top_k,
                access=access,
            )
            if official_structured:
                groups[0] = ScopedCandidates(
                    scope="official", hits=[*official_structured, *official_hits]
                )
            if structured:
                groups.append(ScopedCandidates(scope="mine", hits=structured))
        if workspace is not None:
            private_hits = self.retriever.retrieve(
                course_id=workspace["private_course_id"],
                query=query,
                top_k=candidates,
                access=RetrievalAccess(owner_user_id=subject, scope="mine"),
            )
            if private_hits:
                if any(group.scope == "mine" for group in groups):
                    groups = [
                        ScopedCandidates(
                            scope=group.scope,
                            hits=[*group.hits, *private_hits] if group.scope == "mine" else group.hits,
                        )
                        for group in groups
                    ]
                else:
                    groups.append(ScopedCandidates(scope="mine", hits=private_hits))
        fused = fuse_scoped_candidates(
            groups,
            top_k=top_k,
            exact_targets=exact_targets,
            max_candidates=candidates,
        )
        # Entity relations are resolved over the already-authorized fused set and
        # recorded as PROPOSED rows for the backend to review — never applied: they
        # cannot reorder, merge, delete or rename anything on the path. Under
        # shadow/off the semantic pairs are UNCERTAIN and the deterministic fused
        # order is untouched.
        self._resolve_entity_relations(subject, course_id, workspace, fused)
        # Jev may only REORDER the already-authorized fused candidates; an exact
        # file/page/question target keeps its slot and is never added or dropped.
        # off/shadow/failed all return the deterministic fused order unchanged.
        if self.jev is not None:
            fused = callsites.rerank_retrieval(
                self.jev,
                fused,
                query=query,
                scope=self.jev.scope(
                    owner_user_id=subject,
                    authorization_scope="retrieval",
                    course_id=course_id,
                    workspace_id=str(workspace["id"]) if workspace is not None else None,
                    material_revision=str(workspace["revision"]) if workspace is not None else None,
                ),
            )
        budget = max(0, int(self.settings.max_context_chars)) // max(len(fused), 1)
        # Pre-DeepSeek evidence-bundle check (source.supports_claim.v1 /
        # source.select_span.v1): Jev may only judge the supplied candidates and
        # never author a citation; insufficient/uncertain keeps every source.
        citation = self._annotate_evidence(subject, course_id, query, fused, workspace)
        # EvidenceConsistency (evidence.consistency.v1): condition/conflict check
        # over the already-authorized, already-fused candidates. Annotation only —
        # it never reorders, drops or rewrites a source. The deterministic signal
        # is mode-independent; a genuine contradiction only surfaces in mode "on"
        # and is carried to the teaching prompt as a bounded conflict note.
        consistency = check_evidence_consistency(
            self.jev,
            fused,
            scope=(
                self.jev.scope(
                    owner_user_id=subject,
                    authorization_scope="evidence_consistency",
                    course_id=course_id,
                    workspace_id=str(workspace["id"]) if workspace is not None else None,
                    material_revision=str(workspace["revision"]) if workspace is not None else None,
                )
                if self.jev is not None
                else None
            ),
        )
        consistency_signal = _consistency_signal(consistency)
        conflict_partners = _contradiction_partners(consistency)
        chunk_to_sid = {
            entry.chunk_id: citation_id(index)
            for index, entry in enumerate(fused, start=1)
        }
        sources: list[dict[str, Any]] = []
        for index, entry in enumerate(fused, start=1):
            hit = entry.hit
            source = {
                "id": citation_id(index),
                "document_id": hit.document_id,
                "name": hit.filename,
                "page": _page_number(hit.locator_type, hit.locator_value),
                "locator": f"{hit.locator_type}:{hit.locator_value}",
                "section": hit.section,
                "text": budget_text(str(hit.content or ""), budget),
                # Deterministic per-source consistency signal (always present and
                # byte-identical under off/shadow/unavailable and with no Jev).
                "jev_consistency": consistency_signal.get(entry.chunk_id, COMPATIBLE),
            }
            if reference_verification is not None:
                # How the exact locator that produced this recall was verified, so
                # a rendered citation can be traced to the label behind it.
                source["jev_reference"] = reference_verification
            partners = conflict_partners.get(entry.chunk_id)
            if partners:
                source["jev_conflict_with"] = sorted(
                    chunk_to_sid[partner] for partner in partners if partner in chunk_to_sid
                )
            if citation:
                source["jev_citation_support"] = citation["support"]
                source["jev_selected_span"] = citation["selected_span"] == source["id"]
            sources.append(source)
        return sources

    def _annotate_evidence(
        self,
        subject: str,
        course_id: str,
        query: str,
        fused: list[Any],
        workspace: sqlite3.Row | None,
    ) -> dict[str, str] | None:
        """source.select_span.v1 + source.supports_claim.v1 pre-DeepSeek check.

        Two Jev calls total (select one span, then judge that span against the
        claim). The result is an annotation only: it never drops, adds or
        reorders a source, so an insufficient/uncertain answer keeps the existing
        evidence and hands it to DeepSeek unchanged.
        """
        if self.jev is None or not fused:
            return None
        scope = self.jev.scope(
            owner_user_id=subject,
            authorization_scope="citation",
            course_id=course_id,
            workspace_id=str(workspace["id"]) if workspace is not None else None,
            material_revision=str(workspace["revision"]) if workspace is not None else None,
        )
        spans = [
            {
                "id": citation_id(index),
                "text": str(getattr(entry.hit, "content", "") or ""),
                "version": str(getattr(entry.hit, "document_id", "") or ""),
                "scope": course_id,
            }
            for index, entry in enumerate(fused, start=1)
        ]
        return evidence_bundle_support(self.jev, claim=query, spans=spans, scope=scope)

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
        body: dict[str, Any] = {"title": payload.get("title")}
        # Note: the agent's `validateCreateTask` schema is narrower than its TypeScript
        # typing — `priority` is an enum with no null member, and every other optional
        # field accepts null. Only fields this UI actually sets are sent, so an
        # unset value is omitted rather than sent as an invalid one.
        course = _optional_id(payload.get("course"))
        if course is not None:
            body["courseId"] = course
        due = _date_only(payload.get("due_at"))
        if due is not None:
            body["dueDate"] = due
        return self._task_dto(
            self._agent_request("POST", "/api/tasks", credential, json_body=body)
        )

    def _task_update(self, credential: str, payload: dict[str, Any]) -> dict[str, Any]:
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
                    # Assessment projection: a raw score without a school grade
                    # mapping must still be visible, and must never be shown as
                    # "未测评". `assessment_display` is the ready-to-render label.
                    "raw_score": assessment.get("raw_score"),
                    "assessment_status": assessment.get("status"),
                    "assessment_display": _assessment_display(assessment),
                    "latest_result": assessment.get("latest_result"),
                    "latest_independent_result": assessment.get("latest_independent_result"),
                    "active_session": assessment.get("active_session"),
                    "assessment": assessment,
                    "learning": learning,
                }
            )
        # Registry entries that belong to the caller but are not members of the
        # selected tree (for example the caller's own private nodes) still need to
        # be reachable for their two status entries. They appear as top-level rows
        # after the real tree members; they never fabricate hierarchy.
        member_ids = {member.get("node_id") for member in ordered}
        for node_id, node in sorted(registry.items(), key=lambda item: (item[1].get("title") or "", item[0])):
            if node_id in member_ids:
                continue
            state = node.get("state") or {}
            learning = state.get("learning") or {}
            assessment = state.get("assessment") or {}
            tree.append(
                {
                    "id": node_id,
                    "parent": None,
                    "title": node.get("title") or node_id,
                    "description": node.get("description") or "",
                    "kind": node.get("kind"),
                    "position": len(tree),
                    "progress": learning.get("status") or "NOT_STARTED",
                    "grade": assessment.get("grade_label"),
                    # Assessment projection: a raw score without a school grade
                    # mapping must still be visible, and must never be shown as
                    # "未测评". `assessment_display` is the ready-to-render label.
                    "raw_score": assessment.get("raw_score"),
                    "assessment_status": assessment.get("status"),
                    "assessment_display": _assessment_display(assessment),
                    "latest_result": assessment.get("latest_result"),
                    "latest_independent_result": assessment.get("latest_independent_result"),
                    "active_session": assessment.get("active_session"),
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

    def _generate_exercise(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Run the owner-scoped Question Engine for the existing 做一题 worker.

        This operation is internal to the mounted server.  Its private projection
        never becomes an HTTP response here: ``cm_update`` stores it in the
        private exercise row and exposes it only through the existing reveal
        endpoint.
        """

        if self.question_engine is None:
            raise ApiError(503, "QUESTION_ENGINE_DISABLED", "The Question Engine is disabled.")
        course_id = str(payload["course"])
        node_id = str(payload["node"])
        operation_id = str(payload.get("operation_id") or "").strip()
        cancel_check = payload.get("_cancel_check")
        if cancel_check is not None and not callable(cancel_check):
            raise ApiError(422, "INVALID_CANCEL_CHECK", "Invalid cancellation boundary.")
        self._course_row(course_id, subject)
        workspace = self._workspace_for_node(course_id, subject)
        if self.learning is None:
            raise ApiError(503, "V3_DISABLED", "The V3 learning engine is disabled.")
        # Reuse the learning engine's canonical node authorization and atomic-node
        # validation before authoring can spend money.
        self.learning.node(workspace, node_id)
        try:
            return self.question_engine.generate_one(
                owner_user_id=subject,
                workspace_id=str(workspace["id"]),
                course_id=course_id,
                private_course_id=str(workspace["private_course_id"]),
                node_id=node_id,
                operation_id=operation_id,
                should_cancel=cancel_check,
            )
        except QuestionEngineRuntimeError as error:
            if error.code == "QUESTION_CANCELLED":
                raise asyncio.CancelledError() from error
            unavailable = {
                "AUTHOR_PROVIDER_BLOCKED",
                "AUTHOR_PROVIDER_FAILED",
                "BLIND_SOLVER_PROVIDER_BLOCKED",
                "BLIND_SOLVER_PROVIDER_FAILED",
                "QUESTION_REVIEW_UNAVAILABLE",
                "QUESTION_CANCELLATION_CHECK_FAILED",
            }
            status = 503 if error.code in unavailable else 409
            raise ApiError(status, error.code, str(error)) from error

    # ----------------------------------------- V3 learning state (write paths)

    def _workspace_for_node(self, course_id: str, subject: str) -> sqlite3.Row:
        workspace = self._workspace_row(course_id, subject)
        if workspace is None:
            raise ApiError(409, "WORKSPACE_UNAVAILABLE", "The learning workspace is unavailable.")
        return workspace

    def _begin_learning(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Start (or continue) the V3 learning journey for a knowledge node.

        This is the minimal, truthful write from the shell's free-text teaching to
        the authoritative V3 learning state: it creates the same
        `learning_journeys` row V3's own teach() would create, idempotently, and
        never touches coverage. REQUIRED-item coverage stays exclusively owned by
        V3 teach()/delivery evidence; the node's progress therefore stays honest
        (NOT_STARTED until real coverage exists).
        """

        if self.learning is None:
            raise ApiError(503, "V3_DISABLED", "The V3 learning engine is disabled.")
        course_id = str(payload["course"])
        node_id = str(payload["node"])
        self._course_row(course_id, subject)
        workspace = self._workspace_for_node(course_id, subject)
        node = self.learning.node(workspace, node_id)  # 404/409 with real codes
        raw_operation = payload.get("operation_id") or payload.get("request_id")
        operation_id = str(raw_operation).strip() if raw_operation else ""
        with self.database.connect() as connection:
            journey = LearningOrchestrator.journey(connection, workspace["id"], node)
            spec = connection.execute(
                "SELECT content_json FROM teaching_specs WHERE node_id=? AND version=?",
                (node_id, journey["spec_version"]),
            ).fetchone()
            items = json.loads(spec["content_json"]) if spec is not None else []
            # Accepting this teaching request IS the learning start. The fact is
            # recorded independently of coverage (schema 26) so a started node
            # without accepted evidence still projects LEARNING. Replays of the
            # same accepted operation (or a retried request id) insert nothing.
            start_operation = operation_id or (
                f"node-start:{workspace['id']}:{node_id}:{journey['spec_version']}"
            )
            connection.execute(
                "INSERT OR IGNORE INTO learning_start_events"
                "(id,workspace_id,node_id,spec_version,operation_id,source,accepted_at) "
                "VALUES(?,?,?,?,?,'UI_RUN',strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                (
                    f"start-{hashlib.sha256(f'{workspace['id']}|{node_id}|{journey['spec_version']}|{start_operation}'.encode()).hexdigest()[:24]}",
                    workspace["id"],
                    node_id,
                    journey["spec_version"],
                    start_operation[:120],
                ),
            )
        return {
            "journey_id": journey["id"],
            "node_id": node_id,
            "spec_version": journey["spec_version"],
            "workspace_id": workspace["id"],
            "status": journey["status"],
            "required_items": [
                {
                    "item_id": item.get("item_id"),
                    "requirement": item.get("requirement"),
                    "objective": item.get("objective"),
                    "acceptance": item.get("acceptance"),
                }
                for item in items
                if item.get("requirement") == "REQUIRED"
            ],
        }

    async def _submit_delivery(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Record a completed free-text teaching into the V3 evidence ledger.

        Called by the shell only after the run's conditional final write has
        claimed ``completed`` and the assistant message is persisted, so a
        failed, cancelled or truncated run can never reach this point. Coverage
        is decided by the injected reviewer; without a confirmed reviewer no
        evidence is written and the node honestly stays uncovered.
        """

        if self.learning is None:
            raise ApiError(503, "V3_DISABLED", "The V3 learning engine is disabled.")
        course_id = str(payload["course"])
        node_id = str(payload["node"])
        run_id = str(payload.get("run_id") or "")
        content = str(payload.get("content") or "").strip()
        if not run_id or not content:
            raise ApiError(422, "EMPTY_DELIVERY", "A run id and non-empty teaching content are required.")
        self._course_row(course_id, subject)
        workspace = self._workspace_for_node(course_id, subject)
        node = self.learning.node(workspace, node_id)  # 404/409 with real codes
        with self.database.connect() as connection:
            journey = LearningOrchestrator.journey(connection, workspace["id"], node)
            spec_version = int(journey["spec_version"])
        if int(payload.get("spec_version") or 0) != spec_version:
            raise ApiError(
                422,
                "STALE_SPEC",
                "The teaching spec changed since this run started; no coverage was recorded.",
            )
        with self.database.connect() as connection:
            spec = connection.execute(
                "SELECT content_json FROM teaching_specs WHERE node_id=? AND version=?",
                (node_id, spec_version),
            ).fetchone()
        items = json.loads(spec["content_json"]) if spec is not None else []
        # Non-authoritative Jev item-support signal, recorded in provenance only:
        # the reviewer + server quote/hash validation still decide coverage, so a
        # Jev result can never claim coverage, drop it, or write a grade.
        provenance = {
            "run_id": run_id,
            "bridge_id": payload.get("bridge_id"),
            "course_id": course_id,
            "student_question": str(payload.get("question") or "")[:2000],
            "reviewer": getattr(
                self.coverage_reviewer, "__class__", type(self.coverage_reviewer)
            ).__name__,
        }
        if self.jev is not None:
            required = [item for item in items if item.get("requirement") == "REQUIRED"]
            provenance["jev_item_support"] = callsites.coverage_item_support(
                self.jev,
                required,
                content=content,
                spec_version=spec_version,
                scope=self.jev.scope(
                    owner_user_id=subject,
                    authorization_scope="coverage",
                    course_id=course_id,
                    workspace_id=workspace["id"],
                    node_id=node_id,
                    spec_version=spec_version,
                    material_revision=str(workspace["revision"]) if "revision" in workspace.keys() else None,
                ),
            )
        return await submit_shell_delivery(
            self.database,
            workspace_id=workspace["id"],
            journey_id=journey["id"],
            node=node,
            spec_version=spec_version,
            items=items,
            content=content,
            operation_id=run_id,
            provenance=provenance,
            reviewer=self.coverage_reviewer,
        )

    def _record_problem(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Map a completed shell problem run into the V3 problem ledger.

        Records the original question as an immutable, content-hashed problem
        revision and the completed solution steps as versioned V3 rows, so the
        shell bridge can carry verifiable ids. Never regenerates an answer.
        """

        course_id = str(payload["course"])
        run_id = str(payload.get("run_id") or "")
        question = str(payload.get("question") or "").strip()
        if not run_id or not question:
            raise ApiError(422, "EMPTY_PROBLEM", "A problem run id and question are required.")
        self._course_row(course_id, subject)
        workspace = self._workspace_for_node(course_id, subject)
        steps = []
        for step in payload.get("steps") or []:
            if not isinstance(step, dict) or not str(step.get("number") or "").isdigit():
                raise ApiError(422, "INVALID_STEPS", "Solution steps must carry numeric ordinals.")
            steps.append(
                {
                    "number": int(step["number"]),
                    "title": str(step.get("title") or "")[:160],
                    "content": str(step.get("content") or step.get("title") or "")[:20000],
                }
            )
        return record_shell_problem(
            self.database,
            workspace_id=workspace["id"],
            course_id=course_id,
            question=question,
            steps=steps,
            operation_id=run_id,
        )

    def _assessment_start(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.learning is None:
            raise ApiError(503, "V3_DISABLED", "The V3 learning engine is disabled.")
        course_id = str(payload["course"])
        node_id = str(payload["node"])
        self._course_row(course_id, subject)
        workspace = self._workspace_for_node(course_id, subject)
        revision = self._workspace_revision(workspace["id"])
        return self.learning.start_assessment(
            workspace["id"],
            subject,
            AssessmentStartInput(operation_id=str(payload["request_id"]), revision=revision, node_id=node_id),
        )

    def _assessment_view(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.learning is None:
            raise ApiError(503, "V3_DISABLED", "The V3 learning engine is disabled.")
        course_id = str(payload["course"])
        self._course_row(course_id, subject)
        workspace = self._workspace_for_node(course_id, subject)
        return self.learning.assessment(workspace["id"], subject, str(payload["session"]))

    def _assessment_submit(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.learning is None:
            raise ApiError(503, "V3_DISABLED", "The V3 learning engine is disabled.")
        course_id = str(payload["course"])
        self._course_row(course_id, subject)
        workspace = self._workspace_for_node(course_id, subject)
        answers = [AssessmentAnswer(**item) for item in (payload.get("answers") or [])]
        request = AssessmentSubmitInput(
            operation_id=str(payload["request_id"]),
            revision=0,
            answers=answers,
            unified_answer=payload.get("unified_answer"),
            attachments=[
                AssessmentAttachment(**item) for item in (payload.get("attachments") or [])
            ],
            transcription=payload.get("transcription"),
            submission_revision=payload.get("submission_revision"),
            submission_hash=payload.get("submission_hash"),
            draft=bool(payload.get("draft", False)),
            confirm_unanswered=payload.get("confirm_unanswered") or [],
        )
        # The optimistic revision is read right before the call. On a concurrent
        # edit the V3 engine raises REVISION_CONFLICT; retry once with the fresh
        # revision rather than silently overwriting someone else's state.
        for attempt in range(2):
            request.revision = self._workspace_revision(workspace["id"])
            try:
                return self.learning.submit_assessment(
                    workspace["id"], subject, str(payload["session"]), request
                )
            except ApiError as error:
                if error.code != "REVISION_CONFLICT" or attempt == 1:
                    raise
        raise ApiError(409, "REVISION_CONFLICT", "The workspace changed while submitting.")

    def _assessment_draft_save(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.learning is None:
            raise ApiError(503, "V3_DISABLED", "The V3 learning engine is disabled.")
        course_id = str(payload["course"])
        self._course_row(course_id, subject)
        workspace = self._workspace_for_node(course_id, subject)
        request = AssessmentDraftInput(
            operation_id=str(payload["request_id"]),
            revision=self._workspace_revision(workspace["id"]),
            unified_answer=payload.get("unified_answer"),
            attachments=[
                AssessmentAttachment(**item) for item in (payload.get("attachments") or [])
            ],
        )
        return self.learning.save_assessment_draft(
            workspace["id"], subject, str(payload["session"]), request
        )

    def _assessment_draft_load(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.learning is None:
            raise ApiError(503, "V3_DISABLED", "The V3 learning engine is disabled.")
        course_id = str(payload["course"])
        self._course_row(course_id, subject)
        workspace = self._workspace_for_node(course_id, subject)
        return self.learning.load_assessment_draft(
            workspace["id"], subject, str(payload["session"])
        )

    def _assessment_prepare_cancel(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.learning is None:
            raise ApiError(503, "V3_DISABLED", "The V3 learning engine is disabled.")
        course_id = str(payload["course"])
        self._course_row(course_id, subject)
        workspace = self._workspace_for_node(course_id, subject)
        from app.learning.models import AssessmentAbandonInput as _Op

        request = _Op(
            operation_id=str(payload["request_id"]),
            revision=self._workspace_revision(workspace["id"]),
        )
        return self.learning.cancel_pool_preparation(
            workspace["id"], subject, request, str(payload["job"])
        )

    def _assessment_prepare_resume(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.learning is None:
            raise ApiError(503, "V3_DISABLED", "The V3 learning engine is disabled.")
        course_id = str(payload["course"])
        self._course_row(course_id, subject)
        workspace = self._workspace_for_node(course_id, subject)
        request = AssessmentPreparationStartInput(
            operation_id=str(payload["request_id"]),
            revision=self._workspace_revision(workspace["id"]),
            node_id=str(payload["node"]),
        )
        return self.learning.resume_pool_preparation(workspace["id"], subject, request)

    def _assessment_explain(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.learning is None:
            raise ApiError(503, "V3_DISABLED", "The V3 learning engine is disabled.")
        course_id = str(payload["course"])
        self._course_row(course_id, subject)
        workspace = self._workspace_for_node(course_id, subject)
        request = AssessmentExplanationInput(
            operation_id=str(payload["request_id"]),
            revision=self._workspace_revision(workspace["id"]),
            blueprint_item_id=str(payload["blueprint_item"]),
            step_id=str(payload["step"]),
        )
        return self.learning.explain_assessment_step(
            workspace["id"], subject, str(payload["session"]), request
        )

    def _assessment_abandon(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.learning is None:
            raise ApiError(503, "V3_DISABLED", "The V3 learning engine is disabled.")
        course_id = str(payload["course"])
        self._course_row(course_id, subject)
        workspace = self._workspace_for_node(course_id, subject)
        return self.learning.abandon_assessment(
            workspace["id"],
            subject,
            str(payload["session"]),
            AssessmentAbandonInput(operation_id=str(payload["request_id"]), revision=self._workspace_revision(workspace["id"])),
        )

    def _workspace_revision(self, workspace_id: str) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT revision FROM learning_workspaces WHERE id=?", (workspace_id,)
            ).fetchone()
        if row is None:
            raise ApiError(404, "WORKSPACE_NOT_FOUND", "The workspace was not found.")
        return int(row["revision"])

    # ------------------------------------------------------- legacy V3 history

    def _legacy_conversations(self, subject: str, course_id: str) -> list[dict[str, Any]]:
        """List the caller's pre-existing V3 conversations for one course.

        These rows live in the original `conversations` table and are never copied
        into the refreshed shell's history, so this is a read-only projection over
        the same records the existing Q&A surface uses.
        """

        self._course_row(course_id, subject)
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT conversation.id, conversation.title, conversation.updated_at,"
                "(SELECT COUNT(*) FROM messages WHERE messages.conversation_id=conversation.id)"
                " AS message_count "
                "FROM conversations AS conversation "
                "WHERE conversation.owner_user_id=? AND conversation.course_id=? "
                "ORDER BY conversation.updated_at DESC, conversation.id LIMIT 200",
                (subject, course_id),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "updated_at": row["updated_at"],
                "message_count": row["message_count"],
                "legacy": True,
            }
            for row in rows
        ]

    def _legacy_conversation(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        course_id = str(payload["course"])
        conversation_id = str(payload["id"])
        self._course_row(course_id, subject)
        with self.database.connect() as connection:
            conversation = connection.execute(
                "SELECT id, title, created_at, updated_at FROM conversations "
                "WHERE id=? AND owner_user_id=? AND course_id=?",
                (conversation_id, subject, course_id),
            ).fetchone()
            if conversation is None:
                raise ApiError(404, "CONVERSATION_NOT_FOUND", "The conversation was not found.")
            rows = connection.execute(
                "SELECT role, content, citations_json, created_at FROM messages "
                "WHERE conversation_id=? ORDER BY created_at, rowid",
                (conversation_id,),
            ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            try:
                citations = json.loads(row["citations_json"])
            except (TypeError, ValueError):
                citations = []
            messages.append(
                {
                    "role": row["role"],
                    "text": row["content"],
                    "citations": citations if isinstance(citations, list) else [],
                    "created_at": row["created_at"],
                }
            )
        return {
            "id": conversation["id"],
            "title": conversation["title"],
            "created_at": conversation["created_at"],
            "updated_at": conversation["updated_at"],
            "messages": messages,
            "legacy": True,
        }

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
            "knowledge.exercise.generate",
            "knowledge.begin_learning",
            "knowledge.assessment.start",
            "knowledge.assessment.view",
            "knowledge.assessment.submit",
            "knowledge.assessment.abandon",
            "knowledge.assessment.draft.save",
            "knowledge.assessment.draft.load",
            "knowledge.assessment.prepare.cancel",
            "knowledge.assessment.prepare.resume",
            "knowledge.assessment.explain",
            "knowledge.submit_delivery",
            "knowledge.record_problem",
        }
        # The legacy history routes pass `course` (never `id`), so they need their
        # own boundary check rather than the `id`-shaped one below.
        if operation in {"legacy.conversations", "legacy.conversation"}:
            self._course_row(str(payload["course"]), subject)
        if operation in course_operations:
            course_id = str(payload.get("course") or payload.get("id") or "")
            if course_id and operation not in {"course.list", "course.create", "course.get"}:
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
        if operation == "course.create_shared":
            return self._create_shared_course(subject, payload)
        if operation == 'snapshot.export':
            return await asyncio.to_thread(self._snapshot_export,subject,payload)
        if operation == 'snapshot.import':
            return await asyncio.to_thread(self._snapshot_import,subject,payload)
        if operation in {'snapshot.knowledge.export','snapshot.knowledge.import'}:
            from app.learning import snapshot_transfer
            self._course_row(str(payload['course']),subject,write=operation.endswith('import'))
            workspace=self._workspace_row(str(payload['course']),subject)
            if operation.endswith('export'):
                return await asyncio.to_thread(snapshot_transfer.export_snapshot,self.learning,workspace['id'],subject)
            return await asyncio.to_thread(snapshot_transfer.import_snapshot,self.learning,workspace['id'],subject,
                payload['snapshot'],payload['mapping'],payload['share_id'])
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
        if operation == "knowledge.exercise.generate":
            return await asyncio.to_thread(self._generate_exercise, subject, payload)
        if operation == "knowledge.begin_learning":
            return self._begin_learning(subject, payload)
        if operation == "knowledge.submit_delivery":
            return await self._submit_delivery(subject, payload)
        if operation == "knowledge.record_problem":
            return self._record_problem(subject, payload)
        if operation == "knowledge.assessment.start":
            return self._assessment_start(subject, payload)
        if operation == "knowledge.assessment.view":
            return self._assessment_view(subject, payload)
        if operation == "knowledge.assessment.submit":
            return self._assessment_submit(subject, payload)
        if operation == "knowledge.assessment.abandon":
            return self._assessment_abandon(subject, payload)
        if operation == "knowledge.assessment.draft.save":
            return self._assessment_draft_save(subject, payload)
        if operation == "knowledge.assessment.draft.load":
            return self._assessment_draft_load(subject, payload)
        if operation == "knowledge.assessment.prepare.cancel":
            return self._assessment_prepare_cancel(subject, payload)
        if operation == "knowledge.assessment.prepare.resume":
            return self._assessment_prepare_resume(subject, payload)
        if operation == "knowledge.assessment.explain":
            return self._assessment_explain(subject, payload)
        if operation == "legacy.conversations":
            return self._legacy_conversations(subject, str(payload["course"]))
        if operation == "legacy.conversation":
            return self._legacy_conversation(subject, payload)
        if operation == "verification.grandfather_candidates":
            # Trusted pre-enablement snapshot sources: every user id that
            # already left ownership rows in the V3 database. Client-provided
            # timestamps are never used.
            with self.database.connect() as connection:
                rows = connection.execute(
                    "SELECT DISTINCT owner_user_id AS uid FROM courses "
                    "WHERE owner_user_id IS NOT NULL AND julianday(created_at)<=julianday(?) "
                    "UNION SELECT DISTINCT owner_user_id FROM learning_workspaces WHERE julianday(created_at)<=julianday(?) "
                    "UNION SELECT DISTINCT owner_user_id FROM conversations WHERE julianday(created_at)<=julianday(?)",
                    (payload['cutoff'],payload['cutoff'],payload['cutoff'])
                ).fetchall()
            return [row["uid"] for row in rows if row["uid"]]
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


def _optional_id(value: Any) -> str | None:
    """Normalise an unselected optional identifier to null.

    The calendar's course picker offers "个人学习" with an empty value, and the
    agent's schema accepts either an id matching `^[a-z0-9][a-z0-9-]{1,49}$` or
    null - never an empty string.
    """

    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


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
