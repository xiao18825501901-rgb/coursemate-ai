import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.course_access import require_course_access
from app.db import Database
from app.errors import ApiError
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

MEDIA_TYPES: dict[str, set[str]] = {
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".markdown": {"text/markdown", "text/plain", "application/octet-stream"},
    ".txt": {"text/plain", "application/octet-stream"},
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    },
    ".pptx": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/octet-stream",
    },
}


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

    def create_course(
        self,
        payload: CourseCreate,
        *,
        owner_user_id: str | None = None,
        is_admin: bool = True,
    ) -> Course:
        course_type = "official" if is_admin else "user"
        visibility = "public" if is_admin else "private"
        publication_status = "published" if is_admin else "private"
        owner = None if is_admin else owner_user_id
        try:
            with self.database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if not is_admin:
                    owned_courses = connection.execute(
                        "SELECT COUNT(*) FROM courses "
                        "WHERE owner_user_id = ? AND course_type = 'user'",
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
        return self._course(row, owner_user_id=owner_user_id, is_admin=is_admin)

    def list_courses(
        self,
        *,
        page: int,
        page_size: int,
        owner_user_id: str | None = None,
        is_admin: bool = True,
    ) -> CoursePage:
        offset = (page - 1) * page_size
        where = "1 = 1" if is_admin else "(visibility = 'public' OR owner_user_id = ?)"
        parameters: tuple[object, ...] = () if is_admin else (owner_user_id,)
        with self.database.connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM courses WHERE {where}", parameters
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT * FROM courses WHERE {where}
                ORDER BY updated_at DESC, id LIMIT ? OFFSET ?
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
        row = self._require_course(
            course_id,
            owner_user_id=owner_user_id,
            is_admin=is_admin,
        )
        return self._course(row, owner_user_id=owner_user_id, is_admin=is_admin)

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
        self._require_course(
            row["course_id"], owner_user_id=owner_user_id, is_admin=is_admin
        )
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
            connection.execute(
                f"""
                UPDATE courses SET {', '.join(assignments)},
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (*changes.values(), course_id),
            )
            row = connection.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        if row is None:
            raise RuntimeError("Updated course could not be loaded")
        return self._course(row, owner_user_id=owner_user_id, is_admin=is_admin)

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
            paths = [
                Path(row["stored_path"])
                for row in connection.execute(
                    "SELECT stored_path FROM documents WHERE course_id = ?", (course_id,)
                ).fetchall()
            ]
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
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        self._delete_stored_file(Path(row["stored_path"]))
        self._remove_empty_upload_parents([Path(row["stored_path"])])

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
                "INSERT INTO ingestion_jobs (id, document_id, status) VALUES (?, ?, 'queued')",
                (job_id, document_id),
            )

        return UploadAccepted(
            document=self._get_document(document_id),
            job=self.get_job(job_id),
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
                    "SELECT course_id, stored_path FROM documents WHERE id = ?", (document_id,)
                ).fetchone()
            if row is None:
                raise RuntimeError("Document disappeared before ingestion")

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
        if extension not in LOADERS:
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
        if extension == ".pdf" and not content.startswith(b"%PDF"):
            raise ApiError(400, "INVALID_FILE_CONTENT", "The file does not contain a PDF header.")
        if extension in {".docx", ".pptx"} and not content.startswith(b"PK"):
            raise ApiError(400, "INVALID_FILE_CONTENT", "The file is not an Office ZIP document.")
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
