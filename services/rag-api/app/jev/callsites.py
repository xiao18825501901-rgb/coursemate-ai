"""The real business call sites the CourseMate layer invokes.

This is the 12 case-derived decisions plus the structured-enhancement and Question Engine modules
that have a real business consumer (today: extraction field grounding, used by
the exact-locator reference path). They are thin, business-facing wrappers over
:class:`SemanticDecisionService`. They are what the business modules import — not
the gateway, not the service directly — so a decision can never be reached except
through its one documented call site.

Each function takes ``service`` (a :class:`SemanticDecisionService`, or ``None``
to run the fully deterministic path with zero Jev calls) plus business-shaped
inputs and returns a business-shaped value. Observability (definition key +
version, mode, ``path`` = ``jev`` or ``fallback:<reason>``, confidence, receipt
id, latency, and the rule-12 input budget) is recorded on the service and is
exposed through ``service.summary()`` so a test can assert it without reaching
into the adapter.

The input-budget helper (:func:`bounded_state`) keeps the decisive fields of a
state payload verbatim instead of blindly truncating the tail; when the decisive
content does not fit it lets the caller fall back deterministically rather than
sending a half-question.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.jev.service import (
    DEFAULT_MAX_EVAL_CANDIDATES,
    BudgetProvenance,
    DecisionResult,
    SemanticDecisionService,
    TemplateOption,
)

# Citation support signals: only a real Jev "unsupported" is high-risk and may
# trigger a DeepSeek/deterministic review; a fallback is UNVERIFIED and is never
# presented as a Jev decision.
SUPPORTED = "SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"
UNVERIFIED = "UNVERIFIED"


def bounded_state(
    service: SemanticDecisionService | None,
    definition_key: str,
    fields: dict[str, Any],
    *,
    must_keep: Sequence[str] = (),
    max_chars: int | None = None,
    candidate_count: int = 0,
) -> tuple[dict[str, Any], BudgetProvenance | None]:
    """Bound a state payload via the service's per-definition budget (rule 12).

    With ``service is None`` nothing is ever sent, so the fields are returned
    unchanged with no provenance. Otherwise this delegates to
    :meth:`SemanticDecisionService.bound_state`; the caller catches
    :class:`InputBudgetExceeded` and falls back deterministically.
    """
    if service is None:
        return fields, None
    return service.bound_state(
        definition_key,
        fields,
        must_keep=must_keep,
        max_chars=max_chars,
        candidate_count=candidate_count,
    )


def rerank_retrieval(
    service: SemanticDecisionService | None,
    entries: Sequence[Any],
    *,
    query: str,
    scope: Any,
    max_candidates: int = DEFAULT_MAX_EVAL_CANDIDATES,
) -> list[Any]:
    """1. Retrieval re-rank: reorder only, never add or drop a source.

    Exact file/page/question targets keep their slot no matter what the model
    says; official candidates never crowd out private ones (that ordering is
    fixed before this call). Off/shadow/failed/timeout all return the original
    fused order.
    """
    if service is None:
        return list(entries)
    return service.rerank_retrieval(
        entries, query=query, caller_role="retrieval", cache_scope=scope,
        max_candidates=max_candidates,
    )


def citation_support(
    service: SemanticDecisionService | None,
    *,
    claim: str,
    source_span: str,
    source_version: str,
    task_scope: str,
    scope: Any,
) -> str:
    """2a. Citation support: does this backend span substantively support the claim?

    Returns SUPPORTED / UNSUPPORTED (a real Jev signal) or UNVERIFIED (fallback).
    The model may never invent a source; span ids come from the backend.
    """
    if service is None:
        return UNVERIFIED
    result = service.supports_claim(
        claim=claim, source_span=source_span, source_version=source_version,
        task_scope=task_scope, caller_role="citation", cache_scope=scope,
    )
    if result.used_jev and isinstance(result.value, float):
        return SUPPORTED if result.value >= 0.5 else UNSUPPORTED
    return UNVERIFIED


def select_citation_span(
    service: SemanticDecisionService | None,
    *,
    claim: str,
    candidate_spans: Sequence[str],
    scope: Any,
) -> str:
    """2b. Span selection: select a supplied backend span id, never invent one."""
    if service is None:
        return "NO_SUPPORT"
    result = service.select_span(
        claim=claim, candidate_spans=candidate_spans,
        caller_role="citation", cache_scope=scope,
    )
    return str(result.value)


def keep_history_segment(
    service: SemanticDecisionService | None,
    *,
    segment: str,
    current_task: str,
    fixed_anchor: dict[str, Any],
    remaining_scope: str,
    scope: Any,
) -> bool:
    """3. Context keep/drop for *optional* history only; fixed anchors never drop."""
    if service is None:
        return True
    return service.keep_segment(
        segment=segment, current_task=current_task, fixed_anchor=fixed_anchor,
        remaining_scope=remaining_scope, caller_role="context", cache_scope=scope,
    )


def route_next_action(
    service: SemanticDecisionService | None,
    *,
    message: str,
    fixed_anchor: dict[str, Any],
    current_mode: str,
    active_assessment: str | None,
    scope: Any,
    deterministic: str = "OTHER",
) -> str:
    """4. Intent routing for *ambiguous* follow-ups only.

    Explicit commands (继续 / 暂停 / 只回答 / 显示答案 / ...) are answered by
    ``app.learning.intent_commands.route_explicit_command`` with ZERO Jev calls;
    the caller must route through that first and only reach here when it returns
    ``None``. The user's Thinking/strength choice is never changed here.
    """
    if service is None:
        return deterministic
    result = service.next_action(
        message=message, fixed_anchor=fixed_anchor, current_mode=current_mode,
        active_assessment=active_assessment, caller_role="intent", cache_scope=scope,
        deterministic=deterministic,
    )
    return str(result.value)


def select_pedagogy_method(
    service: SemanticDecisionService | None,
    *,
    learner_request: str,
    known_prior_evidence: Any,
    topic: str,
    template_profile: Any,
    current_step: str,
    scope: Any,
    deterministic: str = "CONTINUE",
) -> str:
    """5. Pedagogy: presentation method passed into the actual plan->work input."""
    if service is None:
        return deterministic
    result = service.next_method(
        learner_request=learner_request, known_prior_evidence=known_prior_evidence,
        topic=topic, template_profile=template_profile, current_step=current_step,
        caller_role="pedagogy", cache_scope=scope, deterministic=deterministic,
    )
    return str(result.value)


def coverage_item_support(
    service: SemanticDecisionService | None,
    items: Sequence[dict[str, Any]],
    *,
    content: str,
    spec_version: int | str,
    scope: Any,
) -> dict[str, str]:
    """6. Coverage item support: a signal only; the backend still decides coverage."""
    if service is None:
        return {str(item["item_id"]): "UNCERTAIN" for item in items}
    return service.item_support(
        items, content=content, spec_version=spec_version,
        caller_role="coverage", cache_scope=scope,
    )


def review_criterion(
    service: SemanticDecisionService | None,
    *,
    frozen_question: dict[str, Any],
    criterion: dict[str, Any],
    reference_solution: str,
    student_answer: str,
    deterministic_verification: str,
    candidate_answer_spans: list[str],
    scope: Any,
    deterministic: str = "NEEDS_REVIEW",
) -> DecisionResult:
    """7. Assessment criterion review inside the grading loop.

    Returns the full :class:`DecisionResult` so the caller can apply the
    ``used_jev`` guard: only a real Jev verdict (mode ``on`` + validated) may
    flag ``NEEDS_REVIEW`` or contradict the grader. The fallback is NEEDS_REVIEW
    but is never treated as a Jev signal, and the final marks are summed
    deterministically by the backend (never ``score * 100``, never zero because
    Jev failed).
    """
    if service is None:
        return DecisionResult(
            value=deterministic, suggestion=None, used_jev=False, mode="off",
            outcome="off", receipt_id=None, input_hash=None,
            path="fallback:off", fallback_reason="off",
            definition_key="assessment.criterion_review.v1",
        )
    return service.criterion_review(
        frozen_question=frozen_question, criterion=criterion,
        reference_solution=reference_solution, student_answer=student_answer,
        deterministic_verification=deterministic_verification,
        candidate_answer_spans=candidate_answer_spans,
        caller_role="assessment", cache_scope=scope, deterministic=deterministic,
    )


def review_question_ambiguity(
    service: SemanticDecisionService,
    *,
    question_text: str,
    question_type: str,
    expected_answer_form: str,
    blueprint_conditions: list[str],
    allowed_rules: list[dict[str, str]],
    scope: Any,
) -> DecisionResult:
    """Question Engine ambiguity signal; never authors an answer or READY state."""
    return service.question_ambiguity(
        question_text=question_text,
        question_type=question_type,
        expected_answer_form=expected_answer_form,
        blueprint_conditions=blueprint_conditions,
        allowed_rules=allowed_rules,
        caller_role="question_validator",
        cache_scope=scope,
    )


def review_question_answer_agreement(
    service: SemanticDecisionService,
    *,
    question_text: str,
    author_candidate_answer: dict[str, Any],
    blind_solution: str,
    blueprint_conditions: list[str],
    scope: Any,
) -> DecisionResult:
    """Compare author and blind results as a signal, never as correctness proof."""
    return service.question_answer_agreement(
        question_text=question_text,
        author_candidate_answer=author_candidate_answer,
        blind_solution=blind_solution,
        blueprint_conditions=blueprint_conditions,
        caller_role="question_validator",
        cache_scope=scope,
    )


def review_mcq_distractor_quality(
    service: SemanticDecisionService,
    *,
    question_text: str,
    options: list[str],
    correct_option_index: int | None,
    distractor_rationales: list[dict[str, Any]],
    misconception_targets: list[str],
    allowed_rules: list[dict[str, str]],
    scope: Any,
) -> DecisionResult:
    """Review private MCQ mappings as a signal, never as publication authority."""
    return service.question_mcq_distractor_quality(
        question_text=question_text,
        options=options,
        correct_option_index=correct_option_index,
        distractor_rationales=distractor_rationales,
        misconception_targets=misconception_targets,
        allowed_rules=allowed_rules,
        caller_role="question_validator",
        cache_scope=scope,
    )


def review_rule_violation_quality(
    service: SemanticDecisionService,
    *,
    question_text: str,
    rule_violation_analysis: dict[str, Any] | None,
    allowed_rules: list[dict[str, str]],
    scope: Any,
) -> DecisionResult:
    """Review rule semantics as a signal; exact evidence binding remains deterministic."""
    return service.question_rule_violation_quality(
        question_text=question_text,
        rule_violation_analysis=rule_violation_analysis,
        allowed_rules=allowed_rules,
        caller_role="question_validator",
        cache_scope=scope,
    )


def match_template(
    service: SemanticDecisionService | None,
    templates: Sequence[TemplateOption],
    *,
    state: dict[str, Any],
    scope: Any,
) -> str:
    """8. Hierarchical template classification; "cannot decide" returns OTHER."""
    if service is None:
        return "OTHER"
    result = service.match_template(
        templates=templates, state=state, caller_role="template", cache_scope=scope,
    )
    return str(result.value)


def select_exercise_prototype(
    service: SemanticDecisionService | None,
    *,
    node: Any,
    eligible_prototypes: Sequence[str],
    recent_exposures: Any,
    learning_evidence: Any,
    scope: Any,
) -> str:
    """9. Exercise prototype: a real authorized prototype id, never the answer."""
    if service is None:
        return "NONE"
    result = service.exercise_prototype(
        node=node, eligible_prototypes=eligible_prototypes,
        recent_exposures=recent_exposures, learning_evidence=learning_evidence,
        caller_role="exercise", cache_scope=scope,
    )
    return str(result.value)


def select_prerequisite(
    service: SemanticDecisionService | None,
    *,
    current_node: str,
    error: str,
    allowed_predecessor_nodes: Sequence[str],
    scope: Any,
) -> str:
    """10. Prerequisite: legal neighbours only, never a new tree."""
    if service is None:
        return "NONE"
    result = service.prerequisite(
        current_node=current_node, error=error,
        allowed_predecessor_nodes=allowed_predecessor_nodes,
        caller_role="prerequisite", cache_scope=scope,
    )
    return str(result.value)


def assess_corpus_quality(
    service: SemanticDecisionService | None,
    *,
    document_fragment: str,
    source_metadata: dict[str, Any],
    parse_flags: list[str],
    scope: Any,
) -> int:
    """11. Corpus quality: flag missing pages/stems/data; never auto-delete originals."""
    if service is None:
        return 1  # retain original; mark parse limitations for ingestion review
    result = service.corpus_quality(
        document_fragment=document_fragment, source_metadata=source_metadata,
        parse_flags=parse_flags, caller_role="corpus", cache_scope=scope,
    )
    return int(result.value)


@dataclass(frozen=True)
class FieldGrounded:
    """One ``extraction.field_grounded.v1`` judgment with its provenance.

    Unlike the other call sites this returns provenance next to the value: the
    extraction path must distinguish "the model says nothing is wrong" from "the
    model never answered", because only the first may be treated as grounded and
    the second has to stay under review. ``verdict`` is always a catalog
    candidate; ``UNCERTAIN`` is the deterministic value.
    """

    verdict: str
    used_jev: bool
    mode: str
    path: str
    fallback_reason: str | None
    receipt_id: str | None
    input_hash: str | None


def verify_extraction_field(
    service: SemanticDecisionService | None,
    *,
    question_id: str,
    part_id: str | None,
    field_name: str,
    candidate_value: Any,
    unit: str | None,
    supplied_text: str,
    source_region: dict[str, Any],
    scope: Any,
) -> FieldGrounded:
    """13. Extraction field grounding: judge a parsed field against its own text.

    Returns a catalog candidate, or ``UNCERTAIN`` — never an acceptance — when
    there is no service, in shadow/off mode, on timeout, or when the model does
    not answer. The value vocabulary is the catalog's, so a caller cannot widen
    it, and nothing here writes, repairs or re-reads anything.
    """
    if service is None:
        return FieldGrounded(
            verdict="UNCERTAIN",
            used_jev=False,
            mode="off",
            path="fallback:no_service",
            fallback_reason="no_service",
            receipt_id=None,
            input_hash=None,
        )
    result = service.field_grounded(
        question_id=question_id, part_id=part_id, field_name=field_name,
        candidate_value=candidate_value, unit=unit, supplied_text=supplied_text,
        source_region=source_region, caller_role="extraction", cache_scope=scope,
    )
    choice = result.value
    verdict = (
        str(choice)
        if result.used_jev and isinstance(choice, str) and choice
        else "UNCERTAIN"
    )
    return FieldGrounded(
        verdict=verdict,
        used_jev=result.used_jev,
        mode=result.mode,
        path=result.path,
        fallback_reason=result.fallback_reason,
        receipt_id=result.receipt_id,
        input_hash=result.input_hash,
    )


__all__ = [
    "SUPPORTED",
    "UNSUPPORTED",
    "UNVERIFIED",
    "FieldGrounded",
    "assess_corpus_quality",
    "bounded_state",
    "citation_support",
    "coverage_item_support",
    "keep_history_segment",
    "match_template",
    "rerank_retrieval",
    "review_criterion",
    "review_question_ambiguity",
    "review_question_answer_agreement",
    "route_next_action",
    "select_citation_span",
    "select_exercise_prototype",
    "select_pedagogy_method",
    "select_prerequisite",
    "verify_extraction_field",
]
