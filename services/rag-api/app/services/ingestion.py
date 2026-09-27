import hashlib
import json
import logging
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

from app.config import Settings
from app.course_access import require_course_access
from app.db import Database
from app.errors import ApiError
from app.learning.uploads import MEDIA_TYPES, validate_file_content
from app.models import (
    Course,
    CourseCreate,
    CoursePage,
    CourseUpdate,
    DirectUploadCreate,
    DirectUploadGrant,
    Document,
    DocumentPage,
    IngestionJob,
    PublicationStatus,
    UploadAccepted,
)
from app.rag.chunking import chunk_sections
from app.rag.embeddings import EmbeddingProvider
from app.rag.errors import DocumentLoadError
from app.rag.loaders import LOADERS, load_document
from app.storage.backends import AliyunOssStorageBackend, LocalStorageBackend, StorageBackend
from app.storage.capacity import CapacityGuard, CapacityUnavailable
from app.storage.factory import storage_backend_from_settings
from app.storage.keys import canonical_object_key, quarantine_object_key

LOGGER = logging.getLogger(__name__)
EMBEDDING_BATCH_SIZE = 10


def _storage_owner_segment(owner_user_id: str) -> str:
    """Create a stable opaque path segment without exposing the identity provider subject."""

    return hashlib.sha256(owner_user_id.encode("utf-8")).hexdigest()[:32]


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class MissingEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("OPENAI_API_KEY is required for document ingestion")


