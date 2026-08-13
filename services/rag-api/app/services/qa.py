import json
import logging
import re
from collections.abc import Iterator
from typing import cast
from uuid import uuid4

from app.course_access import require_course_access
from app.db import Database
from app.errors import ApiError
from app.rag.answers import AnswerProvider
from app.rag.prompt import build_context_with_hits, build_turn_input, build_tutor_instructions
from app.rag.retrieval import HybridRetriever
from app.rag.types import SearchHit
from app.tutor.language import LanguagePreference, detect_language, language_instruction
from app.tutor.references import parse_query_reference
from app.tutor.rewrite import ConversationTurn, rewrite_retrieval_query
from app.tutor.routing import QueryIntent, route_query
from app.tutor.strategy import TeachingApproach, choose_teaching_approach

LOGGER = logging.getLogger(__name__)
NO_SUPPORT_MESSAGE = (
    "I couldn't find enough evidence in the selected course materials to answer that question."
)
DEFAULT_CONVERSATION_TITLE = "New Conversation"
DIRECT_ANSWER = re.compile(
    r"(?:直接(?:给|告诉).{0,4}答案|只要答案|just\s+(?:give\s+me\s+)?the\s+answer)",
    re.IGNORECASE,
)


def conversation_title(question: str, *, max_length: int = 80) -> str:
    normalized = " ".join(question.strip().split())
    return normalized[:max_length].rstrip() or DEFAULT_CONVERSATION_TITLE


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


