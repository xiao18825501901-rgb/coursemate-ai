import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.db import Database
from app.errors import ApiError
from app.models import (
    Course,
    CourseCreate,
    CoursePage,
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

    def create_course(self, payload: CourseCreate) -> Course:
        try:
            with self.database.connect() as connection:
                connection.execute(
                    "INSERT INTO courses (id, name, description) VALUES (?, ?, ?)",
                    (payload.id, payload.name, payload.description),
                )
                row = connection.execute(
                    "SELECT * FROM courses WHERE id = ?", (payload.id,)
                ).fetchone()
        except sqlite3.IntegrityError as error:
            raise ApiError(409, "COURSE_EXISTS", "A course with this ID already exists.") from error
        if row is None:
            raise RuntimeError("Created course could not be loaded")
        return Course.model_validate(dict(row))

    def list_courses(self, *, page: int, page_size: int) -> CoursePage:
        offset = (page - 1) * page_size
        with self.database.connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM courses ORDER BY id LIMIT ? OFFSET ?",
                (page_size, offset),
            ).fetchall()
        return CoursePage(
            items=[Course.model_validate(dict(row)) for row in rows],
            page=page,
            page_size=page_size,
            total=total,
        )

    def list_documents(self, course_id: str, *, page: int, page_size: int) -> DocumentPage:
        self._require_course(course_id)
        offset = (page - 1) * page_size
        with self.database.connect() as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM documents WHERE course_id = ?", (course_id,)
            ).fetchone()[0]
            rows = connection.execute(
                """
                SELECT id, course_id, filename, media_type, extension, sha256, status,
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

    def get_job(self, job_id: str) -> IngestionJob:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise ApiError(404, "JOB_NOT_FOUND", "The ingestion job was not found.")
        return IngestionJob.model_validate(dict(row))

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
    ) -> UploadAccepted:
        self._require_course(course_id)
        extension = self._validate_upload(filename, media_type, content)
        digest = hashlib.sha256(content).hexdigest()
        document_id = f"doc_{uuid4().hex}"
        job_id = f"job_{uuid4().hex}"
        destination = self.settings.upload_dir / course_id / f"{document_id}{extension}"
        destination.parent.mkdir(parents=True, exist_ok=True)

        with self.database.connect() as connection:
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
            destination.write_bytes(content)
            connection.execute(
                """
                INSERT INTO documents (
                    id, course_id, filename, stored_path, media_type, extension, sha256, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    document_id,
                    course_id,
                    filename,
                    str(destination),
                    media_type,
                    extension,
                    digest,
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
                            locator_value, section, embedding
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def _require_course(self, course_id: str) -> None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT 1 FROM courses WHERE id = ?", (course_id,)).fetchone()
        if row is None:
            raise ApiError(404, "COURSE_NOT_FOUND", "The course was not found.")

    def _get_document(self, document_id: str) -> Document:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, course_id, filename, media_type, extension, sha256, status,
                    chunk_count, error_message, created_at, updated_at
                FROM documents WHERE id = ?
                """,
                (document_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Document could not be loaded")
        return Document.model_validate(dict(row))
