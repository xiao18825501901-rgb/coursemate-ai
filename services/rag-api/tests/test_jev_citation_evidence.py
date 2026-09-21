"""DocumentEvidenceResolver: the production layer-1 evidence resolver.

Runs against a real migrated V3 database (``Database.initialize``) and inserts the
minimum rows — courses, documents, document versions, chunks — to prove the
authorization-critical semantics: an authorized document resolves to its text;
another user's private document is ``unauthorized`` with empty text; an unknown
document and a mismatched version are ``missing``; chunk/page/section locators
resolve to the narrowest chunk; an unresolvable locator falls back to the document
text; the text bound is enforced; and the resolver writes nothing.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.db import Database
from app.jev.citation_evidence import DocumentEvidenceResolver

_OFFICIAL_V1 = "Official page one text.\n\nOfficial page two text."


def make_database(tmp_path: Path) -> Database:
    database = Database(
        Settings(
            database_path=tmp_path / "evidence.sqlite3",
            upload_dir=tmp_path / "uploads",
            v3_enabled=True,
        )
    )
    database.initialize()
    return database


def seed(database: Database) -> None:
    """Insert the minimum authorized corpus: two official courses, two workspaces."""
    with database.connect() as connection:
        connection.executemany(
            "INSERT INTO courses (id, name, course_type, owner_user_id, visibility) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                ("course-official", "Official", "official", None, "public"),
                ("course-other", "Other", "official", None, "public"),
                ("ws-corpus-a", "Workspace A", "user", "user-a", "private"),
                ("ws-corpus-b", "Workspace B", "user", "user-b", "private"),
            ],
        )
        connection.executemany(
            "INSERT INTO learning_workspaces (id, owner_user_id, course_id, private_course_id) "
            "VALUES (?, ?, ?, ?)",
            [
                ("ws-a", "user-a", "course-official", "ws-corpus-a"),
                ("ws-b", "user-b", "course-official", "ws-corpus-b"),
            ],
        )
        connection.executemany(
            "INSERT INTO documents (id, course_id, filename, stored_path, media_type, "
            "extension, sha256, byte_size, status) "
            "VALUES (?, ?, ?, ?, 'text/plain', '.txt', ?, ?, 'ready')",
            [
                ("doc-official", "course-official", "official.txt", "official.txt", "a" * 64, 12),
                ("doc-other", "course-other", "other.txt", "other.txt", "c" * 64, 12),
                ("doc-private-a", "ws-corpus-a", "private-a.txt", "private-a.txt", "d" * 64, 12),
                ("doc-private-b", "ws-corpus-b", "private-b.txt", "private-b.txt", "e" * 64, 12),
                ("doc-long", "course-official", "long.txt", "long.txt", "f" * 64, 6000),
            ],
        )
        connection.executemany(
            "INSERT INTO chunks (id, document_id, course_id, ordinal, content, locator_type, "
            "locator_value, section, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[1.0]')",
            [
                (
                    "chunk-official-p1",
                    "doc-official",
                    "course-official",
                    0,
                    "Official page one text.",
                    "page",
                    "1",
                    "Page 1",
                ),
                (
                    "chunk-official-p2",
                    "doc-official",
                    "course-official",
                    1,
                    "Official page two text.",
                    "page",
                    "2",
                    "Page 2",
                ),
                (
                    "chunk-other",
                    "doc-other",
                    "course-other",
                    0,
                    "Other course text.",
                    "page",
                    "1",
                    "Page 1",
                ),
                (
                    "chunk-private-a",
                    "doc-private-a",
                    "ws-corpus-a",
                    0,
                    "Private A text.",
                    "page",
                    "1",
                    "Page 1",
                ),
                (
                    "chunk-private-b",
                    "doc-private-b",
                    "ws-corpus-b",
                    0,
                    "Private B text.",
                    "page",
                    "1",
                    "Page 1",
                ),
                (
                    "chunk-long",
                    "doc-long",
                    "course-official",
                    0,
                    "x" * 6000,
                    "page",
                    "1",
                    "Page 1",
                ),
            ],
        )


def test_authorized_official_document_resolves_full_text(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    seed(database)
    resolver = DocumentEvidenceResolver(
        database, owner_user_id="user-a", course_id="course-official"
    )

    evidence = resolver.resolve(document_id="doc-official", version=None, location=None)

    assert evidence.status == "ok"
    assert evidence.text == _OFFICIAL_V1
    assert evidence.version == "1"
    assert evidence.span_id == "doc-official"


def test_chunk_id_locator_resolves_that_chunk(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    seed(database)
    resolver = DocumentEvidenceResolver(
        database, owner_user_id="user-a", course_id="course-official"
    )

    evidence = resolver.resolve(
        document_id="doc-official", version=None, location="chunk-official-p2"
    )

    assert evidence.status == "ok"
    assert evidence.text == "Official page two text."
    assert evidence.span_id == "chunk-official-p2"


def test_page_locator_resolves_page_chunk(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    seed(database)
    resolver = DocumentEvidenceResolver(
        database, owner_user_id="user-a", course_id="course-official"
    )

    evidence = resolver.resolve(document_id="doc-official", version=None, location="page:2")

    assert evidence.status == "ok"
    assert evidence.text == "Official page two text."
    assert evidence.span_id == "chunk-official-p2"


def test_section_label_resolves_section_chunk(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    seed(database)
    resolver = DocumentEvidenceResolver(
        database, owner_user_id="user-a", course_id="course-official"
    )

    evidence = resolver.resolve(document_id="doc-official", version=None, location="Page 2")

    assert evidence.status == "ok"
    assert evidence.text == "Official page two text."


def test_unresolvable_locator_falls_back_to_document_text(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    seed(database)
    resolver = DocumentEvidenceResolver(
        database, owner_user_id="user-a", course_id="course-official"
    )

    evidence = resolver.resolve(
        document_id="doc-official", version=None, location="no-such-chunk"
    )

    assert evidence.status == "ok"
    assert evidence.text == _OFFICIAL_V1


def test_another_users_private_document_is_unauthorized(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    seed(database)
    resolver = DocumentEvidenceResolver(database, owner_user_id="user-b")

    evidence = resolver.resolve(document_id="doc-private-a", version=None, location=None)

    assert evidence.status == "unauthorized"
    assert evidence.text == ""


def test_document_in_different_course_is_unauthorized(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    seed(database)
    resolver = DocumentEvidenceResolver(
        database, owner_user_id="user-a", course_id="course-official"
    )

    evidence = resolver.resolve(document_id="doc-other", version=None, location=None)

    assert evidence.status == "unauthorized"
    assert evidence.text == ""


def test_unknown_document_is_missing(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    seed(database)
    resolver = DocumentEvidenceResolver(database, owner_user_id="user-a")

    evidence = resolver.resolve(document_id="no-such-doc", version=None, location=None)

    assert evidence.status == "missing"


def test_mismatched_version_is_missing(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    seed(database)
    resolver = DocumentEvidenceResolver(
        database, owner_user_id="user-a", course_id="course-official"
    )

    evidence = resolver.resolve(document_id="doc-official", version="999", location=None)

    assert evidence.status == "missing"


def test_older_version_resolves_that_versions_text(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    seed(database)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO document_versions (id, document_id, version, course_id, "
            "owner_user_id, source_scope, filename, stored_path, media_type, extension, "
            "sha256, byte_size) "
            "VALUES ('doc-official-v2', 'doc-official', 2, 'course-official', NULL, "
            "'OFFICIAL', 'official-v2.txt', 'official-v2.txt', 'text/plain', '.txt', ?, 20)",
            ("b" * 64,),
        )
        connection.execute(
            "INSERT INTO chunks (id, document_id, course_id, ordinal, content, locator_type, "
            "locator_value, section, embedding) "
            "VALUES ('chunk-official-v2', 'doc-official', 'course-official', 2, "
            "'Official version two text.', 'page', '1', 'Page 1', '[1.0]')"
        )
    resolver = DocumentEvidenceResolver(
        database, owner_user_id="user-a", course_id="course-official"
    )

    current = resolver.resolve(document_id="doc-official", version=None, location=None)
    v1 = resolver.resolve(document_id="doc-official", version="1", location=None)

    assert current.status == "ok"
    assert current.version == "2"
    assert current.text == "Official version two text."
    assert v1.status == "ok"
    assert v1.version == "1"
    assert "Official page one text." in v1.text


def test_text_bound_is_enforced(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    seed(database)

    default = DocumentEvidenceResolver(
        database, owner_user_id="user-a", course_id="course-official"
    ).resolve(document_id="doc-long", version=None, location=None)
    bounded = DocumentEvidenceResolver(
        database, owner_user_id="user-a", course_id="course-official", max_chars=100
    ).resolve(document_id="doc-long", version=None, location=None)

    assert default.status == "ok"
    assert len(default.text) == 4000
    assert bounded.status == "ok"
    assert len(bounded.text) == 100


def test_resolver_writes_nothing(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    seed(database)
    resolver = DocumentEvidenceResolver(
        database, owner_user_id="user-a", course_id="course-official"
    )

    tables = (
        "courses",
        "documents",
        "document_versions",
        "chunks",
        "chunk_source_versions",
        "learning_workspaces",
    )
    with database.connect() as connection:
        before = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }

    resolver.resolve(document_id="doc-official", version=None, location=None)
    resolver.resolve(document_id="doc-official", version=None, location="page:2")
    resolver.resolve(document_id="no-such-doc", version=None, location=None)
    resolver.resolve(document_id="doc-official", version="999", location=None)
    resolver.resolve(document_id="doc-private-b", version=None, location=None)

    with database.connect() as connection:
        after = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }

    assert before == after
