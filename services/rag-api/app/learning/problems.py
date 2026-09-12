import sqlite3
from typing import Any, Literal, cast

from app.db import Database
from app.errors import ApiError
from app.learning.previews import IMAGE_MEDIA_TYPES
from app.learning.provider import ProviderImage
from app.learning.workspaces import document_version_for, original_path, workspace_for

ProblemIndexScope = Literal["official", "mine", "union"]


class ProblemRepository:
    """Authorized question index and normalized problem persistence helpers."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _access_sql(scope: ProblemIndexScope) -> tuple[str, list[str]]:
        official = (
            "(entry.course_id = ? AND ("
            "version.source_scope = 'OFFICIAL' OR version.owner_user_id = ? OR "
            "(version.source_scope = 'OWNER_COURSE' AND course.visibility = 'public' "
            "AND course.publication_status = 'published')))"
        )
        private = (
            "(entry.course_id = ? AND version.source_scope = 'WORKSPACE_PRIVATE' "
            "AND version.owner_user_id = ?)"
        )
        if scope == "official":
            return official, ["course_id", "owner_user_id"]
        if scope == "mine":
            return private, ["private_course_id", "owner_user_id"]
        return f"({official} OR {private})", [
            "course_id",
            "owner_user_id",
            "private_course_id",
            "owner_user_id",
        ]

    @staticmethod
    def _payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "chunk_id": row["chunk_id"],
            "document_id": row["document_id"],
            "document_version_id": row["document_version_id"],
            "document_sha256": row["document_sha256"],
            "filename": row["filename"],
            "source_scope": row["source_scope"],
            "question_number": row["question_number"],
            "question_part": row["question_part"],
            "heading_path": row["heading_path"],
            "locator_type": row["locator_type"],
            "locator_value": row["locator_value"],
            "question_text": row["question_text"],
        }

    def list_index(
        self,
        workspace_id: str,
        owner: str,
        *,
        scope: ProblemIndexScope,
        query: str | None,
        document_version_id: str | None,
        filename: str | None,
        question_number: str | None,
        question_part: str | None,
        locator_type: str | None,
        locator_value: str | None,
        limit: int,
    ) -> dict[str, Any]:
        workspace = workspace_for(self.database, workspace_id, owner)
        access_sql, access_fields = self._access_sql(scope)
        values: list[object] = [workspace[field] for field in access_fields]
        conditions = [access_sql]
        exact_filters = {
            "entry.document_version_id": document_version_id,
            "version.filename COLLATE NOCASE": filename,
            "entry.question_number COLLATE NOCASE": question_number,
            "entry.question_part COLLATE NOCASE": question_part,
            "entry.locator_type COLLATE NOCASE": locator_type,
            "entry.locator_value COLLATE NOCASE": locator_value,
        }
        for column, value in exact_filters.items():
            if value is not None:
                conditions.append(f"{column} = ?")
                values.append(value.strip())
        if query is not None and query.strip():
            conditions.append("entry.question_text LIKE ? ESCAPE '\\' COLLATE NOCASE")
            escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%")
            escaped = escaped.replace("_", "\\_")
            values.append(f"%{escaped}%")
        where = " AND ".join(conditions)
        with self.database.connect() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM problem_index_entries AS entry "
                    "JOIN document_versions AS version "
                    "ON version.id = entry.document_version_id "
                    "JOIN courses AS course ON course.id = version.course_id "
                    f"WHERE {where}",
                    values,
                ).fetchone()[0]
            )
            rows = connection.execute(
                "SELECT entry.*,version.document_id,version.filename,"
                "version.sha256 AS document_sha256,"
                "version.source_scope FROM problem_index_entries AS entry "
                "JOIN document_versions AS version "
                "ON version.id = entry.document_version_id "
                "JOIN courses AS course ON course.id = version.course_id "
                f"WHERE {where} ORDER BY version.filename COLLATE NOCASE,entry.rowid LIMIT ?",
                [*values, limit],
            ).fetchall()
        # Defense in depth: the shared document-version authorizer remains the final gate.
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                document_version_for(self.database, row["document_version_id"], owner)
            except ApiError:
                continue
            items.append(self._payload(row))
        return {"items": items, "total": total if len(items) == len(rows) else len(items)}

    def index_entry(
        self, workspace_id: str, owner: str, entry_id: str
    ) -> dict[str, Any]:
        workspace = workspace_for(self.database, workspace_id, owner)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT entry.*,version.document_id,version.filename,"
                "version.sha256 AS document_sha256,"
                "version.source_scope,version.owner_user_id,course.visibility,"
                "course.publication_status FROM problem_index_entries AS entry "
                "JOIN document_versions AS version "
                "ON version.id=entry.document_version_id "
                "JOIN courses AS course ON course.id=version.course_id "
                "WHERE entry.id=?",
                (entry_id,),
            ).fetchone()
        if row is None:
            raise ApiError(404, "PROBLEM_INDEX_NOT_FOUND", "The indexed question was not found.")
        is_private = (
            row["course_id"] == workspace["private_course_id"]
            and row["source_scope"] == "WORKSPACE_PRIVATE"
            and row["owner_user_id"] == owner
        )
        is_course = row["course_id"] == workspace["course_id"] and (
            row["source_scope"] == "OFFICIAL"
            or row["owner_user_id"] == owner
            or (
                row["source_scope"] == "OWNER_COURSE"
                and row["visibility"] == "public"
                and row["publication_status"] == "published"
            )
        )
        if not (is_private or is_course):
            raise ApiError(404, "PROBLEM_INDEX_NOT_FOUND", "The indexed question was not found.")
        try:
            document_version_for(self.database, row["document_version_id"], owner)
        except ApiError as error:
            raise ApiError(
                404, "PROBLEM_INDEX_NOT_FOUND", "The indexed question was not found."
            ) from error
        return self._payload(row)

    def image_input(
        self,
        workspace_id: str,
        owner: str,
        version_id: str,
        *,
        max_bytes: int,
    ) -> tuple[ProviderImage, dict[str, Any]]:
        workspace = workspace_for(self.database, workspace_id, owner)
        try:
            version = document_version_for(self.database, version_id, owner)
        except ApiError as error:
            raise ApiError(404, "PROBLEM_IMAGE_NOT_FOUND", "The image was not found.") from error
        is_private = (
            version["course_id"] == workspace["private_course_id"]
            and version["source_scope"] == "WORKSPACE_PRIVATE"
            and version["owner_user_id"] == owner
        )
        is_course = version["course_id"] == workspace["course_id"] and (
            version["source_scope"] == "OFFICIAL" or version["owner_user_id"] == owner
        )
        media_type = IMAGE_MEDIA_TYPES.get(version["extension"])
        if (
            not (is_private or is_course)
            or media_type not in {"image/png", "image/jpeg"}
        ):
            raise ApiError(404, "PROBLEM_IMAGE_NOT_FOUND", "The image was not found.")
        if version["byte_size"] > max_bytes:
            raise ApiError(
                413,
                "IMAGE_MODEL_LIMIT",
                "The image exceeds the bounded model-input size.",
                details={"limitBytes": max_bytes},
            )
        path = original_path(self.database, version)
        if path is None:
            raise ApiError(410, "SOURCE_UNAVAILABLE", "The image source is unavailable.")
        image = ProviderImage(
            media_type=cast(Literal["image/png", "image/jpeg"], media_type),
            content=path.read_bytes(),
            sha256=version["sha256"],
            source_version_id=version["id"],
        )
        return image, {
            "document_version_id": version["id"],
            "document_sha256": version["sha256"],
            "filename": version["filename"],
            "media_type": media_type,
            "byte_size": version["byte_size"],
        }
