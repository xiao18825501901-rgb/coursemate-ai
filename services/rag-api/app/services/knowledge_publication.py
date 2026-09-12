import sqlite3
from uuid import uuid4

from app.db import Database
from app.errors import ApiError
from app.models import (
    OfficialKnowledgeDraft,
    OfficialKnowledgePublicationRequest,
    OfficialKnowledgePublicationSubmit,
    PublicationReview,
    PublicationSnapshot,
)
from app.services.publication_snapshots import (
    activate_release,
    create_snapshot,
    official_knowledge_snapshot_payload,
    record_audit_event,
    snapshot_hash,
    snapshot_view,
    withdraw_release,
)


class KnowledgePublicationService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def _require_v3(self) -> None:
        if not self.database.v3_enabled:
            raise ApiError(404, "V3_DISABLED", "Official knowledge publication is unavailable.")

    @staticmethod
    def _request(row: sqlite3.Row) -> OfficialKnowledgePublicationRequest:
        return OfficialKnowledgePublicationRequest.model_validate(dict(row))

    @staticmethod
    def _select_request(
        connection: sqlite3.Connection, request_id: str
    ) -> sqlite3.Row | None:
        row: sqlite3.Row | None = connection.execute(
            "SELECT request.id,request.course_id,courses.name AS course_name,"
            "request.tree_version_id,tree.version AS tree_version,tree.title AS tree_title,"
            "request.status,request.submitted_at,request.reviewed_at,request.review_note,"
            "request.submitted_by_user_id,request.reviewed_by_user_id,"
            "snapshot.id AS snapshot_id,snapshot.content_hash AS snapshot_hash,"
            "(SELECT COUNT(*) FROM publication_snapshot_resources AS resource "
            "WHERE resource.snapshot_id=snapshot.id) AS resource_count "
            "FROM official_knowledge_publication_requests AS request "
            "JOIN courses ON courses.id=request.course_id "
            "JOIN knowledge_tree_versions AS tree ON tree.id=request.tree_version_id "
            "JOIN publication_review_snapshots AS snapshot ON snapshot.id=request.snapshot_id "
            "WHERE request.id=?",
            (request_id,),
        ).fetchone()
        return row

    def list_drafts(self) -> list[OfficialKnowledgeDraft]:
        self._require_v3()
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT tree.id AS tree_version_id,tree.course_id,courses.name AS course_name,"
                "tree.version AS tree_version,tree.title,"
                "(SELECT COUNT(*) FROM knowledge_tree_memberships AS member "
                "WHERE member.tree_version_id=tree.id) AS member_count,"
                "(SELECT request.id FROM official_knowledge_publication_requests AS request "
                "WHERE request.tree_version_id=tree.id AND request.status='pending' "
                "ORDER BY request.submitted_at DESC LIMIT 1) AS pending_request_id "
                "FROM knowledge_tree_versions AS tree "
                "JOIN courses ON courses.id=tree.course_id "
                "WHERE tree.tree_kind='OFFICIAL' AND tree.status='DRAFT' "
                "ORDER BY courses.name,tree.version DESC,tree.id"
            ).fetchall()
        return [OfficialKnowledgeDraft.model_validate(dict(row)) for row in rows]

    def submit(
        self,
        payload: OfficialKnowledgePublicationSubmit,
        *,
        submitter_user_id: str,
    ) -> OfficialKnowledgePublicationRequest:
        self._require_v3()
        request_id = "knowledge_publication_" + uuid4().hex
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM official_knowledge_publication_requests "
                "WHERE tree_version_id=? AND status='pending'",
                (payload.tree_version_id,),
            ).fetchone():
                raise ApiError(
                    409,
                    "OFFICIAL_REVIEW_PENDING",
                    "This tree version already has a pending review.",
                )
            summary, resources = official_knowledge_snapshot_payload(
                connection, payload.tree_version_id
            )
            snapshot_id, _ = create_snapshot(
                connection,
                subject_kind="OFFICIAL_KNOWLEDGE",
                request_id=request_id,
                course_id=str(summary["courseId"]),
                workspace_id=None,
                owner_user_id=None,
                summary=summary,
                resources=resources,
            )
            connection.execute(
                "INSERT INTO official_knowledge_publication_requests("
                "id,course_id,tree_version_id,snapshot_id,submitted_by_user_id,status) "
                "VALUES(?,?,?,?,?,'pending')",
                (
                    request_id,
                    summary["courseId"],
                    payload.tree_version_id,
                    snapshot_id,
                    submitter_user_id,
                ),
            )
            record_audit_event(
                connection,
                subject_kind="OFFICIAL_KNOWLEDGE",
                request_id=request_id,
                actor_user_id=submitter_user_id,
                action="SUBMITTED",
            )
            row = self._select_request(connection, request_id)
        assert row is not None
        return self._request(row)

    def list_pending(self) -> list[OfficialKnowledgePublicationRequest]:
        self._require_v3()
        with self.database.connect() as connection:
            request_ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM official_knowledge_publication_requests "
                    "WHERE status='pending' ORDER BY submitted_at,id"
                ).fetchall()
            ]
            rows = [self._select_request(connection, request_id) for request_id in request_ids]
        return [self._request(row) for row in rows if row is not None]

    def snapshot(self, request_id: str) -> PublicationSnapshot:
        self._require_v3()
        with self.database.connect() as connection:
            if self._select_request(connection, request_id) is None:
                raise ApiError(
                    404,
                    "OFFICIAL_PUBLICATION_NOT_FOUND",
                    "The official review request was not found.",
                )
            return snapshot_view(
                connection,
                subject_kind="OFFICIAL_KNOWLEDGE",
                request_id=request_id,
            )

    def review(
        self,
        request_id: str,
        payload: PublicationReview,
        *,
        reviewer_user_id: str,
    ) -> OfficialKnowledgePublicationRequest:
        self._require_v3()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            request = self._select_request(connection, request_id)
            if request is None or request["status"] != "pending":
                raise ApiError(
                    404,
                    "OFFICIAL_PUBLICATION_NOT_FOUND",
                    "The pending official review request was not found.",
                )
            if request["submitted_by_user_id"] == reviewer_user_id:
                raise ApiError(
                    409,
                    "INDEPENDENT_REVIEW_REQUIRED",
                    "A second administrator must review official knowledge content.",
                )
            summary, resources = official_knowledge_snapshot_payload(
                connection, request["tree_version_id"]
            )
            if snapshot_hash(summary, resources) != request["snapshot_hash"]:
                raise ApiError(
                    409,
                    "PUBLICATION_SNAPSHOT_STALE",
                    "The official tree no longer matches the submitted snapshot.",
                )
            approved = payload.decision == "approve"
            if approved:
                connection.execute(
                    "UPDATE knowledge_tree_versions SET status='RETIRED' "
                    "WHERE course_id=? AND tree_kind='OFFICIAL' AND status='PUBLISHED' "
                    "AND id!=?",
                    (request["course_id"], request["tree_version_id"]),
                )
                node_rows = connection.execute(
                    "SELECT resource_id FROM publication_snapshot_resources "
                    "WHERE snapshot_id=? AND resource_kind='KNOWLEDGE_NODE'",
                    (request["snapshot_id"],),
                ).fetchall()
                connection.executemany(
                    "UPDATE knowledge_nodes SET status='PUBLISHED' WHERE id=?",
                    [(row["resource_id"],) for row in node_rows],
                )
                spec_rows = connection.execute(
                    "SELECT resource_id,version_label FROM publication_snapshot_resources "
                    "WHERE snapshot_id=? AND resource_kind='TEACHING_SPEC'",
                    (request["snapshot_id"],),
                ).fetchall()
                connection.executemany(
                    "UPDATE teaching_spec_metadata SET status='PUBLISHED' "
                    "WHERE node_id=? AND version=?",
                    [
                        (row["resource_id"], int(row["version_label"]))
                        for row in spec_rows
                    ],
                )
                connection.execute(
                    "UPDATE knowledge_tree_versions SET status='PUBLISHED',"
                    "reviewed_by_user_id=?,reviewed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                    "WHERE id=?",
                    (reviewer_user_id, request["tree_version_id"]),
                )
            connection.execute(
                "UPDATE official_knowledge_publication_requests SET status=?,"
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
                    subject_kind="OFFICIAL_KNOWLEDGE",
                    request_id=request_id,
                    snapshot_id=request["snapshot_id"],
                )
            record_audit_event(
                connection,
                subject_kind="OFFICIAL_KNOWLEDGE",
                request_id=request_id,
                actor_user_id=reviewer_user_id,
                action="APPROVED" if approved else "REJECTED",
            )
            reviewed = self._select_request(connection, request_id)
        assert reviewed is not None
        return self._request(reviewed)

    def withdraw(self, request_id: str, *, actor_user_id: str) -> None:
        self._require_v3()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            request = self._select_request(connection, request_id)
            if request is None or request["status"] not in {"pending", "approved"}:
                raise ApiError(
                    404,
                    "OFFICIAL_PUBLICATION_NOT_FOUND",
                    "The active official publication was not found.",
                )
            if request["status"] == "approved":
                connection.execute(
                    "UPDATE knowledge_tree_versions SET status='RETIRED' WHERE id=?",
                    (request["tree_version_id"],),
                )
                withdraw_release(
                    connection,
                    subject_kind="OFFICIAL_KNOWLEDGE",
                    request_id=request_id,
                    actor_user_id=actor_user_id,
                )
            connection.execute(
                "UPDATE official_knowledge_publication_requests SET status='withdrawn' "
                "WHERE id=?",
                (request_id,),
            )
            record_audit_event(
                connection,
                subject_kind="OFFICIAL_KNOWLEDGE",
                request_id=request_id,
                actor_user_id=actor_user_id,
                action="WITHDRAWN",
            )
