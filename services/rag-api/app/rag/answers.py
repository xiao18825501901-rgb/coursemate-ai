from collections.abc import Iterator
from typing import Protocol

from openai import OpenAI

from app.rag.prompt import QA_INSTRUCTIONS


class AnswerProvider(Protocol):
    def stream_answer(self, *, question: str, context: str) -> Iterator[str]:
        """Yield visible answer text deltas."""


class OpenAIAnswerProvider:
    """Stream grounded text from the official OpenAI Responses API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        client: OpenAI | None = None,
        max_output_tokens: int = 1_200,
    ) -> None:
        self.client = client or OpenAI(api_key=api_key)
        self.model = model
        self.max_output_tokens = max_output_tokens

    def stream_answer(self, *, question: str, context: str) -> Iterator[str]:
        stream = self.client.responses.create(
            model=self.model,
            instructions=QA_INSTRUCTIONS,
            input=f"Question:\n{question}\n\n{context}",
            max_output_tokens=self.max_output_tokens,
            store=False,
            stream=True,
        )
        for event in stream:
            if event.type == "response.output_text.delta":
                yield event.delta
            elif event.type == "response.failed":
                raise RuntimeError("OpenAI response failed")


class MissingAnswerProvider:
    def stream_answer(self, *, question: str, context: str) -> Iterator[str]:
        raise RuntimeError("OPENAI_API_KEY is required for grounded answers")
