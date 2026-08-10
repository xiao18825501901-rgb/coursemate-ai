import json
import re
import sqlite3

from app.db import Database
from app.rag.embeddings import cosine_similarity
from app.rag.types import SearchHit


def _search_hit(row: sqlite3.Row, *, score: float, channel: str) -> SearchHit:
    return SearchHit(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        course_id=row["course_id"],
        filename=row["filename"],
        content=row["content"],
        locator_type=row["locator_type"],
        locator_value=row["locator_value"],
        section=row["section"],
        score=score,
        channels=(channel,),
    )


class ChunkRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def keyword_search(self, course_id: str, query: str, *, limit: int) -> list[SearchHit]:
        tokens = re.findall(r"\w+", query, flags=re.UNICODE)
        if not tokens or limit <= 0:
            return []
        fts_query = " OR ".join(f'"{token}"' for token in tokens[:24])
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    c.course_id,
                    d.filename,
                    c.content,
                    c.locator_type,
                    c.locator_value,
                    c.section,
                    bm25(chunks_fts) AS rank
                FROM chunks_fts
                JOIN chunks AS c ON c.rowid = chunks_fts.rowid
                JOIN documents AS d ON d.id = c.document_id
                WHERE chunks_fts MATCH ?
                    AND chunks_fts.course_id = ?
                    AND c.course_id = ?
                ORDER BY rank ASC, c.id ASC
                LIMIT ?
                """,
                (fts_query, course_id, course_id, limit),
            ).fetchall()
        return [
            _search_hit(row, score=-float(row["rank"]), channel="keyword")
            for row in rows
        ]

    def vector_search(
        self,
        course_id: str,
        query_vector: list[float],
        *,
        limit: int,
    ) -> list[SearchHit]:
        if not query_vector or limit <= 0:
            return []
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    c.course_id,
                    d.filename,
                    c.content,
                    c.locator_type,
                    c.locator_value,
                    c.section,
                    c.embedding
                FROM chunks AS c
                JOIN documents AS d ON d.id = c.document_id
                WHERE c.course_id = ?
                """,
                (course_id,),
            ).fetchall()

        scored: list[SearchHit] = []
        for row in rows:
            try:
                stored = json.loads(row["embedding"])
                if not isinstance(stored, list):
                    continue
                embedding = [float(value) for value in stored]
                score = cosine_similarity(query_vector, embedding)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            scored.append(_search_hit(row, score=score, channel="vector"))
        return sorted(scored, key=lambda item: (-item.score, item.chunk_id))[:limit]
