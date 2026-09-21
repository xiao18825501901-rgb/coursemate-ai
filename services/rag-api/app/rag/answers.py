import re
from collections.abc import Iterator, Sequence
from typing import Any, Protocol

from openai import OpenAI

from app.evaluation.deepseek_contract import REASONING_DISABLED
from app.evaluation.provider_safety import validate_deepseek_base_url
from app.jev import callsites
from app.jev.service import SemanticDecisionService


def evidence_bundle_support(
    service: SemanticDecisionService | None,
    *,
    claim: str,
    spans: Sequence[dict[str, str]],
    scope: Any,
) -> dict[str, str]:
    """Pre-DeepSeek evidence-bundle check (source.supports_claim.v1 +
    source.select_span.v1) for grounded answers.

    The backend supplies the claim, the span ids and the actual source text; Jev
    may only judge the supplied candidates and never authors a citation. The
    result is an annotation only — ``selected_span`` (or ``NO_SUPPORT``) and the
    support verdict for that span — and every supplied source is always handed
    to DeepSeek unchanged, so insufficient/uncertain evidence is never
    auto-deleted.
    """
    if service is None or not spans:
        return {"selected_span": "NO_SUPPORT", "support": callsites.UNVERIFIED}
    span_ids = [str(span["id"]) for span in spans]
    by_id = {str(span["id"]): span for span in spans}
    selected = callsites.select_citation_span(
        service, claim=claim, candidate_spans=span_ids, scope=scope
    )
    span = by_id.get(selected)
    if span is None:
        return {"selected_span": selected, "support": callsites.UNVERIFIED}
    support = callsites.citation_support(
        service,
        claim=claim,
        source_span=str(span.get("text", ""))[:4000],
        source_version=str(span.get("version", "")),
        task_scope=str(span.get("scope", "qa")),
        scope=scope,
    )
    return {"selected_span": selected, "support": support}


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


class DeepSeekAnswerProvider:
    """Stream grounded text from DeepSeek's Responses API (deepseek-flash).

    The base URL is pinned to ``api.deepseek.com`` by the settings validator; this
    class never rewrites the host or falls back to OpenAI/Qwen. Native thinking is
    explicitly disabled so only ``output_text.delta`` is projected (no reasoning
    chain is ever yielded).
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "deepseek-flash",
        client: OpenAI | None = None,
        base_url: str = "https://api.deepseek.com",
        max_output_tokens: int = 1_200,
    ) -> None:
        validate_deepseek_base_url(base_url)
        self.client = client or OpenAI(api_key=api_key, base_url=base_url)
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
            extra_body={"reasoning": REASONING_DISABLED},
        )
        for event in stream:
            if event.type == "response.output_text.delta":
                yield event.delta
            elif event.type == "response.failed":
                raise RuntimeError("DeepSeek response failed")


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
