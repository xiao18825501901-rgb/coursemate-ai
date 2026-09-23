"""A course's display type and student-verification gate, from the row to what the shell reads.

Migration 025 states the policy: "official courses display as campus courses and require
verification; user courses display as private". Its backfill enforces that for rows that existed
when the column was added — but a course created *afterwards* kept `display_type=NULL` and
`requires_student_verification=0`, which is the column disagreeing with the policy.

These tests pin the created values **and** the effect, and they pin the reason this was never an
access-control hole: every gate ORs the flag with `display_type=='campus'` or
`course_type=='official'`. A test that only checked the column would not have shown that, and a test
that only checked the gate would not have shown the inconsistency.
"""

from __future__ import annotations

import pathlib
import sqlite3
from contextlib import ExitStack

from app.config import Settings
from app.db import Database
from app.models import CourseCreate, PublicationStatus
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.services.ingestion import IngestionService

_STACKS: list[ExitStack] = []


def service(
    tmp_path: pathlib.Path, *, v3_enabled: bool = True
) -> tuple[IngestionService, sqlite3.Connection]:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        app_env="test",
        v3_enabled=v3_enabled,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )
    database = Database(settings)
    database.initialize()
    stack = ExitStack()
    _STACKS.append(stack)
    connection = stack.enter_context(database.connect())
    connection.isolation_level = None
    return IngestionService(database, settings, DeterministicEmbeddingProvider()), connection


