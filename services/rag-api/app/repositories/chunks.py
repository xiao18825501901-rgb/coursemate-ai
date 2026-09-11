import json
import re
import sqlite3
from dataclasses import dataclass, replace
from typing import Literal

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


@dataclass(frozen=True)
class RetrievalAccess:
    owner_user_id: str
    scope: Literal["official", "mine"]


def _source_access(
    course_id: str,
    access: RetrievalAccess | None,
    *,
    fts: bool = False,
) -> tuple[str, str, list[object], str]:
    if access is None:
        prefix = "chunks_fts.course_id = ? AND " if fts else ""
        parameters: list[object] = [course_id, course_id] if fts else [course_id]
        return "", prefix + "c.course_id = ?", parameters, "d.filename"
    joins = (
        "JOIN chunk_source_versions AS csv ON csv.chunk_id=c.id "
        "JOIN document_versions AS dv ON dv.id=csv.document_version_id "
    )
    if access.scope == "official":
        condition = (
            "dv.course_id=? AND (dv.source_scope='OFFICIAL' OR "
            "(dv.source_scope='OWNER_COURSE' AND (dv.owner_user_id=? OR EXISTS("
            "SELECT 1 FROM courses AS source_course WHERE source_course.id=dv.course_id "
            "AND source_course.visibility='public' "
            "AND source_course.publication_status='published'))))"
        )
    else:
        condition = (
            "dv.course_id=? AND dv.source_scope='WORKSPACE_PRIVATE' "
            "AND dv.owner_user_id=?"
        )
    return joins, condition, [course_id, access.owner_user_id], "dv.filename"


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

    def keyword_search(
        self,
        course_id: str,
        query: str,
        *,
        limit: int,
        access: RetrievalAccess | None = None,
    ) -> list[SearchHit]:
        tokens = _query_tokens(query)
        if not tokens or limit <= 0:
            return []
        fts_query = " OR ".join(f'"{token}"' for token in tokens)
        source_joins, source_condition, source_parameters, filename = _source_access(
            course_id, access, fts=True
        )
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    c.course_id,
                    {filename} AS filename,
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
                {source_joins}
                WHERE chunks_fts MATCH ?
                    AND {source_condition}
                ORDER BY rank ASC, c.id ASC
                LIMIT ?
                """,  # noqa: S608 -- SQL fragments are fixed by RetrievalAccess.
                (fts_query, *source_parameters, limit),
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
        access: RetrievalAccess | None = None,
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
        source_joins, source_condition, source_parameters, filename = _source_access(
            course_id, access
        )
        conditions = [source_condition]
        parameters: list[object] = list(source_parameters)
        if reference.document:
            conditions.append(f"{filename} = ? COLLATE NOCASE")
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
                    {filename} AS filename,
                    c.content,
                    c.locator_type,
                    c.locator_value,
                    c.section,
                    c.metadata_json,
                    c.parent_key
                FROM chunks AS c
                JOIN documents AS d ON d.id = c.document_id
                {source_joins}
                WHERE {where}
                ORDER BY
                    CASE json_extract(c.metadata_json, '$.fragment_role')
                        WHEN 'target' THEN 0 ELSE 1
                    END,
                    {filename} COLLATE NOCASE,
                    c.ordinal,
                    c.id
                LIMIT ?
                """,  # noqa: S608 -- fragments are fixed above; values stay parameterized.
                parameters,
            ).fetchall()
        exact_hits = [
            _search_hit(row, score=1.0, channel="locator")
            for row in rows
        ]
        if not exact_hits or not reference.question_part or limit <= len(exact_hits):
            return exact_hits
        parent_keys = list(
            dict.fromkeys(hit.parent_key for hit in exact_hits if hit.parent_key is not None)
        )
        if not parent_keys:
            return exact_hits
        placeholders = ", ".join("?" for _ in parent_keys)
        remaining = limit - len(exact_hits)
        excluded_ids = {hit.chunk_id for hit in exact_hits}
        parent_joins, parent_condition, parent_parameters, parent_filename = _source_access(
            course_id, access
        )
        with self.database.connect() as connection:
            parent_rows = connection.execute(
                f"""
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    c.course_id,
                    {parent_filename} AS filename,
                    c.content,
                    c.locator_type,
                    c.locator_value,
                    c.section,
                    c.metadata_json,
                    c.parent_key
                FROM chunks AS c
                JOIN documents AS d ON d.id = c.document_id
                {parent_joins}
                WHERE {parent_condition} AND c.parent_key IN ({placeholders})
                ORDER BY {parent_filename} COLLATE NOCASE, c.ordinal, c.id
                """,  # noqa: S608 -- placeholder count derives from matched parent rows.
                [*parent_parameters, *parent_keys],
            ).fetchall()
        parent_hits = [
            replace(
                _search_hit(row, score=0.5, channel="parent_context"),
                channels=("parent_context",),
            )
            for row in parent_rows
            if row["chunk_id"] not in excluded_ids
        ][:remaining]
        return [*exact_hits, *parent_hits]

    def vector_search(
        self,
        course_id: str,
        query_vector: list[float],
        *,
        limit: int,
        access: RetrievalAccess | None = None,
    ) -> list[SearchHit]:
        if not query_vector or limit <= 0:
            return []
        source_joins, source_condition, source_parameters, filename = _source_access(
            course_id, access
        )
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    c.course_id,
                    {filename} AS filename,
                    c.content,
                    c.locator_type,
                    c.locator_value,
                    c.section,
                    c.metadata_json,
                    c.parent_key,
                    c.embedding
                FROM chunks AS c
                JOIN documents AS d ON d.id = c.document_id
                {source_joins}
                WHERE {source_condition}
                """,  # noqa: S608 -- SQL fragments are fixed by RetrievalAccess.
                source_parameters,
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
