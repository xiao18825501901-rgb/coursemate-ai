from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class LanguagePreference(StrEnum):
    AUTO = "auto"
    CHINESE = "zh-CN"
    ENGLISH = "en"
    BILINGUAL = "bilingual"


class CourseType(StrEnum):
    OFFICIAL = "official"
    USER = "user"


class CourseVisibility(StrEnum):
    PRIVATE = "private"
    PUBLIC = "public"


class PublicationStatus(StrEnum):
    PRIVATE = "private"
    PENDING = "pending"
    PUBLISHED = "published"
    REJECTED = "rejected"


class StudentLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class AnswerDepth(StrEnum):
    CONCISE = "concise"
    BALANCED = "balanced"
    DETAILED = "detailed"


class ExamplePreference(StrEnum):
    MINIMAL = "minimal"
    WHEN_HELPFUL = "when-helpful"
    WORKED = "worked"


class ExercisePolicy(StrEnum):
    NONE = "none"
    OFFER = "offer"
    ALWAYS = "always"


class CitationPreference(StrEnum):
    STANDARD = "standard"
    DETAILED = "detailed"


class MathDetailLevel(StrEnum):
    LIGHT = "light"
    STANDARD = "standard"
    FULL = "full"


class TerminologyStyle(StrEnum):
    PLAIN = "plain"
    BILINGUAL = "bilingual"
    FORMAL = "formal"


class TeachingStyle(StrEnum):
    INTUITION_FIRST = "intuition-first"
    STEP_BY_STEP = "step-by-step"
    SOCRATIC = "socratic"
    ANALOGY = "analogy"
    WORKED_EXAMPLES = "worked-examples"


class CourseCreate(ApiModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,49}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1_000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name cannot be blank")
        return value.strip()


class Course(CourseCreate):
    owner_user_id: str | None = Field(exclude=True)
    course_type: CourseType
    visibility: CourseVisibility
    publication_status: PublicationStatus
    published_at: datetime | None
    is_owner: bool = False
    can_manage: bool = False
    created_at: datetime
    updated_at: datetime


class CourseUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1_000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("name cannot be blank")
        return value.strip()


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
    conversation_id: str | None = Field(default=None, pattern=r"^conv_[a-f0-9]{32}$")
    question: str = Field(min_length=1, max_length=2_000)


class RetrievalDiagnosticsRequest(ApiModel):
    course_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,49}$")
    question: str = Field(min_length=1, max_length=2_000)


class ConversationCreate(ApiModel):
    course_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,49}$")
    preferred_language: LanguagePreference = LanguagePreference.AUTO


class ConversationUpdate(ApiModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("title must contain visible text")
        return normalized


class ConversationSummary(ApiModel):
    id: str
    course_id: str
    title: str
    preferred_language: LanguagePreference
    message_count: int
    created_at: datetime
    updated_at: datetime


class ConversationPage(ApiModel):
    items: list[ConversationSummary]
    page: int
    page_size: int
    total: int


class TeachingProfileInput(ApiModel):
    language: LanguagePreference = LanguagePreference.AUTO
    student_level: StudentLevel = StudentLevel.INTERMEDIATE
    learning_goal: str = Field(
        default="Understand the course material", min_length=1, max_length=240
    )
    teaching_styles: list[TeachingStyle] = Field(
        default_factory=lambda: [TeachingStyle.INTUITION_FIRST, TeachingStyle.STEP_BY_STEP],
        min_length=1,
        max_length=5,
    )
    answer_depth: AnswerDepth = AnswerDepth.BALANCED
    example_preference: ExamplePreference = ExamplePreference.WHEN_HELPFUL
    exercise_policy: ExercisePolicy = ExercisePolicy.OFFER
    exam_orientation: bool = False
    citation_preference: CitationPreference = CitationPreference.STANDARD
    math_detail_level: MathDetailLevel = MathDetailLevel.STANDARD
    terminology_style: TerminologyStyle = TerminologyStyle.BILINGUAL
    custom_requirements: str = Field(default="", max_length=1_000)

    @field_validator("learning_goal")
    @classmethod
    def normalize_goal(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("learning goal cannot be blank")
        return normalized

    @field_validator("teaching_styles")
    @classmethod
    def unique_styles(cls, value: list[TeachingStyle]) -> list[TeachingStyle]:
        if len(set(value)) != len(value):
            raise ValueError("teaching styles must be unique")
        return value


class TeachingProfileBuilderRequest(ApiModel):
    requirement: str = Field(min_length=3, max_length=1_000)


class TeachingProfilePreview(TeachingProfileInput):
    generated_prompt: str


class TeachingProfile(TeachingProfilePreview):
    id: str
    course_id: str
    version: int
    created_at: datetime
    updated_at: datetime


class TeachingProfilePage(ApiModel):
    items: list[TeachingProfile]


class PublicationSubmit(ApiModel):
    share_materials_consent: bool
    rights_confirmation: bool
    consent_version: str = Field(pattern=r"^v[1-9][0-9]*$")


class PublicationReview(ApiModel):
    decision: str = Field(pattern=r"^(approve|reject)$")
    review_note: str = Field(default="", max_length=1_000)


class PublicationRequest(ApiModel):
    id: str
    course_id: str
    course_name: str
    owner_user_id: str = Field(exclude=True)
    status: str
    share_materials_consent: bool
    rights_confirmation: bool
    consent_version: str
    consented_at: datetime
    submitted_at: datetime
    reviewed_at: datetime | None
    reviewed_by_user_id: str | None = Field(exclude=True)
    review_note: str


class PublicationRequestPage(ApiModel):
    items: list[PublicationRequest]


class ConversationMessage(ApiModel):
    id: str
    role: str
    content: str
    citations: list[dict[str, object]]
    metadata: dict[str, object]
    created_at: datetime


class ConversationDetail(ApiModel):
    id: str
    course_id: str
    title: str
    preferred_language: LanguagePreference
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessage]


class ErrorDetail(ApiModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorEnvelope(ApiModel):
    error: ErrorDetail
