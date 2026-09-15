"""Injectable coverage review for free-text shell deliveries.

The refreshed shell teaches with free text; whether that text actually delivers
a REQUIRED teaching item is a semantic judgment the server cannot make by
itself. This module owns that judgment behind one injectable interface so the
local/tests can run deterministically and production never claims coverage
without an authorized reviewer.

* ``NullCoverageReviewer`` (default): nothing is confirmed; teaching content is
  still recorded as a teaching unit, but no coverage evidence is written.
* ``DeterministicCoverageReviewer``: a documented test-grade heuristic - an
  item counts only when EVERY sentence of its authored acceptance statement
  appears in the delivered content. It is rejected in production.
* Model review: a paid Qwen call evaluating the content against the items is
  the intended production reviewer; it is NOT implemented and NOT authorized,
  so ``resolve_coverage_reviewer`` raises instead of silently downgrading.
"""

from __future__ import annotations

import re
from typing import Any, Protocol


class CoverageReviewer(Protocol):
    def review(
        self,
        items: list[dict[str, Any]],
        content: str,
        context: dict[str, Any],
    ) -> list[str]:
        """Return the item_ids this delivery is confirmed to cover."""


class NullCoverageReviewer:
    """No semantic confirmation available; no coverage is claimed."""

    def review(
        self,
        items: list[dict[str, Any]],
        content: str,
        context: dict[str, Any],
    ) -> list[str]:
        return []


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

    def review(
        self,
        items: list[dict[str, Any]],
        content: str,
        context: dict[str, Any],
    ) -> list[str]:
        normalized = re.sub(r"\s+", " ", content or "")
        confirmed: list[str] = []
        for item in items:
            if item.get("requirement") != "REQUIRED":
                continue
            acceptance = _sentences(item.get("acceptance"))
            if not acceptance:
                continue
            if all(sentence in normalized for sentence in acceptance):
                confirmed.append(str(item["item_id"]))
        return confirmed


def resolve_coverage_reviewer(
    environment: str,
    name: str | None,
    *,
    allow_billable: bool,
) -> CoverageReviewer:
    """Resolve the configured reviewer with environment guards.

    ``none`` (default) never claims coverage. ``deterministic`` is local/test
    only. ``model`` is the documented paid option and is refused until it is
    implemented and billing is authorized.
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
            raise ValueError("Model coverage review requires authorized billing")
        raise NotImplementedError(
            "The paid model coverage reviewer is documented but not implemented; "
            "see QWEN_LIVE_TWO_STAGE_REPORT.md for the planned cost."
        )
    raise ValueError(f"Unknown coverage reviewer mode: {name!r}")
