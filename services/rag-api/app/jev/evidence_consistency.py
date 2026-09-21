"""EvidenceConsistency: condition/conflict check inside evidence-pack construction.

Where it sits (deterministic-first chain)::

    permissions -> exact locator -> recall -> merge/dedupe -> relevance (rerank)
    -> condition/conflict check (this module) -> evidence pack

It runs **after** the global RRF fusion and the Jev rerank and **before** the
evidence pack is handed to DeepSeek. It is an *annotation* layer: it never
reorders, drops or adds a candidate, so the retrieval rules cannot regress here:

* an exact file/page/question target keeps its slot (this module does not touch
  ordering at all),
* official candidates may not crowd out private ones (no reordering),
* a semantic score may never replace a user's explicit target (no scores here),
* a rerank may only reorder authorized candidates (this module reorders nothing).

It compares candidate **pairs** that code first narrows deterministically (same
concept, same numeric value/variable, or an explicit version relation) and lets
Jev look at **at most 8 pairs** per request — never an O(n^2) model comparison.
The report records how many comparable pairs were left unchecked, so a caller can
never be led to believe the whole corpus was compared.

Relations (the ``evidence.consistency.v1`` Choice candidates)::

    SAME_CONTEXT_CONTRADICTION   a genuine conflict under identical assumptions
    DIFFERENT_ASSUMPTIONS        each valid under its own stated conditions/scope
    VERSION_OR_TASK_DIFFERENCE   different versions or different tasks (deterministic)
    COMPATIBLE                   agree or complement
    INSUFFICIENT_EVIDENCE        fragments too thin to judge

Business output handling:

* a real contradiction keeps **both** sources and requests that DeepSeek explain
  the conflict and its boundary (``needs_deepseek_conflict_explanation``);
* different assumptions are explained as different scopes (never a conflict);
* missing evidence (a real Jev ``INSUFFICIENT_EVIDENCE``) records a bounded
  extra-read request for the caller, never a drop;
* a newer document never overrides older conclusions unless an explicit
  version/correction relation exists — version differences surface as
  ``VERSION_OR_TASK_DIFFERENCE``, never as an override or a contradiction.

A prompt-injection signal is **only a marker**: a legitimate example of prompt
injection inside teaching material is annotated (``prompt_injection_markers``)
and the document is never dropped, and system permissions are never decided by
any "safety" score here (there is none).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from app.jev.catalog import DecisionDefinition
from app.jev.gateway import DecisionRequest
from app.jev.models import CacheScope
from app.jev.service import SemanticDecisionService

# Pending catalog registration (see report + STRUCTURED_DECISION_CONTRACTS.md).
# Deliberately NOT added to decision_catalog.json: another workstream registers it.
EVIDENCE_CONSISTENCY_KEY = "evidence.consistency.v1"

SAME_CONTEXT_CONTRADICTION = "SAME_CONTEXT_CONTRADICTION"
DIFFERENT_ASSUMPTIONS = "DIFFERENT_ASSUMPTIONS"
VERSION_OR_TASK_DIFFERENCE = "VERSION_OR_TASK_DIFFERENCE"
COMPATIBLE = "COMPATIBLE"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

RELATIONS = (
    SAME_CONTEXT_CONTRADICTION,
    DIFFERENT_ASSUMPTIONS,
    VERSION_OR_TASK_DIFFERENCE,
    COMPATIBLE,
    INSUFFICIENT_EVIDENCE,
)

# The owner's pair budget: Jev sees at most this many candidate pairs per request.
DEFAULT_MAX_PAIRS = 8
# Bounded per-candidate text sent to Jev for a pair comparison.
_MAX_SEMANTIC_TEXT_CHARS = 2_000
# Bounded extra-read candidates surfaced for INSUFFICIENT_EVIDENCE (one read total).
_MAX_EXTRA_READ_CANDIDATES = 2

# The pending definition, held as a module constant (a real DecisionDefinition, not
# a catalog entry). It is used to build the DecisionRequest the gateway evaluates,
# so modes/bounds/receipts still apply exactly like a registered definition.
_EVIDENCE_CONSISTENCY_DEFINITION = DecisionDefinition(
    key=EVIDENCE_CONSISTENCY_KEY,
    primitive="Choice",
    required_state=("left", "right"),
    criteria={relation: relation for relation in RELATIONS},
    instructions=(
        "Classify the relation between two already-authorized evidence candidates "
        "about the same concept/value in the same context. SAME_CONTEXT_CONTRADICTION "
        "only for a genuine conflict under identical assumptions; DIFFERENT_ASSUMPTIONS "
        "when each is valid under different stated conditions; VERSION_OR_TASK_DIFFERENCE "
        "when they concern different versions or tasks; COMPATIBLE when both agree or "
        "complement; INSUFFICIENT_EVIDENCE when the fragments are too thin to judge. "
        "Never infer a document should be dropped or a permission changed."
    ),
    failure_policy="COMPATIBLE (keep both, no conflict escalation).",
    cache_scope=(
        "authorization_scope",
        "course",
        "workspace",
        "material_revision",
        "node_spec_version",
        "question_definition_hash",
        "input_hash",
        "provider_model_version",
    ),
)

# Deterministic narrowing signatures.
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]+")
_VALUE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*"
    r"(%|percent|percentage\s+points?|个百分点|百分点|km|m/s|ms|kg|℃|°C|°F|m|s)",
    re.I,
)
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
        "has", "have", "had", "not", "but", "will", "would", "should", "can", "could",
        "may", "might", "must", "than", "then", "also", "into", "over", "under",
        "between", "before", "after", "such", "these", "those", "they", "them",
        "their", "there", "here", "where", "when", "what", "which", "who", "how",
        "why", "you", "your", "all", "any", "each", "every", "some", "more", "most",
        "other", "only", "very", "just", "about", "above", "below", "example",
        "examples", "text", "content", "course", "material", "page", "pages",
        "section", "chapter", "question", "answer", "evidence", "source", "sources",
        "document", "file", "notes", "note",
    }
)
_PROMPT_INJECTION_MARKER = re.compile(
    r"ignore\s+(?:all\s+)?(?:previous\s+|prior\s+)?instructions"
    r"|disregard\s+(?:all\s+)?instructions"
    r"|forget\s+(?:all\s+)?(?:previous\s+)?instructions"
    r"|do\s+not\s+follow\s+",
    re.I,
)


def _canonical_unit(unit: str) -> str:
    """Fold a unit token to one comparable key without erasing its meaning."""
    normalized = unit.casefold().strip()
    if normalized in {"%", "percent"}:
        return "percent"
    if normalized in {"percentage points", "percentage point", "个百分点", "百分点"}:
        return "percentage_points"
    return normalized


def _variables(text: str) -> frozenset[str]:
    """Numeric value/quantity tokens (number + unit), e.g. ``5|percent``.

    ``5%`` and ``5 percentage points`` canonicalize to different keys and are
    therefore never treated as the same value.
    """
    found: set[str] = set()
    for number, unit in _VALUE.findall(text):
        found.add(f"{number}|{_canonical_unit(unit)}")
    return frozenset(found)


def _concepts(text: str) -> frozenset[str]:
    """Significant topic tokens (ASCII words length >= 3, or CJK runs)."""
    found: set[str] = set()
    for token in _WORD.findall(text):
        key = token.casefold()
        if key in _STOPWORDS:
            continue
        found.add(key)
        if len(found) >= 64:
            break
    return frozenset(found)


@dataclass(frozen=True)
class _Candidate:
    index: int
    candidate_id: str
    document_id: str
    version: str
    section: str
    locator: str
    text: str
    variables: frozenset[str]
    concepts: frozenset[str]


def _candidate_view(index: int, candidate: Any) -> _Candidate:
    hit = getattr(candidate, "hit", candidate)
    text = str(getattr(hit, "content", "") or "")
    candidate_id = str(getattr(candidate, "chunk_id", "") or getattr(hit, "chunk_id", "") or "")
    if not candidate_id:
        candidate_id = f"candidate-{index}"
    document_id = str(getattr(hit, "document_id", "") or getattr(hit, "filename", "") or "")
    version = str(getattr(hit, "version", "") or getattr(hit, "revision", "") or "")
    section = str(getattr(hit, "section", "") or "")
    locator = f"{getattr(hit, 'locator_type', '')}:{getattr(hit, 'locator_value', '')}"
    return _Candidate(
        index=index,
        candidate_id=candidate_id,
        document_id=document_id,
        version=version,
        section=section,
        locator=str(locator),
        text=text,
        variables=_variables(text),
        concepts=_concepts(text),
    )


@dataclass(frozen=True)
class ComparablePair:
    """One deterministic narrowing: a pair worth comparing, and why."""

    left_id: str
    right_id: str
    reason: str  # "version" | "task" | "variable" | "concept"
    deterministic_relation: str | None = None  # set for version/task (zero Jev)


@dataclass(frozen=True)
class ConsistencyFinding:
    """The relation for one compared pair."""

    relation: str
    left_id: str
    right_id: str
    reason: str
    used_jev: bool


@dataclass(frozen=True)
class ConsistencyDecision:
    """The gateway result for one pair comparison."""

    relation: str
    used_jev: bool
    mode: str
    outcome: str
    receipt_id: str | None


@dataclass
class ConsistencyReport:
    """Everything the caller needs to build (or annotate) the evidence pack."""

    findings: list[ConsistencyFinding] = field(default_factory=list)
    comparable_pairs: int = 0
    checked_pairs: int = 0
    unchecked_pairs: int = 0
    total_possible_pairs: int = 0
    requested_extra_reads: tuple[str, ...] = ()
    prompt_injection_markers: tuple[str, ...] = ()
    dropped_ids: tuple[str, ...] = ()  # invariant: always empty

    @property
    def needs_deepseek_conflict_explanation(self) -> bool:
        """A genuine contradiction exists and DeepSeek should explain its boundary."""
        return any(
            finding.relation == SAME_CONTEXT_CONTRADICTION for finding in self.findings
        )

    @property
    def contradictions(self) -> list[ConsistencyFinding]:
        return [f for f in self.findings if f.relation == SAME_CONTEXT_CONTRADICTION]

    @property
    def version_differences(self) -> list[ConsistencyFinding]:
        return [f for f in self.findings if f.relation == VERSION_OR_TASK_DIFFERENCE]

    @property
    def different_assumptions(self) -> list[ConsistencyFinding]:
        return [f for f in self.findings if f.relation == DIFFERENT_ASSUMPTIONS]


def narrow_candidate_pairs(candidates: Sequence[Any]) -> list[ComparablePair]:
    """Deterministically narrow candidate pairs (never O(n^2) in the model).

    Pairs are produced by grouping candidates on, in priority order:

    1. same document -> ``version`` (different revisions) or ``task`` (different
       section/locator): these carry a deterministic ``VERSION_OR_TASK_DIFFERENCE``
       relation and cost zero Jev calls;
    2. same numeric value/quantity (``variable``);
    3. same significant concept token (``concept``).

    Within each group only *adjacent* candidates are paired, so the number of
    pairs is linear in the number of candidates — the model never sees a full
    cross product.
    """
    views = [_candidate_view(index, candidate) for index, candidate in enumerate(candidates)]
    return _narrow_pairs(views)


def _narrow_pairs(views: Sequence[_Candidate]) -> list[ComparablePair]:
    pairs: list[ComparablePair] = []
    seen: set[tuple[int, int]] = set()

    def add(index_a: int, index_b: int, reason: str, relation: str | None = None) -> None:
        if index_a == index_b:
            return
        key = (index_a, index_b) if index_a < index_b else (index_b, index_a)
        if key in seen:
            return
        seen.add(key)
        pairs.append(
            ComparablePair(
                left_id=views[index_a].candidate_id,
                right_id=views[index_b].candidate_id,
                reason=reason,
                deterministic_relation=relation,
            )
        )

    by_document: dict[str, list[int]] = {}
    for index, view in enumerate(views):
        if view.document_id:
            by_document.setdefault(view.document_id, []).append(index)
    for indices in by_document.values():
        for a, b in pairwise(indices):
            left, right = views[a], views[b]
            if left.version and right.version and left.version != right.version:
                add(a, b, "version", VERSION_OR_TASK_DIFFERENCE)
            elif left.section != right.section or left.locator != right.locator:
                add(a, b, "task", VERSION_OR_TASK_DIFFERENCE)

    by_variable: dict[str, list[int]] = {}
    for index, view in enumerate(views):
        for variable in view.variables:
            by_variable.setdefault(variable, []).append(index)
    for indices in by_variable.values():
        for a, b in pairwise(indices):
            add(a, b, "variable")

    by_concept: dict[str, list[int]] = {}
    for index, view in enumerate(views):
        for concept in view.concepts:
            by_concept.setdefault(concept, []).append(index)
    for indices in by_concept.values():
        for a, b in pairwise(indices):
            add(a, b, "concept")

    return pairs


def _consistency_decision(
    service: SemanticDecisionService,
    left_text: str,
    right_text: str,
    scope: CacheScope | None,
) -> ConsistencyDecision:
    request = DecisionRequest(
        definition=_EVIDENCE_CONSISTENCY_DEFINITION,
        state={
            "left": left_text[:_MAX_SEMANTIC_TEXT_CHARS],
            "right": right_text[:_MAX_SEMANTIC_TEXT_CHARS],
        },
        caller_role="evidence_consistency",
        cache_scope=scope or CacheScope(),
        criteria={relation: relation for relation in RELATIONS},
    )
    decision = service.gateway.evaluate(request)
    suggestion = decision.suggestion
    used = decision.mode == "on" and suggestion is not None
    relation = COMPATIBLE
    if used and suggestion is not None and suggestion.choice is not None:
        relation = suggestion.choice
    return ConsistencyDecision(
        relation=relation,
        used_jev=used,
        mode=decision.mode,
        outcome=decision.outcome,
        receipt_id=decision.receipt_id,
    )


def check_evidence_consistency(
    service: SemanticDecisionService | None,
    candidates: Sequence[Any],
    *,
    scope: CacheScope | None = None,
    max_pairs: int = DEFAULT_MAX_PAIRS,
) -> ConsistencyReport:
    """Run the condition/conflict check over already-reranked authorized candidates.

    The candidate list is never mutated; the returned report is an annotation the
    caller folds into the evidence pack. A pair whose relation must be judged
    semantically is handed to Jev at most ``max_pairs`` times (default 8); any
    further comparable pair is recorded in ``unchecked_pairs``, and
    ``total_possible_pairs`` makes the un-compared cross product explicit.
    """
    views = [_candidate_view(index, candidate) for index, candidate in enumerate(candidates)]
    report = ConsistencyReport()
    report.total_possible_pairs = len(views) * (len(views) - 1) // 2
    report.prompt_injection_markers = tuple(
        view.candidate_id for view in views if _PROMPT_INJECTION_MARKER.search(view.text)
    )
    by_id = {view.candidate_id: view for view in views}

    pairs = _narrow_pairs(views)
    report.comparable_pairs = len(pairs)

    semantic_budget = max(0, max_pairs)
    semantic_used = 0
    unchecked = 0
    extra_read_ids: list[str] = []
    for pair in pairs:
        if pair.deterministic_relation is not None:
            report.findings.append(
                ConsistencyFinding(
                    relation=pair.deterministic_relation,
                    left_id=pair.left_id,
                    right_id=pair.right_id,
                    reason=pair.reason,
                    used_jev=False,
                )
            )
            continue
        if semantic_used >= semantic_budget:
            unchecked += 1
            continue
        semantic_used += 1
        left_view = by_id.get(pair.left_id)
        right_view = by_id.get(pair.right_id)
        if service is None or left_view is None or right_view is None:
            relation = COMPATIBLE
            used = False
        else:
            decision = _consistency_decision(service, left_view.text, right_view.text, scope)
            relation = decision.relation
            used = decision.used_jev
        report.findings.append(
            ConsistencyFinding(
                relation=relation,
                left_id=pair.left_id,
                right_id=pair.right_id,
                reason=pair.reason,
                used_jev=used,
            )
        )
        if used and relation == INSUFFICIENT_EVIDENCE:
            for candidate_id in (pair.left_id, pair.right_id):
                if candidate_id not in extra_read_ids:
                    extra_read_ids.append(candidate_id)

    report.unchecked_pairs = unchecked
    report.checked_pairs = len(report.findings)
    report.requested_extra_reads = tuple(extra_read_ids[:_MAX_EXTRA_READ_CANDIDATES])
    report.dropped_ids = ()
    return report


class EvidenceConsistency:
    """Thin service wrapper for :func:`check_evidence_consistency`."""

    def __init__(
        self, service: SemanticDecisionService | None, *, max_pairs: int = DEFAULT_MAX_PAIRS
    ) -> None:
        self.service = service
        self.max_pairs = max_pairs

    def check(
        self, candidates: Sequence[Any], *, scope: CacheScope | None = None
    ) -> ConsistencyReport:
        return check_evidence_consistency(
            self.service, candidates, scope=scope, max_pairs=self.max_pairs
        )


def deepseek_conflict_prompt(finding: ConsistencyFinding) -> str:
    """The explanation request handed to DeepSeek for a genuine contradiction."""
    return (
        f"Two retained sources about the same concept conflict under identical "
        f"assumptions ({finding.left_id} vs {finding.right_id}). Explain the "
        f"conflict and its boundary of applicability; keep both sources."
    )


__all__ = [
    "COMPATIBLE",
    "ComparablePair",
    "ConsistencyDecision",
    "ConsistencyFinding",
    "ConsistencyReport",
    "DIFFERENT_ASSUMPTIONS",
    "DEFAULT_MAX_PAIRS",
    "EVIDENCE_CONSISTENCY_KEY",
    "EvidenceConsistency",
    "INSUFFICIENT_EVIDENCE",
    "RELATIONS",
    "SAME_CONTEXT_CONTRADICTION",
    "VERSION_OR_TASK_DIFFERENCE",
    "check_evidence_consistency",
    "deepseek_conflict_prompt",
    "narrow_candidate_pairs",
]
