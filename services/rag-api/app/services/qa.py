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

    def get_conversation(
        self, *, owner_user_id: str, conversation_id: str
    ) -> dict[str, object]:
        with self.database.connect() as connection:
            conversation = connection.execute(
                """
                SELECT id, course_id, created_at, updated_at
                FROM conversations
                WHERE id = ? AND owner_user_id = ?
                """,
                (conversation_id, owner_user_id),
            ).fetchone()
            if conversation is None:
                raise ApiError(404, "CONVERSATION_NOT_FOUND", "The conversation was not found.")
            messages = connection.execute(
                """
                SELECT id, role, content, citations_json, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at, rowid
                """,
                (conversation_id,),
            ).fetchall()
        return {
            "id": conversation["id"],
            "course_id": conversation["course_id"],
            "created_at": conversation["created_at"],
            "updated_at": conversation["updated_at"],
            "messages": [
                {
                    "id": row["id"],
                    "role": row["role"],
                    "content": row["content"],
                    "citations": json.loads(row["citations_json"]),
                    "created_at": row["created_at"],
                }
                for row in messages
            ],
        }

    def _start_conversation(
        self, *, owner_user_id: str, course_id: str, question: str
    ) -> str:
        conversation_id = f"conv_{uuid4().hex}"
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO conversations (id, owner_user_id, course_id) VALUES (?, ?, ?)",
                (conversation_id, owner_user_id, course_id),
            )
            connection.execute(
                """
                INSERT INTO messages (id, conversation_id, role, content)
                VALUES (?, ?, 'user', ?)
                """,
                (f"msg_{uuid4().hex}", conversation_id, question),
            )
        return conversation_id

    def _record_answer(
        self,
        *,
        conversation_id: str,
        content: str,
        citations: list[dict[str, object]],
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (id, conversation_id, role, content, citations_json)
                VALUES (?, ?, 'assistant', ?, ?)
                """,
                (
                    f"msg_{uuid4().hex}",
                    conversation_id,
                    content,
                    json.dumps(citations, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            connection.execute(
                """
                UPDATE conversations
                SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (conversation_id,),
            )

    def stream(
        self, *, owner_user_id: str, course_id: str, question: str
    ) -> Iterator[str]:
        request_id = f"qa_{uuid4().hex}"
        conversation_id = self._start_conversation(
            owner_user_id=owner_user_id,
            course_id=course_id,
            question=question,
        )
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
                "conversationId": conversation_id,
                "courseId": course_id,
                "retrievedChunks": len(included_hits),
            },
        )
        if not included_hits:
            self._record_answer(
                conversation_id=conversation_id,
                content=NO_SUPPORT_MESSAGE,
                citations=[],
            )
            yield encode_sse("delta", {"text": NO_SUPPORT_MESSAGE})
            yield encode_sse("done", {"requestId": request_id})
            return

        try:
            answer_parts: list[str] = []
            for delta in self.answer_provider.stream_answer(question=question, context=context):
                if delta:
                    answer_parts.append(delta)
                    yield encode_sse("delta", {"text": delta})
            citations = [
                _citation(item, index)
                for index, item in enumerate(included_hits, start=1)
            ]
            answer_text = "".join(answer_parts).strip()
            if not answer_text:
                raise RuntimeError("Answer provider returned no visible text")
            self._record_answer(
                conversation_id=conversation_id,
                content=answer_text,
                citations=citations,
            )
            for citation in citations:
                yield encode_sse("citation", citation)
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
