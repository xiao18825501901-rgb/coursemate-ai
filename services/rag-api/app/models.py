from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


PublicationResourceId = Annotated[
    str,
    Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$"),
]


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
    preferred_language: LanguagePreference
    display_type: str | None = None
    requires_student_verification: bool = False
    document_count: int = 0
    index_status: str = "empty"
    published_at: datetime | None
    is_owner: bool = False
    can_manage: bool = False
    created_at: datetime
    updated_at: datetime


class CourseUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1_000)
    preferred_language: LanguagePreference | None = None

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
    byte_size: int
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
    preferred_language: LanguagePreference | None = None


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
    snapshot_id: str | None = None
    snapshot_hash: str | None = None
    resource_count: int = 0


class PublicationRequestPage(ApiModel):
    items: list[PublicationRequest]


class PublicationSnapshotResource(ApiModel):
    kind: str
    id: str
    version: str
    display_name: str
    source_scope: str
    content_hash: str
    metadata: dict[str, Any]


class PublicationSnapshot(ApiModel):
    id: str
    subject_kind: str
    request_id: str
    course_id: str
    workspace_id: str | None
    content_hash: str
    created_at: datetime
    summary: dict[str, Any]
    resources: list[PublicationSnapshotResource]


class OfficialKnowledgePublicationSubmit(ApiModel):
    tree_version_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")


class OfficialKnowledgeDraft(ApiModel):
    tree_version_id: str
    course_id: str
    course_name: str
    tree_version: int
    title: str
    member_count: int
    pending_request_id: str | None


class OfficialKnowledgeDraftPage(ApiModel):
    items: list[OfficialKnowledgeDraft]


class OfficialKnowledgeDraftGenerate(ApiModel):
    """Admin request to build an OFFICIAL DRAFT knowledge tree from real corpus.

    Hard ceilings come from the builder's fixed constants; this model's bounds
    mirror them so validation fails loudly before any provider call.
    """

    operation_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    max_nodes: int = Field(default=1, ge=1, le=10)
    max_model_calls: int = Field(default=2, ge=1, le=20)
    max_reserved_output_tokens: int = Field(default=8_000, ge=1, le=20_000)
    dry_run: bool = False


class OfficialKnowledgeDraftCorpus(ApiModel):
    document_count: int
    chunk_count: int
    version_count: int


class OfficialKnowledgeDraftBudget(ApiModel):
    max_nodes: int
    max_model_calls: int
    max_reserved_output_tokens: int
    planned_model_calls: int
    planned_reserved_output_tokens: int
    model_calls_made: int
    reserved_output_tokens_booked: int


class OfficialKnowledgeDraftGeneration(ApiModel):
    course_id: str
    operation_id: str
    dry_run: bool
    existing_draft: bool
    tree_version_id: str | None = None
    tree_version: int | None = None
    node_ids: list[str] = Field(default_factory=list)
    corpus_fingerprint: str
    corpus: OfficialKnowledgeDraftCorpus
    budget: OfficialKnowledgeDraftBudget
    evidence_chunk_count: int = 0
    evidence_rows: list[str] = Field(default_factory=list)


class OfficialKnowledgeCourseNodeTarget(ApiModel):
    """One atomic generation target: topic scope comes from the course source
    map (never invented by the model); evidence queries select real corpus
    chunks the model must ground on."""

    node_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    title: str = Field(min_length=1, max_length=150)
    description: str = Field(min_length=1, max_length=6000)
    major: Literal["CS", "SMART_MANUFACTURING", "MATERIALS", "ENERGY"]
    parent_key: str | None = None
    prerequisites: list[str] = Field(default_factory=list, max_length=20)
    evidence_queries: list[str] = Field(min_length=1, max_length=4)


class OfficialKnowledgeCourseModuleTarget(ApiModel):
    """One composite module derived from the course source map."""

    module_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    title: str = Field(min_length=1, max_length=150)
    description: str = Field(min_length=1, max_length=6000)
    major: Literal["CS", "SMART_MANUFACTURING", "MATERIALS", "ENERGY"]
    parent_key: str | None = None
    prerequisites: list[str] = Field(default_factory=list, max_length=20)


