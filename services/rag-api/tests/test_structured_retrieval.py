import json
from pathlib import Path

from app.config import Settings
from app.db import Database
from app.repositories.chunks import ChunkRepository
from app.tutor.references import DocumentKind, QueryReference


def make_database(tmp_path: Path) -> Database:
    database = Database(
        Settings(database_path=tmp_path / "rag.sqlite3", upload_dir=tmp_path / "uploads")
    )
    database.initialize()
    return database


def seed_structured_chunks(database: Database) -> None:
    with database.connect() as connection:
        connection.executemany(
            "INSERT INTO courses (id, name, description) VALUES (?, ?, ?)",
            [
                ("ge2324", "GE2324", "Data mining"),
                ("cs3481", "CS3481", "Computer graphics"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO documents (
                id, course_id, filename, stored_path, media_type, extension, sha256, status
            ) VALUES (?, ?, ?, ?, 'application/pdf', '.pdf', ?, 'ready')
            """,
            [
                ("ge-a2", "ge2324", "assignment_2.pdf", "ge-a2.pdf", "a" * 64),
                ("cs-a2", "cs3481", "assignment_2.pdf", "cs-a2.pdf", "b" * 64),
                ("ge-t1", "ge2324", "tut1.pdf", "ge-t1.pdf", "c" * 64),
            ],
        )
        rows = [
            (
                "ge-q1a",
                "ge-a2",
                "ge2324",
                0,
                "Question 1 shared table\n(a) Calculate the first centroid.",
                "page",
                "1",
                "Page 1",
                {
                    "document_kind": "assignment",
                    "document_number": "2",
                    "question_number": "1",
                    "question_part": "a",
                },
                "assignment:2:q1",
            ),
            (
                "ge-q1c",
                "ge-a2",
                "ge2324",
                1,
                "Question 1 shared table\n(c) Explain convergence.",
                "page",
                "1",
                "Page 1",
                {
                    "document_kind": "assignment",
                    "document_number": "2",
                    "question_number": "1",
                    "question_part": "c",
                },
                "assignment:2:q1",
            ),
            (
                "ge-page2",
                "ge-a2",
                "ge2324",
                2,
                "Question 2 regression task.",
                "page",
                "2",
                "Page 2",
                {
                    "document_kind": "assignment",
                    "document_number": "2",
                    "question_number": "2",
                    "question_part": None,
                },
                "assignment:2:q2",
            ),
            (
                "cs-q1c",
                "cs-a2",
                "cs3481",
                0,
                "Question 1(c) graphics answer.",
                "page",
                "1",
                "Page 1",
                {
                    "document_kind": "assignment",
                    "document_number": "2",
                    "question_number": "1",
                    "question_part": "c",
                },
                "assignment:2:q1",
            ),
            (
                "ge-t1q2",
                "ge-t1",
                "ge2324",
                0,
                "Tutorial 1 Question 2 cosine similarity.",
                "page",
                "1",
                "Page 1",
                {
                    "document_kind": "tutorial",
                    "document_number": "1",
                    "question_number": "2",
                    "question_part": None,
                },
                "tutorial:1:q2",
            ),
        ]
        connection.executemany(
            """
            INSERT INTO chunks (
                id, document_id, course_id, ordinal, content, locator_type,
                locator_value, section, embedding, metadata_json, parent_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[1.0,0.0]', ?, ?)
            """,
            [(*row[:8], json.dumps(row[8]), row[9]) for row in rows],
        )


def test_exact_filename_question_and_part_are_resolved_without_cross_course_leak(
    tmp_path: Path,
) -> None:
    repository = ChunkRepository(make_database(tmp_path))
    seed_structured_chunks(repository.database)

    hits = repository.structured_search(
        "ge2324",
        QueryReference(
            document="assignment_2.pdf",
            document_kind=DocumentKind.ASSIGNMENT,
            document_number="2",
            question_number="1",
            question_part="c",
        ),
        limit=5,
    )

    assert [hit.chunk_id for hit in hits] == ["ge-q1c"]
    assert hits[0].channels == ("locator",)
    assert all(hit.course_id == "ge2324" for hit in hits)


def test_document_kind_and_question_work_without_explicit_filename(tmp_path: Path) -> None:
    repository = ChunkRepository(make_database(tmp_path))
    seed_structured_chunks(repository.database)

    hits = repository.structured_search(
        "ge2324",
        QueryReference(
            document_kind=DocumentKind.TUTORIAL,
            document_number="1",
            question_number="2",
        ),
        limit=5,
    )

    assert [hit.chunk_id for hit in hits] == ["ge-t1q2"]


def test_exact_page_locator_filters_the_named_document(tmp_path: Path) -> None:
    repository = ChunkRepository(make_database(tmp_path))
    seed_structured_chunks(repository.database)

    hits = repository.structured_search(
        "ge2324",
        QueryReference(document="assignment_2.pdf", page_number=2),
        limit=5,
    )

    assert [hit.chunk_id for hit in hits] == ["ge-page2"]


def test_empty_reference_does_not_expand_to_the_entire_course(tmp_path: Path) -> None:
    repository = ChunkRepository(make_database(tmp_path))
    seed_structured_chunks(repository.database)

    assert repository.structured_search("ge2324", QueryReference(), limit=5) == []
