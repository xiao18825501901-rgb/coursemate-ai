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
            producer_metadata = json.loads(row["metadata_json"])
            metadata = {
                "documentVersionId": row["document_version_id"],
                "kind": row["kind"],
                "mediaType": row["media_type"],
                "sha256": row["sha256"],
                "byteSize": row["byte_size"],
                "producerVersion": row["producer_version"],
            }
            resources.append(
                resource(
                    kind="DERIVED_ARTIFACT",
                    resource_id=row["id"],
                    version=row["producer_version"],
                    display_name=f"{row['kind']} for {row['document_version_id']}",
                    source_scope="OWNER_COURSE",
                    metadata=metadata,
                    digest_value={**metadata, "producerMetadata": producer_metadata},
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


def official_knowledge_snapshot_payload(
    connection: sqlite3.Connection,
    tree_version_id: str,
) -> tuple[dict[str, Any], list[SnapshotResourceData]]:
    tree = connection.execute(
        "SELECT tree.*,courses.name AS course_name,courses.course_type "
        "FROM knowledge_tree_versions AS tree "
        "JOIN courses ON courses.id=tree.course_id WHERE tree.id=?",
        (tree_version_id,),
    ).fetchone()
    if (
        tree is None
        or tree["tree_kind"] != "OFFICIAL"
        or tree["course_type"] != "official"
        or tree["status"] != "DRAFT"
    ):
        raise ApiError(
            404,
            "OFFICIAL_TREE_DRAFT_NOT_FOUND",
            "The official knowledge-tree draft was not found.",
        )
    member_rows = connection.execute(
        "SELECT member.node_id,member.parent_node_id,member.ordinal,"
        "member.teaching_spec_version,node.title,node.description,node.major,node.kind,"
        "node.status AS node_status,node.owner_user_id,spec.content_json,spec.content_hash,"
        "metadata.status AS spec_status,metadata.change_reason AS spec_change_reason "
        "FROM knowledge_tree_memberships AS member "
        "JOIN knowledge_nodes AS node ON node.id=member.node_id "
        "LEFT JOIN teaching_specs AS spec ON spec.node_id=member.node_id "
        "AND spec.version=member.teaching_spec_version "
        "LEFT JOIN teaching_spec_metadata AS metadata ON metadata.node_id=member.node_id "
        "AND metadata.version=member.teaching_spec_version "
        "WHERE member.tree_version_id=? ORDER BY member.ordinal,member.node_id",
        (tree_version_id,),
    ).fetchall()
    if not member_rows:
        raise ApiError(
            422,
            "OFFICIAL_TREE_EMPTY",
            "An official knowledge tree must contain at least one reviewed node.",
        )
    members: list[dict[str, Any]] = []
    resources: list[SnapshotResourceData] = []
    for row in member_rows:
        valid_node = row["owner_user_id"] is None and row["node_status"] in {
            "CANDIDATE",
            "PUBLISHED",
        }
        valid_spec = (
            row["kind"] == "COMPOSITE"
            and row["teaching_spec_version"] is None
        ) or (
            row["kind"] == "ATOMIC"
            and row["teaching_spec_version"] is not None
            and row["content_json"] is not None
            and row["spec_status"] in {"DRAFT", "PUBLISHED"}
        )
        if not valid_node or not valid_spec:
            raise ApiError(
                422,
                "OFFICIAL_TREE_REVIEW_INVALID",
                "Every official member must bind an eligible canonical node and exact Spec.",
            )
        member = {
            "nodeId": row["node_id"],
            "parentNodeId": row["parent_node_id"],
            "ordinal": row["ordinal"],
            "teachingSpecVersion": row["teaching_spec_version"],
        }
        members.append(member)
        aliases = [
            {
                "alias": alias["alias"],
                "normalizedAlias": alias["normalized_alias"],
                "locale": alias["locale"],
            }
            for alias in connection.execute(
                "SELECT alias,normalized_alias,locale FROM knowledge_node_aliases "
                "WHERE node_id=? ORDER BY locale,normalized_alias",
                (row["node_id"],),
            ).fetchall()
        ]
        node_metadata = {
            "nodeId": row["node_id"],
            "title": row["title"],
            "description": row["description"],
            "major": row["major"],
            "kind": row["kind"],
            "aliases": aliases,
        }
        resources.append(
            resource(
                kind="KNOWLEDGE_NODE",
                resource_id=row["node_id"],
                version="canonical",
                display_name=row["title"],
                source_scope="OFFICIAL",
                metadata=node_metadata,
            )
        )
        if row["teaching_spec_version"] is not None:
            spec_items = json.loads(row["content_json"])
            spec_metadata = {
                "nodeId": row["node_id"],
                "versionNumber": row["teaching_spec_version"],
                "items": spec_items,
                "sourceHash": row["content_hash"],
                "changeReason": row["spec_change_reason"],
            }
            resources.append(
                resource(
                    kind="TEACHING_SPEC",
                    resource_id=row["node_id"],
                    version=str(row["teaching_spec_version"]),
                    display_name=f"{row['title']} Teaching Spec v{row['teaching_spec_version']}",
                    source_scope="OFFICIAL",
                    metadata=spec_metadata,
                )
            )
    edge_rows = connection.execute(
        "SELECT node_id,prerequisite_node_id FROM knowledge_prerequisite_edges "
        "WHERE tree_version_id=? ORDER BY node_id,prerequisite_node_id",
        (tree_version_id,),
    ).fetchall()
    prerequisites = [
        {"nodeId": row["node_id"], "prerequisiteNodeId": row["prerequisite_node_id"]}
        for row in edge_rows
    ]
    tree_metadata = {
        "treeVersionId": tree["id"],
        "versionNumber": tree["version"],
        "title": tree["title"],
        "changeReason": tree["change_reason"],
        "sourceHash": tree["content_hash"],
        "members": members,
        "prerequisites": prerequisites,
    }
    resources.append(
        resource(
            kind="TREE_VERSION",
            resource_id=tree["id"],
            version=str(tree["version"]),
            display_name=tree["title"],
            source_scope="OFFICIAL",
            metadata=tree_metadata,
        )
    )
    node_ids = sorted({str(row["node_id"]) for row in member_rows})
    placeholders = ",".join("?" for _ in node_ids)
    evidence_rows = connection.execute(
        "SELECT id,node_id,document_version_id,chunk_id,source_scope,locator_type,"
        "locator_value,status FROM material_evidence "
        f"WHERE node_id IN ({placeholders}) AND source_scope='OFFICIAL' "
        "AND status='ACTIVE' "
        "ORDER BY node_id,id",
        node_ids,
    ).fetchall()
    for row in evidence_rows:
        metadata = {
            "nodeId": row["node_id"],
            "documentVersionId": row["document_version_id"],
            "chunkId": row["chunk_id"],
            "locatorType": row["locator_type"],
            "locatorValue": row["locator_value"],
            "status": row["status"],
        }
        resources.append(
            resource(
                kind="MATERIAL_EVIDENCE",
                resource_id=row["id"],
                version="1",
                display_name=f"Evidence for {row['node_id']}",
                source_scope="OFFICIAL",
                metadata=metadata,
            )
        )
    summary: dict[str, Any] = {
        "courseId": tree["course_id"],
        "courseName": tree["course_name"],
        "treeVersionId": tree["id"],
        "treeVersion": tree["version"],
        "title": tree["title"],
        "memberCount": len(member_rows),
    }
    return summary, resources


def overlay_snapshot_payload(
    connection: sqlite3.Connection,
    *,
    workspace_id: str,
    owner_user_id: str,
    node_ids: list[str],
    document_version_ids: list[str],
    artifact_ids: list[str],
    evidence_ids: list[str],
) -> tuple[dict[str, Any], list[SnapshotResourceData]]:
    collections = (node_ids, document_version_ids, artifact_ids, evidence_ids)
    if any(len(values) != len(set(values)) for values in collections):
        raise ApiError(
            422,
            "DUPLICATE_PUBLICATION_RESOURCE",
            "Each selected private resource may appear only once.",
        )
    if not any(collections):
        raise ApiError(
            422,
            "EMPTY_OVERLAY_PUBLICATION",
            "Select at least one private Overlay resource for review.",
        )
    workspace = connection.execute(
        "SELECT workspace.*,courses.name AS course_name,courses.course_type,"
        "courses.visibility,courses.publication_status "
        "FROM learning_workspaces AS workspace "
        "JOIN courses ON courses.id=workspace.course_id "
        "WHERE workspace.id=? AND workspace.owner_user_id=?",
        (workspace_id, owner_user_id),
    ).fetchone()
    if workspace is None:
        raise ApiError(404, "WORKSPACE_NOT_FOUND", "The workspace was not found.")
    if (
        workspace["course_type"] != "official"
        or workspace["visibility"] != "public"
        or workspace["publication_status"] != "published"
    ):
        raise ApiError(
            409,
            "OFFICIAL_COURSE_REQUIRED",
            "A private Overlay can be shared only against a published official course.",
        )
    resources: list[SnapshotResourceData] = []
    if node_ids:
        placeholders = ",".join("?" for _ in node_ids)
        node_rows = connection.execute(
            "SELECT id,title,description,major,kind FROM knowledge_nodes "
            f"WHERE id IN ({placeholders}) AND course_id=? AND owner_user_id=? "
            "AND status='PRIVATE' ORDER BY id",
            (*node_ids, workspace["course_id"], owner_user_id),
        ).fetchall()
        if len(node_rows) != len(node_ids):
            raise ApiError(
                404,
                "OVERLAY_RESOURCE_NOT_FOUND",
                "A selected private node was not found.",
            )
        for row in node_rows:
            metadata = {
                "nodeId": row["id"],
                "title": row["title"],
                "description": row["description"],
                "major": row["major"],
                "kind": row["kind"],
            }
            resources.append(
                resource(
                    kind="KNOWLEDGE_NODE",
                    resource_id=row["id"],
                    version="private",
                    display_name=row["title"],
                    source_scope="WORKSPACE_PRIVATE",
                    metadata=metadata,
                )
            )
            if row["kind"] == "ATOMIC":
                spec = connection.execute(
                    "SELECT spec.version,spec.content_json,spec.content_hash "
                    "FROM teaching_specs AS spec "
                    "JOIN teaching_spec_metadata AS metadata "
                    "ON metadata.node_id=spec.node_id AND metadata.version=spec.version "
                    "WHERE spec.node_id=? AND metadata.status='PRIVATE_ACTIVE' "
                    "ORDER BY spec.version DESC LIMIT 1",
                    (row["id"],),
                ).fetchone()
                if spec is None:
                    raise ApiError(
                        422,
                        "PRIVATE_SPEC_REQUIRED",
                        "Every selected private atomic node needs an active exact Spec.",
                    )
                spec_metadata = {
                    "nodeId": row["id"],
                    "versionNumber": spec["version"],
                    "items": json.loads(spec["content_json"]),
                    "sourceHash": spec["content_hash"],
                }
                resources.append(
                    resource(
                        kind="TEACHING_SPEC",
                        resource_id=row["id"],
                        version=str(spec["version"]),
                        display_name=f"{row['title']} Teaching Spec v{spec['version']}",
                        source_scope="WORKSPACE_PRIVATE",
                        metadata=spec_metadata,
                    )
                )
    if document_version_ids:
        placeholders = ",".join("?" for _ in document_version_ids)
        document_rows = connection.execute(
            "SELECT version.id,version.document_id,version.version,version.filename,"
            "version.media_type,version.extension,version.sha256,version.byte_size,"
            "version.source_scope,documents.status,documents.chunk_count "
            "FROM document_versions AS version "
            "JOIN documents ON documents.id=version.document_id "
            f"WHERE version.id IN ({placeholders}) AND version.course_id=? "
            "AND version.owner_user_id=? AND version.source_scope='WORKSPACE_PRIVATE' "
            "ORDER BY version.id",
            (*document_version_ids, workspace["private_course_id"], owner_user_id),
        ).fetchall()
        if len(document_rows) != len(document_version_ids):
            raise ApiError(
                404,
                "OVERLAY_RESOURCE_NOT_FOUND",
                "A selected private document version was not found.",
            )
        if any(row["status"] != "ready" for row in document_rows):
            raise ApiError(
                409,
                "PUBLICATION_SOURCE_NOT_READY",
                "Every selected document must finish indexing before review.",
            )
        for row in document_rows:
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
                    resource_id=row["id"],
                    version=str(row["version"]),
                    display_name=row["filename"],
                    source_scope="WORKSPACE_PRIVATE",
                    metadata=metadata,
                )
            )
    if artifact_ids:
        placeholders = ",".join("?" for _ in artifact_ids)
        artifact_rows = connection.execute(
            "SELECT id,document_version_id,kind,media_type,sha256,byte_size,"
            "producer_version,metadata_json FROM derived_artifacts "
            f"WHERE id IN ({placeholders}) AND status='READY' ORDER BY id",
            artifact_ids,
        ).fetchall()
        if len(artifact_rows) != len(artifact_ids) or any(
            row["document_version_id"] not in document_version_ids for row in artifact_rows
        ):
            raise ApiError(
                404,
                "OVERLAY_RESOURCE_NOT_FOUND",
                "A selected artifact was not found in the explicitly selected documents.",
            )
        for row in artifact_rows:
            producer_metadata = json.loads(row["metadata_json"])
            metadata = {
                "documentVersionId": row["document_version_id"],
                "kind": row["kind"],
                "mediaType": row["media_type"],
                "sha256": row["sha256"],
                "byteSize": row["byte_size"],
                "producerVersion": row["producer_version"],
            }
            resources.append(
                resource(
                    kind="DERIVED_ARTIFACT",
                    resource_id=row["id"],
                    version=row["producer_version"],
                    display_name=f"{row['kind']} for {row['document_version_id']}",
                    source_scope="WORKSPACE_PRIVATE",
                    metadata=metadata,
                    digest_value={**metadata, "producerMetadata": producer_metadata},
                )
            )
    if evidence_ids:
        placeholders = ",".join("?" for _ in evidence_ids)
        evidence_rows = connection.execute(
            "SELECT evidence.id,evidence.node_id,evidence.document_version_id,"
            "evidence.chunk_id,evidence.locator_type,evidence.locator_value,"
            "node.owner_user_id AS node_owner,node.title AS node_title,node.status AS node_status "
            "FROM material_evidence AS evidence "
            "JOIN knowledge_nodes AS node ON node.id=evidence.node_id "
            f"WHERE evidence.id IN ({placeholders}) AND evidence.owner_user_id=? "
            "AND evidence.source_scope='WORKSPACE_PRIVATE' AND evidence.status='ACTIVE' "
            "AND node.course_id=? ORDER BY evidence.id",
            (*evidence_ids, owner_user_id, workspace["course_id"]),
        ).fetchall()
        if len(evidence_rows) != len(evidence_ids):
            raise ApiError(
                404,
                "OVERLAY_RESOURCE_NOT_FOUND",
                "A selected private evidence record was not found.",
            )
        selected_nodes = set(node_ids)
        selected_versions = set(document_version_ids)
        canonical_refs: dict[str, str] = {}
        for row in evidence_rows:
            if row["document_version_id"] not in selected_versions:
                raise ApiError(
                    422,
                    "EVIDENCE_SOURCE_NOT_SELECTED",
                    "Select the exact private document version referenced by each evidence item.",
                )
            if row["node_owner"] is not None and row["node_id"] not in selected_nodes:
                raise ApiError(
                    422,
                    "PRIVATE_NODE_NOT_SELECTED",
                    "Private evidence cannot implicitly publish an unselected private node.",
                )
            if row["node_owner"] is None:
                if row["node_status"] != "PUBLISHED":
                    raise ApiError(
                        422,
                        "CANONICAL_REFERENCE_NOT_PUBLISHED",
                        "Private evidence may reference only a published canonical node.",
                    )
                canonical_refs[row["node_id"]] = row["node_title"]
            metadata = {
                "nodeId": row["node_id"],
                "documentVersionId": row["document_version_id"],
                "chunkId": row["chunk_id"],
                "locatorType": row["locator_type"],
                "locatorValue": row["locator_value"],
            }
            resources.append(
                resource(
                    kind="MATERIAL_EVIDENCE",
                    resource_id=row["id"],
                    version="1",
                    display_name=f"Evidence for {row['node_title']}",
                    source_scope="WORKSPACE_PRIVATE",
                    metadata=metadata,
                )
            )
        for node_id, title in sorted(canonical_refs.items()):
            metadata = {"nodeId": node_id, "title": title}
            resources.append(
                resource(
                    kind="CANONICAL_NODE_REFERENCE",
                    resource_id=node_id,
                    version="published",
                    display_name=title,
                    source_scope="OFFICIAL",
                    metadata=metadata,
                )
            )
    summary: dict[str, Any] = {
        "courseId": workspace["course_id"],
        "courseName": workspace["course_name"],
        "workspaceId": workspace_id,
        "selectedNodeCount": len(node_ids),
        "selectedDocumentCount": len(document_version_ids),
        "selectedArtifactCount": len(artifact_ids),
        "selectedEvidenceCount": len(evidence_ids),
    }
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
