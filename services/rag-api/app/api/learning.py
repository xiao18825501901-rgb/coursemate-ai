import sqlite3
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth import AuthenticatedUser, require_user
from app.db import Database
from app.errors import ApiError
from app.learning.models import (
    AssessmentAbandonInput,
    AssessmentAssistInput,
    AssessmentStartInput,
    AssessmentSubmitInput,
    BridgeInput,
    GradePolicyDraftInput,
    GradePolicyPreviewInput,
    NodeDraft,
    PersonalPlanInput,
    PreferenceInput,
    ReturnInput,
    SolveInput,
    TeachingSpecDraft,
    TeachInput,
)
from app.learning.orchestrator import LearningOrchestrator
from app.learning.previews import (
    IMAGE_MEDIA_TYPES,
    capability,
    csv_preview,
    notebook_preview,
    safe_text_preview,
)
from app.learning.workspaces import (
    artifact_for,
    artifact_path,
    current_document_version,
    document_version_for,
    join_course,
    original_path,
    sized_file_path,
    valid_preview_artifact,
    workspace_for,
)
from app.models import UploadAccepted

router = APIRouter(prefix="/api/learning", dependencies=[Depends(require_user)])
User = Annotated[AuthenticatedUser, Depends(require_user)]
PRIVATE_FILE_HEADERS = {
    "Cache-Control": "private, no-store",
    "Vary": "Authorization",
    "X-Content-Type-Options": "nosniff",
}


def _preview_descriptor(
    extension: str,
    source_available: bool,
    artifact_id: str | None,
    artifact_recorded: bool,
) -> dict[str, object]:
    if artifact_id is not None:
        return capability(extension, artifact_id)
    if not source_available:
        return {
            "kind": "DOWNLOAD_ONLY",
            "available": False,
            "reason": (
                "SOURCE_AND_DERIVED_ARTIFACT_UNAVAILABLE"
                if artifact_recorded
                else "ORIGINAL_UNAVAILABLE"
            ),
        }
    descriptor = capability(extension)
    if artifact_recorded and extension in {
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
    }:
        descriptor["reason"] = "DERIVED_ARTIFACT_UNAVAILABLE"
    return descriptor


def _recorded_preview_artifact(database: Database, version_id: str) -> bool:
    with database.connect() as connection:
        return (
            connection.execute(
                "SELECT 1 FROM derived_artifacts "
                "WHERE document_version_id=? AND kind='PREVIEW_PDF' "
                "AND status='READY' LIMIT 1",
                (version_id,),
            ).fetchone()
            is not None
        )


def _source_file_response(
    version: sqlite3.Row, path: Path, download: bool
) -> FileResponse:
    media = {
        ".pdf": "application/pdf",
        ".txt": "text/plain; charset=utf-8",
        ".md": "text/plain; charset=utf-8",
        ".markdown": "text/plain; charset=utf-8",
        **IMAGE_MEDIA_TYPES,
    }
    extension = version["extension"]
    supported = extension in media
    return FileResponse(
        path,
        media_type=media.get(extension, "application/octet-stream"),
        filename=version["filename"],
        content_disposition_type="attachment" if download or not supported else "inline",
        headers=PRIVATE_FILE_HEADERS,
    )


def _version_preview(version: sqlite3.Row, request: Request, user: User) -> object:
    database = request.app.state.database
    path = original_path(database, version)
    extension = version["extension"]
    artifact = valid_preview_artifact(database, version["id"])
    if artifact is not None and extension in {
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
    }:
        return artifact_content(artifact["id"], request, user)
    if path is None:
        raise ApiError(410, "ORIGINAL_UNAVAILABLE", "The original file is unavailable.")
    if extension in (".pdf", *IMAGE_MEDIA_TYPES):
        return _source_file_response(version, path, False)
    if extension in (".txt", ".md", ".markdown"):
        return safe_text_preview(path, request.app.state.settings)
    if extension == ".csv":
        return csv_preview(path, request.app.state.settings)
    if extension == ".ipynb":
        return notebook_preview(path, request.app.state.settings)
    raise ApiError(
        409,
        "PREVIEW_NOT_AVAILABLE",
        "A safe preview is not available; download the original file.",
        details={"reason": capability(extension)["reason"]},
    )


