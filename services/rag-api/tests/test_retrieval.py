import json
from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.rag.embeddings import cosine_similarity
from app.rag.retrieval import HybridRetriever, reciprocal_rank_fusion
from app.rag.types import SearchHit
from app.repositories.chunks import ChunkRepository


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def make_database(tmp_path: Path) -> Database:
    database = Database(
        Settings(
            database_path=tmp_path / "rag.sqlite3",
            upload_dir=tmp_path / "uploads",
        )
    )
    database.initialize()
    return database


def seed_chunks(database: Database) -> None:
    with database.connect() as connection:
        connection.executemany(
            "INSERT INTO courses (id, name, description) VALUES (?, ?, ?)",
            [
                ("cs3481", "CS3481", "Computer graphics"),
                ("ge2324", "GE2324", "Heritage and conservation"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO documents (
                id, course_id, filename, stored_path, media_type, extension, sha256, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "doc-cs",
                    "cs3481",
                    "lighting.md",
                    "lighting.md",
                    "text/markdown",
                    ".md",
                    "a" * 64,
                    "ready",
                ),
                (
                    "doc-ge",
                    "ge2324",
                    "heritage.md",
                    "heritage.md",
                    "text/markdown",
                    ".md",
                    "b" * 64,
                    "ready",
                ),
            ],
        )
        connection.executemany(
            """
            INSERT INTO chunks (
                id, document_id, course_id, ordinal, content, locator_type,
                locator_value, section, embedding
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "chunk-cs-1",
                    "doc-cs",
                    "cs3481",
                    0,
                    "Phong lighting combines diffuse and specular reflection.",
                    "section",
                    "Lighting",
                    "Lighting",
                    json.dumps([1.0, 0.0]),
                ),
                (
                    "chunk-cs-2",
                    "doc-cs",
                    "cs3481",
                    1,
                    "Rasterization converts triangles into fragments.",
                    "section",
                    "Rasterization",
                    "Rasterization",
                    json.dumps([0.8, 0.2]),
                ),
                (
                    "chunk-ge-1",
                    "doc-ge",
                    "ge2324",
                    0,
                    "Heritage conservation protects cultural significance.",
                    "section",
                    "Conservation",
                    "Conservation",
                    json.dumps([0.0, 1.0]),
                ),
            ],
        )


def hit(chunk_id: str, score: float, channel: str) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id="doc",
        course_id="cs3481",
        filename="notes.md",
        content=chunk_id,
        locator_type="section",
        locator_value="Notes",
        section="Notes",
        score=score,
        channels=(channel,),
    )


def test_cosine_similarity_handles_normal_and_zero_vectors() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    with pytest.raises(ValueError, match="dimensions"):
        cosine_similarity([1.0], [1.0, 2.0])


def test_rrf_promotes_hits_found_by_both_channels() -> None:
    fused = reciprocal_rank_fusion(
        [hit("a", 10.0, "keyword"), hit("b", 9.0, "keyword")],
        [hit("b", 0.9, "vector"), hit("c", 0.8, "vector")],
        top_k=3,
    )

    assert [item.chunk_id for item in fused] == ["b", "a", "c"]
    assert fused[0].channels == ("keyword", "vector")


def test_rrf_does_not_let_a_weak_lexical_match_override_the_best_keyword_hit() -> None:
    keyword_hits = [hit("assignment", 10.0, "keyword")]
    keyword_hits.extend(
        hit(f"filler-{index}", 9.0 - index, "keyword") for index in range(16)
    )
    keyword_hits.append(hit("vector-collision", 0.1, "keyword"))

    fused = reciprocal_rank_fusion(
        keyword_hits,
        [hit("vector-collision", 1.0, "vector")],
        top_k=6,
    )

    assert fused[0].chunk_id == "assignment"
    assert any(item.chunk_id == "vector-collision" for item in fused)


def test_keyword_and_vector_retrieval_are_course_scoped(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    seed_chunks(database)
    repository = ChunkRepository(database)

    keyword_hits = repository.keyword_search("cs3481", "Phong lighting", limit=5)
    vector_hits = repository.vector_search("cs3481", [1.0, 0.0], limit=5)

    assert [item.chunk_id for item in keyword_hits] == ["chunk-cs-1"]
    assert vector_hits[0].chunk_id == "chunk-cs-1"
    assert {item.course_id for item in keyword_hits + vector_hits} == {"cs3481"}
    assert all(item.chunk_id != "chunk-ge-1" for item in keyword_hits + vector_hits)


def test_keyword_search_prioritizes_assignment_terms_over_question_stopwords(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    seed_chunks(database)
    with database.connect() as connection:
        connection.executemany(
            """
            INSERT INTO documents (
                id, course_id, filename, stored_path, media_type, extension, sha256, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "doc-ge-assignment",
                    "ge2324",
                    "assignment_2.pdf",
                    "assignment_2.pdf",
                    "application/pdf",
                    ".pdf",
                    "c" * 64,
                    "ready",
                ),
                (
                    "doc-ge-distractor",
                    "ge2324",
                    "hypothesis-testing.pptx",
                    "hypothesis-testing.pptx",
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    ".pptx",
                    "d" * 64,
                    "ready",
                ),
            ],
        )
        connection.executemany(
            """
            INSERT INTO chunks (
                id, document_id, course_id, ordinal, content, locator_type,
                locator_value, section, embedding
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "chunk-ge-assignment",
                    "doc-ge-assignment",
                    "ge2324",
                    0,
                    "Assignment 2 requires K-means clustering to reduce 16 input "
                    "colors to 3 representative colors.",
                    "page",
                    "1",
                    "Assignment 2",
                    json.dumps([0.0, 1.0]),
                ),
                (
                    "chunk-ge-distractor",
                    "doc-ge-distractor",
                    "ge2324",
                    0,
                    "What does this ask students to do with a sample, and what "
                    "does independence require?",
                    "slide",
                    "51",
                    "Hypothesis testing",
                    json.dumps([0.0, 1.0]),
                ),
            ],
        )

    hits = ChunkRepository(database).keyword_search(
        "ge2324",
        "What does Assignment 2 ask students to do with K-means and colors?",
        limit=5,
    )

    assert hits[0].filename == "assignment_2.pdf"


def test_hybrid_retriever_fuses_channels_and_empty_queries_remain_empty(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    seed_chunks(database)
    retriever = HybridRetriever(ChunkRepository(database), FakeEmbeddingProvider())

    hits = retriever.retrieve(course_id="cs3481", query="Phong", top_k=2)
    empty = retriever.retrieve(course_id="missing", query="Phong", top_k=2)

    assert hits[0].chunk_id == "chunk-cs-1"
    assert hits[0].channels == ("keyword", "vector")
    assert empty == []
