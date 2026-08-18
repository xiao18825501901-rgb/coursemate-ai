import json
from pathlib import Path

from app.rag.embeddings import DeterministicEmbeddingProvider
from app.rag.retrieval import HybridRetriever
from app.repositories.chunks import ChunkRepository
from tests.test_retrieval import make_database

CASES_PATH = Path(__file__).parent / "eval" / "retrieval_cases.json"

CORPUS = {
    "cs3481": [
        ("chunk-cs-phong", "Phong lighting has ambient, diffuse, and specular terms."),
        ("chunk-cs-raster", "Rasterization converts triangles into screen-space fragments."),
        ("chunk-cs-dbscan", "A DBSCAN core point has at least MinPts in its eps-neighborhood."),
        (
            "chunk-cs-complete",
            "Complete-link uses the farthest pair distance and resists the chaining effect.",
        ),
    ],
    "ge2324": [
        (
            "chunk-ge-heritage",
            "Heritage conservation protects cultural significance and historic value.",
        ),
        ("chunk-ge-pearson", "Pearson correlation measures linear association."),
        ("chunk-ge-spearman", "Spearman correlation uses ranks for monotonic association."),
        (
            "chunk-ge-kendall",
            "Kendall tau compares concordant and discordant observation pairs.",
        ),
    ],
}


def _seed_evaluation_corpus(repository: ChunkRepository) -> None:
    provider = DeterministicEmbeddingProvider()
    with repository.database.connect() as connection:
        for course_id in CORPUS:
            connection.execute(
                "INSERT INTO courses (id, name, description) VALUES (?, ?, '')",
                (course_id, course_id.upper()),
            )
        for course_id, records in CORPUS.items():
            for index, (chunk_id, content) in enumerate(records):
                document_id = f"doc-{chunk_id}"
                connection.execute(
                    """
                    INSERT INTO documents (
                        id, course_id, filename, stored_path, media_type, extension, sha256, status
                    ) VALUES (?, ?, ?, ?, 'text/markdown', '.md', ?, 'ready')
                    """,
                    (
                        document_id,
                        course_id,
                        f"{chunk_id}.md",
                        f"{chunk_id}.md",
                        f"{index:064x}",
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO chunks (
                        id, document_id, course_id, ordinal, content, locator_type,
                        locator_value, section, embedding
                    ) VALUES (?, ?, ?, 0, ?, 'section', 'Evaluation', 'Evaluation', ?)
                    """,
                    (
                        chunk_id,
                        document_id,
                        course_id,
                        content,
                        json.dumps(provider.embed_texts([content])[0]),
                    ),
                )


def test_hybrid_retrieval_evaluation_meets_recall_and_rank_gate(tmp_path: Path) -> None:
    repository = ChunkRepository(make_database(tmp_path))
    _seed_evaluation_corpus(repository)
    retriever = HybridRetriever(repository, DeterministicEmbeddingProvider())
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    reciprocal_ranks: list[float] = []
    recall_hits = 0

    for case in cases:
        hits = retriever.retrieve(
            course_id=case["courseId"],
            query=case["query"],
            top_k=3,
        )
        ids = [hit.chunk_id for hit in hits]
        assert all(hit.course_id == case["courseId"] for hit in hits)
        if case["expectedChunkId"] in ids:
            recall_hits += 1
            reciprocal_ranks.append(1 / (ids.index(case["expectedChunkId"]) + 1))
        else:
            reciprocal_ranks.append(0.0)

    recall_at_3 = recall_hits / len(cases)
    mean_reciprocal_rank = sum(reciprocal_ranks) / len(cases)
    assert recall_at_3 >= 0.95
    assert mean_reciprocal_rank >= 0.90