def _version_details(database: Database, version: sqlite3.Row) -> dict[str, object]:
    source_available = original_path(database, version) is not None
    artifact = valid_preview_artifact(database, version["id"])
    preview = _preview_descriptor(
        version["extension"],
        source_available,
        artifact["id"] if artifact is not None else None,
        _recorded_preview_artifact(database, version["id"]),
    )
    return {
        "id": version["id"],
        "document_id": version["document_id"],
        "version_number": version["version"],
        "course_id": version["course_id"],
        "source_scope": version["source_scope"],
        "access_scope": _version_access_scope(database, version),
        "filename": version["filename"],
        "extension": version["extension"],
        "media_type": version["media_type"],
        "sha256": version["sha256"],
        "byte_size": version["byte_size"],
        "created_at": version["created_at"],
        # Ownership is enforced server-side and is intentionally not disclosed.
        "owner_user_id": None,
        "original_status": "AVAILABLE" if source_available else "ORIGINAL_UNAVAILABLE",
        "preview_supported": preview["available"],
        "preview": preview,
    }


def _version_access_scope(database: Database, version: sqlite3.Row) -> str:
    with database.connect() as connection:
        course = connection.execute(
            "SELECT visibility,publication_status FROM courses WHERE id=?",
            (version["course_id"],),
        ).fetchone()
    return _access_scope_label(
        version["source_scope"],
        course["visibility"] if course is not None else None,
        course["publication_status"] if course is not None else None,
    )


def _access_scope_label(
    source_scope: str,
    course_visibility: str | None,
    publication_status: str | None,
) -> str:
    if source_scope == "OFFICIAL":
        return "COURSE_SHARED"
    if (
        source_scope == "OWNER_COURSE"
        and course_visibility == "public"
        and publication_status == "published"
    ):
        return "REVIEWED_SHARED"
    return "OWNER_PRIVATE"


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: str = Field(min_length=1, max_length=100)


@router.post("/workspaces")
def join(payload: WorkspaceCreate, request: Request, user: User) -> dict[str, object]:
    return join_course(
        request.app.state.database,
        payload.course_id,
        user.user_id,
        request.app.state.settings.user_course_max_courses,
    )


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str, request: Request, user: User) -> dict[str, object]:
    return dict(workspace_for(request.app.state.database, workspace_id, user.user_id))


