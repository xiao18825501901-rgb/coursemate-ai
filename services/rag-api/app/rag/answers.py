import re
from collections.abc import Iterator
from typing import Protocol

from openai import OpenAI


class AnswerProvider(Protocol):
    def stream_answer(
        self, *, question: str, context: str, instructions: str
    ) -> Iterator[str]:
        """Yield visible answer text deltas."""


class OpenAIAnswerProvider:
    """Stream grounded text from the official OpenAI Responses API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        client: OpenAI | None = None,
        base_url: str | None = None,
        max_output_tokens: int = 1_200,
    ) -> None:
        self.client = client or (
            OpenAI(api_key=api_key, base_url=base_url)
            if base_url
            else OpenAI(api_key=api_key)
        )
        self.model = model
        self.max_output_tokens = max_output_tokens

    def stream_answer(
        self, *, question: str, context: str, instructions: str
    ) -> Iterator[str]:
        stream = self.client.responses.create(
            model=self.model,
            instructions=instructions,
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
    def stream_answer(
        self, *, question: str, context: str, instructions: str
    ) -> Iterator[str]:
        raise RuntimeError("OPENAI_API_KEY is required for grounded answers")


class ExtractiveAnswerProvider:
    """Deterministic local answerer for demos when the OpenAI network is unavailable."""

    def stream_answer(
        self, *, question: str, context: str, instructions: str
    ) -> Iterator[str]:
        question_tokens = {
            token
            for token in re.findall(r"\w+", question.casefold())
            if len(token) > 2
        }
        cleaned_context = re.sub(r"^\[S\d+\] file=.*$", "", context, flags=re.MULTILINE)
        cleaned_context = cleaned_context.replace(
            "--- BEGIN UNTRUSTED COURSE MATERIAL ---", ""
        ).replace("--- END UNTRUSTED COURSE MATERIAL ---", "")
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", cleaned_context)
            if len(sentence.strip()) >= 20
        ]
        ranked = sorted(
            enumerate(sentences),
            key=lambda item: (
                -len(question_tokens & set(re.findall(r"\w+", item[1].casefold()))),
                item[0],
            ),
        )
        selected = [sentence for _, sentence in ranked[:3]]
        if not selected:
            yield "The retrieved sources did not contain readable supporting text."
            return
        answer = "Based on the selected course material: " + " ".join(selected)
        for offset in range(0, len(answer), 96):
            yield answer[offset : offset + 96]