def _diagnostic_hit(item: SearchHit) -> dict[str, object]:
    return {
        "chunkId": item.chunk_id,
        "documentId": item.document_id,
        "courseId": item.course_id,
        "filename": item.filename,
        "locatorType": item.locator_type,
        "locatorValue": item.locator_value,
        "section": item.section,
        "score": item.score,
        "channels": list(item.channels),
        "metadata": {
            "".join(
                [key.split("_")[0], *(part.capitalize() for part in key.split("_")[1:])]
            ): value
            for key, value in item.metadata.items()
        },
        "excerpt": item.content[:500],
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

    def require_course(
        self,
        course_id: str,
        *,
        owner_user_id: str | None = None,
        is_admin: bool = True,
    ) -> None:
        require_course_access(
            self.database,
            course_id,
            owner_user_id=owner_user_id,
            is_admin=is_admin,
        )

    def retrieval_diagnostics(self, *, course_id: str, question: str) -> dict[str, object]:
        self.require_course(course_id)
        reference = parse_query_reference(question)
        diagnostics = self.retriever.diagnose(
            course_id=course_id,
            query=question,
            reference=reference,
            top_k=self.top_k,
        )
        selected = cast(list[SearchHit], diagnostics["selected"])
        context, included = build_context_with_hits(
            selected,
            max_chars=self.max_context_chars,
        )
        return {
            "query": question,
            "retrievalStrategy": diagnostics["strategy"],
            "reference": {
                "document": reference.document,
                "documentKind": reference.document_kind.value
                if reference.document_kind
                else None,
                "documentNumber": reference.document_number,
                "questionNumber": reference.question_number,
                "questionPart": reference.question_part,
                "pageNumber": reference.page_number,
                "slideNumber": reference.slide_number,
            },
            "structuredCandidates": [
                _diagnostic_hit(item)
                for item in cast(list[SearchHit], diagnostics["structured"])
            ],
            "keywordCandidates": [
                _diagnostic_hit(item)
                for item in cast(list[SearchHit], diagnostics["keyword"])
            ],
            "vectorCandidates": [
                _diagnostic_hit(item)
                for item in cast(list[SearchHit], diagnostics["vector"])
            ],
            "selectedChunks": [_diagnostic_hit(item) for item in included],
            "finalContext": context,
        }

    def get_conversation(
        self, *, owner_user_id: str, conversation_id: str
    ) -> dict[str, object]:
        with self.database.connect() as connection:
            conversation = connection.execute(
                """
                SELECT id, course_id, title, preferred_language, created_at, updated_at
                FROM conversations
                WHERE id = ? AND owner_user_id = ?
                """,
                (conversation_id, owner_user_id),
            ).fetchone()
            if conversation is None:
                raise ApiError(404, "CONVERSATION_NOT_FOUND", "The conversation was not found.")
            messages = connection.execute(
                """
                SELECT id, role, content, citations_json, metadata_json, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at, rowid
                """,
                (conversation_id,),
            ).fetchall()
        return {
            "id": conversation["id"],
            "course_id": conversation["course_id"],
            "title": conversation["title"],
            "preferred_language": conversation["preferred_language"],
            "created_at": conversation["created_at"],
            "updated_at": conversation["updated_at"],
            "messages": [
                {
                    "id": row["id"],
                    "role": row["role"],
                    "content": row["content"],
                    "citations": json.loads(row["citations_json"]),
                    "metadata": json.loads(row["metadata_json"]),
                    "created_at": row["created_at"],
                }
                for row in messages
            ],
        }

    def require_conversation(
        self, *, owner_user_id: str, course_id: str, conversation_id: str
    ) -> None:
        with self.database.connect() as connection:
            found = connection.execute(
                """
                SELECT 1 FROM conversations
                WHERE id = ? AND owner_user_id = ? AND course_id = ?
                """,
                (conversation_id, owner_user_id, course_id),
            ).fetchone()
        if found is None:
            raise ApiError(404, "CONVERSATION_NOT_FOUND", "The conversation was not found.")

    def create_conversation(
        self, *, owner_user_id: str, course_id: str, preferred_language: str = "auto"
    ) -> dict[str, object]:
        conversation_id = f"conv_{uuid4().hex}"
        with self.database.connect() as connection:
            row = connection.execute(
                """
                INSERT INTO conversations (
                    id, owner_user_id, course_id, title, preferred_language
                ) VALUES (?, ?, ?, ?, ?)
                RETURNING id, course_id, title, preferred_language, created_at, updated_at
                """,
                (
                    conversation_id,
                    owner_user_id,
                    course_id,
                    DEFAULT_CONVERSATION_TITLE,
                    preferred_language,
                ),
            ).fetchone()
        assert row is not None
        return {
            **dict(row),
            "message_count": 0,
        }

    def list_conversations(
        self,
        *,
        owner_user_id: str,
        course_id: str | None,
        page: int,
        page_size: int,
    ) -> dict[str, object]:
        where = "owner_user_id = ?"
        parameters: list[object] = [owner_user_id]
        if course_id is not None:
            where += " AND course_id = ?"
            parameters.append(course_id)
        offset = (page - 1) * page_size
        with self.database.connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM conversations WHERE {where}",  # noqa: S608
                parameters,
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT conversations.id, conversations.course_id,
                       conversations.title, conversations.preferred_language,
                       conversations.created_at, conversations.updated_at,
                       COUNT(messages.id) AS message_count
                FROM conversations
                LEFT JOIN messages ON messages.conversation_id = conversations.id
                WHERE conversations.{where}
                GROUP BY conversations.id
                ORDER BY conversations.updated_at DESC, conversations.id DESC
                LIMIT ? OFFSET ?
                """,  # noqa: S608
                [*parameters, page_size, offset],
            ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def rename_conversation(
        self, *, owner_user_id: str, conversation_id: str, title: str
    ) -> dict[str, object]:
        normalized = " ".join(title.strip().split())
        with self.database.connect() as connection:
            row = connection.execute(
                """
                UPDATE conversations
                SET title = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ? AND owner_user_id = ?
                RETURNING id, course_id, title, preferred_language, created_at, updated_at
                """,
                (normalized, conversation_id, owner_user_id),
            ).fetchone()
            if row is None:
                raise ApiError(404, "CONVERSATION_NOT_FOUND", "The conversation was not found.")
            message_count = connection.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
        return {**dict(row), "message_count": message_count}

    def delete_conversation(self, *, owner_user_id: str, conversation_id: str) -> None:
        with self.database.connect() as connection:
            result = connection.execute(
                "DELETE FROM conversations WHERE id = ? AND owner_user_id = ?",
                (conversation_id, owner_user_id),
            )
            if result.rowcount == 0:
                raise ApiError(404, "CONVERSATION_NOT_FOUND", "The conversation was not found.")

    def _recent_history(self, conversation_id: str | None) -> list[ConversationTurn]:
        if conversation_id is None:
            return []
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM messages
                WHERE conversation_id = ? AND role IN ('user', 'assistant')
                ORDER BY created_at DESC, rowid DESC
                LIMIT 12
                """,
                (conversation_id,),
            ).fetchall()
        return [
            ConversationTurn(role=row["role"], content=row["content"])
            for row in reversed(rows)
        ]

    def _course_metadata_context(self, course_id: str) -> str:
        with self.database.connect() as connection:
            course = connection.execute(
                "SELECT name, description FROM courses WHERE id = ?",
                (course_id,),
            ).fetchone()
            documents = connection.execute(
                """
                SELECT filename, status, chunk_count
                FROM documents
                WHERE course_id = ?
                ORDER BY filename, id
                LIMIT 100
                """,
                (course_id,),
            ).fetchall()
        assert course is not None
        lines = [
            "--- BEGIN TRUSTED COURSE METADATA ---",
            f"course: {course['name']}",
            f"description: {course['description']}",
            f"document_count: {len(documents)}",
        ]
        lines.extend(
            f"document: {row['filename']}; status={row['status']}; chunks={row['chunk_count']}"
            for row in documents
        )
        lines.append("--- END TRUSTED COURSE METADATA ---")
        return "\n".join(lines)

    def _record_question(
        self,
        *,
        owner_user_id: str,
        course_id: str,
        question: str,
        conversation_id: str | None,
    ) -> tuple[str, LanguagePreference]:
        if conversation_id is None:
            created = self.create_conversation(
                owner_user_id=owner_user_id,
                course_id=course_id,
            )
            conversation_id = str(created["id"])
        title = conversation_title(question)
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (id, conversation_id, role, content)
                VALUES (?, ?, 'user', ?)
                """,
                (f"msg_{uuid4().hex}", conversation_id, question),
            )
            connection.execute(
                """
                UPDATE conversations
                SET title = CASE WHEN title = ? THEN ? ELSE title END,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ? AND owner_user_id = ? AND course_id = ?
                """,
                (
                    DEFAULT_CONVERSATION_TITLE,
                    title,
                    conversation_id,
                    owner_user_id,
                    course_id,
                ),
            )
            preference_row = connection.execute(
                "SELECT preferred_language FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        assert preference_row is not None
        preference = cast(LanguagePreference, str(preference_row["preferred_language"]))
        return conversation_id, preference

    def _record_answer(
        self,
        *,
        conversation_id: str,
        content: str,
        citations: list[dict[str, object]],
        metadata: dict[str, object],
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, citations_json, metadata_json
                ) VALUES (?, ?, 'assistant', ?, ?, ?)
                """,
                (
                    f"msg_{uuid4().hex}",
                    conversation_id,
                    content,
                    json.dumps(citations, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
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
        self,
        *,
        owner_user_id: str,
        course_id: str,
        question: str,
        conversation_id: str | None = None,
    ) -> Iterator[str]:
        request_id = f"qa_{uuid4().hex}"
        history = self._recent_history(conversation_id)
        route = route_query(question)
        rewrite = rewrite_retrieval_query(question, history)
        retrieval_query = rewrite.query if route.uses_course_retrieval else question
        query_reference = parse_query_reference(retrieval_query)
        is_referenced_example = query_reference.question_number is not None
        example_mode = (
            "direct" if is_referenced_example and DIRECT_ANSWER.search(question) else "guided"
        ) if is_referenced_example else None
        teaching_approach: TeachingApproach | None = None
        if route.intent is QueryIntent.COURSE_TUTORING:
            teaching_approach = choose_teaching_approach(
                [*history, ConversationTurn(role="user", content=question)]
            )
        conversation_id, preferred_language = self._record_question(
            owner_user_id=owner_user_id,
            course_id=course_id,
            question=question,
            conversation_id=conversation_id,
        )
        if route.uses_course_retrieval:
            hits = self.retriever.retrieve_structured(
                course_id=course_id,
                reference=query_reference,
                top_k=self.top_k,
            )
            retrieval_strategy = "structured_locator" if hits else "hybrid"
            if not hits:
                hits = self.retriever.retrieve(
                    course_id=course_id,
                    query=retrieval_query,
                    top_k=self.top_k,
                )
            context, included_hits = build_context_with_hits(
                hits,
                max_chars=self.max_context_chars,
            )
        elif route.intent is QueryIntent.COURSE_META:
            context = self._course_metadata_context(course_id)
            included_hits = []
            retrieval_strategy = "course_metadata"
        else:
            context = ""
            included_hits = []
            retrieval_strategy = "not_applicable"
        grounding_mode = {
            QueryIntent.COURSE_GROUNDED: "grounded",
            QueryIntent.COURSE_TUTORING: "mixed",
            QueryIntent.GENERAL_CONVERSATION: "general",
            QueryIntent.COURSE_META: "metadata",
            QueryIntent.AMBIGUOUS: "grounded",
        }[route.intent]
        response_metadata: dict[str, object] = {
            "queryIntent": route.intent.value,
            "groundingMode": grounding_mode,
            "retrievalQueryRewritten": rewrite.was_rewritten
            if route.uses_course_retrieval
            else False,
            "retrievalStrategy": retrieval_strategy,
            "teachingApproach": teaching_approach.value if teaching_approach else None,
            "exampleMode": example_mode,
        }
        yield encode_sse(
            "meta",
            {
                "requestId": request_id,
                "conversationId": conversation_id,
                "courseId": course_id,
                "retrievedChunks": len(included_hits),
                **response_metadata,
            },
        )
        if not included_hits and route.intent in {
            QueryIntent.COURSE_GROUNDED,
            QueryIntent.AMBIGUOUS,
        }:
            self._record_answer(
                conversation_id=conversation_id,
                content=NO_SUPPORT_MESSAGE,
                citations=[],
                metadata=response_metadata,
            )
            yield encode_sse("delta", {"text": NO_SUPPORT_MESSAGE})
            yield encode_sse("done", {"requestId": request_id})
            return

        try:
            answer_parts: list[str] = []
            instructions = build_tutor_instructions(
                language_instruction(preferred_language, detect_language(question)),
                intent=route.intent,
                teaching_approach=teaching_approach,
                example_mode=example_mode,
            )
            for delta in self.answer_provider.stream_answer(
                question=build_turn_input(question, history),
                context=context,
                instructions=instructions,
            ):
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
                metadata=response_metadata,
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
