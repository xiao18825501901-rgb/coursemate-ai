import hashlib
import json
import sqlite3
from typing import Any, TypedDict
from uuid import uuid4

from app.errors import ApiError
from app.models import PublicationSnapshot


class SnapshotResourceData(TypedDict):
    kind: str
    id: str
    version: str
    display_name: str
    source_scope: str
    content_hash: str
    metadata: dict[str, Any]


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def resource(
    *,
    kind: str,
    resource_id: str,
    version: str,
    display_name: str,
    source_scope: str,
    metadata: dict[str, Any],
    digest_value: object | None = None,
) -> SnapshotResourceData:
    return {
        "kind": kind,
        "id": resource_id,
        "version": version,
        "display_name": display_name,
        "source_scope": source_scope,
        "content_hash": content_hash(metadata if digest_value is None else digest_value),
        "metadata": metadata,
    }


def snapshot_hash(summary: dict[str, Any], resources: list[SnapshotResourceData]) -> str:
    ordered = sorted(
        resources,
        key=lambda item: (item["kind"], item["id"], item["version"]),
    )
    return content_hash({"summary": summary, "resources": ordered})


def create_snapshot(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    request_id: str,
    course_id: str,
    workspace_id: str | None,
    owner_user_id: str | None,
    summary: dict[str, Any],
    resources: list[SnapshotResourceData],
) -> tuple[str, str]:
    snapshot_id = "snapshot_" + uuid4().hex
    digest = snapshot_hash(summary, resources)
    connection.execute(
        "INSERT INTO publication_review_snapshots("
        "id,subject_kind,request_id,course_id,workspace_id,owner_user_id,"
        "summary_json,content_hash) VALUES(?,?,?,?,?,?,?,?)",
        (
            snapshot_id,
            subject_kind,
            request_id,
            course_id,
            workspace_id,
            owner_user_id,
            canonical_json(summary),
            digest,
        ),
    )
    connection.executemany(
        "INSERT INTO publication_snapshot_resources("
        "snapshot_id,resource_kind,resource_id,version_label,display_name,"
        "source_scope,content_hash,metadata_json) VALUES(?,?,?,?,?,?,?,?)",
        [
            (
                snapshot_id,
                item["kind"],
                item["id"],
                item["version"],
                item["display_name"],
                item["source_scope"],
                item["content_hash"],
                canonical_json(item["metadata"]),
            )
            for item in resources
        ],
    )
    return snapshot_id, digest


def snapshot_view(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    request_id: str,
) -> PublicationSnapshot:
    row = connection.execute(
        "SELECT * FROM publication_review_snapshots "
        "WHERE subject_kind=? AND request_id=?",
        (subject_kind, request_id),
    ).fetchone()
    if row is None:
        raise ApiError(404, "PUBLICATION_SNAPSHOT_NOT_FOUND", "The review snapshot was not found.")
    resource_rows = connection.execute(
        "SELECT resource_kind,resource_id,version_label,display_name,source_scope,"
        "content_hash,metadata_json FROM publication_snapshot_resources "
        "WHERE snapshot_id=? ORDER BY resource_kind,resource_id,version_label",
        (row["id"],),
    ).fetchall()
    return PublicationSnapshot.model_validate(
        {
            "id": row["id"],
            "subject_kind": row["subject_kind"],
            "request_id": row["request_id"],
            "course_id": row["course_id"],
            "workspace_id": row["workspace_id"],
            "content_hash": row["content_hash"],
            "created_at": row["created_at"],
            "summary": json.loads(row["summary_json"]),
            "resources": [
                {
                    "kind": item["resource_kind"],
                    "id": item["resource_id"],
                    "version": item["version_label"],
                    "display_name": item["display_name"],
                    "source_scope": item["source_scope"],
                    "content_hash": item["content_hash"],
                    "metadata": json.loads(item["metadata_json"]),
                }
                for item in resource_rows
            ],
        }
    )


