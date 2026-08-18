from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.rag.embeddings import cosine_similarity


@dataclass(frozen=True)
class EmbeddingCase:
    id: str
    course_id: str
    query: str
    filename: str
    locator_type: str
    locator_value: str


@dataclass(frozen=True)
class CorpusChunk:
    id: str
    course_id: str
    filename: str
    locator_type: str
    locator_value: str
    content: str


def calculate_embedding_cost_ceiling(
    input_token_ceilings: list[int], *, price_per_million: float
) -> float:
    if not input_token_ceilings or any(value < 0 for value in input_token_ceilings):
        raise ValueError("Embedding token ceilings must be non-negative and non-empty.")
    if not math.isfinite(price_per_million) or price_per_million <= 0:
        raise ValueError("Embedding price must be positive finite.")
    return round(sum(input_token_ceilings) * price_per_million / 1_000_000, 8)


def load_embedding_cases(path: Path) -> list[EmbeddingCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("Embedding benchmark dataset must be a non-empty JSON array.")
    cases = [
        EmbeddingCase(
            id=str(value["id"]),
            course_id=str(value["courseId"]),
            query=str(value["query"]),
            filename=str(value["filename"]),
            locator_type=str(value["locatorType"]),
            locator_value=str(value["locatorValue"]),
        )
        for value in payload
    ]
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Embedding benchmark case IDs must be unique.")
    if any(not all(asdict(case).values()) for case in cases):
        raise ValueError("Embedding benchmark case fields must be non-empty.")
    return cases


def load_official_corpus(
    database_path: Path,
    cases: list[EmbeddingCase],
) -> tuple[list[CorpusChunk], dict[str, set[str]]]:
    connection = sqlite3.connect(
        f"{database_path.resolve().as_uri()}?mode=ro", uri=True, timeout=10
    )
    connection.row_factory = sqlite3.Row
    try:
        allowed_courses = sorted({case.course_id for case in cases})
        placeholders = ",".join("?" for _ in allowed_courses)
        courses = connection.execute(
            f"""
            SELECT id, course_type, visibility
            FROM courses
            WHERE id IN ({placeholders})
            """,  # noqa: S608 - placeholders are generated, values remain parameterized.
            allowed_courses,
        ).fetchall()
        course_state = {
            str(row["id"]): (str(row["course_type"]), str(row["visibility"]))
            for row in courses
        }
        if any(
            course_state.get(course_id) != ("official", "public")
            for course_id in allowed_courses
        ):
            raise ValueError("Embedding benchmark may use only official public courses.")
        rows = connection.execute(
            f"""
            SELECT c.id, c.course_id, d.filename, c.locator_type, c.locator_value, c.content
            FROM chunks AS c
            JOIN documents AS d ON d.id = c.document_id
            WHERE c.course_id IN ({placeholders})
            ORDER BY c.course_id, d.filename, c.ordinal, c.id
            """,  # noqa: S608 - placeholders are generated, values remain parameterized.
            allowed_courses,
        ).fetchall()
    finally:
        connection.close()
    chunks = [
        CorpusChunk(
            id=str(row["id"]),
            course_id=str(row["course_id"]),
            filename=str(row["filename"]),
            locator_type=str(row["locator_type"]),
            locator_value=str(row["locator_value"]),
            content=str(row["content"]),
        )
        for row in rows
    ]
    expected_ids = {
        case.id: {
            chunk.id
            for chunk in chunks
            if chunk.course_id == case.course_id
            and chunk.filename.casefold() == case.filename.casefold()
            and chunk.locator_type == case.locator_type
            and chunk.locator_value == case.locator_value
        }
        for case in cases
    }
    missing = [case_id for case_id, identifiers in expected_ids.items() if not identifiers]
    if missing:
        raise ValueError(f"Embedding judgments did not resolve for case IDs: {', '.join(missing)}")
    return chunks, expected_ids


def evaluate_embeddings(
    cases: list[EmbeddingCase],
    chunks: list[CorpusChunk],
    *,
    expected_ids: dict[str, set[str]],
    query_vectors: list[list[float]],
    chunk_vectors: list[list[float]],
    top_k: int,
) -> dict[str, Any]:
    if len(query_vectors) != len(cases) or len(chunk_vectors) != len(chunks):
        raise ValueError("Embedding vector count does not match cases or corpus chunks.")
    if top_k <= 0:
        raise ValueError("top_k must be positive.")
    results: list[dict[str, Any]] = []
    reciprocal_ranks: list[float] = []
    hits = 0
    for case_index, case in enumerate(cases):
        ranked = sorted(
            (
                (cosine_similarity(query_vectors[case_index], chunk_vectors[index]), chunk.id)
                for index, chunk in enumerate(chunks)
                if chunk.course_id == case.course_id
            ),
            key=lambda item: (-item[0], item[1]),
        )[:top_k]
        returned_ids = [chunk_id for _, chunk_id in ranked]
        rank = next(
            (
                index
                for index, chunk_id in enumerate(returned_ids, start=1)
                if chunk_id in expected_ids[case.id]
            ),
            None,
        )
        if rank is not None:
            hits += 1
            reciprocal_ranks.append(1 / rank)
        else:
            reciprocal_ranks.append(0.0)
        results.append(
            {
                "case_id": case.id,
                "course_id": case.course_id,
                "expected_chunk_ids": sorted(expected_ids[case.id]),
                "returned_chunk_ids": returned_ids,
                "rank": rank,
            }
        )
    return {
        "case_count": len(cases),
        "top_k": top_k,
        "recall_at_k": hits / len(cases) if cases else 0.0,
        "mean_reciprocal_rank": (
            sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0
        ),
        "results": results,
    }
