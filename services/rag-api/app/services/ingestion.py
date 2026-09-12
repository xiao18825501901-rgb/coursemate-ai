import hashlib
import json
import logging
import sqlite3
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
    Document,
    DocumentPage,
    IngestionJob,
    UploadAccepted,
)
from app.rag.chunking import chunk_sections
from app.rag.embeddings import EmbeddingProvider
from app.rag.errors import DocumentLoadError
from app.rag.loaders import LOADERS, load_document

LOGGER = logging.getLogger(__name__)
EMBEDDING_BATCH_SIZE = 10


def _storage_owner_segment(owner_user_id: str) -> str:
    """Create a stable opaque path segment without exposing the identity provider subject."""

    return hashlib.sha256(owner_user_id.encode("utf-8")).hexdigest()[:32]


class MissingEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("OPENAI_API_KEY is required for document ingestion")


class IngestionService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self.database = database
        self.settings = settings
        self.embedding_provider = embedding_provider

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
    ) -> Course:
        course_type = "official" if is_admin else "user"
        if self.settings.v3_enabled and payload.id.startswith("ws-"):
            raise ApiError(422, "RESERVED_COURSE_ID", "This course ID namespace is reserved.")
        visibility = "public" if is_admin else "private"
        publication_status = "published" if is_admin else "private"
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
                connection.execute(
                    """
                    INSERT INTO courses (
                        id, name, description, owner_user_id, course_type, visibility,
                        publication_status, published_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?,
                        CASE WHEN ? = 'published'
                            THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now') ELSE NULL END,
                        strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                    """,
                    (
                        payload.id,
                        payload.name,
                        payload.description,
                        owner,
                        course_type,
                        visibility,
                        publication_status,
                        publication_status,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM courses WHERE id = ?", (payload.id,)
                ).fetchone()
        except sqlite3.IntegrityError as error:
            raise ApiError(409, "COURSE_EXISTS", "A course with this ID already exists.") from error
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
        upload_root = self.settings.upload_dir.resolve()
        stored_path = path.resolve()
        try:
            stored_path.relative_to(upload_root)
        except ValueError:
            LOGGER.error("Refused to delete document path outside upload root")
            return
        stored_path.unlink(missing_ok=True)
        stored_path.with_name(f"{stored_path.name}.ocr.md").unlink(missing_ok=True)

    def _remove_empty_upload_parents(self, paths: list[Path]) -> None:
        upload_root = self.settings.upload_dir.resolve()
        for path in paths:
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
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
                connection.execute(
                    """
                    INSERT INTO documents (
                        id, course_id, filename, stored_path, media_type, extension, sha256,
                        byte_size, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        document_id,
                        course_id,
                        filename,
                        str(destination),
                        media_type,
                        extension,
                        digest,
                        len(content),
                    ),
                )
                connection.execute(
                    "INSERT INTO ingestion_jobs (id, document_id, status) "
                    "VALUES (?, ?, 'queued')",
                    (job_id, document_id),
                )
                # Make commit failures part of the same compensating boundary as inserts.
                connection.commit()
            except Exception:
                self._delete_stored_file(destination)
                self._remove_empty_upload_parents([destination])
                raise

        return UploadAccepted(
            document=self._get_document(document_id),
            job=self.get_job(job_id, owner_user_id=owner_user_id, is_admin=is_admin),
        )

    def process_document(self, document_id: str, job_id: str) -> None:
        try:
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
