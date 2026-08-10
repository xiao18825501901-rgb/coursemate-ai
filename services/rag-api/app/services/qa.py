import json
import logging
from collections.abc import Iterator
from uuid import uuid4

from app.db import Database
from app.errors import ApiError
from app.rag.answers import AnswerProvider
from app.rag.prompt import build_context_with_hits
from app.rag.retrieval import HybridRetriever
from app.rag.types import SearchHit

LOGGER = logging.getLogger(__name__)
NO_SUPPORT_MESSAGE = (
    "I couldn't find enough evidence in the selected course materials to answer that question."
)


def encode_sse(event: str, data: dict[str, object]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


def _citation(item: SearchHit, index: int) -> dict[str, object]:
    excerpt = item.content[:360].strip()
    return {
        "sourceLabel": f"S{index}",
        "courseId": item.course_id,
        "documentId": item.document_id,
        "chunkId": item.chunk_id,
        "filename": item.filename,
        "locatorType": item.locator_type,
        "locatorValue": item.locator_value,
        "section": item.section,
        "excerpt": excerpt,
        "channels": list(item.channels),
    }


class QaService:
    def __init__(
        self,
        database: Database,
        retriever: HybridRetriever,
        answer_provider: AnswerProvider,
        *,
        top_k: int,
        max_context_chars: int,
    ) -> None:
        self.database = database
        self.retriever = retriever
        self.answer_provider = answer_provider
        self.top_k = top_k
        self.max_context_chars = max_context_chars

    def require_course(self, course_id: str) -> None:
        with self.database.connect() as connection:
            found = connection.execute(
                "SELECT 1 FROM courses WHERE id = ?", (course_id,)
            ).fetchone()
        if found is None:
            raise ApiError(404, "COURSE_NOT_FOUND", "The course was not found.")

    def stream(self, *, course_id: str, question: str) -> Iterator[str]:
        request_id = f"qa_{uuid4().hex}"
        hits = self.retriever.retrieve(
            course_id=course_id,
            query=question,
            top_k=self.top_k,
        )
        context, included_hits = build_context_with_hits(
            hits,
            max_chars=self.max_context_chars,
        )
        yield encode_sse(
            "meta",
            {
                "requestId": request_id,
                "courseId": course_id,
                "retrievedChunks": len(included_hits),
            },
        )
        if not included_hits:
            yield encode_sse("delta", {"text": NO_SUPPORT_MESSAGE})
            yield encode_sse("done", {"requestId": request_id})
            return

        try:
            for delta in self.answer_provider.stream_answer(question=question, context=context):
                if delta:
                    yield encode_sse("delta", {"text": delta})
            for index, item in enumerate(included_hits, start=1):
                yield encode_sse("citation", _citation(item, index))
            yield encode_sse("done", {"requestId": request_id})
        except Exception:
            LOGGER.exception("Grounded answer generation failed for request %s", request_id)
            yield encode_sse(
                "error",
                {
                    "code": "MODEL_ERROR",
                    "message": "The answer model could not complete the request.",
                },
            )