class OfficialKnowledgeCoursePlan(ApiModel):
    modules: list[OfficialKnowledgeCourseModuleTarget] = Field(default_factory=list, max_length=40)
    nodes: list[OfficialKnowledgeCourseNodeTarget] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def valid_plan(self) -> "OfficialKnowledgeCoursePlan":
        module_keys = {m.module_key for m in self.modules}
        node_keys = {n.node_key for n in self.nodes}
        if module_keys & node_keys:
            raise ValueError("Module and node keys must be disjoint")
        if len(module_keys) != len(self.modules) or len(node_keys) != len(self.nodes):
            raise ValueError("Plan keys must be unique")
        for node in self.nodes:
            if node.parent_key is not None and node.parent_key not in module_keys:
                raise ValueError("A node parent must be a plan module")
            for prereq in node.prerequisites:
                if prereq not in node_keys:
                    raise ValueError("A node prerequisite must reference a plan node")
        for module in self.modules:
            if module.parent_key is not None and module.parent_key not in module_keys:
                raise ValueError("A module parent must be a plan module")
            if module.parent_key == module.module_key:
                raise ValueError("A module cannot be its own parent")
        parents: dict[str, str] = {m.module_key: m.parent_key or "" for m in self.modules}
        for node in self.nodes:
            parents[node.node_key] = node.parent_key or ""
        for key in list(parents):
            seen: set[str] = set()
            cursor = parents[key]
            while cursor:
                if cursor in seen:
                    raise ValueError("Plan hierarchy contains a cycle")
                seen.add(cursor)
                cursor = parents.get(cursor, "")
        children: dict[str, int] = {}
        for key, parent in parents.items():
            children[parent] = children.get(parent, 0) + 1
        for module in self.modules:
            if children.get(module.module_key, 0) == 0:
                raise ValueError("Every module needs at least one child")
        return self


class OfficialKnowledgeCourseBuild(ApiModel):
    operation_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    plan: OfficialKnowledgeCoursePlan
    max_model_calls_per_batch: int = Field(default=2, ge=1, le=20)
    max_reserved_output_tokens_per_batch: int = Field(default=8000, ge=1, le=20000)
    dry_run: bool = False


class OfficialKnowledgeCourseProgress(ApiModel):
    course_id: str
    plan_hash: str
    corpus_fingerprint: str
    builder_version: str
    status: str
    node_total: int
    node_completed: int
    completed_node_ids: dict[str, str] = Field(default_factory=dict)
    final_tree_version_id: str | None = None


class OfficialKnowledgeCourseBuildResult(ApiModel):
    course_id: str
    operation_id: str
    dry_run: bool
    existing_finalized: bool
    progress: OfficialKnowledgeCourseProgress
    model_calls_made: int
    reserved_output_tokens_booked: int
    final_tree_version_id: str | None = None


class OfficialKnowledgePublicationRequest(ApiModel):
    id: str
    course_id: str
    course_name: str
    tree_version_id: str
    tree_version: int
    tree_title: str
    status: str
    submitted_by_user_id: str = Field(exclude=True)
    submitted_at: datetime
    reviewed_at: datetime | None
    reviewed_by_user_id: str | None = Field(exclude=True)
    review_note: str
    snapshot_id: str
    snapshot_hash: str
    resource_count: int


class OfficialKnowledgePublicationRequestPage(ApiModel):
    items: list[OfficialKnowledgePublicationRequest]


class OverlayPublicationSubmit(ApiModel):
    node_ids: list[PublicationResourceId] = Field(default_factory=list, max_length=500)
    document_version_ids: list[PublicationResourceId] = Field(
        default_factory=list, max_length=500
    )
    artifact_ids: list[PublicationResourceId] = Field(default_factory=list, max_length=500)
    evidence_ids: list[PublicationResourceId] = Field(default_factory=list, max_length=1_000)
    share_selected_content_consent: bool
    rights_confirmation: bool
    consent_version: str = Field(pattern=r"^v[1-9][0-9]*$")


class OverlayNodeCandidate(ApiModel):
    id: str
    title: str
    kind: str
    spec_version: int | None


class OverlayDocumentCandidate(ApiModel):
    id: str
    document_id: str
    version: int
    filename: str
    sha256: str
    byte_size: int
    status: str


class OverlayArtifactCandidate(ApiModel):
    id: str
    document_version_id: str
    kind: str
    producer_version: str
    sha256: str
    byte_size: int


class OverlayEvidenceCandidate(ApiModel):
    id: str
    node_id: str
    node_title: str
    node_is_private: bool
    document_version_id: str
    locator_type: str
    locator_value: str


class OverlayPublicationCandidates(ApiModel):
    nodes: list[OverlayNodeCandidate]
    documents: list[OverlayDocumentCandidate]
    artifacts: list[OverlayArtifactCandidate]
    evidence: list[OverlayEvidenceCandidate]


class OverlayPublicationRequest(ApiModel):
    id: str
    course_id: str
    course_name: str
    workspace_id: str
    owner_user_id: str = Field(exclude=True)
    status: str
    share_selected_content_consent: bool
    rights_confirmation: bool
    consent_version: str
    consented_at: datetime
    submitted_at: datetime
    reviewed_at: datetime | None
    reviewed_by_user_id: str | None = Field(exclude=True)
    review_note: str
    snapshot_id: str
    snapshot_hash: str
    resource_count: int


class OverlayPublicationRequestPage(ApiModel):
    items: list[OverlayPublicationRequest]


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
