import sqlite3
from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.jev.entity_resolution import accepted_name_groups, expand_query
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


CJK_CLUSTERING_TERM = "\u805a\u7c7b\u5206\u6790"
CJK_CLUSTERING_QUERY = "\u805a\u7c7b\u5206\u6790\u662f\u4ec0\u4e48\u610f\u601d"


@pytest.mark.golden
def test_accepted_alias_lets_a_cjk_question_reach_english_material(
    real_corpus_repository: ChunkRepository,
) -> None:
    """A Chinese question about a concept the registry also names in English must
    reach the English material — on the real corpus, through the real registry
    lookup, the real expansion and the real lexical search.

    The lexical channel is the honest place to measure this: the deterministic stub
    embedding used by this fixture answers any query with *some* similarity, so a
    whole-retriever comparison would not isolate the alias's effect. Production runs
    a real embedding model, where the same expansion also helps the vector channel.
    """

    database = real_corpus_repository.database
    # The golden fixture builds the ingestion-only schema; the knowledge registry
    # (migration 014+) belongs to the V3 schema, so apply it to the same file the
    # real adapter reads instead of hand-writing the two tables.
    registry_database = Database(
        Settings(
            database_path=database.path,
            upload_dir=database.upload_dir,
            v3_enabled=True,
        )
    )
    registry_database.initialize()
    with registry_database.connect() as connection:
        connection.execute(
            "INSERT INTO knowledge_nodes("
            "id,course_id,owner_user_id,title,description,major,kind,status) "
            "VALUES('golden-alias-clustering','ge2324',NULL,?,?,?,'ATOMIC','PUBLISHED')",
            (CJK_CLUSTERING_TERM, "Golden alias fixture", "CS"),
        )
        connection.execute(
            "INSERT INTO knowledge_node_aliases(node_id,alias,normalized_alias,locale) "
            "VALUES('golden-alias-clustering','clustering','clustering','en')"
        )

    groups = accepted_name_groups(registry_database, "ge2324", "golden-subject")
    assert any("clustering" in group for group in groups)

    expanded = expand_query(CJK_CLUSTERING_QUERY, name_groups=groups)
    assert expanded.original_query == CJK_CLUSTERING_QUERY
    assert expanded.added_aliases == ("clustering",)
    assert expanded.matched_groups == (CJK_CLUSTERING_TERM,)

    # The Chinese question alone cannot lexically match the English material …
    assert (
        real_corpus_repository.keyword_search("ge2324", CJK_CLUSTERING_QUERY, limit=8) == []
    )
    # … and with the accepted alias it reaches the document that discusses it.
    hits = real_corpus_repository.keyword_search(
        "ge2324", expanded.expanded_query, limit=8
    )
    assert hits
    assert {hit.filename for hit in hits} == {"assignment_2.pdf"}
    assert any("clustering" in hit.content.lower() for hit in hits)
