import sqlite3
from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.models import CourseCreate
from app.rag.embeddings import DeterministicEmbeddingProvider
from app.repositories.chunks import ChunkRepository
from app.services.ingestion import IngestionService
from app.tutor.references import parse_query_reference

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DATABASE = REPOSITORY_ROOT / "data" / "rag.sqlite3"
REAL_FILES = (
    "CS_3481_Assignment_2.pdf",
    "assignment_2.pdf",
    "tut1.pdf",
    "GE2324_Tut07.docx",
)


def _real_file_rows() -> list[sqlite3.Row]:
    if not CORPUS_DATABASE.is_file():
        pytest.skip("Local read-only CourseMate corpus is unavailable")
    connection = sqlite3.connect(f"file:{CORPUS_DATABASE}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(
            """
            SELECT course_id, filename, stored_path, media_type
            FROM documents
            WHERE filename IN (?, ?, ?, ?)
            ORDER BY course_id, filename
            """,
            REAL_FILES,
        ).fetchall()
    finally:
        connection.close()


@pytest.fixture
def real_corpus_repository(tmp_path: Path) -> ChunkRepository:
    rows = _real_file_rows()
    if {row["filename"] for row in rows} != set(REAL_FILES):
        pytest.skip("Required CS3481/GE2324 golden files are unavailable")
    settings = Settings(
        database_path=tmp_path / "stage3-golden.sqlite3",
        upload_dir=tmp_path / "uploads",
        chunk_size=1_000,
        chunk_overlap=100,
    )
    database = Database(settings)
    database.initialize()
    service = IngestionService(database, settings, DeterministicEmbeddingProvider())
    for course_id in sorted({str(row["course_id"]) for row in rows}):
        service.create_course(
            CourseCreate(id=course_id, name=course_id.upper(), description="Golden corpus")
        )
    for row in rows:
        source = Path(row["stored_path"])
        accepted = service.queue_document(
            course_id=row["course_id"],
            filename=row["filename"],
            media_type=row["media_type"],
            content=source.read_bytes(),
        )
        sidecar = source.with_name(f"{source.name}.ocr.md")
        if sidecar.is_file():
            service.attach_pdf_transcription(
                accepted.document.id,
                sidecar.read_text(encoding="utf-8"),
            )
        service.process_document(accepted.document.id, accepted.job.id)
        assert service.get_document(accepted.document.id).status.value == "ready"
    return ChunkRepository(database)


@pytest.mark.golden
def test_real_cs3481_filename_and_question_number(
    real_corpus_repository: ChunkRepository,
) -> None:
    hits = real_corpus_repository.structured_search(
        "cs3481",
        parse_query_reference("CS_3481_Assignment_2.pdf Question 2"),
        limit=6,
    )

    assert hits
    assert {hit.filename for hit in hits} == {"CS_3481_Assignment_2.pdf"}
    assert {hit.metadata["question_number"] for hit in hits} == {"2"}
    assert {hit.course_id for hit in hits} == {"cs3481"}


@pytest.mark.golden
def test_real_ge2324_filename_question_and_subpart_with_parent_context(
    real_corpus_repository: ChunkRepository,
) -> None:
    hits = real_corpus_repository.structured_search(
        "ge2324",
        parse_query_reference("assignment_2.pdf Question 1(b)"),
        limit=6,
    )

    assert hits[0].filename == "assignment_2.pdf"
    assert hits[0].metadata["question_number"] == "1"
    assert hits[0].metadata["question_part"] == "b"
    assert hits[0].channels == ("locator",)
    assert any(hit.channels == ("parent_context",) for hit in hits[1:])
    assert "same result" in hits[0].content


@pytest.mark.golden
def test_real_tutorial_reference_includes_cross_page_question_context(
    real_corpus_repository: ChunkRepository,
) -> None:
    hits = real_corpus_repository.structured_search(
        "cs3481",
        parse_query_reference("Tutorial 1 Question 2"),
        limit=8,
    )

    assert hits
    assert {hit.filename for hit in hits} == {"tut1.pdf"}
    assert {hit.metadata["question_number"] for hit in hits} == {"2"}
    assert {hit.locator_value for hit in hits} == {"1", "2"}
    assert any("article 1 and article 2" in hit.content for hit in hits)


@pytest.mark.golden
def test_real_cs3481_cross_page_numeric_subpart_is_exact(
    real_corpus_repository: ChunkRepository,
) -> None:
    hits = real_corpus_repository.structured_search(
        "cs3481",
        parse_query_reference("CS_3481_Assignment_2.pdf Question 3(2)"),
        limit=8,
    )

    assert hits
    assert hits[0].metadata["question_number"] == "3"
    assert hits[0].metadata["question_part"] == "2"
    assert hits[0].locator_value == "2"
    assert "Compute the test statistic" in hits[0].content


@pytest.mark.golden
def test_real_exact_locator_is_course_isolated(
    real_corpus_repository: ChunkRepository,
) -> None:
    wrong_course = real_corpus_repository.structured_search(
        "cs3481",
        parse_query_reference("assignment_2.pdf Question 1(b)"),
        limit=6,
    )
    ge_tutorial = real_corpus_repository.structured_search(
        "ge2324",
        parse_query_reference("GE2324_Tut07.docx Q1"),
        limit=6,
    )

    assert wrong_course == []
    assert ge_tutorial
    assert {hit.course_id for hit in ge_tutorial} == {"ge2324"}
    assert {hit.filename for hit in ge_tutorial} == {"GE2324_Tut07.docx"}
