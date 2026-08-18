import sqlite3
from uuid import uuid4

from app.course_access import require_course_access
from app.db import Database
from app.errors import ApiError
from app.models import PublicationRequest, PublicationReview, PublicationSubmit


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
            active = connection.execute(
                "SELECT 1 FROM course_publication_requests "
                "WHERE course_id = ? AND status = 'pending'",
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
            connection.execute(
                "UPDATE courses SET publication_status = 'pending', visibility = 'private', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                (course_id,),
            )
            row = self._select_request(connection, request_id)
        assert row is not None
        return self._request(row)

    @staticmethod
    def _select_request(
        connection: sqlite3.Connection, request_id: str
    ) -> sqlite3.Row | None:
        row: sqlite3.Row | None = connection.execute(
            """
            SELECT course_publication_requests.*, courses.name AS course_name
            FROM course_publication_requests
            JOIN courses ON courses.id = course_publication_requests.course_id
            WHERE course_publication_requests.id = ?
            """,
            (request_id,),
        ).fetchone()
        return row

    def list_pending(self) -> list[PublicationRequest]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT course_publication_requests.*, courses.name AS course_name
                FROM course_publication_requests
                JOIN courses ON courses.id = course_publication_requests.course_id
                WHERE course_publication_requests.status = 'pending'
                ORDER BY submitted_at, course_publication_requests.id
                """
            ).fetchall()
        return [self._request(row) for row in rows]

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
            pending = connection.execute(
                "SELECT id FROM course_publication_requests "
                "WHERE course_id = ? AND owner_user_id = ? AND status = 'pending'",
                (course_id, owner_user_id),
            ).fetchone()
            if pending is None:
                raise ApiError(404, "PUBLICATION_NOT_FOUND", "Pending request was not found.")
            connection.execute(
                "UPDATE course_publication_requests SET status = 'withdrawn' WHERE id = ?",
                (pending["id"],),
            )
            connection.execute(
                "UPDATE courses SET publication_status = 'private', visibility = 'private', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                (course_id,),
            )

    def review(
        self,
        request_id: str,
        payload: PublicationReview,
        *,
        reviewer_user_id: str,
    ) -> PublicationRequest:
        with self.database.connect() as connection:
            row = self._select_request(connection, request_id)
            if row is None or row["status"] != "pending":
                raise ApiError(404, "PUBLICATION_NOT_FOUND", "Pending request was not found.")
            approved = payload.decision == "approve"
            connection.execute(
                """
                UPDATE course_publication_requests
                SET status = ?, reviewed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    reviewed_by_user_id = ?, review_note = ?
                WHERE id = ?
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
                SET publication_status = ?, visibility = ?,
                    published_at = CASE WHEN ?
                        THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now') ELSE NULL END,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (
                    "published" if approved else "rejected",
                    "public" if approved else "private",
                    approved,
                    row["course_id"],
                ),
            )
            reviewed = self._select_request(connection, request_id)
        assert reviewed is not None
        return self._request(reviewed)

    def unpublish(self, course_id: str) -> None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT course_type, publication_status FROM courses WHERE id = ?",
                (course_id,),
            ).fetchone()
            if row is None or row["course_type"] != "user":
                raise ApiError(404, "COURSE_NOT_FOUND", "The community course was not found.")
            connection.execute(
                "UPDATE courses SET publication_status = 'private', visibility = 'private', "
                "published_at = NULL, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE id = ?",
                (course_id,),
            )
