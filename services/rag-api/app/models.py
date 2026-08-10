from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


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


class CourseCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,49}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1_000)


class Course(CourseCreate):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
