"""Injectable coverage review for free-text shell deliveries.

The refreshed shell teaches with free text; whether that text actually delivers
a REQUIRED teaching item is a semantic judgment the server cannot make by
itself. This module owns that judgment behind one injectable interface so the
local/tests can run deterministically and production can opt into an
independently billed model review:

* ``NullCoverageReviewer`` (default): nothing is confirmed; teaching content is
  still recorded as a teaching unit, but no coverage evidence is written.
* ``DeterministicCoverageReviewer``: a documented test-grade heuristic - an
  item counts only when EVERY sentence of its authored acceptance statement
  appears in the delivered content. It is rejected in production.
* ``ModelCoverageReviewer``: one independent, default-off post-processing call
  to the site model (qwen3.8-max) that reviews the already-saved teaching
  content against the frozen spec items. It never regenerates teaching, never
  decides grades, and its verdicts are only CANDIDATES: the server validates
  every confirmed item against the frozen spec and the saved body before any
  coverage is recorded. Enabling it is a separate paid authorization.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

# Invoke signature: messages, max_tokens -> response text. Injected so contract
# tests can use MockTransport/local fake upstreams without any billing.
Invoke = Callable[[list[dict[str, str]], int], Awaitable[str]]

REVIEWER_POLICY_VERSION = "SHELL_COVERAGE_REVIEW_V1"
DECISIONS = ("covered", "partial", "not_covered", "uncertain")


@dataclass
class ReviewOutcome:
    """The persisted review decision: candidates only, never coverage itself."""

    status: str  # 'completed' | 'failed' | 'skipped'
    confirmed: list[str] = field(default_factory=list)
    verdicts: dict[str, dict[str, Any]] = field(default_factory=dict)
    error: str = ""
    reviewer: str = "NullCoverageReviewer"
    policy_version: str = REVIEWER_POLICY_VERSION


class CoverageReviewer(Protocol):
    async def review(
        self,
        items: list[dict[str, Any]],
        content: str,
        context: dict[str, Any],
    ) -> ReviewOutcome:
        """Return a ReviewOutcome; confirmed ids are candidates only."""


class NullCoverageReviewer:
    """No semantic confirmation available; no coverage is claimed."""

    async def review(
        self,
        items: list[dict[str, Any]],
        content: str,
        context: dict[str, Any],
    ) -> ReviewOutcome:
        return ReviewOutcome(status="skipped", reviewer="NullCoverageReviewer")


_SENTENCE_SPLIT = re.compile(r"[。；\n]+")


def _sentences(value: Any) -> list[str]:
    text = str(value or "")
    return [
        re.sub(r"\s+", " ", piece).strip()
        for piece in _SENTENCE_SPLIT.split(text)
        if re.sub(r"\s+", " ", piece).strip()
    ]


class DeterministicCoverageReviewer:
    """Test-grade heuristic: full acceptance sentences must appear verbatim.

    Explicitly documented as a local, deterministic rule for isolated tests -
    NOT production semantic truth. Merely mentioning a term or answering a
    request does not satisfy it; the complete authored acceptance statement
    must be present in the delivered content.
    """

    async def review(
        self,
        items: list[dict[str, Any]],
        content: str,
        context: dict[str, Any],
    ) -> ReviewOutcome:
        normalized = re.sub(r"\s+", " ", content or "")
        confirmed: list[str] = []
        verdicts: dict[str, dict[str, Any]] = {}
        for item in items:
            if item.get("requirement") != "REQUIRED":
                continue
            acceptance = _sentences(item.get("acceptance"))
            if not acceptance:
                verdicts[str(item["item_id"])] = {
                    "decision": "uncertain",
                    "reason": "spec acceptance missing",
                    "evidence_quote": "",
                }
                continue
            if all(sentence in normalized for sentence in acceptance):
                confirmed.append(str(item["item_id"]))
                verdicts[str(item["item_id"])] = {
                    "decision": "covered",
                    "reason": "deterministic acceptance-sentence rule",
                    "evidence_quote": " ".join(acceptance),
                }
            else:
                verdicts[str(item["item_id"])] = {
                    "decision": "not_covered",
                    "reason": "deterministic acceptance-sentence rule not satisfied",
                    "evidence_quote": "",
                }
        return ReviewOutcome(
            status="completed",
            confirmed=confirmed,
            verdicts=verdicts,
            reviewer="DeterministicCoverageReviewer",
        )


class ModelCoverageReviewer:
    """Production reviewer: one independent, default-off model call.

    The verdicts are candidates. Every ``covered`` verdict must carry an
    evidence quote that the server later verifies against the saved body, and
    every id must belong to the frozen spec items passed in. Malformed output,
    refusals and transport errors fail closed: nothing is confirmed and the
    teaching itself is never touched.
    """

    def __init__(self, invoke: Invoke, *, model: str, max_tokens: int = 800):
        self.invoke = invoke
        self.model = model
        self.max_tokens = max_tokens

    async def review(
        self,
        items: list[dict[str, Any]],
        content: str,
        context: dict[str, Any],
    ) -> ReviewOutcome:
        required = [item for item in items if item.get("requirement") == "REQUIRED"]
        prompt_items = [
            {
                "item_id": str(item["item_id"]),
                "objective": str(item.get("objective") or ""),
                "acceptance": str(item.get("acceptance") or ""),
            }
            for item in required
        ]
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 CourseMate 的覆盖评审器。你只评审已经完整保存的教学内容是否"
                    "实际完成了给定 REQUIRED 教学项，不授课、不评分、不决定学生是否掌握。"
                    "逐项输出判定：covered / partial / not_covered / uncertain；"
                    "covered 必须给出正文中真实存在的证据引文（逐字），不确定就不要判 covered。"
                    "只输出 JSON，形如 {\"verdicts\":[{\"item_id\":\"…\",\"decision\":\"covered\","
                    "\"reason\":\"…\",\"evidence_quote\":\"…\"}]}。只使用给定 item_id。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "spec_version": context.get("spec_version"),
                        "items": prompt_items,
                        "teaching_content": content,
                        "student_question": context.get("student_question", ""),
                        "bridge_question": context.get("bridge_question"),
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            raw = await self.invoke(messages, self.max_tokens)
            verdicts, error = _parse_verdicts(raw, {str(i["item_id"]) for i in required})
            confirmed = [
                item_id
                for item_id, verdict in verdicts.items()
                if verdict.get("decision") == "covered"
                and str(verdict.get("evidence_quote") or "").strip()
            ]
            return ReviewOutcome(
                status="completed" if error == "" else "failed",
                confirmed=confirmed,
                verdicts=verdicts,
                error=error,
                reviewer="ModelCoverageReviewer",
            )
        except Exception as error:  # fail closed: no coverage, teaching untouched
            return ReviewOutcome(
                status="failed",
                reviewer="ModelCoverageReviewer",
                error=f"{type(error).__name__}: {str(error)[:200]}",
            )


def _parse_verdicts(raw: str, known_ids: set[str]) -> tuple[dict[str, dict[str, Any]], str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        return {}, f"invalid reviewer JSON: {error.msg[:120]}"
    if not isinstance(data, dict):
        return {}, "reviewer output is not an object"
    rows = data.get("verdicts")
    if not isinstance(rows, list):
        return {}, "reviewer output lacks a verdicts list"
    verdicts: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("item_id") or "")
        if item_id not in known_ids:
            continue  # out-of-scope or forged ids never write coverage
        decision = str(row.get("decision") or "")
        if decision not in DECISIONS:
            continue
        verdicts[item_id] = {
            "decision": decision,
            "reason": str(row.get("reason") or "")[:1000],
            "evidence_quote": str(row.get("evidence_quote") or "")[:2000],
        }
    return verdicts, ""


def qwen_review_invoke(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: float,
    allow_billable: bool,
) -> Invoke:
    """Build the production HTTP invoke over the site's single Qwen credential.

    The billable gate is checked BEFORE any network request, and there are no
    implicit retries: an unknown outcome is recorded as unknown, never retried
    to fake exactly-once billing.
    """

    import httpx

    async def invoke(messages: list[dict[str, str]], max_tokens: int) -> str:
        if not allow_billable:
            raise RuntimeError("BILLING_NOT_AUTHORIZED: coverage review is disabled")
        endpoint = base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": False,
            "enable_thinking": False,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=12)) as client:
            response = await client.post(
                endpoint, headers={"Authorization": "Bearer " + api_key}, json=body
            )
        if response.status_code != 200:
            raise RuntimeError(f"PROVIDER_HTTP_{response.status_code}")
        data = response.json()
        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise RuntimeError("INVALID_PROVIDER_RESPONSE")
        choice = choices[0]
        if choice.get("finish_reason") not in (None, "stop"):
            raise RuntimeError("INCOMPLETE_PROVIDER_RESPONSE")
        content = (choice.get("message") or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("EMPTY_REVIEWER_RESPONSE")
        return content

    return invoke


def resolve_coverage_reviewer(
    environment: str,
    name: str | None,
    *,
    allow_billable: bool,
    base_url: str = "",
    api_key: str = "",
    model: str = "",
    timeout: float = 60.0,
) -> CoverageReviewer:
    """Resolve the configured reviewer with environment guards.

    ``none`` (default) never claims coverage. ``deterministic`` is local/test
    only. ``model`` is the production reviewer: it requires the same site
    credential as the two-stage flow, and enabling it is a separate paid
    authorization (``allow_billable``); without it the resolver refuses before
    any request can be built.
    """

    mode = (name or "none").strip().lower()
    if mode in {"", "none"}:
        return NullCoverageReviewer()
    if mode == "deterministic":
        if environment == "production":
            raise ValueError("Deterministic coverage review is forbidden in production")
        return DeterministicCoverageReviewer()
    if mode == "model":
        if not allow_billable:
            raise ValueError(
                "Model coverage review is a separately billed third call; "
                "enable CMUI_ALLOW_BILLABLE only after the budget is approved."
            )
        if not base_url or not api_key or not model:
            raise ValueError("Model coverage review requires the site model credential.")
        return ModelCoverageReviewer(
            qwen_review_invoke(
                base_url=base_url,
                api_key=api_key,
                model=model,
                timeout=timeout,
                allow_billable=allow_billable,
            ),
            model=model,
        )
    raise ValueError(f"Unknown coverage reviewer mode: {name!r}")