@router.get("/workspaces/{workspace_id}/documents")
def documents(
    workspace_id: str,
    request: Request,
    user: User,
    scope: Literal["official", "mine", "union"] = "union",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> dict[str, object]:
    database = request.app.state.database
    workspace = workspace_for(database, workspace_id, user.user_id)
    official = (
        "(document_versions.course_id=? AND "
        "(document_versions.source_scope='OFFICIAL' OR "
        "(document_versions.source_scope='OWNER_COURSE' "
        "AND (document_versions.owner_user_id=? OR EXISTS("
        "SELECT 1 FROM courses AS source_course "
        "WHERE source_course.id=document_versions.course_id "
        "AND source_course.visibility='public' "
        "AND source_course.publication_status='published')))))"
    )
    private = (
        "(document_versions.course_id=? AND "
        "document_versions.source_scope='WORKSPACE_PRIVATE' "
        "AND document_versions.owner_user_id=?)"
    )
    access_parameters: tuple[object, ...]
    if scope == "official":
        access_clause = official
        access_parameters = (workspace["course_id"], user.user_id)
    elif scope == "mine":
        access_clause = private
        access_parameters = (workspace["private_course_id"], user.user_id)
    else:
        access_clause = f"({official} OR {private})"
        access_parameters = (
            workspace["course_id"],
            user.user_id,
            workspace["private_course_id"],
            user.user_id,
        )
    with database.connect() as db:
        rows = db.execute(
            "SELECT documents.id, documents.status, documents.chunk_count, "
            "document_versions.filename, document_versions.extension, "
            "document_versions.byte_size, document_versions.sha256, "
            "document_versions.course_id, document_versions.stored_path, "
            "document_versions.id AS version_id, "
            "document_versions.version AS version_number, "
            "document_versions.source_scope, "
            "source_course.visibility AS source_visibility, "
            "source_course.publication_status AS source_publication_status, "
            "preview_artifact.id AS preview_artifact_id, "
            "preview_artifact.stored_path AS preview_artifact_stored_path, "
            "preview_artifact.byte_size AS preview_artifact_byte_size "
            "FROM documents JOIN document_versions "
            "ON document_versions.document_id=documents.id "
            "AND document_versions.version=("
            "  SELECT MAX(latest.version) FROM document_versions AS latest "
            "  WHERE latest.document_id=documents.id"
            ") "
            "JOIN courses AS source_course ON source_course.id=document_versions.course_id "
            "LEFT JOIN derived_artifacts AS preview_artifact ON preview_artifact.id=("
            " SELECT id FROM derived_artifacts AS candidate_artifact "
            " WHERE candidate_artifact.document_version_id=document_versions.id "
            " AND candidate_artifact.kind='PREVIEW_PDF' "
            " AND candidate_artifact.status='READY' "
            " ORDER BY candidate_artifact.created_at DESC LIMIT 1) "
            f"WHERE {access_clause} "
            "ORDER BY documents.created_at,documents.id LIMIT ? OFFSET ?",
            (*access_parameters, page_size, (page - 1) * page_size),
        ).fetchall()
    data = []
    for row in rows:
        item = {
            key: row[key]
            for key in (
                "id",
                "filename",
                "extension",
                "byte_size",
                "sha256",
                "status",
                "course_id",
                "version_id",
                "version_number",
                "source_scope",
            )
        }
        artifact_id = (
            row["preview_artifact_id"]
            if sized_file_path(
                database,
                row["preview_artifact_stored_path"],
                row["preview_artifact_byte_size"],
            )
            is not None
            else None
        )
        descriptor = _preview_descriptor(
            row["extension"],
            sized_file_path(database, row["stored_path"], row["byte_size"])
            is not None,
            artifact_id,
            row["preview_artifact_id"] is not None,
        )
        item["preview"] = descriptor
        item["access_scope"] = _access_scope_label(
            row["source_scope"],
            row["source_visibility"],
            row["source_publication_status"],
        )
        data.append(item)
    return {"data": data, "page": page, "page_size": page_size}


@router.post("/workspaces/{workspace_id}/documents", status_code=202, response_model=UploadAccepted)
async def upload(
    workspace_id: str,
    request: Request,
    user: User,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
) -> UploadAccepted:
    state = request.app.state
    workspace = workspace_for(state.database, workspace_id, user.user_id)
    content = await file.read(state.settings.max_upload_bytes + 1)
    accepted = state.ingestion_service.queue_document(
        course_id=workspace["private_course_id"],
        filename=file.filename or "",
        media_type=file.content_type or "application/octet-stream",
        content=content,
        owner_user_id=user.user_id,
        is_admin=False,
    )
    background_tasks.add_task(
        state.ingestion_service.process_document, accepted.document.id, accepted.job.id
    )
    return cast(UploadAccepted, accepted)


@router.get("/document-versions/{version_id}")
def version_metadata(version_id: str, request: Request, user: User) -> dict[str, object]:
    database = request.app.state.database
    version = document_version_for(database, version_id, user.user_id)
    return _version_details(database, version)


@router.get("/document-versions/{version_id}/preview")
def version_preview(version_id: str, request: Request, user: User) -> object:
    version = document_version_for(
        request.app.state.database, version_id, user.user_id
    )
    return _version_preview(version, request, user)


@router.api_route(
    "/document-versions/{version_id}/content", methods=["GET", "HEAD"]
)
def version_content(
    version_id: str,
    request: Request,
    user: User,
    download: bool = False,
) -> FileResponse:
    database = request.app.state.database
    version = document_version_for(database, version_id, user.user_id)
    path = original_path(database, version)
    if path is None:
        raise ApiError(410, "ORIGINAL_UNAVAILABLE", "The original file is unavailable.")
    return _source_file_response(version, path, download)


@router.get("/documents/{document_id}")
def metadata(document_id: str, request: Request, user: User) -> dict[str, object]:
    database = request.app.state.database
    version = current_document_version(database, document_id, user.user_id)
    details = _version_details(database, version)
    return {
        "id": version["document_id"],
        "filename": version["filename"],
        "version": version["sha256"],
        "version_id": version["id"],
        "version_number": version["version"],
        "source_scope": version["source_scope"],
        "access_scope": details["access_scope"],
        "owner_user_id": details["owner_user_id"],
        "original_status": details["original_status"],
        "preview_supported": details["preview_supported"],
        "preview": details["preview"],
    }


@router.get("/documents/{document_id}/preview")
def preview(document_id: str, request: Request, user: User) -> object:
    version = current_document_version(
        request.app.state.database, document_id, user.user_id
    )
    return _version_preview(version, request, user)


@router.api_route("/documents/{document_id}/content", methods=["GET", "HEAD"])
def content(document_id: str, request: Request, user: User, download: bool = False) -> FileResponse:
    database = request.app.state.database
    version = current_document_version(database, document_id, user.user_id)
    path = original_path(database, version)
    if path is None:
        raise ApiError(410, "ORIGINAL_UNAVAILABLE", "The original file is unavailable.")
    return _source_file_response(version, path, download)


@router.api_route("/artifacts/{artifact_id}/content", methods=["GET", "HEAD"])
def artifact_content(
    artifact_id: str, request: Request, user: User
) -> FileResponse:
    database = request.app.state.database
    artifact = artifact_for(database, artifact_id, user.user_id)
    path = artifact_path(database, artifact)
    if path is None:
        raise ApiError(
            410,
            "ARTIFACT_UNAVAILABLE",
            "The derived preview artifact is unavailable.",
        )
    inline = artifact["media_type"] in {
        "application/pdf",
        *IMAGE_MEDIA_TYPES.values(),
        "text/plain",
    }
    return FileResponse(
        path,
        media_type=artifact["media_type"],
        filename=path.name,
        content_disposition_type="inline" if inline else "attachment",
        headers=PRIVATE_FILE_HEADERS,
    )


@router.get("/workspaces/{workspace_id}/state")
def learning_state(workspace_id: str, request: Request, user: User) -> dict[str, Any]:
    return cast(LearningOrchestrator, request.app.state.learning).state(workspace_id, user.user_id)


@router.get("/workspaces/{workspace_id}/knowledge")
def knowledge_state(workspace_id: str, request: Request, user: User) -> dict[str, Any]:
    return cast(LearningOrchestrator, request.app.state.learning).knowledge_state(
        workspace_id, user.user_id
    )


@router.post("/workspaces/{workspace_id}/assessments")
def start_assessment(
    workspace_id: str,
    payload: AssessmentStartInput,
    request: Request,
    user: User,
) -> dict[str, Any]:
    return cast(LearningOrchestrator, request.app.state.learning).start_assessment(
        workspace_id,
        user.user_id,
        payload,
    )


@router.get("/workspaces/{workspace_id}/assessments/{session_id}")
def assessment(
    workspace_id: str,
    session_id: str,
    request: Request,
    user: User,
) -> dict[str, Any]:
    return cast(LearningOrchestrator, request.app.state.learning).assessment(
        workspace_id,
        user.user_id,
        session_id,
    )


@router.post("/workspaces/{workspace_id}/assessments/{session_id}/submit")
def submit_assessment(
    workspace_id: str,
    session_id: str,
    payload: AssessmentSubmitInput,
    request: Request,
    user: User,
) -> dict[str, Any]:
    return cast(LearningOrchestrator, request.app.state.learning).submit_assessment(
        workspace_id,
        user.user_id,
        session_id,
        payload,
    )


@router.post("/workspaces/{workspace_id}/assessments/{session_id}/assist")
def assist_assessment(
    workspace_id: str,
    session_id: str,
    payload: AssessmentAssistInput,
    request: Request,
    user: User,
) -> dict[str, Any]:
    return cast(LearningOrchestrator, request.app.state.learning).assist_assessment(
        workspace_id,
        user.user_id,
        session_id,
        payload,
    )


@router.post("/workspaces/{workspace_id}/assessments/{session_id}/abandon")
def abandon_assessment(
    workspace_id: str,
    session_id: str,
    payload: AssessmentAbandonInput,
    request: Request,
    user: User,
) -> dict[str, Any]:
    return cast(LearningOrchestrator, request.app.state.learning).abandon_assessment(
        workspace_id,
        user.user_id,
        session_id,
        payload,
    )


@router.get("/grade-policies")
def grade_policies(request: Request, user: User) -> dict[str, Any]:
    if not user.is_admin:
        raise ApiError(403, "ADMIN_REQUIRED", "Administrator access is required.")
    service = cast(LearningOrchestrator, request.app.state.learning).assessments
    return {"items": service.grade_policies()}


@router.post("/grade-policies")
def create_grade_policy(
    payload: GradePolicyDraftInput,
    request: Request,
    user: User,
) -> dict[str, Any]:
    if not user.is_admin:
        raise ApiError(403, "ADMIN_REQUIRED", "Administrator access is required.")
    return cast(LearningOrchestrator, request.app.state.learning).create_grade_policy(
        user.user_id,
        payload,
    )


@router.post("/grade-policies/{policy_id}/preview")
def preview_grade_policy(
    policy_id: str,
    payload: GradePolicyPreviewInput,
    request: Request,
    user: User,
) -> dict[str, Any]:
    if not user.is_admin:
        raise ApiError(403, "ADMIN_REQUIRED", "Administrator access is required.")
    service = cast(LearningOrchestrator, request.app.state.learning).assessments
    return service.preview_grade_policy(policy_id, payload.raw_score)


@router.post("/grade-policies/{policy_id}/publish")
def publish_grade_policy(
    policy_id: str,
    request: Request,
    user: User,
) -> dict[str, Any]:
    if not user.is_admin:
        raise ApiError(403, "ADMIN_REQUIRED", "Administrator access is required.")
    return cast(LearningOrchestrator, request.app.state.learning).publish_grade_policy(
        user.user_id,
        policy_id,
    )


@router.get("/workspaces/{workspace_id}/problem-index")
def problem_index(
    workspace_id: str,
    request: Request,
    user: User,
    scope: Literal["official", "mine", "union"] = "union",
    query: str | None = Query(default=None, max_length=500),
    document_version_id: str | None = Query(default=None, max_length=100),
    filename: str | None = Query(default=None, max_length=500),
    question_number: str | None = Query(default=None, max_length=40),
    question_part: str | None = Query(default=None, max_length=40),
    locator_type: str | None = Query(default=None, max_length=40),
    locator_value: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    return cast(LearningOrchestrator, request.app.state.learning).problem_index(
        workspace_id,
        user.user_id,
        scope=scope,
        query=query,
        document_version_id=document_version_id,
        filename=filename,
        question_number=question_number,
        question_part=question_part,
        locator_type=locator_type,
        locator_value=locator_value,
        limit=limit,
    )


@router.post("/workspaces/{workspace_id}/nodes")
def create_node(
    workspace_id: str, payload: NodeDraft, request: Request, user: User
) -> dict[str, Any]:
    return cast(LearningOrchestrator, request.app.state.learning).create_node(
        workspace_id, user.user_id, payload
    )


@router.post("/workspaces/{workspace_id}/plans")
def personal_plan(
    workspace_id: str,
    payload: PersonalPlanInput,
    request: Request,
    user: User,
) -> dict[str, Any]:
    return cast(LearningOrchestrator, request.app.state.learning).personal_plan(
        workspace_id, user.user_id, payload
    )


@router.post("/workspaces/{workspace_id}/nodes/{node_id}/specs")
def create_spec(
    workspace_id: str,
    node_id: str,
    payload: TeachingSpecDraft,
    request: Request,
    user: User,
) -> dict[str, Any]:
    return cast(LearningOrchestrator, request.app.state.learning).create_spec(
        workspace_id, user.user_id, node_id, payload
    )


@router.post("/workspaces/{workspace_id}/solutions")
def solve(workspace_id: str, payload: SolveInput, request: Request, user: User) -> dict[str, Any]:
    return cast(LearningOrchestrator, request.app.state.learning).solve(
        workspace_id, user.user_id, payload
    )


@router.post("/workspaces/{workspace_id}/bridges")
def bridge(workspace_id: str, payload: BridgeInput, request: Request, user: User) -> dict[str, Any]:
    return cast(LearningOrchestrator, request.app.state.learning).bridge(
        workspace_id, user.user_id, payload
    )


@router.post("/workspaces/{workspace_id}/units")
def teach(workspace_id: str, payload: TeachInput, request: Request, user: User) -> dict[str, Any]:
    return cast(LearningOrchestrator, request.app.state.learning).teach(
        workspace_id, user.user_id, payload
    )


@router.post("/workspaces/{workspace_id}/bridges/{bridge_id}/return")
def return_bridge(
    workspace_id: str, bridge_id: str, payload: ReturnInput, request: Request, user: User
) -> dict[str, Any]:
    return cast(LearningOrchestrator, request.app.state.learning).return_bridge(
        workspace_id, user.user_id, bridge_id, payload
    )


@router.patch("/workspaces/{workspace_id}/preferences")
def preferences(
    workspace_id: str, payload: PreferenceInput, request: Request, user: User
) -> dict[str, Any]:
    return cast(LearningOrchestrator, request.app.state.learning).preferences(
        workspace_id, user.user_id, payload
    )


@router.get("/workspaces/{workspace_id}/events")
def events(
    workspace_id: str, request: Request, user: User, after: int = Query(0, ge=0)
) -> dict[str, Any]:
    database = request.app.state.database
    workspace_for(database, workspace_id, user.user_id)
    with database.connect() as db:
        rows = db.execute(
            "SELECT sequence,operation_id,kind,payload_json FROM learning_events "
            "WHERE workspace_id=? AND sequence>? ORDER BY sequence LIMIT 100",
            (workspace_id, after),
        ).fetchall()
    return {"events": [dict(r) for r in rows]}
