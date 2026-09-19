import sqlite3
from typing import cast

from app.db import Database
from app.errors import ApiError


def require_course_access(
    database: Database,
    course_id: str,
    *,
    owner_user_id: str | None,
    is_admin: bool,
    write: bool = False,
    content: bool = True,
) -> sqlite3.Row:
    """Return a course only when the caller may use it; hide private-course existence."""

    with database.connect() as connection:
        row = connection.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        workspace = (
            connection.execute(
                "SELECT owner_user_id,course_id FROM learning_workspaces WHERE private_course_id=?",
                (course_id,),
            ).fetchone()
            if database.v3_enabled
            else None
        )
    if workspace is not None and workspace["owner_user_id"] != owner_user_id:
        raise ApiError(404, "COURSE_NOT_FOUND", "The course was not found.")
    allowed = row is not None and (
        row["owner_user_id"] == owner_user_id
        or (is_admin and row["course_type"] == "official")
        or (not write and row["visibility"] == "public")
    )
    if not allowed:
        raise ApiError(404, "COURSE_NOT_FOUND", "The course was not found.")
    if content:
        check_course_content_access(database,row,owner_user_id,is_admin=is_admin)
        if workspace is not None:
            with database.connect() as connection:
                parent=connection.execute('SELECT * FROM courses WHERE id=?',(workspace['course_id'],)).fetchone()
            if parent is not None:
                check_course_content_access(database,parent,owner_user_id,is_admin=is_admin)
    if write and row["course_type"] == "user" and row["publication_status"] == "pending":
        raise ApiError(
            409,
            "PUBLICATION_REVIEW_LOCKED",
            "Withdraw the pending review before changing its version-bound content.",
        )
    if write and row["course_type"] == "user" and row["publication_status"] == "published":
        raise ApiError(
            409,
            "PUBLISHED_COURSE_LOCKED",
            "Unpublish this course before changing its reviewed content or settings.",
        )
    return cast(sqlite3.Row, row)


def check_course_content_access(database, course, owner, *, is_admin=False):
    """One injected campus policy for legacy services and the mounted shell."""
    policy=getattr(database,'course_content_authorizer',None)
    if policy is not None:
        policy(course,owner,is_admin)
