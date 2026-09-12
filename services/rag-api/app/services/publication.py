import json
import sqlite3
from typing import cast
from uuid import uuid4

from app.course_access import require_course_access
from app.db import Database
from app.errors import ApiError
from app.models import (
    PublicationRequest,
    PublicationReview,
    PublicationSnapshot,
    PublicationSubmit,
)
from app.services.publication_snapshots import (
    activate_release,
    course_snapshot_payload,
    create_snapshot,
    record_audit_event,
    snapshot_hash,
    snapshot_view,
    withdraw_release,
)


class PublicationService:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _request(row: sqlite3.Row) -> PublicationRequest:
        values = dict(row)
        values["share_materials_consent"] = bool(values["share_materials_consent"])
        values["rights_confirmation"] = bool(values["rights_confirmation"])
        return PublicationRequest.model_validate(values)

    def submit(
        self,
        course_id: str,
        payload: PublicationSubmit,
        *,
        owner_user_id: str,
        is_admin: bool,
    ) -> PublicationRequest:
        course = require_course_access(
            self.database,
            course_id,
            owner_user_id=owner_user_id,
            is_admin=is_admin,
            write=True,
        )
        if course["course_type"] != "user" or course["owner_user_id"] != owner_user_id:
            raise ApiError(403, "OWNER_REQUIRED", "Only the course owner can request publication.")
        if not payload.share_materials_consent or not payload.rights_confirmation:
            raise ApiError(
                422,
                "PUBLICATION_CONSENT_REQUIRED",
                "Publication requires sharing consent and confirmation of permission to share.",
            )
        request_id = f"publication_{uuid4().hex}"
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self.database.v3_enabled and connection.execute(
                "SELECT 1 FROM learning_workspaces WHERE private_course_id=?", (course_id,)
            ).fetchone():
                raise ApiError(409, "WORKSPACE_PRIVATE", "Workspace files cannot be published.")
            active = connection.execute(
                "SELECT 1 FROM course_publication_requests "
                "WHERE course_id=? AND status='pending'",
                (course_id,),
            ).fetchone()
            if active is not None:
                raise ApiError(409, "PUBLICATION_PENDING", "A review is already pending.")
            connection.execute(
                """
                INSERT INTO course_publication_requests (
                    id, course_id, owner_user_id, status, share_materials_consent,
                    rights_confirmation, consent_version, consented_at
                ) VALUES (?, ?, ?, 'pending', 1, 1, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (request_id, course_id, owner_user_id, payload.consent_version),
            )
            if self.database.v3_enabled:
                summary, resources = course_snapshot_payload(connection, course_id)
                create_snapshot(
                    connection,
                    subject_kind="COURSE",
                    request_id=request_id,
                    course_id=course_id,
                    workspace_id=None,
                    owner_user_id=owner_user_id,
                    summary=summary,
                    resources=resources,
                )
                record_audit_event(
                    connection,
                    subject_kind="COURSE",
                    request_id=request_id,
                    actor_user_id=owner_user_id,
                    action="SUBMITTED",
                    details={"consentVersion": payload.consent_version},
                )
            connection.execute(
                "UPDATE courses SET publication_status='pending',visibility='private',"
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (course_id,),
            )
            row = self._select_request(connection, request_id)
        assert row is not None
        return self._request(row)

    def _select_request(
        self, connection: sqlite3.Connection, request_id: str
    ) -> sqlite3.Row | None:
        if self.database.v3_enabled:
            snapshot_projection = """
                snapshot.id AS snapshot_id,
                snapshot.content_hash AS snapshot_hash,
                COALESCE((SELECT COUNT(*) FROM publication_snapshot_resources AS resource
                    WHERE resource.snapshot_id=snapshot.id),0) AS resource_count
            """
            snapshot_join = """
                LEFT JOIN publication_review_snapshots AS snapshot
                  ON snapshot.subject_kind='COURSE'
                 AND snapshot.request_id=course_publication_requests.id
            """
        else:
            snapshot_projection = (
                "NULL AS snapshot_id, NULL AS snapshot_hash, 0 AS resource_count"
            )
            snapshot_join = ""
        row: sqlite3.Row | None = connection.execute(
            f"""
            SELECT course_publication_requests.*, courses.name AS course_name,
                   {snapshot_projection}
            FROM course_publication_requests
            JOIN courses ON courses.id=course_publication_requests.course_id
            {snapshot_join}
            WHERE course_publication_requests.id=?
            """,
            (request_id,),
        ).fetchone()
        return cast(sqlite3.Row, row)

    def list_pending(self) -> list[PublicationRequest]:
        with self.database.connect() as connection:
            request_ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM course_publication_requests "
                    "WHERE status='pending' ORDER BY submitted_at,id"
                ).fetchall()
            ]
            rows = [self._select_request(connection, request_id) for request_id in request_ids]
        return [self._request(row) for row in rows if row is not None]

    def snapshot(self, request_id: str) -> PublicationSnapshot:
        if not self.database.v3_enabled:
            raise ApiError(404, "V3_DISABLED", "The V3 publication snapshot is unavailable.")
        with self.database.connect() as connection:
            request = self._select_request(connection, request_id)
            if request is None:
                raise ApiError(404, "PUBLICATION_NOT_FOUND", "The request was not found.")
            return snapshot_view(connection, subject_kind="COURSE", request_id=request_id)

    def scoped_document(self, request_id: str, version_id: str) -> sqlite3.Row:
        if not self.database.v3_enabled:
            raise ApiError(404, "V3_DISABLED", "The scoped review file is unavailable.")
        with self.database.connect() as connection:
            request = connection.execute(
                "SELECT status FROM course_publication_requests WHERE id=?", (request_id,)
            ).fetchone()
            if request is None or request["status"] not in {"pending", "approved"}:
                raise ApiError(404, "PUBLICATION_NOT_FOUND", "The active request was not found.")
            row = connection.execute(
                "SELECT version.*,resource.metadata_json "
                "FROM publication_review_snapshots AS snapshot "
                "JOIN publication_snapshot_resources AS resource "
                "ON resource.snapshot_id=snapshot.id "
                "AND resource.resource_kind='DOCUMENT_VERSION' "
                "JOIN document_versions AS version ON version.id=resource.resource_id "
                "WHERE snapshot.subject_kind='COURSE' AND snapshot.request_id=? "
                "AND resource.resource_id=?",
                (request_id, version_id),
            ).fetchone()
        if row is None:
            raise ApiError(404, "PUBLICATION_RESOURCE_NOT_FOUND", "The review file was not found.")
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

    def withdraw(
        self,
        course_id: str,
        *,
        owner_user_id: str,
        is_admin: bool,
    ) -> None:
        course = require_course_access(
            self.database,
            course_id,
            owner_user_id=owner_user_id,
            is_admin=is_admin,
        )
        if course["course_type"] != "user" or course["owner_user_id"] != owner_user_id:
            raise ApiError(404, "COURSE_NOT_FOUND", "The course was not found.")
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            statuses = "('pending','approved')" if self.database.v3_enabled else "('pending')"
            active = connection.execute(
                "SELECT id,status FROM course_publication_requests "
                f"WHERE course_id=? AND owner_user_id=? AND status IN {statuses} "
                "ORDER BY submitted_at DESC LIMIT 1",
                (course_id, owner_user_id),
            ).fetchone()
            if active is None:
                raise ApiError(404, "PUBLICATION_NOT_FOUND", "Active request was not found.")
            connection.execute(
                "UPDATE course_publication_requests SET status='withdrawn' WHERE id=?",
                (active["id"],),
            )
            connection.execute(
                "UPDATE courses SET publication_status='private',visibility='private',"
                "published_at=NULL,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE id=?",
                (course_id,),
            )
            if self.database.v3_enabled:
                withdraw_release(
                    connection,
                    subject_kind="COURSE",
                    request_id=active["id"],
                    actor_user_id=owner_user_id,
                )
                record_audit_event(
                    connection,
                    subject_kind="COURSE",
                    request_id=active["id"],
                    actor_user_id=owner_user_id,
                    action="WITHDRAWN",
                )

    def review(
        self,
        request_id: str,
        payload: PublicationReview,
        *,
        reviewer_user_id: str,
    ) -> PublicationRequest:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._select_request(connection, request_id)
            if row is None or row["status"] != "pending":
                raise ApiError(404, "PUBLICATION_NOT_FOUND", "Pending request was not found.")
            if self.database.v3_enabled:
                if row["snapshot_id"] is None:
                    raise ApiError(
                        409,
                        "PUBLICATION_SNAPSHOT_REQUIRED",
                        "Withdraw this legacy request and submit a version-bound review snapshot.",
                    )
                if row["owner_user_id"] == reviewer_user_id:
                    raise ApiError(
                        409,
                        "INDEPENDENT_REVIEW_REQUIRED",
                        "The submitting owner cannot approve their own publication.",
                    )
                summary, resources = course_snapshot_payload(connection, row["course_id"])
                if snapshot_hash(summary, resources) != row["snapshot_hash"]:
                    raise ApiError(
                        409,
                        "PUBLICATION_SNAPSHOT_STALE",
                        "The course no longer matches the submitted review snapshot.",
                    )
            approved = payload.decision == "approve"
            connection.execute(
                """
                UPDATE course_publication_requests
                SET status=?, reviewed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                    reviewed_by_user_id=?, review_note=?
                WHERE id=?
                """,
                (
                    "approved" if approved else "rejected",
                    reviewer_user_id,
                    payload.review_note.strip(),
                    request_id,
                ),
            )
            connection.execute(
                """
                UPDATE courses
                SET publication_status=?, visibility=?,
                    published_at=CASE WHEN ?
                        THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NULL END,
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE id=?
                """,
                (
                    "published" if approved else "rejected",
                    "public" if approved else "private",
                    approved,
                    row["course_id"],
                ),
            )
            if self.database.v3_enabled:
                if approved:
                    activate_release(
                        connection,
                        subject_kind="COURSE",
                        request_id=request_id,
                        snapshot_id=row["snapshot_id"],
                    )
                record_audit_event(
                    connection,
                    subject_kind="COURSE",
                    request_id=request_id,
                    actor_user_id=reviewer_user_id,
                    action="APPROVED" if approved else "REJECTED",
                )
            reviewed = self._select_request(connection, request_id)
        assert reviewed is not None
        return self._request(reviewed)

    def unpublish(self, course_id: str, *, actor_user_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            workspace_filter = (
                " AND NOT EXISTS (SELECT 1 FROM learning_workspaces "
                "WHERE private_course_id=courses.id)"
                if self.database.v3_enabled
                else ""
            )
            row = connection.execute(
                "SELECT course_type,publication_status FROM courses WHERE id=?"
                + workspace_filter,
                (course_id,),
            ).fetchone()
            if row is None or row["course_type"] != "user":
                raise ApiError(404, "COURSE_NOT_FOUND", "The community course was not found.")
            request = connection.execute(
                "SELECT id FROM course_publication_requests "
                "WHERE course_id=? AND status='approved' ORDER BY submitted_at DESC LIMIT 1",
                (course_id,),
            ).fetchone()
            connection.execute(
                "UPDATE courses SET publication_status='private',visibility='private',"
                "published_at=NULL,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE id=?",
                (course_id,),
            )
            if self.database.v3_enabled and request is not None:
                connection.execute(
                    "UPDATE course_publication_requests SET status='withdrawn' WHERE id=?",
                    (request["id"],),
                )
                withdraw_release(
                    connection,
                    subject_kind="COURSE",
                    request_id=request["id"],
                    actor_user_id=actor_user_id,
                )
                record_audit_event(
                    connection,
                    subject_kind="COURSE",
                    request_id=request["id"],
                    actor_user_id=actor_user_id,
                    action="UNPUBLISHED",
                )
