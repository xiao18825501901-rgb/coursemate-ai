"""The 12 real business call sites the CourseMate layer invokes.

These are thin, business-facing wrappers over :class:`LayaDecisionService`. They
are what the business modules import — not the gateway, not the compiler — so a
decision can never be reached except through its one documented call site.

Each function takes ``service`` (a :class:`LayaDecisionService`, or ``None`` to run
the fully deterministic path with zero Laya calls) plus business-shaped inputs and
returns a business-shaped value. Observability (definition id + version, mode,
``path`` = ``laya`` or ``fallback:<reason>``, latency, distribution concentration,
receipt id) is recorded on ``service.records``/``service.summary()``; the counts are
exposed there so a test can assert them without reaching into the adapter.
"""

from __future__ import annotations

from typing import Any, Sequence

from app.laya.compiler import TemplateOption
from app.laya.decisions import DEFAULT_MAX_EVAL_CANDIDATES, LayaDecisionService
from app.laya.models import LayaScope

# Citation support signals: only a real Laya "unsupported" is high-risk and may
# trigger a DeepSeek/deterministic review; a fallback is UNVERIFIED and is never
# presented as a Laya decision.
SUPPORTED = "SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"
UNVERIFIED = "UNVERIFIED"


def rerank_retrieval(
    service: LayaDecisionService | None,
    entries: Sequence[Any],
    *,
    query: str,
    scope: LayaScope,
    max_candidates: int = DEFAULT_MAX_EVAL_CANDIDATES,
) -> list[Any]:
    """1. Retrieval re-rank: reorder only, never add or drop a source.

    Exact file/page/question targets keep their slot no matter what the model
    says; official candidates never crowd out private ones (that ordering is fixed
    before this call). Off/shadow/failed/timeout all return the original fused
    order.
    """
    if service is None:
        return list(entries)
    return service.rerank_retrieval(entries, query=query, cache_scope=scope,
                                     max_candidates=max_candidates)


def citation_support(
    service: LayaDecisionService | None,
    *,
    claim: str,
    source_span: str,
    source_version: str,
    task_scope: str,
    scope: LayaScope,
) -> str:
    """2a. Citation support: does this backend span substantively support the claim?

    Returns SUPPORTED / UNSUPPORTED (a real Laya signal) or UNVERIFIED (fallback).
    The model may never invent a source; span ids come from the backend.
    """
    if service is None:
        return UNVERIFIED
    result = service.supports_claim(
        claim=claim, source_span=source_span, source_version=source_version,
        task_scope=task_scope, cache_scope=scope,
    )
    if result.used_laya and isinstance(result.value, float):
        return SUPPORTED if result.value >= 0.5 else UNSUPPORTED
    return UNVERIFIED


def select_citation_span(
    service: LayaDecisionService | None,
    *,
    claim: str,
    candidate_spans: Sequence[str],
    scope: LayaScope,
) -> str:
    """2b. Span selection: select a supplied backend span id, never invent one."""
    if service is None:
        return "NO_SUPPORT"
    result = service.select_span(claim=claim, candidate_spans=candidate_spans,
                                 cache_scope=scope)
    return str(result.value)


def keep_history_segment(
    service: LayaDecisionService | None,
    *,
    segment: str,
    current_task: str,
    fixed_anchor: dict[str, Any],
    remaining_scope: str,
    scope: LayaScope,
) -> bool:
    """3. Context keep/drop for *optional* history only; fixed anchors never drop."""
    if service is None:
        return True
    return service.keep_segment(
        segment=segment, current_task=current_task, fixed_anchor=fixed_anchor,
        remaining_scope=remaining_scope, cache_scope=scope,
    )


def route_next_action(
    service: LayaDecisionService | None,
    *,
    message: str,
    fixed_anchor: dict[str, Any],
    current_mode: str,
    active_assessment: str | None,
    scope: LayaScope,
    deterministic: str = "OTHER",
) -> str:
    """4. Intent routing for *ambiguous* follow-ups only.

    Explicit commands (继续 / 暂停 / 只回答 / 显示答案 / ...) are answered by
    ``app.learning.intent_commands.route_explicit_command`` with ZERO Laya calls;
    the caller must route through that first and only reach here when it returns
    ``None``. The user's Thinking/strength choice is never changed here.
    """
    if service is None:
        return deterministic
    result = service.next_action(
        message=message, fixed_anchor=fixed_anchor, current_mode=current_mode,
        active_assessment=active_assessment, cache_scope=scope,
        deterministic=deterministic,
    )
    return str(result.value)


