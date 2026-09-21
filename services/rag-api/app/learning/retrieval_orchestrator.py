"""Global candidate fusion for the integrated retrieval chain.

Why this module exists
----------------------
The V3 UI adapter used to call the official retrieval first, append the private
workspace retrieval and then keep the first `top_k` items. With `top_k = 2` and
two candidates per scope the private space was searched and then silently
dropped: official hits filled every slot regardless of relevance
(`ISOLATED_SOURCE_PROBES.json`, finding "candidate_truncation").

This orchestrator fixes the ordering bug — nothing else — before any semantic
(Jev) judgement is layered on top:

    authorized scopes -> per-scope candidates with rank evidence
    -> dedupe by chunk id -> ONE global ranking (reciprocal rank fusion)
    -> exact-target protection (an explicitly referenced file/page/question
       keeps its slot; it may not be replaced by a semantically "similar" hit)
    -> text budget with boundary-aware truncation
    -> public projection (S1..Sn assigned only here)

Design constraints taken from the governing plan:

* Source identity (official vs private) is NOT a ranking score. Both scopes are
  already authorized before fusion; a private note in the same course must be
  able to outrank an official fragment.
* Rank evidence is kept per scope (`ranks`, `scopes`) so a later decision layer
  can compare candidates on one scale instead of trusting append order.
* This module never calls a model. It is deterministic and cheap by design, so
  the deterministic state fix is not credited to any semantic layer.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

DEFAULT_RANK_CONSTANT = 60
DEFAULT_MAX_CANDIDATES = 40
DEFAULT_PER_HIT_CHARS = 4000

_FILE_NAME = re.compile(r"[\w\u4e00-\u9fff][\w\u4e00-\u9fff .()\-]{0,80}\.(?:pdf|docx|pptx|txt|md|csv|ipynb|png|jpe?g|webp)", re.I)
_QUESTION_REF = re.compile(r"(?:question|q|题|第)\s*([0-9]{1,3})", re.I)
_PAGE_REF = re.compile(r"(?:page|p\.?|页)\s*([0-9]{1,4})", re.I)


@dataclass(frozen=True)
class ExactTarget:
    """An explicitly referenced locator the ranking must not displace."""

    kind: str  # 'file' | 'page' | 'question'
    value: str
    raw: str


@dataclass(frozen=True)
class ScopedCandidates:
    """Candidates recalled from one authorized scope, in that scope's rank order."""

    scope: str
    hits: Sequence[Any]


@dataclass
class FusedHit:
    hit: Any
    score: float
    scopes: tuple[str, ...]
    ranks: dict[str, int] = field(default_factory=dict)
    exact: bool = False

    @property
    def chunk_id(self) -> str:
        return str(getattr(self.hit, "chunk_id", "") or id(self.hit))


def exact_targets_from_query(query: str) -> tuple[ExactTarget, ...]:
    """Extract explicit file / page / question references from the raw query."""

    targets: list[ExactTarget] = []
    for match in _FILE_NAME.finditer(query or ""):
        targets.append(ExactTarget("file", match.group(0).strip().casefold(), match.group(0).strip()))
    for match in _PAGE_REF.finditer(query or ""):
        targets.append(ExactTarget("page", match.group(1), match.group(0).strip()))
    for match in _QUESTION_REF.finditer(query or ""):
        targets.append(ExactTarget("question", match.group(1), match.group(0).strip()))
    return tuple(targets)


def _hit_matches_target(hit: Any, target: ExactTarget) -> bool:
    if target.kind == "file":
        return str(getattr(hit, "filename", "") or "").casefold() == target.value
    if target.kind == "page":
        locator_type = str(getattr(hit, "locator_type", "") or "").casefold()
        locator_value = str(getattr(hit, "locator_value", "") or "")
        return locator_type in {"page", "slide"} and locator_value == target.value
    if target.kind == "question":
        locator_value = str(getattr(hit, "locator_value", "") or "")
        section = str(getattr(hit, "section", "") or "")
        if locator_value == target.value:
            return True
        numbers = set(re.findall(r"[0-9]{1,3}", section))
        return target.value in numbers
    return False


