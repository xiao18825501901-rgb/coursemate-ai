import json
import sqlite3
from typing import cast
from uuid import uuid4

from app.db import Database
from app.errors import ApiError
from app.models import (
    OverlayPublicationCandidates,
    OverlayPublicationRequest,
    OverlayPublicationSubmit,
    PublicationReview,
    PublicationSnapshot,
)
from app.services.publication_snapshots import (
    activate_release,
    create_snapshot,
    overlay_snapshot_payload,
    record_audit_event,
    snapshot_hash,
    snapshot_view,
    withdraw_release,
)


class OverlayPublicationService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def _require_v3(self) -> None:
        if not self.database.v3_enabled:
            raise ApiError(404, "V3_DISABLED", "Private Overlay publication is unavailable.")

    @staticmethod
    def _request(row: sqlite3.Row) -> OverlayPublicationRequest:
        values = dict(row)
        values["share_selected_content_consent"] = bool(
            values["share_selected_content_consent"]
        )
        values["rights_confirmation"] = bool(values["rights_confirmation"])
        return OverlayPublicationRequest.model_validate(values)

    @staticmethod
    def _select_request(
        connection: sqlite3.Connection, request_id: str
    ) -> sqlite3.Row | None:
        row: sqlite3.Row | None = connection.execute(
            "SELECT request.*,courses.name AS course_name,"
            "snapshot.content_hash AS snapshot_hash,"
            "(SELECT COUNT(*) FROM publication_snapshot_resources AS resource "
            "WHERE resource.snapshot_id=snapshot.id) AS resource_count "
            "FROM overlay_publication_requests AS request "
            "JOIN courses ON courses.id=request.course_id "
            "JOIN publication_review_snapshots AS snapshot ON snapshot.id=request.snapshot_id "
            "WHERE request.id=?",
            (request_id,),
        ).fetchone()
        return row

    def submit(
        self,
        workspace_id: str,
        payload: OverlayPublicationSubmit,
        *,
        owner_user_id: str,
    ) -> OverlayPublicationRequest:
        self._require_v3()
        if not payload.share_selected_content_consent or not payload.rights_confirmation:
            raise ApiError(
                422,
                "PUBLICATION_CONSENT_REQUIRED",
                "Overlay publication requires explicit selected-content consent "
                "and rights confirmation.",
            )
        request_id = "overlay_publication_" + uuid4().hex
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM overlay_publication_requests "
                "WHERE workspace_id=? AND status='pending'",
                (workspace_id,),
            ).fetchone():
                raise ApiError(
                    409,
                    "OVERLAY_REVIEW_PENDING",
                    "This workspace already has a pending Overlay review.",
                )
            summary, resources = overlay_snapshot_payload(
                connection,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                node_ids=payload.node_ids,
                document_version_ids=payload.document_version_ids,
                artifact_ids=payload.artifact_ids,
                evidence_ids=payload.evidence_ids,
            )
            snapshot_id, _ = create_snapshot(
                connection,
                subject_kind="OVERLAY",
                request_id=request_id,
                course_id=str(summary["courseId"]),
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                summary=summary,
                resources=resources,
            )
            connection.execute(
                "INSERT INTO overlay_publication_requests("
                "id,course_id,workspace_id,owner_user_id,snapshot_id,status,"
                "share_selected_content_consent,rights_confirmation,consent_version,"
                "consented_at) VALUES(?,?,?,?,?,'pending',1,1,?,"
                "strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                (
                    request_id,
                    summary["courseId"],
                    workspace_id,
                    owner_user_id,
                    snapshot_id,
                    payload.consent_version,
                ),
            )
            record_audit_event(
                connection,
                subject_kind="OVERLAY",
                request_id=request_id,
                actor_user_id=owner_user_id,
                action="SUBMITTED",
                details={"consentVersion": payload.consent_version},
            )
            row = self._select_request(connection, request_id)
        assert row is not None
        return self._request(row)

    def list_pending(self) -> list[OverlayPublicationRequest]:
        self._require_v3()
        with self.database.connect() as connection:
            ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM overlay_publication_requests "
                    "WHERE status='pending' ORDER BY submitted_at,id"
                ).fetchall()
            ]
            rows = [self._select_request(connection, request_id) for request_id in ids]
        return [self._request(row) for row in rows if row is not None]

    def candidates(
        self,
        workspace_id: str,
        *,
        owner_user_id: str,
    ) -> OverlayPublicationCandidates:
        self._require_v3()
        with self.database.connect() as connection:
            workspace = connection.execute(
                "SELECT course_id,private_course_id FROM learning_workspaces "
                "WHERE id=? AND owner_user_id=?",
                (workspace_id, owner_user_id),
            ).fetchone()
            if workspace is None:
                raise ApiError(404, "WORKSPACE_NOT_FOUND", "The workspace was not found.")
            nodes = connection.execute(
                "SELECT node.id,node.title,node.kind,("
                "SELECT MAX(metadata.version) FROM teaching_spec_metadata AS metadata "
                "WHERE metadata.node_id=node.id AND metadata.status='PRIVATE_ACTIVE'"
                ") AS spec_version FROM knowledge_nodes AS node "
                "WHERE node.course_id=? AND node.owner_user_id=? AND node.status='PRIVATE' "
                "ORDER BY node.title,node.id",
                (workspace["course_id"], owner_user_id),
            ).fetchall()
            documents = connection.execute(
                "SELECT version.id,version.document_id,version.version,version.filename,"
                "version.sha256,version.byte_size,documents.status "
                "FROM document_versions AS version "
                "JOIN documents ON documents.id=version.document_id "
                "WHERE version.course_id=? AND version.owner_user_id=? "
                "AND version.source_scope='WORKSPACE_PRIVATE' "
                "ORDER BY version.filename,version.version DESC,version.id",
                (workspace["private_course_id"], owner_user_id),
            ).fetchall()
            artifacts = connection.execute(
                "SELECT artifact.id,artifact.document_version_id,artifact.kind,"
                "artifact.producer_version,artifact.sha256,artifact.byte_size "
                "FROM derived_artifacts AS artifact "
                "JOIN document_versions AS version "
                "ON version.id=artifact.document_version_id "
                "WHERE version.course_id=? AND version.owner_user_id=? "
                "AND version.source_scope='WORKSPACE_PRIVATE' AND artifact.status='READY' "
                "ORDER BY version.filename,artifact.kind,artifact.id",
                (workspace["private_course_id"], owner_user_id),
            ).fetchall()
            evidence_rows = connection.execute(
                "SELECT evidence.id,evidence.node_id,node.title AS node_title,"
                "CASE WHEN node.owner_user_id IS NULL THEN 0 ELSE 1 END AS node_is_private,"
                "evidence.document_version_id,evidence.locator_type,evidence.locator_value "
                "FROM material_evidence AS evidence "
                "JOIN knowledge_nodes AS node ON node.id=evidence.node_id "
                "JOIN document_versions AS version "
                "ON version.id=evidence.document_version_id "
                "WHERE evidence.owner_user_id=? "
                "AND evidence.source_scope='WORKSPACE_PRIVATE' "
                "AND evidence.status='ACTIVE' AND node.course_id=? "
                "AND version.course_id=? AND version.owner_user_id=? "
                "ORDER BY node.title,evidence.id",
                (
                    owner_user_id,
                    workspace["course_id"],
                    workspace["private_course_id"],
                    owner_user_id,
                ),
            ).fetchall()
        return OverlayPublicationCandidates.model_validate(
            {
                "nodes": [dict(row) for row in nodes],
                "documents": [dict(row) for row in documents],
                "artifacts": [dict(row) for row in artifacts],
                "evidence": [
                    {**dict(row), "node_is_private": bool(row["node_is_private"])}
                    for row in evidence_rows
                ],
            }
        )

    def current(self, workspace_id: str, *, owner_user_id: str) -> OverlayPublicationRequest:
        self._require_v3()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id FROM overlay_publication_requests "
                "WHERE workspace_id=? AND owner_user_id=? "
                "ORDER BY submitted_at DESC LIMIT 1",
                (workspace_id, owner_user_id),
            ).fetchone()
            request = self._select_request(connection, row["id"]) if row is not None else None
        if request is None:
            raise ApiError(404, "OVERLAY_PUBLICATION_NOT_FOUND", "No Overlay request was found.")
        return self._request(request)

    def owner_snapshot(
        self,
        workspace_id: str,
        *,
        owner_user_id: str,
    ) -> PublicationSnapshot:
        self._require_v3()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT request.id FROM overlay_publication_requests AS request "
                "JOIN learning_workspaces AS workspace ON workspace.id=request.workspace_id "
                "WHERE request.workspace_id=? AND request.owner_user_id=? "
                "AND workspace.owner_user_id=? "
                "ORDER BY request.submitted_at DESC LIMIT 1",
                (workspace_id, owner_user_id, owner_user_id),
            ).fetchone()
            if row is None:
                raise ApiError(
                    404,
                    "OVERLAY_PUBLICATION_NOT_FOUND",
                    "No Overlay review snapshot was found.",
                )
            return snapshot_view(
                connection,
                subject_kind="OVERLAY",
                request_id=row["id"],
            )

    def snapshot(self, request_id: str) -> PublicationSnapshot:
        self._require_v3()
        with self.database.connect() as connection:
            if self._select_request(connection, request_id) is None:
                raise ApiError(
                    404,
                    "OVERLAY_PUBLICATION_NOT_FOUND",
                    "The Overlay review request was not found.",
                )
            return snapshot_view(connection, subject_kind="OVERLAY", request_id=request_id)

    def public_snapshot(self, request_id: str) -> PublicationSnapshot:
        self._require_v3()
        with self.database.connect() as connection:
            active = connection.execute(
                "SELECT 1 FROM overlay_publication_requests AS request "
                "JOIN publication_releases AS release "
                "ON release.subject_kind='OVERLAY' AND release.request_id=request.id "
                "WHERE request.id=? AND request.status='approved' "
                "AND release.status='ACTIVE'",
                (request_id,),
            ).fetchone()
            if active is None:
                raise ApiError(
                    404,
                    "SHARED_OVERLAY_NOT_FOUND",
                    "The shared Overlay was not found.",
                )
            view = snapshot_view(connection, subject_kind="OVERLAY", request_id=request_id)
        summary = {key: value for key, value in view.summary.items() if key != "workspaceId"}
        return view.model_copy(update={"workspace_id": None, "summary": summary})

    def scoped_document(
        self,
        request_id: str,
        version_id: str,
        *,
        public_access: bool,
    ) -> sqlite3.Row:
        self._require_v3()
        with self.database.connect() as connection:
            if public_access:
                active = connection.execute(
                    "SELECT 1 FROM overlay_publication_requests AS request "
                    "JOIN publication_releases AS release "
                    "ON release.subject_kind='OVERLAY' AND release.request_id=request.id "
                    "WHERE request.id=? AND request.status='approved' "
                    "AND release.status='ACTIVE'",
                    (request_id,),
                ).fetchone()
            else:
                active = connection.execute(
                    "SELECT 1 FROM overlay_publication_requests "
                    "WHERE id=? AND status IN ('pending','approved')",
                    (request_id,),
                ).fetchone()
            if active is None:
                raise ApiError(404, "SHARED_OVERLAY_NOT_FOUND", "The shared Overlay was not found.")
            row = connection.execute(
                "SELECT version.*,resource.metadata_json "
                "FROM publication_review_snapshots AS snapshot "
                "JOIN publication_snapshot_resources AS resource "
                "ON resource.snapshot_id=snapshot.id "
                "AND resource.resource_kind='DOCUMENT_VERSION' "
                "JOIN document_versions AS version ON version.id=resource.resource_id "
                "WHERE snapshot.subject_kind='OVERLAY' AND snapshot.request_id=? "
                "AND resource.resource_id=?",
                (request_id, version_id),
            ).fetchone()
        if row is None:
            raise ApiError(404, "PUBLICATION_RESOURCE_NOT_FOUND", "The shared file was not found.")
        metadata = json.loads(row["metadata_json"])
        if row["sha256"] != metadata.get("sha256") or row["filename"] != metadata.get(
            "filename"
        ):
            raise ApiError(
                409,
                "PUBLICATION_SNAPSHOT_STALE",
                "The selected source no longer matches the reviewed snapshot.",
            )
        return cast(sqlite3.Row, row)

    @staticmethod
    def _selected_ids(
        connection: sqlite3.Connection,
        snapshot_id: str,
        resource_kind: str,
    ) -> list[str]:
        return [
            str(row["resource_id"])
            for row in connection.execute(
                "SELECT resource_id FROM publication_snapshot_resources "
                "WHERE snapshot_id=? AND resource_kind=? ORDER BY resource_id",
                (snapshot_id, resource_kind),
            ).fetchall()
        ]

    def review(
        self,
        request_id: str,
        payload: PublicationReview,
        *,
        reviewer_user_id: str,
    ) -> OverlayPublicationRequest:
        self._require_v3()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            request = self._select_request(connection, request_id)
            if request is None or request["status"] != "pending":
                raise ApiError(
                    404,
                    "OVERLAY_PUBLICATION_NOT_FOUND",
                    "The pending Overlay review request was not found.",
                )
            if request["owner_user_id"] == reviewer_user_id:
                raise ApiError(
                    409,
                    "INDEPENDENT_REVIEW_REQUIRED",
                    "The Overlay owner cannot approve their own submission.",
                )
            summary, resources = overlay_snapshot_payload(
                connection,
                workspace_id=request["workspace_id"],
                owner_user_id=request["owner_user_id"],
                node_ids=self._selected_ids(
                    connection, request["snapshot_id"], "KNOWLEDGE_NODE"
                ),
                document_version_ids=self._selected_ids(
                    connection, request["snapshot_id"], "DOCUMENT_VERSION"
                ),
                artifact_ids=self._selected_ids(
                    connection, request["snapshot_id"], "DERIVED_ARTIFACT"
                ),
                evidence_ids=self._selected_ids(
                    connection, request["snapshot_id"], "MATERIAL_EVIDENCE"
                ),
            )
            if snapshot_hash(summary, resources) != request["snapshot_hash"]:
                raise ApiError(
                    409,
                    "PUBLICATION_SNAPSHOT_STALE",
                    "The selected Overlay no longer matches the submitted snapshot.",
                )
            approved = payload.decision == "approve"
            connection.execute(
                "UPDATE overlay_publication_requests SET status=?,"
                "reviewed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),"
                "reviewed_by_user_id=?,review_note=? WHERE id=?",
                (
                    "approved" if approved else "rejected",
                    reviewer_user_id,
                    payload.review_note.strip(),
                    request_id,
                ),
            )
            if approved:
                activate_release(
                    connection,
                    subject_kind="OVERLAY",
                    request_id=request_id,
                    snapshot_id=request["snapshot_id"],
                )
            record_audit_event(
                connection,
                subject_kind="OVERLAY",
                request_id=request_id,
                actor_user_id=reviewer_user_id,
                action="APPROVED" if approved else "REJECTED",
            )
            reviewed = self._select_request(connection, request_id)
        assert reviewed is not None
        return self._request(reviewed)

    def withdraw_current(self, workspace_id: str, *, owner_user_id: str) -> None:
        self._require_v3()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            request = connection.execute(
                "SELECT id,status FROM overlay_publication_requests "
                "WHERE workspace_id=? AND owner_user_id=? "
                "AND status IN ('pending','approved') "
                "ORDER BY submitted_at DESC LIMIT 1",
                (workspace_id, owner_user_id),
            ).fetchone()
            if request is None:
                raise ApiError(
                    404,
                    "OVERLAY_PUBLICATION_NOT_FOUND",
                    "No active Overlay publication was found.",
                )
            connection.execute(
                "UPDATE overlay_publication_requests SET status='withdrawn' WHERE id=?",
                (request["id"],),
            )
            if request["status"] == "approved":
                withdraw_release(
                    connection,
                    subject_kind="OVERLAY",
                    request_id=request["id"],
                    actor_user_id=owner_user_id,
                )
            record_audit_event(
                connection,
                subject_kind="OVERLAY",
                request_id=request["id"],
                actor_user_id=owner_user_id,
                action="WITHDRAWN",
            )