def select_pedagogy_method(
    service: LayaDecisionService | None,
    *,
    learner_request: str,
    known_prior_evidence: Any,
    topic: str,
    template_profile: Any,
    current_step: str,
    scope: LayaScope,
    deterministic: str = "CONTINUE",
) -> str:
    """5. Pedagogy: presentation method passed into the actual plan→work input."""
    if service is None:
        return deterministic
    result = service.next_method(
        learner_request=learner_request, known_prior_evidence=known_prior_evidence,
        topic=topic, template_profile=template_profile, current_step=current_step,
        cache_scope=scope, deterministic=deterministic,
    )
    return str(result.value)


def coverage_item_support(
    service: LayaDecisionService | None,
    items: Sequence[dict[str, Any]],
    *,
    content: str,
    spec_version: int | str,
    scope: LayaScope,
) -> dict[str, str]:
    """6. Coverage item support: a signal only; the backend still decides coverage."""
    if service is None:
        return {str(item["item_id"]): "UNCERTAIN" for item in items}
    return service.item_support(items, content=content, spec_version=spec_version,
                                cache_scope=scope)


def review_criterion(
    service: LayaDecisionService | None,
    *,
    frozen_question: dict[str, Any],
    criterion: dict[str, Any],
    reference_solution: str,
    student_answer: str,
    deterministic_verification: str,
    candidate_answer_spans: list[str],
    scope: LayaScope,
    deterministic: str = "NEEDS_REVIEW",
) -> str:
    """7. Assessment criterion review inside the grading loop.

    Never ``score * 100``, never zero because the service failed: the fallback is
    NEEDS_REVIEW (which routes to the existing review path) and the final marks are
    summed deterministically by the backend.
    """
    if service is None:
        return deterministic
    result = service.criterion_review(
        frozen_question=frozen_question, criterion=criterion,
        reference_solution=reference_solution, student_answer=student_answer,
        deterministic_verification=deterministic_verification,
        candidate_answer_spans=candidate_answer_spans, cache_scope=scope,
        deterministic=deterministic,
    )
    return str(result.value)


def match_template(
    service: LayaDecisionService | None,
    templates: Sequence[TemplateOption],
    *,
    state: dict[str, Any],
    scope: LayaScope,
) -> str:
    """8. Hierarchical template classification; "cannot decide" returns OTHER."""
    if service is None:
        return "OTHER"
    result = service.match_template(templates, state=state, cache_scope=scope)
    return str(result.value)


def select_exercise_prototype(
    service: LayaDecisionService | None,
    *,
    node: Any,
    eligible_prototypes: Sequence[str],
    recent_exposures: Any,
    learning_evidence: Any,
    scope: LayaScope,
) -> str:
    """9. Exercise prototype: a real authorized prototype id, never the answer."""
    if service is None:
        return "NONE"
    result = service.exercise_prototype(
        node=node, eligible_prototypes=eligible_prototypes,
        recent_exposures=recent_exposures, learning_evidence=learning_evidence,
        cache_scope=scope,
    )
    return str(result.value)


def select_prerequisite(
    service: LayaDecisionService | None,
    *,
    current_node: str,
    error: str,
    allowed_predecessor_nodes: Sequence[str],
    scope: LayaScope,
) -> str:
    """10. Prerequisite: legal neighbours only, never a new tree."""
    if service is None:
        return "NONE"
    result = service.prerequisite(
        current_node=current_node, error=error,
        allowed_predecessor_nodes=allowed_predecessor_nodes, cache_scope=scope,
    )
    return str(result.value)


def assess_corpus_quality(
    service: LayaDecisionService | None,
    *,
    document_fragment: str,
    source_metadata: dict[str, Any],
    parse_flags: list[str],
    scope: LayaScope,
) -> int:
    """11. Corpus quality: flag missing pages/stems/data; never auto-delete originals."""
    if service is None:
        return 1  # retain original; mark parse limitations for ingestion review
    result = service.corpus_quality(
        document_fragment=document_fragment, source_metadata=source_metadata,
        parse_flags=parse_flags, cache_scope=scope,
    )
    return int(result.value)


__all__ = [
    "SUPPORTED",
    "UNSUPPORTED",
    "UNVERIFIED",
    "assess_corpus_quality",
    "citation_support",
    "coverage_item_support",
    "keep_history_segment",
    "match_template",
    "rerank_retrieval",
    "review_criterion",
    "route_next_action",
    "select_citation_span",
    "select_exercise_prototype",
    "select_pedagogy_method",
    "select_prerequisite",
]
