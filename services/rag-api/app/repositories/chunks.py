import json
import re
import sqlite3

from app.db import Database
from app.rag.embeddings import cosine_similarity
from app.rag.types import SearchHit
from app.tutor.references import QueryReference

ENGLISH_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "ask",
        "at",
        "be",
        "by",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)


def _query_tokens(query: str) -> list[str]:
    tokens = [token.casefold() for token in re.findall(r"\w+", query, flags=re.UNICODE)]
    meaningful = [
        token for token in tokens if len(token) > 1 and token not in ENGLISH_STOP_WORDS
    ]
    selected = meaningful or tokens
    return list(dict.fromkeys(selected))[:24]


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
        metadata=json.loads(row["metadata_json"]),
        parent_key=row["parent_key"],
    )


class ChunkRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def keyword_search(self, course_id: str, query: str, *, limit: int) -> list[SearchHit]:
        tokens = _query_tokens(query)
        if not tokens or limit <= 0:
            return []
        fts_query = " OR ".join(f'"{token}"' for token in tokens)
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
                    c.metadata_json,
                    c.parent_key,
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

    def structured_search(
        self,
        course_id: str,
        reference: QueryReference,
        *,
        limit: int,
    ) -> list[SearchHit]:
        """Resolve explicit document and structural locators inside one course."""

        if limit <= 0 or not any(
            (
                reference.document,
                reference.document_kind,
                reference.document_number,
                reference.question_number,
                reference.question_part,
                reference.page_number,
                reference.slide_number,
            )
        ):
            return []
        conditions = ["c.course_id = ?"]
        parameters: list[object] = [course_id]
        if reference.document:
            conditions.append("d.filename = ? COLLATE NOCASE")
            parameters.append(reference.document)
        if reference.document_kind and not reference.document:
            conditions.append("json_extract(c.metadata_json, '$.document_kind') = ?")
            parameters.append(reference.document_kind.value)
        if reference.document_number and not reference.document:
            conditions.append("json_extract(c.metadata_json, '$.document_number') = ?")
            parameters.append(reference.document_number)
        if reference.question_number:
            conditions.append("json_extract(c.metadata_json, '$.question_number') = ?")
            parameters.append(reference.question_number)
        if reference.question_part:
            conditions.append("json_extract(c.metadata_json, '$.question_part') = ?")
            parameters.append(reference.question_part)
        if reference.page_number is not None:
            conditions.extend(("c.locator_type = 'page'", "c.locator_value = ?"))
            parameters.append(str(reference.page_number))
        if reference.slide_number is not None:
            conditions.extend(("c.locator_type = 'slide'", "c.locator_value = ?"))
            parameters.append(str(reference.slide_number))
        parameters.append(limit)
        where = " AND ".join(conditions)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    c.course_id,
                    d.filename,
                    c.content,
                    c.locator_type,
                    c.locator_value,
                    c.section,
                    c.metadata_json,
                    c.parent_key
                FROM chunks AS c
                JOIN documents AS d ON d.id = c.document_id
                WHERE {where}
                ORDER BY d.filename COLLATE NOCASE, c.ordinal, c.id
                LIMIT ?
                """,  # noqa: S608 -- fragments are fixed above; values stay parameterized.
                parameters,
            ).fetchall()
        return [
            _search_hit(row, score=1.0, channel="locator")
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
                    c.metadata_json,
                    c.parent_key,
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
