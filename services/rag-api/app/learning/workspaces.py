import hashlib
import sqlite3
from pathlib import Path
from typing import cast
from uuid import uuid4

from app.db import Database
from app.errors import ApiError
from app.course_access import check_course_content_access


def accessible_course(database: Database, course_id: str, owner: str) -> sqlite3.Row:
    # Content administration is not permission to read another user's private workspace.
    with database.connect() as db:
        row = db.execute(
            "SELECT * FROM courses WHERE id=? AND (owner_user_id=? OR visibility='public')",
            (course_id, owner),
        ).fetchone()
    if row is None:
        raise ApiError(404, "COURSE_NOT_FOUND", "The course was not found.")
    check_course_content_access(database,row,owner)
    return cast(sqlite3.Row, row)


def workspace_for(database: Database, workspace_id: str, owner: str) -> sqlite3.Row:
    with database.connect() as db:
        row = db.execute(
            "SELECT * FROM learning_workspaces WHERE id=? AND owner_user_id=?",
            (workspace_id, owner),
        ).fetchone()
    if row is None:
        raise ApiError(404, "WORKSPACE_NOT_FOUND", "The workspace was not found.")
    accessible_course(database, row["course_id"], owner)
    return cast(sqlite3.Row, row)


def join_course(database: Database, course_id: str, owner: str, limit: int) -> dict[str, object]:
    accessible_course(database, course_id, owner)
    with database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM learning_workspaces WHERE course_id=? AND owner_user_id=?",
            (course_id, owner),
        ).fetchone()
        if row is None:
            if (
                db.execute(
                    "SELECT COUNT(*) FROM learning_workspaces WHERE owner_user_id=?", (owner,)
                ).fetchone()[0]
                >= limit
            ):
                raise ApiError(429, "WORKSPACE_QUOTA", "Workspace quota reached.")
            if db.execute(
                "SELECT 1 FROM learning_workspaces WHERE private_course_id=?", (course_id,)
            ).fetchone():
                raise ApiError(422, "INVALID_COURSE", "Cannot enroll a private storage corpus.")
            identifier, corpus = str(uuid4()), "ws-" + uuid4().hex
            db.execute(
                "INSERT INTO "
                "courses(id,name,owner_user_id,course_type,visibility,publication_status)"
                " VALUES(?,?,?,'user','private','private')",
                (corpus, "My workspace files", owner),
            )
            db.execute(
                "INSERT INTO learning_workspaces(id,owner_user_id,course_id,private_course_id)"
                " VALUES(?,?,?,?)",
                (identifier, owner, course_id, corpus),
            )
            row = db.execute(
                "SELECT * FROM learning_workspaces WHERE id=?", (identifier,)
            ).fetchone()
        return dict(row)


def document_for(database: Database, document_id: str, owner: str) -> sqlite3.Row:
    with database.connect() as db:
        row = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        workspace = db.execute(
            "SELECT * FROM learning_workspaces WHERE private_course_id="
            "(SELECT course_id FROM documents WHERE id=?)",
            (document_id,),
        ).fetchone()
    if row is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "The document was not found.")
    try:
        if workspace is not None:
            workspace_for(database, workspace["id"], owner)
        accessible_course(database, row["course_id"], owner)
    except ApiError as error:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "The document was not found.") from error
    return cast(sqlite3.Row, row)


def current_document_version(
    database: Database, document_id: str, owner: str
) -> sqlite3.Row:
    document_for(database, document_id, owner)
    with database.connect() as db:
        row = db.execute(
            "SELECT * FROM document_versions WHERE document_id=? "
            "ORDER BY version DESC LIMIT 1",
            (document_id,),
        ).fetchone()
    if row is None:
        raise ApiError(
            409,
            "DOCUMENT_VERSION_UNAVAILABLE",
            "The document source version is unavailable.",
        )
    try:
        _authorize_document_version(database, row, owner)
    except ApiError as error:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "The document was not found.") from error
    return cast(sqlite3.Row, row)


def _authorize_document_version(
    database: Database, version: sqlite3.Row, owner: str
) -> None:
    if version["source_scope"] == "OFFICIAL":
        accessible_course(database, version["course_id"], owner)
        return
    if version["owner_user_id"] == owner:
        return
    if version["source_scope"] == "OWNER_COURSE":
        try:
            course = accessible_course(database, version["course_id"], owner)
        except ApiError as error:
            raise ApiError(
                404,
                "DOCUMENT_VERSION_NOT_FOUND",
                "The source version was not found.",
            ) from error
        if course["visibility"] == "public" and course["publication_status"] == "published":
            return
    raise ApiError(404, "DOCUMENT_VERSION_NOT_FOUND", "The source version was not found.")


def document_version_for(
    database: Database, version_id: str, owner: str
) -> sqlite3.Row:
    with database.connect() as db:
        row = db.execute(
            "SELECT * FROM document_versions WHERE id=?", (version_id,)
        ).fetchone()
    if row is None:
        raise ApiError(404, "DOCUMENT_VERSION_NOT_FOUND", "The source version was not found.")
    _authorize_document_version(database, row, owner)
    return cast(sqlite3.Row, row)


def artifact_for(database: Database, artifact_id: str, owner: str) -> sqlite3.Row:
    with database.connect() as db:
        row = db.execute(
            "SELECT * FROM derived_artifacts WHERE id=?", (artifact_id,)
        ).fetchone()
    if row is None:
        raise ApiError(404, "ARTIFACT_NOT_FOUND", "The derived artifact was not found.")
    try:
        document_version_for(database, row["document_version_id"], owner)
    except ApiError as error:
        raise ApiError(
            404,
            "ARTIFACT_NOT_FOUND",
            "The derived artifact was not found.",
        ) from error
    return cast(sqlite3.Row, row)


def stored_file_path(database: Database, stored_path: str) -> Path | None:
    path = Path(stored_path)
    root = database.upload_dir.resolve()
    # No client paths; no symlinks escaping storage; legacy absent originals stay absent.
    if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
        return None
    return path.resolve()


def sized_file_path(
    database: Database, stored_path: str | None, byte_size: int | None
) -> Path | None:
    if stored_path is None or byte_size is None:
        return None
    path = stored_file_path(database, stored_path)
    return path if path is not None and path.stat().st_size == byte_size else None


def _verified_path(
    database: Database,
    stored_path: str,
    byte_size: int,
    expected_sha256: str,
) -> Path | None:
    path = sized_file_path(database, stored_path, byte_size)
    if path is None:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return path if digest.hexdigest() == expected_sha256 else None


def original_path(database: Database, document_version: sqlite3.Row) -> Path | None:
    return _verified_path(
        database,
        document_version["stored_path"],
        document_version["byte_size"],
        document_version["sha256"],
    )


def artifact_path(database: Database, artifact: sqlite3.Row) -> Path | None:
    if artifact["status"] != "READY" or not artifact["stored_path"]:
        return None
    return _verified_path(
        database,
        artifact["stored_path"],
        artifact["byte_size"],
        artifact["sha256"],
    )


def valid_preview_artifact(database: Database, version_id: str) -> sqlite3.Row | None:
    with database.connect() as db:
        rows = db.execute(
            "SELECT * FROM derived_artifacts "
            "WHERE document_version_id=? AND kind='PREVIEW_PDF' AND status='READY' "
            "ORDER BY created_at DESC",
            (version_id,),
        ).fetchall()
    return next((row for row in rows if artifact_path(database, row) is not None), None)
