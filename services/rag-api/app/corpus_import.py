import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.errors import ApiError
from app.models import CourseCreate
from app.services.ingestion import IngestionService

COURSES = {
    "cs3481": ("CS3481", "Course materials imported from the supplied CS3481 exports."),
    "ge2324": ("GE2324", "Course materials imported from the supplied GE2324 exports."),
}

MEDIA_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

ImportStatus = Literal["ready", "failed", "duplicate", "inventory-only", "missing", "invalid"]


class InventoryFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    courseId: str
    sourcePath: str
    relativePath: str
    fullPath: str
    filename: str
    extension: str
    sizeBytes: int = Field(ge=0)
    lastWriteTimeUtc: str
    importerMode: str


class CorpusInventory(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schemaVersion: int
    sources: list[dict[str, object]]
    files: list[InventoryFile]


class ImportItem(BaseModel):
    course_id: str
    filename: str
    extension: str
    status: ImportStatus
    chunks: int = 0
    reason: str | None = None


class ImportSummary(BaseModel):
    total: int
    ready: int = 0
    failed: int = 0
    duplicate: int = 0
    inventory_only: int = 0
    missing: int = 0
    invalid: int = 0
    chunks: int = 0


class ImportReport(BaseModel):
    schema_version: int = 1
    embedding_mode: str
    generated_at: datetime
    summary: ImportSummary
    items: list[ImportItem]


def load_inventory(path: Path) -> CorpusInventory:
    return CorpusInventory.model_validate_json(path.read_text(encoding="utf-8-sig"))


def _is_within_source(file_path: Path, source_path: Path) -> bool:
    try:
        file_path.resolve(strict=False).relative_to(source_path.resolve(strict=False))
    except ValueError:
        return False
    return True


def _ensure_courses(service: IngestionService) -> None:
    existing = {course.id for course in service.list_courses(page=1, page_size=100).items}
    for course_id, (name, description) in COURSES.items():
        if course_id not in existing:
            service.create_course(CourseCreate(id=course_id, name=name, description=description))


def import_corpus(
    inventory: CorpusInventory,
    *,
    service: IngestionService,
    embedding_mode: str,
    transcription_dir: Path | None = None,
    on_progress: Callable[[int, int, ImportItem], None] | None = None,
) -> ImportReport:
    """Import the generated read-only inventory and report every record explicitly."""

    _ensure_courses(service)
    items: list[ImportItem] = []
    total = len(inventory.files)
    for index, record in enumerate(inventory.files, start=1):
        extension = record.extension.casefold()
        path = Path(record.fullPath)
        source = Path(record.sourcePath)
        if record.importerMode != "index" or extension not in MEDIA_TYPES:
            item = ImportItem(
                course_id=record.courseId,
                filename=record.filename,
                extension=extension,
                status="inventory-only",
                reason=f"Importer mode: {record.importerMode}",
            )
        elif not _is_within_source(path, source):
            item = ImportItem(
                course_id=record.courseId,
                filename=record.filename,
                extension=extension,
                status="invalid",
                reason="The file path escapes its declared source directory.",
            )
        elif not path.is_file():
            item = ImportItem(
                course_id=record.courseId,
                filename=record.filename,
                extension=extension,
                status="missing",
                reason="The inventory file is no longer present.",
            )
        elif path.stat().st_size != record.sizeBytes:
            item = ImportItem(
                course_id=record.courseId,
                filename=record.filename,
                extension=extension,
                status="invalid",
                reason="The source size changed after the inventory was generated.",
            )
        else:
            try:
                content = path.read_bytes()
                transcription_path = (
                    transcription_dir / f"{hashlib.sha256(content).hexdigest()}.md"
                    if transcription_dir is not None and extension == ".pdf"
                    else None
                )
                transcription = (
                    transcription_path.read_text(encoding="utf-8")
                    if transcription_path is not None and transcription_path.is_file()
                    else None
                )
                accepted = service.queue_document(
                    course_id=record.courseId,
                    filename=record.filename,
                    media_type=MEDIA_TYPES[extension],
                    content=content,
                )
                if transcription is not None:
                    service.attach_pdf_transcription(accepted.document.id, transcription)
                service.process_document(accepted.document.id, accepted.job.id)
                job = service.get_job(accepted.job.id)
                if job.status.value == "completed":
                    item = ImportItem(
                        course_id=record.courseId,
                        filename=record.filename,
                        extension=extension,
                        status="ready",
                        chunks=job.processed_chunks,
                        reason=(
                            "A verified local transcription supplied text for this scanned PDF."
                            if transcription is not None
                            else None
                        ),
                    )
                else:
                    item = ImportItem(
                        course_id=record.courseId,
                        filename=record.filename,
                        extension=extension,
                        status="failed",
                        reason=job.error_message or "Ingestion failed.",
                    )
            except ApiError as error:
                if error.code != "DUPLICATE_DOCUMENT":
                    raise
                document_id = error.details.get("documentId")
                if not isinstance(document_id, str):
                    raise RuntimeError("Duplicate error did not identify its document") from error
                document = service.get_document(document_id)
                if document.status.value == "failed":
                    if transcription is not None:
                        service.attach_pdf_transcription(document_id, transcription)
                    job = service.retry_failed_document(document_id)
                    item = ImportItem(
                        course_id=record.courseId,
                        filename=record.filename,
                        extension=extension,
                        status="ready" if job.status.value == "completed" else "failed",
                        chunks=job.processed_chunks,
                        reason=(
                            "A verified local transcription supplied text for this scanned PDF."
                            if transcription is not None and job.status.value == "completed"
                            else job.error_message
                        ),
                    )
                elif document.status.value == "ready":
                    item = ImportItem(
                        course_id=record.courseId,
                        filename=record.filename,
                        extension=extension,
                        status="ready",
                        chunks=document.chunk_count,
                        reason="Already indexed; no duplicate rows were created.",
                    )
                else:
                    item = ImportItem(
                        course_id=record.courseId,
                        filename=record.filename,
                        extension=extension,
                        status="duplicate",
                        reason=f"Existing document is {document.status.value}.",
                    )
        items.append(item)
        if on_progress:
            on_progress(index, total, item)

    summary = ImportSummary(total=total)
    for item in items:
        summary.chunks += item.chunks
        field_name = item.status.replace("-", "_")
        setattr(summary, field_name, getattr(summary, field_name) + 1)
    return ImportReport(
        embedding_mode=embedding_mode,
        generated_at=datetime.now(UTC),
        summary=summary,
        items=items,
    )