def course_row(connection: sqlite3.Connection, course_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    assert row is not None, course_id
    return row


def shell_view(connection: sqlite3.Connection, course_id: str) -> dict[str, object]:
    """The fields the shell actually reads, derived the way `ui_extension.domain` derives them.

    The derivation matters: `display_type` falls back to `campus` for an official course when the
    column is empty, and the shell's gate is `display_type == 'campus' || requires_...`.
    """
    row = course_row(connection, course_id)
    official = row["course_type"] == "official"
    display_type = row["display_type"] or ("campus" if official else "private")
    requires = bool(row["requires_student_verification"])
    return {
        "official": official,
        "display_type": display_type,
        "requires_student_verification": requires,
        "gated": display_type == "campus" or requires,
    }


def test_an_official_course_is_created_as_campus_and_gated(tmp_path) -> None:
    ingestor, connection = service(tmp_path)
    ingestor.create_course(CourseCreate(id="official-1", name="Official"), is_admin=True)

    row = course_row(connection, "official-1")
    assert row["course_type"] == "official"
    assert row["display_type"] == "campus"
    assert row["requires_student_verification"] == 1
    assert shell_view(connection, "official-1") == {
        "official": True,
        "display_type": "campus",
        "requires_student_verification": True,
        "gated": True,
    }


def test_a_user_course_is_created_private_and_not_gated_by_the_campus_rule(tmp_path) -> None:
    ingestor, connection = service(tmp_path)
    ingestor.create_course(
        CourseCreate(id="mine-1", name="Mine"), owner_user_id="user-1", is_admin=False
    )

    row = course_row(connection, "mine-1")
    assert row["course_type"] == "user"
    assert row["owner_user_id"] == "user-1"
    assert row["display_type"] == "private"
    assert row["requires_student_verification"] == 0
    assert shell_view(connection, "mine-1")["gated"] is False


def test_an_unpublished_campus_course_is_still_labelled_campus_and_gated(tmp_path) -> None:
    """The campus import creates its course private; the label and the gate are not visibility."""
    ingestor, connection = service(tmp_path)
    ingestor.create_course(
        CourseCreate(id="campus-1", name="Campus"),
        is_admin=True,
        publication_status=PublicationStatus.PRIVATE,
    )

    row = course_row(connection, "campus-1")
    assert (row["visibility"], row["publication_status"]) == ("private", "private")
    assert row["display_type"] == "campus"
    assert row["requires_student_verification"] == 1
    # Private and unpublished, yet still gated: visibility hides it, the gate decides who may read
    # it once it is visible.
    assert shell_view(connection, "campus-1")["gated"] is True


def test_creating_a_course_does_not_rewrite_existing_rows(tmp_path) -> None:
    """No backfill: the migration's policy applies to new courses, and history is left alone."""
    ingestor, connection = service(tmp_path)
    ingestor.create_course(CourseCreate(id="first", name="First"), is_admin=True)
    before = dict(course_row(connection, "first"))

    ingestor.create_course(
        CourseCreate(id="second", name="Second"), owner_user_id="user-1", is_admin=False
    )
    ingestor.create_course(CourseCreate(id="third", name="Third"), is_admin=True)

    assert dict(course_row(connection, "first")) == before


def test_a_legacy_row_without_the_columns_values_is_still_gated_by_the_fallback(tmp_path) -> None:
    """Why the old inconsistency was never an access-control hole.

    A row created before this change — `display_type` NULL, flag 0 — is still reported as campus by
    the shell's derivation, which is exactly what the authorizer in `ui_extension.mount` ORs with
    the raw flag. Removing the fallback would turn the inconsistency into a real gap, so it is
    pinned here rather than described in prose.
    """
    ingestor, connection = service(tmp_path)
    ingestor.create_course(CourseCreate(id="legacy", name="Legacy"), is_admin=True)
    connection.execute(
        "UPDATE courses SET display_type=NULL, requires_student_verification=0 WHERE id='legacy'"
    )

    view = shell_view(connection, "legacy")
    assert view["display_type"] == "campus", "the fallback is what keeps the legacy row gated"
    assert view["gated"] is True


def test_every_official_course_requires_verification_and_every_user_course_does_not(
    tmp_path,
) -> None:
    """The invariant migration 025 states, checked over every row this code can create."""
    ingestor, connection = service(tmp_path)
    ingestor.create_course(CourseCreate(id="official-a", name="A"), is_admin=True)
    ingestor.create_course(
        CourseCreate(id="official-b", name="B"),
        is_admin=True,
        publication_status=PublicationStatus.PRIVATE,
    )
    ingestor.create_course(
        CourseCreate(id="user-a", name="C"), owner_user_id="user-1", is_admin=False
    )

    rows = connection.execute(
        "SELECT course_type, display_type, requires_student_verification FROM courses"
    ).fetchall()
    for row in rows:
        if row["course_type"] == "official":
            assert row["display_type"] == "campus", row["display_type"]
            assert row["requires_student_verification"] == 1
        else:
            assert row["display_type"] == "private", row["display_type"]
            assert row["requires_student_verification"] == 0


def test_the_created_course_object_reports_what_the_row_says(tmp_path) -> None:
    """The API returns the `Course` model, so the response must not disagree with the row."""
    ingestor, connection = service(tmp_path)
    created = ingestor.create_course(CourseCreate(id="official-c", name="C"), is_admin=True)

    assert created.display_type == "campus"
    assert created.requires_student_verification is True
    assert (
        created.model_dump()["display_type"] == course_row(connection, "official-c")["display_type"]
    )


def test_a_deployment_without_the_v3_schema_can_still_create_courses(tmp_path) -> None:
    """The regression the full suite caught in round 74.

    `display_type` and `requires_student_verification` arrive with the V3 schema, so a deployment
    without it does not have the columns. Naming them unconditionally in the INSERT broke every
    non-V3 deployment — 54 tests — with "table courses has no column named display_type". A
    deployment without V3 has no campus feature to label, so the honest behaviour is to write the
    columns when the schema has them and not to name them when it does not.
    """
    ingestor, connection = service(tmp_path, v3_enabled=False)

    columns = {row["name"] for row in connection.execute("PRAGMA table_info(courses)")}
    assert "display_type" not in columns, "this test is only meaningful without the V3 columns"

    official = ingestor.create_course(CourseCreate(id="official-plain", name="P"), is_admin=True)
    mine = ingestor.create_course(
        CourseCreate(id="mine-plain", name="M"), owner_user_id="user-1", is_admin=False
    )

    assert official.course_type == "official" and official.visibility == "public"
    assert mine.course_type == "user" and mine.visibility == "private"
    assert connection.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 2
    # No column, so no claim about it: the model reports its own default rather than a value the
    # database never stored.
    assert official.display_type is None
    assert official.requires_student_verification is False