def course_snapshot_payload(
    connection: sqlite3.Connection,
    course_id: str,
) -> tuple[dict[str, Any], list[SnapshotResourceData]]:
    course = connection.execute(
        "SELECT id,name,description,course_type,visibility,preferred_language "
        "FROM courses WHERE id=?",
        (course_id,),
    ).fetchone()
    if course is None:
        raise ApiError(404, "COURSE_NOT_FOUND", "The course was not found.")
    summary: dict[str, Any] = {
        "courseId": course["id"],
        "name": course["name"],
        "description": course["description"],
        "courseType": course["course_type"],
        "preferredLanguage": course["preferred_language"],
    }
    resources = [
        resource(
            kind="COURSE_METADATA",
            resource_id=course_id,
            version="snapshot",
            display_name=course["name"],
            source_scope="OWNER_COURSE",
            metadata=summary.copy(),
        )
    ]
    document_rows = connection.execute(
        "SELECT documents.id AS document_id,documents.status,documents.chunk_count,"
        "version.id AS version_id,version.version,version.filename,version.media_type,"
        "version.extension,version.sha256,version.byte_size,version.source_scope "
        "FROM documents JOIN document_versions AS version "
        "ON version.document_id=documents.id "
        "AND version.version=(SELECT MAX(current.version) FROM document_versions AS current "
        "WHERE current.document_id=documents.id) "
        "WHERE documents.course_id=? ORDER BY documents.id",
        (course_id,),
    ).fetchall()
    unavailable = [row["document_id"] for row in document_rows if row["status"] != "ready"]
    if unavailable:
        raise ApiError(
            409,
            "PUBLICATION_SOURCE_NOT_READY",
            "Every submitted document must finish indexing before review.",
            details={"documentIds": unavailable},
        )
    version_ids: list[str] = []
    for row in document_rows:
        version_ids.append(str(row["version_id"]))
        metadata = {
            "documentId": row["document_id"],
            "versionNumber": row["version"],
            "filename": row["filename"],
            "mediaType": row["media_type"],
            "extension": row["extension"],
            "sha256": row["sha256"],
            "byteSize": row["byte_size"],
            "chunkCount": row["chunk_count"],
        }
        resources.append(
            resource(
                kind="DOCUMENT_VERSION",
                resource_id=row["version_id"],
                version=str(row["version"]),
                display_name=row["filename"],
                source_scope=row["source_scope"],
                metadata=metadata,
            )
        )
    if version_ids:
        placeholders = ",".join("?" for _ in version_ids)
        chunk_rows = connection.execute(
            "SELECT chunks.id,chunks.document_id,chunks.ordinal,chunks.content,"
            "chunks.locator_type,chunks.locator_value,chunks.section,chunks.metadata_json,"
            "chunk_source_versions.document_version_id "
            "FROM chunks JOIN chunk_source_versions "
            "ON chunk_source_versions.chunk_id=chunks.id "
            f"WHERE chunk_source_versions.document_version_id IN ({placeholders}) "
            "ORDER BY chunks.document_id,chunks.ordinal,chunks.id",
            version_ids,
        ).fetchall()
        for row in chunk_rows:
            metadata = {
                "documentId": row["document_id"],
                "documentVersionId": row["document_version_id"],
                "ordinal": row["ordinal"],
                "locatorType": row["locator_type"],
                "locatorValue": row["locator_value"],
                "section": row["section"],
            }
            resources.append(
                resource(
                    kind="CHUNK",
                    resource_id=row["id"],
                    version="1",
                    display_name=f"Chunk {row['ordinal'] + 1}",
                    source_scope="OWNER_COURSE",
                    metadata=metadata,
                    digest_value={
                        **metadata,
                        "content": row["content"],
                        "sourceMetadata": json.loads(row["metadata_json"]),
                    },
                )
            )
        artifact_rows = connection.execute(
            "SELECT id,document_version_id,kind,status,media_type,sha256,byte_size,"
            "producer_version,metadata_json FROM derived_artifacts "
            f"WHERE document_version_id IN ({placeholders}) AND status='READY' "
            "ORDER BY document_version_id,kind,id",
            version_ids,
        ).fetchall()
        for row in artifact_rows:
            metadata = {
                "documentVersionId": row["document_version_id"],
                "kind": row["kind"],
                "mediaType": row["media_type"],
                "sha256": row["sha256"],
                "byteSize": row["byte_size"],
                "producerVersion": row["producer_version"],
                "producerMetadata": json.loads(row["metadata_json"]),
            }
            resources.append(
                resource(
                    kind="DERIVED_ARTIFACT",
                    resource_id=row["id"],
                    version=row["producer_version"],
                    display_name=f"{row['kind']} for {row['document_version_id']}",
                    source_scope="OWNER_COURSE",
                    metadata=metadata,
                )
            )
    profile = connection.execute(
        "SELECT * FROM course_teaching_profiles WHERE course_id=? "
        "ORDER BY version DESC LIMIT 1",
        (course_id,),
    ).fetchone()
    if profile is not None:
        profile_metadata = {
            "profileId": profile["id"],
            "versionNumber": profile["version"],
            "language": profile["language"],
            "studentLevel": profile["student_level"],
            "learningGoal": profile["learning_goal"],
            "teachingStyles": json.loads(profile["teaching_styles_json"]),
            "answerDepth": profile["answer_depth"],
            "examplePreference": profile["example_preference"],
            "exercisePolicy": profile["exercise_policy"],
            "examOrientation": bool(profile["exam_orientation"]),
            "citationPreference": profile["citation_preference"],
            "mathDetailLevel": profile["math_detail_level"],
            "terminologyStyle": profile["terminology_style"],
            "customRequirements": profile["custom_requirements"],
            "generatedPrompt": profile["generated_prompt"],
        }
        resources.append(
            resource(
                kind="TEACHING_PROFILE",
                resource_id=profile["id"],
                version=str(profile["version"]),
                display_name=f"Teaching profile v{profile['version']}",
                source_scope="OWNER_COURSE",
                metadata=profile_metadata,
            )
        )
    return summary, resources


def record_audit_event(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    request_id: str,
    actor_user_id: str,
    action: str,
    details: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        "INSERT INTO publication_audit_events("
        "id,subject_kind,request_id,actor_user_id,action,details_json) "
        "VALUES(?,?,?,?,?,?)",
        (
            "audit_" + uuid4().hex,
            subject_kind,
            request_id,
            actor_user_id,
            action,
            canonical_json(details or {}),
        ),
    )


def activate_release(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    request_id: str,
    snapshot_id: str,
) -> None:
    connection.execute(
        "INSERT INTO publication_releases("
        "id,subject_kind,request_id,snapshot_id,status) VALUES(?,?,?,?,'ACTIVE')",
        ("release_" + uuid4().hex, subject_kind, request_id, snapshot_id),
    )


def withdraw_release(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    request_id: str,
    actor_user_id: str,
) -> None:
    connection.execute(
        "UPDATE publication_releases SET status='WITHDRAWN',"
        "cache_generation=cache_generation+1,"
        "withdrawn_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),"
        "withdrawn_by_user_id=? "
        "WHERE subject_kind=? AND request_id=? AND status='ACTIVE'",
        (actor_user_id, subject_kind, request_id),
    )
