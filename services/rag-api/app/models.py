from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        from_attributes=True,
    )


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class CourseCreate(ApiModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,49}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1_000)


class Course(CourseCreate):
    created_at: datetime


class CoursePage(ApiModel):
    items: list[Course]
    page: int
    page_size: int
    total: int


class Document(ApiModel):
    id: str
    course_id: str
    filename: str
    media_type: str
    extension: str
    sha256: str
    status: DocumentStatus
    chunk_count: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class DocumentPage(ApiModel):
    items: list[Document]
    page: int
    page_size: int
    total: int


class IngestionJob(ApiModel):
    id: str
    document_id: str
    status: JobStatus
    processed_chunks: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class UploadAccepted(ApiModel):
    document: Document
    job: IngestionJob


class Health(ApiModel):
    status: str
    service: str


class QaChatRequest(ApiModel):
    course_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,49}$")
    question: str = Field(min_length=1, max_length=2_000)


class ErrorDetail(ApiModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorEnvelope(ApiModel):
    error: ErrorDetail