class IngestionService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        embedding_provider: EmbeddingProvider,
        storage_backend: StorageBackend | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.embedding_provider = embedding_provider
        self.storage_backend = storage_backend or storage_backend_from_settings(settings)

    def begin_direct_upload(
        self,
        *,
        course_id: str,
        payload: DirectUploadCreate,
        owner_user_id: str,
        is_admin: bool,
    ) -> DirectUploadGrant:
        course = self._require_course(
            course_id, owner_user_id=owner_user_id, is_admin=is_admin, write=True
        )
        if not isinstance(self.storage_backend, AliyunOssStorageBackend):
            raise ApiError(
                409,
                "DIRECT_UPLOAD_UNAVAILABLE",
                "Direct object upload is not configured for this deployment.",
            )
        extension = Path(payload.filename).suffix.casefold()
        if extension not in MEDIA_TYPES:
            raise ApiError(400, "UNSUPPORTED_EXTENSION", "This file extension is not supported.")
        if payload.media_type not in MEDIA_TYPES[extension]:
            raise ApiError(
                400, "INVALID_MEDIA_TYPE", "The media type does not match the file type."
            )
        if payload.byte_size > self.settings.max_upload_bytes:
            raise ApiError(400, "FILE_TOO_LARGE", "The uploaded file exceeds the size limit.")
        self._check_document_admission(
            course=course,
            course_id=course_id,
            owner_user_id=owner_user_id,
            is_admin=is_admin,
            byte_size=payload.byte_size,
            sha256=payload.sha256,
        )
        upload_id = f"upl_{uuid4().hex}"
        object_id = f"obj_{uuid4().hex}"
        key = quarantine_object_key(
            owner_user_id=owner_user_id,
            upload_id=upload_id,
            extension=extension,
        )
        url, headers, expires_at = self.storage_backend.presign_quarantine_put(
            key,
            size=payload.byte_size,
            sha256=payload.sha256,
            content_type=payload.media_type,
            ttl_seconds=self.settings.oss_presign_ttl_seconds,
        )
        expires = datetime.now(UTC) + timedelta(seconds=self.settings.oss_presign_ttl_seconds)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO storage_objects(
                    id,backend,bucket,object_key,byte_size,sha256,media_type,state,
                    owner_user_id,course_id
                ) VALUES(?, 'ALIYUN_OSS', ?, ?, ?, ?, ?, 'QUARANTINE', ?, ?)
                """,
                (
                    object_id,
                    self.storage_backend.bucket,
                    key,
                    payload.byte_size,
                    payload.sha256,
                    payload.media_type,
                    owner_user_id,
                    course_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO storage_upload_sessions(
                    id,owner_user_id,course_id,filename,extension,media_type,
                    expected_size,expected_sha256,quarantine_object_id,status,expires_at
                ) VALUES(?,?,?,?,?,?,?,?,?,'CREATED',?)
                """,
                (
                    upload_id,
                    owner_user_id,
                    course_id,
                    payload.filename,
                    extension,
                    payload.media_type,
                    payload.byte_size,
                    payload.sha256,
                    object_id,
                    expires.isoformat(),
                ),
            )
        return DirectUploadGrant(
            upload_id=upload_id,
            url=url,
            headers=headers,
            expires_at=datetime.fromisoformat(expires_at),
        )

    def finalize_direct_upload(
        self,
        *,
        upload_id: str,
        owner_user_id: str,
        is_admin: bool,
    ) -> UploadAccepted:
        if not isinstance(self.storage_backend, AliyunOssStorageBackend):
            raise ApiError(409, "DIRECT_UPLOAD_UNAVAILABLE", "Direct upload is unavailable.")
        with self.database.connect() as connection:
            session = connection.execute(
                """
                SELECT storage_upload_sessions.*, storage_objects.object_key
                FROM storage_upload_sessions
                JOIN storage_objects ON storage_objects.id=quarantine_object_id
                WHERE storage_upload_sessions.id=? AND storage_upload_sessions.owner_user_id=?
                """,
                (upload_id, owner_user_id),
            ).fetchone()
        if session is None:
            raise ApiError(404, "UPLOAD_NOT_FOUND", "The upload session was not found.")
        self._require_course(
            session["course_id"], owner_user_id=owner_user_id, is_admin=is_admin, write=True
        )
        if session["status"] == "FINALIZED":
            with self.database.connect() as connection:
                document = connection.execute(
                    "SELECT id FROM documents WHERE storage_object_id=?",
                    (session["canonical_object_id"],),
                ).fetchone()
                job = connection.execute(
                    "SELECT id FROM ingestion_jobs WHERE document_id=? ORDER BY created_at LIMIT 1",
                    (document["id"],),
                ).fetchone() if document else None
            if document and job:
                return UploadAccepted(
                    document=self._get_document(document["id"]),
                    job=self.get_job(job["id"], owner_user_id=owner_user_id, is_admin=is_admin),
                )
            raise RuntimeError("Finalized upload has no document receipt")
        if datetime.fromisoformat(session["expires_at"]) < datetime.now(UTC):
            with self.database.connect() as connection:
                connection.execute(
                    "UPDATE storage_upload_sessions SET status='EXPIRED' WHERE id=?",
                    (upload_id,),
                )
            raise ApiError(410, "UPLOAD_EXPIRED", "The upload session has expired.")
        with self.database.connect() as connection:
            changed = connection.execute(
                "UPDATE storage_upload_sessions SET status='VERIFYING' "
                "WHERE id=? AND status='CREATED'",
                (upload_id,),
            ).rowcount
        if changed != 1:
            raise ApiError(
                409,
                "UPLOAD_FINALIZATION_IN_PROGRESS",
                "Upload verification is in progress.",
            )
        try:
            content = self.storage_backend.read_range(
                session["object_key"], start=0, end=session["expected_size"] - 1
            )
            self._validate_upload(session["filename"], session["media_type"], content)
            if hashlib.sha256(content).hexdigest() != session["expected_sha256"]:
                raise ApiError(
                    409, "UPLOAD_HASH_MISMATCH", "The uploaded object failed verification."
                )
            document_id = f"doc_{uuid4().hex}"
            job_id = f"job_{uuid4().hex}"
            key = canonical_object_key(
                owner_user_id=owner_user_id,
                course_id=session["course_id"],
                document_id=document_id,
                sha256=session["expected_sha256"],
                extension=session["extension"],
            )
            stored = self.storage_backend.promote_verified(
                session["object_key"],
                key,
                expected_size=session["expected_size"],
                expected_sha256=session["expected_sha256"],
                content_type=session["media_type"],
            )
            canonical_id = f"obj_{uuid4().hex}"
            cache_path = self.settings.storage_cache_dir / key
            cache_available = self._cache_if_capacity_allows(key, content, cache_path)
            with self.database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._check_document_admission_sql(
                    connection=connection,
                    course_id=session["course_id"],
                    owner_user_id=owner_user_id,
                    is_admin=is_admin,
                    byte_size=session["expected_size"],
                    sha256=session["expected_sha256"],
                )
                connection.execute(
                    """
                    INSERT INTO storage_objects(
                        id,backend,bucket,object_key,version_id,byte_size,sha256,crc64,etag,
                        media_type,state,owner_user_id,course_id,local_cache_path,
                        verified_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,'CANONICAL',?,?,?,
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                    """,
                    (
                        canonical_id, "ALIYUN_OSS", stored.bucket, stored.key,
                        stored.version_id, stored.size, stored.sha256, stored.crc64,
                        stored.etag, stored.content_type, owner_user_id,
                        session["course_id"],
                        str(cache_path) if cache_available else None,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO documents(
                        id,course_id,filename,stored_path,media_type,extension,sha256,
                        byte_size,status,error_message,storage_object_id
                    ) VALUES(?,?,?,?,?,?,?,?, 'pending', ?, ?)
                    """,
                    (
                        document_id, session["course_id"], session["filename"],
                        str(cache_path), session["media_type"], session["extension"],
                        session["expected_sha256"], session["expected_size"],
                        None if cache_available else "WAITING_CAPACITY", canonical_id,
                    ),
                )
                connection.execute(
                    "UPDATE storage_objects SET document_id=? WHERE id=?",
                    (document_id, canonical_id),
                )
                connection.execute(
                    "INSERT INTO ingestion_jobs(id,document_id,status,error_message) "
                    "VALUES(?,?,'queued',?)",
                    (job_id, document_id, None if cache_available else "WAITING_CAPACITY"),
                )
                connection.execute(
                    "UPDATE storage_upload_sessions SET status='FINALIZED',canonical_object_id=?,"
                    "finalized_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),"
                    "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                    (canonical_id, upload_id),
                )
                connection.execute(
                    "UPDATE storage_objects SET verified_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                    "WHERE id=?",
                    (session["quarantine_object_id"],),
                )
            return UploadAccepted(
                document=self._get_document(document_id),
                job=self.get_job(job_id, owner_user_id=owner_user_id, is_admin=is_admin),
            )
        except Exception:
            with self.database.connect() as connection:
                connection.execute(
                    "UPDATE storage_upload_sessions SET status='INVALID',"
                    "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                    "WHERE id=? AND status='VERIFYING'",
                    (upload_id,),
                )
            raise

    def _cache_if_capacity_allows(self, key: str, content: bytes, cache_path: Path) -> bool:
        reservation_id = self._reserve_capacity(
            peak_bytes=len(content), owner_kind="CACHE_WRITE", owner_id=key
        )
        if reservation_id is None:
            return False
        try:
            local = LocalStorageBackend(self.settings.storage_cache_dir)
            local.put_bytes(
                key,
                content,
                expected_sha256=hashlib.sha256(content).hexdigest(),
                content_type="application/octet-stream",
            )
            return cache_path.is_file()
        finally:
            self._release_capacity(reservation_id)

    def _reserve_capacity(
        self, *, peak_bytes: int, owner_kind: str, owner_id: str
    ) -> str | None:
        cache_root = self.settings.storage_cache_dir
        existing = cache_root
        while not existing.exists() and existing != existing.parent:
            existing = existing.parent
        usage = shutil.disk_usage(existing)
        cache_bytes = 0
        if cache_root.is_dir():
            for path in cache_root.rglob("*"):
                if path.is_file():
                    try:
                        cache_bytes += path.stat().st_size
                    except OSError:
                        continue
        if cache_bytes + peak_bytes > self.settings.storage_cache_max_bytes:
            return None
        reservation_id = f"cap_{uuid4().hex}"
        expires_at = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE storage_capacity_reservations SET status='EXPIRED' "
                "WHERE status='ACTIVE' AND expires_at <= ?",
                (datetime.now(UTC).isoformat(),),
            )
            outstanding = connection.execute(
                "SELECT COALESCE(SUM(peak_bytes),0) FROM storage_capacity_reservations "
                "WHERE status='ACTIVE' AND expires_at > ?",
                (datetime.now(UTC).isoformat(),),
            ).fetchone()[0]
            try:
                CapacityGuard(
                    total_bytes=usage.total,
                    free_bytes=usage.free,
                    outstanding_reservations=outstanding,
                    reserve_min_bytes=self.settings.storage_reserve_min_bytes,
                    reserve_fraction=self.settings.storage_reserve_fraction,
                ).reserve(peak_bytes=peak_bytes)
            except CapacityUnavailable:
                return None
            connection.execute(
                "INSERT INTO storage_capacity_reservations("
                "id,filesystem_id,owner_kind,owner_id,peak_bytes,status,expires_at"
                ") VALUES(?,?,?,?,?,'ACTIVE',?)",
                (
                    reservation_id,
                    str(existing.resolve().anchor),
                    owner_kind,
                    owner_id,
                    peak_bytes,
                    expires_at,
                ),
            )
        return reservation_id

    def _release_capacity(self, reservation_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE storage_capacity_reservations SET status='RELEASED',"
                "released_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE id=? AND status='ACTIVE'",
                (reservation_id,),
            )

    def _ensure_document_cache(self, document_id: str, job_id: str) -> bool:
        if not self.database.v3_enabled:
            with self.database.connect() as connection:
                legacy = connection.execute(
                    "SELECT stored_path FROM documents WHERE id=?", (document_id,)
                ).fetchone()
            return legacy is not None
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT documents.stored_path,documents.byte_size,documents.sha256,
                    documents.media_type,storage_objects.object_key
                FROM documents
                LEFT JOIN storage_objects ON storage_objects.id=documents.storage_object_id
                WHERE documents.id=?
                """,
                (document_id,),
            ).fetchone()
        if row is None or Path(row["stored_path"]).is_file():
            return row is not None
        if not row["object_key"] or not isinstance(
            self.storage_backend, AliyunOssStorageBackend
        ):
            return True
        reservation_id = self._reserve_capacity(
            peak_bytes=row["byte_size"],
            owner_kind="INGESTION_CACHE",
            owner_id=document_id,
        )
        if reservation_id is None:
            with self.database.connect() as connection:
                connection.execute(
                    "UPDATE documents SET status='pending',error_message='WAITING_CAPACITY' "
                    "WHERE id=?",
                    (document_id,),
                )
                connection.execute(
                    "UPDATE ingestion_jobs SET status='queued',error_message='WAITING_CAPACITY' "
                    "WHERE id=?",
                    (job_id,),
                )
            return False
        try:
            content = self.storage_backend.read_range(
                row["object_key"], start=0, end=row["byte_size"] - 1
            )
            if len(content) != row["byte_size"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
                raise RuntimeError("Durable object failed cache hydration verification")
            destination = Path(row["stored_path"])
            relative = destination.resolve().relative_to(
                self.settings.storage_cache_dir.resolve()
            ).as_posix()
            LocalStorageBackend(self.settings.storage_cache_dir).put_bytes(
                relative,
                content,
                expected_sha256=row["sha256"],
                content_type=row["media_type"],
            )
            with self.database.connect() as connection:
                connection.execute(
                    "UPDATE storage_objects SET local_cache_path=?,updated_at="
                    "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=("
                    "SELECT storage_object_id FROM documents WHERE id=?)",
                    (str(destination), document_id),
                )
                connection.execute(
                    "UPDATE documents SET error_message=NULL WHERE id=?", (document_id,)
                )
                connection.execute(
                    "UPDATE ingestion_jobs SET error_message=NULL WHERE id=?", (job_id,)
                )
            return True
        finally:
            self._release_capacity(reservation_id)

    def _check_document_admission(
        self,
        *,
        course: sqlite3.Row,
        course_id: str,
        owner_user_id: str,
        is_admin: bool,
        byte_size: int,
        sha256: str,
    ) -> None:
        with self.database.connect() as connection:
            self._check_document_admission_sql(
                connection=connection,
                course_id=course_id,
                owner_user_id=owner_user_id,
                is_admin=is_admin,
                byte_size=byte_size,
                sha256=sha256,
                course=course,
            )

    def _check_document_admission_sql(
        self,
        *,
        connection: sqlite3.Connection,
        course_id: str,
        owner_user_id: str,
        is_admin: bool,
        byte_size: int,
        sha256: str,
        course: sqlite3.Row | None = None,
    ) -> None:
        course = course or connection.execute(
            "SELECT * FROM courses WHERE id=?", (course_id,)
        ).fetchone()
        if course is None:
            raise ApiError(404, "COURSE_NOT_FOUND", "The course was not found.")
        if not is_admin and course["course_type"] == "user":
            document_count = connection.execute(
                "SELECT COUNT(*) FROM documents WHERE course_id=?", (course_id,)
            ).fetchone()[0]
            if document_count >= self.settings.user_course_max_files:
                raise ApiError(
                    429,
                    "COURSE_FILE_QUOTA_EXCEEDED",
                    "The course file quota has been reached.",
                    details={"limit": self.settings.user_course_max_files},
                )
            used_bytes = connection.execute(
                "SELECT COALESCE(SUM(documents.byte_size),0) FROM documents "
                "JOIN courses ON courses.id=documents.course_id "
                "WHERE courses.owner_user_id=? AND courses.course_type='user'",
                (owner_user_id,),
            ).fetchone()[0]
            if used_bytes + byte_size > self.settings.user_course_max_total_upload_bytes:
                raise ApiError(
                    413,
                    "USER_STORAGE_QUOTA_EXCEEDED",
                    "The total private-course upload quota would be exceeded.",
                    details={
                        "limitBytes": self.settings.user_course_max_total_upload_bytes,
                        "usedBytes": used_bytes,
                    },
                )
        duplicate = connection.execute(
            "SELECT id FROM documents WHERE course_id=? AND sha256=?",
            (course_id, sha256),
        ).fetchone()
        if duplicate is not None:
            raise ApiError(
                409,
                "DUPLICATE_DOCUMENT",
                "This course already contains a document with the same content.",
                details={"documentId": duplicate["id"]},
            )

    @staticmethod
    def _course(row: sqlite3.Row, *, owner_user_id: str | None, is_admin: bool) -> Course:
        values = dict(row)
        values["is_owner"] = bool(owner_user_id and row["owner_user_id"] == owner_user_id)
        values["can_manage"] = is_admin or values["is_owner"]
        return Course.model_validate(values)

    def _load_course(self, course_id: str) -> sqlite3.Row:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT courses.*,
                    (SELECT COUNT(*) FROM documents WHERE course_id = courses.id)
                        AS document_count,
                    CASE
                        WHEN NOT EXISTS (
                            SELECT 1 FROM documents WHERE course_id = courses.id
                        ) THEN 'empty'
                        WHEN EXISTS (
                            SELECT 1 FROM documents
                            WHERE course_id = courses.id AND status = 'failed'
                        ) THEN 'failed'
                        WHEN EXISTS (
                            SELECT 1 FROM documents
                            WHERE course_id = courses.id AND status != 'ready'
                        ) THEN 'indexing'
                        ELSE 'indexed'
                    END AS index_status
                FROM courses
                WHERE courses.id = ?
                """,
                (course_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Course could not be loaded")
        return cast(sqlite3.Row, row)

    def create_course(
        self,
        payload: CourseCreate,
        *,
        owner_user_id: str | None = None,
        is_admin: bool = True,
        publication_status: PublicationStatus | None = None,
    ) -> Course:
        """Create a course, optionally with an explicit publication state.

        An administrator course is published as it is created — that is the existing behaviour and
        stays the default. Campus material needs the opposite: it is created **not published**, so
        that nothing reaches a student before a reviewer has decided its rights, and so that the
        decision is one transaction rather than a create-then-demote pair that a crash could split.
        A non-administrator cannot use this to publish anything.
        """
        course_type = "official" if is_admin else "user"
        if self.settings.v3_enabled and payload.id.startswith("ws-"):
            raise ApiError(422, "RESERVED_COURSE_ID", "This course ID namespace is reserved.")
        if not is_admin and not owner_user_id:
            # A private course without an owner is not a duplicate-ID problem, but the insert
            # failed a NOT NULL and the handler below used to report it as `COURSE_EXISTS` — a
            # false cause, and one the caller acts on: `ui_extension/domain.py` retries
            # `COURSE_EXISTS` three times against fresh random ids, so a missing owner would have
            # been retried and then surfaced as a duplicate that never existed. Say what is wrong.
            raise ApiError(
                422,
                "COURSE_OWNER_REQUIRED",
                "A private course needs its owner; pass owner_user_id.",
            )
        if (
            publication_status is not None
            and not is_admin
            and publication_status != PublicationStatus.PRIVATE
        ):
            raise ApiError(
                403, "PUBLICATION_NOT_ALLOWED", "Only an administrator can publish a course."
            )
        if publication_status is None:
            publication_status = (
                PublicationStatus.PUBLISHED if is_admin else PublicationStatus.PRIVATE
            )
        # A course that is not published is not visible to anyone but its owner and admins.
        visibility = "public" if publication_status == PublicationStatus.PUBLISHED else "private"
        owner = None if is_admin else owner_user_id
        try:
            with self.database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if not is_admin:
                    workspace_filter = (
                        " AND NOT EXISTS (SELECT 1 FROM learning_workspaces "
                        "WHERE private_course_id=courses.id)"
                        if self.settings.v3_enabled
                        else ""
                    )
                    owned_courses = connection.execute(
                        "SELECT COUNT(*) FROM courses "
                        "WHERE owner_user_id = ? AND course_type = 'user'"
                        + workspace_filter,
                        (owner_user_id,),
                    ).fetchone()[0]
                    if owned_courses >= self.settings.user_course_max_courses:
                        raise ApiError(
                            429,
                            "COURSE_QUOTA_EXCEEDED",
                            "The private-course quota has been reached.",
                            details={"limit": self.settings.user_course_max_courses},
                        )
                # `display_type` and `requires_student_verification` arrive with the V3 schema
                # (migration 025 adds them under a table_info guard), so a deployment without V3
                # does not have them and the INSERT must not name them. The full suite caught that
                # the hard way: naming them unconditionally broke every non-V3 test with
                # "table courses has no column named display_type".
                course_columns = {
                    info["name"] for info in connection.execute("PRAGMA table_info(courses)")
                }
                has_display_columns = {
                    "display_type",
                    "requires_student_verification",
                } <= course_columns
                optional_columns = (
                    ", display_type, requires_student_verification" if has_display_columns else ""
                )
                optional_placeholders = ", ?, ?" if has_display_columns else ""
                values: list[object] = [
                    payload.id,
                    payload.name,
                    payload.description,
                    owner,
                    course_type,
                    visibility,
                    publication_status.value,
                    publication_status.value,
                ]
                if has_display_columns:
                    # Migration 025 states the policy -- "official courses display as campus
                    # courses and require verification" -- but its backfill only touches rows that
                    # existed when the column was added, so a course created afterwards kept
                    # `display_type=NULL, requires_student_verification=0`. The access gates OR that
                    # flag with `display_type == 'campus'` and `course_type == 'official'`, so
                    # nothing was ever let through; what was wrong was the column disagreeing with
                    # the policy, which a future reader of the flag alone would inherit.
                    values.extend(["campus" if is_admin else "private", 1 if is_admin else 0])
                connection.execute(
                    f"""
                    INSERT INTO courses (
                        id, name, description, owner_user_id, course_type, visibility,
                        publication_status, published_at, updated_at{optional_columns}
                    ) VALUES (?, ?, ?, ?, ?, ?, ?,
                        CASE WHEN ? = 'published'
                            THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now') ELSE NULL END,
                        strftime('%Y-%m-%dT%H:%M:%fZ', 'now'){optional_placeholders})
                    """,
                    values,
                )
                row = connection.execute(
                    "SELECT * FROM courses WHERE id = ?", (payload.id,)
                ).fetchone()
        except sqlite3.IntegrityError as error:
            # Only a UNIQUE violation means "this ID is taken". Every other integrity failure
            # (a missing owner, a foreign key, a CHECK) is a different problem, and reporting it
            # as `COURSE_EXISTS` both hides the cause and triggers the caller's collision retry.
            if "UNIQUE" in str(error).upper():
                raise ApiError(
                    409, "COURSE_EXISTS", "A course with this ID already exists."
                ) from error
            raise ApiError(
                422,
                "COURSE_CREATE_FAILED",
                f"The course could not be created: {error}",
            ) from error
        if row is None:
            raise RuntimeError("Created course could not be loaded")
        return self._course(
            self._load_course(payload.id), owner_user_id=owner_user_id, is_admin=is_admin
        )

    def list_courses(
        self,
        *,
        page: int,
        page_size: int,
        owner_user_id: str | None = None,
        is_admin: bool = True,
    ) -> CoursePage:
        offset = (page - 1) * page_size
        # Administrator status grants official-content administration, not ambient access
        # to another owner's private course metadata. Review uses scoped snapshots instead.
        where = "(visibility = 'public' OR owner_user_id = ?)"
        if self.settings.v3_enabled:
            where += (
                " AND NOT EXISTS (SELECT 1 FROM learning_workspaces "
                "WHERE private_course_id=courses.id)"
            )
        parameters: tuple[object, ...] = (owner_user_id,)
        with self.database.connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM courses WHERE {where}", parameters
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT courses.*,
                    COUNT(documents.id) AS document_count,
                    CASE
                        WHEN COUNT(documents.id) = 0 THEN 'empty'
                        WHEN SUM(CASE WHEN documents.status = 'failed' THEN 1 ELSE 0 END) > 0
                            THEN 'failed'
                        WHEN SUM(CASE WHEN documents.status != 'ready' THEN 1 ELSE 0 END) > 0
                            THEN 'indexing'
                        ELSE 'indexed'
                    END AS index_status
                FROM courses
                LEFT JOIN documents ON documents.course_id = courses.id
                WHERE {where}
                GROUP BY courses.id
                ORDER BY courses.updated_at DESC, courses.id LIMIT ? OFFSET ?
                """,
                (*parameters, page_size, offset),
            ).fetchall()
        return CoursePage(
            items=[
                self._course(row, owner_user_id=owner_user_id, is_admin=is_admin)
                for row in rows
            ],
            page=page,
            page_size=page_size,
            total=total,
        )

    def get_course(
        self,
        course_id: str,
        *,
        owner_user_id: str,
        is_admin: bool,
    ) -> Course:
        self._require_course(
            course_id,
            owner_user_id=owner_user_id,
            is_admin=is_admin,
        )
        return self._course(
            self._load_course(course_id), owner_user_id=owner_user_id, is_admin=is_admin
        )

    def list_documents(
        self,
        course_id: str,
        *,
        page: int,
        page_size: int,
        owner_user_id: str | None = None,
        is_admin: bool = True,
    ) -> DocumentPage:
        self._require_course(course_id, owner_user_id=owner_user_id, is_admin=is_admin)
        offset = (page - 1) * page_size
        with self.database.connect() as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM documents WHERE course_id = ?", (course_id,)
            ).fetchone()[0]
            rows = connection.execute(
                """
                SELECT id, course_id, filename, media_type, extension, sha256, byte_size, status,
                    chunk_count, error_message, created_at, updated_at
                FROM documents
                WHERE course_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (course_id, page_size, offset),
            ).fetchall()
        return DocumentPage(
            items=[Document.model_validate(dict(row)) for row in rows],
            page=page,
            page_size=page_size,
            total=total,
        )

    def get_job(
        self,
        job_id: str,
        *,
        owner_user_id: str | None = None,
        is_admin: bool = True,
    ) -> IngestionJob:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT ingestion_jobs.*, documents.course_id
                FROM ingestion_jobs
                JOIN documents ON documents.id = ingestion_jobs.document_id
                WHERE ingestion_jobs.id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            raise ApiError(404, "JOB_NOT_FOUND", "The ingestion job was not found.")
        try:
            self._require_course(
                row["course_id"], owner_user_id=owner_user_id, is_admin=is_admin
            )
        except ApiError as error:
            raise ApiError(404, "JOB_NOT_FOUND", "The ingestion job was not found.") from error
        return IngestionJob.model_validate(
            {key: row[key] for key in IngestionJob.model_fields}
        )

    def update_course(
        self,
        course_id: str,
        payload: CourseUpdate,
        *,
        owner_user_id: str,
        is_admin: bool,
    ) -> Course:
        self._require_course(
            course_id, owner_user_id=owner_user_id, is_admin=is_admin, write=True
        )
        changes = payload.model_dump(exclude_none=True)
        if not changes:
            raise ApiError(422, "EMPTY_UPDATE", "At least one course field is required.")
        assignments = [f"{field} = ?" for field in changes]
        with self.database.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE courses SET {', '.join(assignments)},
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (*changes.values(), course_id),
            )
        if cursor.rowcount != 1:
            raise RuntimeError("Updated course could not be loaded")
        return self._course(
            self._load_course(course_id), owner_user_id=owner_user_id, is_admin=is_admin
        )

    def delete_course(
        self,
        course_id: str,
        *,
        owner_user_id: str,
        is_admin: bool,
    ) -> None:
        self._require_course(
            course_id, owner_user_id=owner_user_id, is_admin=is_admin, write=True
        )
        with self.database.connect() as connection:
            if self.settings.v3_enabled and connection.execute(
                "SELECT 1 FROM learning_workspaces WHERE course_id=? OR private_course_id=?",
                (course_id, course_id),
            ).fetchone():
                raise ApiError(
                    409, "ACTIVE_WORKSPACE",
                    "Archive learning workspaces before deleting this course."
                )
            if self.settings.v3_enabled:
                stored_rows = connection.execute(
                    "SELECT document_versions.stored_path FROM document_versions "
                    "WHERE document_versions.course_id=? "
                    "UNION SELECT derived_artifacts.stored_path FROM derived_artifacts "
                    "JOIN document_versions ON document_versions.id="
                    "derived_artifacts.document_version_id "
                    "WHERE document_versions.course_id=? "
                    "AND derived_artifacts.stored_path IS NOT NULL",
                    (course_id, course_id),
                ).fetchall()
            else:
                stored_rows = connection.execute(
                    "SELECT stored_path FROM documents WHERE course_id = ?", (course_id,)
                ).fetchall()
            paths = [Path(row["stored_path"]) for row in stored_rows]
            connection.execute("DELETE FROM courses WHERE id = ?", (course_id,))
        for path in paths:
            self._delete_stored_file(path)
        self._remove_empty_upload_parents(paths)

    def delete_document(
        self,
        course_id: str,
        document_id: str,
        *,
        owner_user_id: str,
        is_admin: bool,
    ) -> None:
        self._require_course(
            course_id, owner_user_id=owner_user_id, is_admin=is_admin, write=True
        )
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT stored_path FROM documents WHERE id = ? AND course_id = ?",
                (document_id, course_id),
            ).fetchone()
            if row is None:
                raise ApiError(404, "DOCUMENT_NOT_FOUND", "The document was not found.")
            if self.settings.v3_enabled:
                stored_rows = connection.execute(
                    "SELECT stored_path FROM document_versions WHERE document_id=? "
                    "UNION SELECT derived_artifacts.stored_path FROM derived_artifacts "
                    "JOIN document_versions ON document_versions.id="
                    "derived_artifacts.document_version_id "
                    "WHERE document_versions.document_id=? "
                    "AND derived_artifacts.stored_path IS NOT NULL",
                    (document_id, document_id),
                ).fetchall()
                paths = [Path(item["stored_path"]) for item in stored_rows]
            else:
                paths = [Path(row["stored_path"])]
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        for path in paths:
            self._delete_stored_file(path)
        self._remove_empty_upload_parents(paths)

    def _delete_stored_file(self, path: Path) -> None:
        stored_path = path.resolve()
        roots = (
            self.settings.upload_dir.resolve(),
            self.settings.storage_cache_dir.resolve(),
        )
        if not any(_is_relative_to(stored_path, root) for root in roots):
            LOGGER.error("Refused to delete document path outside upload root")
            return
        stored_path.unlink(missing_ok=True)
        stored_path.with_name(f"{stored_path.name}.ocr.md").unlink(missing_ok=True)

    def _remove_empty_upload_parents(self, paths: list[Path]) -> None:
        for path in paths:
            upload_root = next(
                (
                    root
                    for root in (
                        self.settings.upload_dir.resolve(),
                        self.settings.storage_cache_dir.resolve(),
                    )
                    if _is_relative_to(path.resolve(), root)
                ),
                None,
            )
            if upload_root is None:
                continue
            parent = path.resolve().parent
            while parent != upload_root:
                try:
                    parent.relative_to(upload_root)
                    parent.rmdir()
                except (OSError, ValueError):
                    break
                parent = parent.parent

    def get_document(self, document_id: str) -> Document:
        return self._get_document(document_id)

    def attach_pdf_transcription(self, document_id: str, transcription: str) -> None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT stored_path, extension FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
        if row is None:
            raise ValueError("Document does not exist")
        if row["extension"] != ".pdf":
            raise ValueError("Transcriptions can only be attached to PDF documents")
        stored_path = Path(row["stored_path"])
        stored_path.with_name(f"{stored_path.name}.ocr.md").write_text(
            transcription,
            encoding="utf-8",
        )

    def retry_failed_document(self, document_id: str) -> IngestionJob:
        document = self._get_document(document_id)
        if document.status.value != "failed":
            raise ValueError("Only failed documents can be retried")
        job_id = f"job_{uuid4().hex}"
        with self.database.connect() as connection:
            connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            connection.execute(
                """
                UPDATE documents
                SET status = 'pending', chunk_count = 0, error_message = NULL,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (document_id,),
            )
            connection.execute(
                "INSERT INTO ingestion_jobs (id, document_id, status) VALUES (?, ?, 'queued')",
                (job_id, document_id),
            )
        self.process_document(document_id, job_id)
        return self.get_job(job_id)

    def queue_document(
        self,
        *,
        course_id: str,
        filename: str,
        media_type: str,
        content: bytes,
        owner_user_id: str | None = None,
        is_admin: bool = True,
    ) -> UploadAccepted:
        self._require_course(
            course_id, owner_user_id=owner_user_id, is_admin=is_admin, write=True
        )
        extension = self._validate_upload(filename, media_type, content)
        digest = hashlib.sha256(content).hexdigest()
        document_id = f"doc_{uuid4().hex}"
        job_id = f"job_{uuid4().hex}"
        course = self._require_course(
            course_id, owner_user_id=owner_user_id, is_admin=is_admin, write=True
        )
        if course["course_type"] == "user":
            owner_segment = _storage_owner_segment(str(course["owner_user_id"]))
            destination = (
                self.settings.upload_dir
                / "users"
                / owner_segment
                / course_id
                / f"{document_id}{extension}"
            )
        else:
            destination = (
                self.settings.upload_dir / "official" / course_id / f"{document_id}{extension}"
            )
        storage_object_id: str | None = None
        storage_key: str | None = None
        stored_object = None
        cache_available = True
        if isinstance(self.storage_backend, AliyunOssStorageBackend):
            storage_key = canonical_object_key(
                owner_user_id=owner_user_id or "official-system",
                course_id=course_id,
                document_id=document_id,
                sha256=digest,
                extension=extension,
            )
            destination = self.settings.storage_cache_dir / storage_key
            storage_object_id = f"obj_{uuid4().hex}"
            self._check_document_admission(
                course=course,
                course_id=course_id,
                owner_user_id=owner_user_id or "official-system",
                is_admin=is_admin,
                byte_size=len(content),
                sha256=digest,
            )
            stored_object = self.storage_backend.put_bytes(
                storage_key,
                content,
                expected_sha256=digest,
                content_type=media_type,
            )
            cache_available = self._cache_if_capacity_allows(
                storage_key, content, destination
            )
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not is_admin and course["course_type"] == "user":
                document_count = connection.execute(
                    "SELECT COUNT(*) FROM documents WHERE course_id = ?",
                    (course_id,),
                ).fetchone()[0]
                if document_count >= self.settings.user_course_max_files:
                    raise ApiError(
                        429,
                        "COURSE_FILE_QUOTA_EXCEEDED",
                        "The course file quota has been reached.",
                        details={"limit": self.settings.user_course_max_files},
                    )
                used_bytes = connection.execute(
                    "SELECT COALESCE(SUM(documents.byte_size), 0) FROM documents "
                    "JOIN courses ON courses.id = documents.course_id "
                    "WHERE courses.owner_user_id = ? AND courses.course_type = 'user'",
                    (owner_user_id,),
                ).fetchone()[0]
                if used_bytes + len(content) > self.settings.user_course_max_total_upload_bytes:
                    raise ApiError(
                        413,
                        "USER_STORAGE_QUOTA_EXCEEDED",
                        "The total private-course upload quota would be exceeded.",
                        details={
                            "limitBytes": self.settings.user_course_max_total_upload_bytes,
                            "usedBytes": used_bytes,
                        },
                    )
            duplicate = connection.execute(
                "SELECT id FROM documents WHERE course_id = ? AND sha256 = ?",
                (course_id, digest),
            ).fetchone()
            if duplicate is not None:
                raise ApiError(
                    409,
                    "DUPLICATE_DOCUMENT",
                    "This course already contains a document with the same content.",
                    details={"documentId": duplicate["id"]},
                )
            try:
                if stored_object is not None:
                    connection.execute(
                        """
                        INSERT INTO storage_objects(
                            id,backend,bucket,object_key,version_id,byte_size,sha256,
                            crc64,etag,media_type,state,owner_user_id,course_id,
                            local_cache_path,verified_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,'CANONICAL',?,?,?,
                            strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                        """,
                        (
                            storage_object_id,
                            "ALIYUN_OSS",
                            stored_object.bucket,
                            stored_object.key,
                            stored_object.version_id,
                            stored_object.size,
                            stored_object.sha256,
                            stored_object.crc64,
                            stored_object.etag,
                            stored_object.content_type,
                            owner_user_id or "official-system",
                            course_id,
                            str(destination) if cache_available else None,
                        ),
                    )
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(content)
                document_values = (
                    document_id,
                    course_id,
                    filename,
                    str(destination),
                    media_type,
                    extension,
                    digest,
                    len(content),
                )
                if self.database.v3_enabled:
                    connection.execute(
                        """
                        INSERT INTO documents (
                            id,course_id,filename,stored_path,media_type,extension,sha256,
                            byte_size,status,error_message,storage_object_id
                        ) VALUES(?,?,?,?,?,?,?,?,'pending',?,?)
                        """,
                        (
                            *document_values,
                            None if cache_available else "WAITING_CAPACITY",
                            storage_object_id,
                        ),
                    )
                else:
                    connection.execute(
                        """
                        INSERT INTO documents (
                            id,course_id,filename,stored_path,media_type,extension,sha256,
                            byte_size,status
                        ) VALUES(?,?,?,?,?,?,?,?,'pending')
                        """,
                        document_values,
                    )
                connection.execute(
                    "INSERT INTO ingestion_jobs (id, document_id, status,error_message) "
                    "VALUES (?, ?, 'queued', ?)",
                    (job_id, document_id, None if cache_available else "WAITING_CAPACITY"),
                )
                if storage_object_id is not None:
                    connection.execute(
                        "UPDATE storage_objects SET document_id=? WHERE id=?",
                        (document_id, storage_object_id),
                    )
                # Make commit failures part of the same compensating boundary as inserts.
                connection.commit()
            except Exception:
                if stored_object is None:
                    self._delete_stored_file(destination)
                    self._remove_empty_upload_parents([destination])
                else:
                    LOGGER.exception(
                        "Durable object %s exists without a committed document; retain for GC audit",
                        storage_object.key,
                    )
                raise

        return UploadAccepted(
            document=self._get_document(document_id),
            job=self.get_job(job_id, owner_user_id=owner_user_id, is_admin=is_admin),
        )

    def import_snapshot(self, *, course_id: str, owner_user_id: str,
                        content: bytes, snapshot: dict) -> dict:
        """Import trusted, frozen server-side index without an embedding call.

        Queueing retains the normal upload policy, storage layout, quotas and
        version triggers. Content deduplication is also the crash/retry boundary.
        This method is internal, never accepts index data from an HTTP caller.
        """
        if hashlib.sha256(content).hexdigest() != snapshot['sha256']:
            raise ApiError(409, 'SNAPSHOT_HASH_MISMATCH', 'Snapshot integrity check failed.')
        if snapshot['embedding_model'] != self.settings.rag_embedding_model:
            raise ApiError(409, 'SNAPSHOT_INDEX_INCOMPATIBLE', 'Snapshot index requires an approved rebuild.')
        self._require_course(course_id,owner_user_id=owner_user_id,is_admin=False,write=True)
        with self.database.connect() as connection:
            existing=connection.execute('SELECT id FROM documents WHERE course_id=? AND sha256=?',
                                        (course_id,snapshot['sha256'])).fetchone()
        try:
            if existing:
                document_id=existing['id']
            else:
                accepted = self.queue_document(course_id=course_id, filename=snapshot['filename'],
                    media_type=snapshot['media_type'], content=content,
                    owner_user_id=owner_user_id, is_admin=False)
                document_id = accepted.document.id
        except ApiError as error:
            if error.code not in {'DUPLICATE_DOCUMENT','COURSE_FILE_QUOTA_EXCEEDED','USER_STORAGE_QUOTA_EXCEEDED'}:
                raise
            with self.database.connect() as connection:
                existing = connection.execute('SELECT id FROM documents WHERE course_id=? AND sha256=?',
                                              (course_id, snapshot['sha256'])).fetchone()
                if existing is None: raise
                document_id = existing['id']
        chunk_map = {}
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            for chunk in snapshot['chunks']:
                chunk_id = 'chk_' + hashlib.sha256(f"{document_id}:{chunk['id']}".encode()).hexdigest()[:32]
                chunk_map[chunk['id']] = chunk_id
                connection.execute('INSERT OR IGNORE INTO chunks(id,document_id,course_id,ordinal,content,locator_type,locator_value,section,embedding,metadata_json,parent_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (chunk_id, document_id, course_id, chunk['ordinal'], chunk['content'],
                     chunk['locator_type'], chunk['locator_value'], chunk['section'],
                     chunk['embedding'], chunk['metadata_json'], chunk['parent_key']))
            connection.execute("UPDATE documents SET status='ready',chunk_count=?,error_message=NULL WHERE id=?",
                               (len(snapshot['chunks']), document_id))
            connection.execute("UPDATE ingestion_jobs SET status='completed',processed_chunks=?,error_message=NULL WHERE document_id=?",
                               (len(snapshot['chunks']), document_id))
            version = connection.execute('SELECT id FROM document_versions WHERE document_id=? ORDER BY version DESC LIMIT 1', (document_id,)).fetchone()
        return {'document_id': document_id, 'version_id': version['id'], 'chunks': chunk_map}

    def process_document(self, document_id: str, job_id: str) -> None:
        try:
            if not self._ensure_document_cache(document_id, job_id):
                return
            with self.database.connect() as connection:
                connection.execute(
                    """
                    UPDATE documents
                    SET status = 'processing', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (document_id,),
                )
                connection.execute(
                    """
                    UPDATE ingestion_jobs
                    SET status = 'processing', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (job_id,),
                )
                row = connection.execute(
                    "SELECT course_id, stored_path, extension FROM documents WHERE id = ?",
                    (document_id,),
                ).fetchone()
            if row is None:
                raise RuntimeError("Document disappeared before ingestion")

            if row["extension"] not in LOADERS:
                with self.database.connect() as connection:
                    connection.execute(
                        "UPDATE documents SET status='ready',chunk_count=0,error_message=NULL,"
                        "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                        (document_id,),
                    )
                    connection.execute(
                        "UPDATE ingestion_jobs SET status='completed',processed_chunks=0,"
                        "error_message=NULL,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                        "WHERE id=?",
                        (job_id,),
                    )
                return

            sections = load_document(Path(row["stored_path"]))
            chunks = chunk_sections(
                sections,
                chunk_size=self.settings.chunk_size,
                overlap=self.settings.chunk_overlap,
            )
            embeddings: list[list[float]] = []
            for offset in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
                batch = chunks[offset : offset + EMBEDDING_BATCH_SIZE]
                embeddings.extend(
                    self.embedding_provider.embed_texts([chunk.content for chunk in batch])
                )
            if len(embeddings) != len(chunks) or any(not vector for vector in embeddings):
                raise RuntimeError("Embedding provider returned an invalid result count")

            with self.database.connect() as connection:
                for chunk, embedding in zip(chunks, embeddings, strict=True):
                    connection.execute(
                        """
                        INSERT INTO chunks (
                            id, document_id, course_id, ordinal, content, locator_type,
                            locator_value, section, embedding, metadata_json, parent_key
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"chk_{uuid4().hex}",
                            document_id,
                            row["course_id"],
                            chunk.ordinal,
                            chunk.content,
                            chunk.locator_type,
                            chunk.locator_value,
                            chunk.section,
                            json.dumps(embedding, separators=(",", ":")),
                            json.dumps(chunk.metadata, ensure_ascii=False, separators=(",", ":")),
                            chunk.parent_key,
                        ),
                    )
                connection.execute(
                    """
                    UPDATE documents
                    SET status = 'ready', chunk_count = ?, error_message = NULL,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (len(chunks), document_id),
                )
                connection.execute(
                    """
                    UPDATE ingestion_jobs
                    SET status = 'completed', processed_chunks = ?, error_message = NULL,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (len(chunks), job_id),
                )
        except Exception as error:
            public_message = (
                error.message if isinstance(error, DocumentLoadError) else "Ingestion failed."
            )
            LOGGER.exception("Document ingestion failed for %s", document_id)
            with self.database.connect() as connection:
                connection.execute(
                    """
                    UPDATE documents
                    SET status = 'failed', error_message = ?,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (public_message, document_id),
                )
                connection.execute(
                    """
                    UPDATE ingestion_jobs
                    SET status = 'failed', error_message = ?,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (public_message, job_id),
                )

    def _validate_upload(self, filename: str, media_type: str, content: bytes) -> str:
        if (
            not filename
            or len(filename) > 200
            or "/" in filename
            or "\\" in filename
            or any(ord(character) < 32 for character in filename)
        ):
            raise ApiError(400, "INVALID_FILENAME", "The upload filename is not safe.")
        extension = Path(filename).suffix.lower()
        allowed_extensions = MEDIA_TYPES if self.settings.v3_enabled else LOADERS
        if extension not in allowed_extensions:
            raise ApiError(400, "UNSUPPORTED_EXTENSION", "This file extension is not supported.")
        if media_type not in MEDIA_TYPES[extension]:
            raise ApiError(
                400,
                "INVALID_MEDIA_TYPE",
                "The media type does not match the file type.",
            )
        if len(content) > self.settings.max_upload_bytes:
            raise ApiError(400, "FILE_TOO_LARGE", "The uploaded file exceeds the size limit.")
        if not content:
            raise ApiError(400, "EMPTY_FILE", "The uploaded file is empty.")
        validate_file_content(extension, content, self.settings)
        return extension

    def _require_course(
        self,
        course_id: str,
        *,
        owner_user_id: str | None = None,
        is_admin: bool = True,
        write: bool = False,
    ) -> sqlite3.Row:
        return require_course_access(
            self.database,
            course_id,
            owner_user_id=owner_user_id,
            is_admin=is_admin,
            write=write,
        )

    def _get_document(self, document_id: str) -> Document:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, course_id, filename, media_type, extension, sha256, byte_size, status,
                    chunk_count, error_message, created_at, updated_at
                FROM documents WHERE id = ?
                """,
                (document_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Document could not be loaded")
        return Document.model_validate(dict(row))