def fuse_scoped_candidates(
    groups: Iterable[ScopedCandidates],
    *,
    top_k: int,
    rank_constant: int = DEFAULT_RANK_CONSTANT,
    scope_weights: dict[str, float] | None = None,
    exact_targets: Sequence[ExactTarget] = (),
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> list[FusedHit]:
    """Fuse authorized scopes into ONE ranking and return at most `top_k` hits.

    Reciprocal rank fusion: each candidate contributes
    ``weight / (rank_constant + rank)`` per scope it appears in, where `rank` is
    its 1-based position inside that scope. Ranks are comparable across scopes
    because every scope is already access-controlled and equally trusted;
    weights exist only to express a deliberate product preference, never to
    model "official beats private".
    """

    weights = scope_weights or {}
    fused: dict[str, FusedHit] = {}
    order: dict[str, int] = {}
    for group in groups:
        weight = float(weights.get(group.scope, 1.0))
        # Each authorized scope contributes at most its own recall width; the cap
        # is applied PER SCOPE on purpose. Applying it while iterating scopes in
        # append order is exactly the bug this module fixes: the first scope
        # would consume the whole budget and later scopes would never compete.
        for rank, hit in enumerate(list(group.hits)[:max_candidates], start=1):
            chunk_id = str(getattr(hit, "chunk_id", "") or "")
            if not chunk_id:
                # A candidate without a stable identity cannot be deduped or
                # cited; keep it out of the fused ranking instead of guessing.
                continue
            contribution = weight / (rank_constant + rank)
            entry = fused.get(chunk_id)
            if entry is None:
                entry = FusedHit(hit=hit, score=0.0, scopes=())
                fused[chunk_id] = entry
                order[chunk_id] = len(order)
            entry.score += contribution
            entry.ranks[group.scope] = rank
            entry.scopes = tuple(sorted({*entry.scopes, group.scope}))
    matched: list[FusedHit] = []
    for entry in fused.values():
        entry.exact = any(
            _hit_matches_target(entry.hit, target) for target in exact_targets
        )
        matched.append(entry)
    # Exact targets first (stable), then the fused ranking; ties break on first
    # appearance so the result is deterministic for identical inputs.
    matched.sort(key=lambda item: (not item.exact, -item.score, order[item.chunk_id]))
    return matched[: max(0, top_k)]


def budget_text(text: str, budget: int, *, per_hit_chars: int = DEFAULT_PER_HIT_CHARS) -> str:
    """Trim to a budget without cutting mid-token where a boundary is nearby.

    The previous implementation divided the context budget by the hit's list
    position, which could cut formulas, units or table headers in half. Here the
    cut lands on the nearest paragraph/sentence/line boundary inside the budget
    and marks the truncation explicitly.
    """

    limit = min(int(budget), per_hit_chars)
    if limit <= 0 or len(text) <= limit:
        return text
    window = text[:limit]
    for boundary in ("\n\n", "\n", "。 ", "。", ". ", "；", ";"):
        index = window.rfind(boundary)
        if index >= limit // 2:
            return window[: index + len(boundary)].rstrip() + " …"
    return window.rstrip() + " …"


def citation_id(index: int) -> str:
    """Public reference id assigned only at projection time (S1..Sn)."""

    return f"S{index}"


def trace_digest(fused: Sequence[FusedHit]) -> str:
    """Stable digest of the ranking decision, stored for audit (no raw text)."""

    payload = "|".join(
        f"{item.chunk_id}:{item.score:.6f}:{','.join(item.scopes)}:{int(item.exact)}"
        for item in fused
    )
    return hashlib.sha256(payload.encode()).hexdigest()
