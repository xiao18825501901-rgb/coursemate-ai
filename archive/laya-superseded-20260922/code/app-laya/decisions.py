"""The Laya decision facade: 12 typed business helpers over :class:`LayaGateway`.

This is the Laya successor to the retired ``app.jev.service.SemanticDecisionService``.
Every helper:

* builds legal candidates ONLY from server-side authorized data (the caller passes
  the authorized ids/spans/items — the model may only *select* one);
* builds its request through :mod:`app.laya.compiler` so nothing is silently
  truncated — an oversized/insufficient-context request degrades to the documented
  deterministic path instead of being re-cut to indistinct options;
* applies a deterministic fallback in ``off``/``shadow``/``advisory``/failed — in
  ``shadow`` the deterministic result is returned and the Laya suggestion is
  recorded in the receipt only (``used_laya`` stays False);
* records a ``path`` of ``"laya"`` (only when the validated suggestion is actually
  used, i.e. mode ``on``) or ``"fallback:<reason>"`` (everything else, including
  ``shadow``/``off``/``advisory`` and every failure mode);
* never writes DB state, grades, LEARNED or budgets — the only side effect is a
  ``laya_decision_receipts`` row (owned by the adapter) plus this service's
  in-memory telemetry, which exists so a test can assert the counts.

The official response semantics (see ``work/laya-recon/rl_agent_api.py``):

* ``choice`` -> ``{choice, probabilities{key}, confidence}``;
* ``score``  -> ``{score = Σ i·p_i (0..K-1), legend, probabilities}``;
* ``noul``   -> ``{noul = P(true)}``;
* ``confidence`` = ``1 - normalized entropy`` (distribution concentration, never
  ``p_correct``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Sequence
from uuid import uuid4

from app.jev.catalog import Catalog, DecisionDefinition
from app.jev.models import owner_scope_hash
from app.laya.adapter import LayaConfig, LayaDecision, LayaGateway
from app.laya.compiler import (
    CompiledDecision,
    InputTooLongError,
    InsufficientContextError,
    LayaCompileError,
    TemplateOption,
    build_hierarchical_template_decision,
    compile_decision,
)
from app.laya.models import LayaQuestion, LayaRequest, LayaScope

# Retrieval re-rank candidate cap (the owner's bound: 12-16 authorized candidates).
DEFAULT_MAX_EVAL_CANDIDATES = 16

# The three primitives the catalog speaks, mapped to the lowercase service names.
_PRIMITIVE_KIND = {"Choice": "choice", "Score": "score", "Noul": "noul"}

# Candidate id sets (authorized by the catalog; the model may only select one).
_INTENT_ACTIONS = (
    "CONTINUE", "ANSWER_AND_RESUME", "ANSWER_ONLY", "REPAIR_PREREQUISITE",
    "QUIZ_WAIT", "SUBMIT_ASSESSMENT", "PAUSE", "OTHER",
)
_PEDAGOGY_METHODS = (
    "WORKED_EXAMPLE", "TRACE", "DEFINITION", "COUNTEREXAMPLE", "COMPARE", "CONTINUE",
)
_COVERAGE_SIGNALS = ("SUPPORTED", "PARTIAL", "UNSUPPORTED", "UNCERTAIN")
_CRITERION_VERDICTS = ("SATISFIED", "PARTIAL", "NOT_SATISFIED", "NEEDS_REVIEW")


@dataclass(frozen=True)
class DecisionOutcome:
    """The value to use plus the recorded Laya decision (mirrors the Jev result)."""

    value: Any
    path: str  # "laya" | "fallback:<reason>"
    used_laya: bool
    mode: str
    definition_id: str
    definition_version: str
    receipt_id: str | None
    confidence: float | None  # distribution concentration; None for noul
    probabilities: dict[str, float]
    fallback_reason: str | None
    latency_ms: float
    suggestion: Any = None  # the validated Laya suggestion (observability only)


@dataclass(frozen=True)
class DecisionRecord:
    """One per-call telemetry record, keyed exactly like a receipt row."""

    definition_id: str
    definition_version: str
    mode: str
    path: str
    latency_ms: float
    concentration: float | None
    receipt_id: str | None
    fallback_reason: str | None = None


class LayaDecisionService:
    """Non-authoritative semantic-decision layer over the Laya gateway."""

    def __init__(self, gateway: LayaGateway, *, config: LayaConfig | None = None) -> None:
        self.gateway = gateway
        self.catalog = gateway.catalog
        self.config = config or gateway.config
        self.records: list[DecisionRecord] = []
        self.counts: dict[str, int] = {}

    # ------------------------------------------------------------------ scope

    @staticmethod
    def scope(
        *,
        owner_user_id: str,
        authorization_scope: str,
        course_id: str | None = None,
        workspace_id: str | None = None,
        material_revision: str | None = None,
        node_id: str | None = None,
        spec_version: int | str | None = None,
        question_hash: str | None = None,
    ) -> LayaScope:
        """Build a cache scope bound to (owner, authorization scope)."""
        return LayaScope(
            owner_scope_hash=owner_scope_hash(owner_user_id, authorization_scope),
            course_id=course_id,
            workspace_id=workspace_id,
            material_revision=material_revision,
            node_id=node_id,
            spec_version=str(spec_version) if spec_version is not None else None,
            question_hash=question_hash,
        )

    # ------------------------------------------------------------- observability

    def summary(self) -> dict[str, Any]:
        """Counts per ``definition_id::path`` plus the live breaker state."""
        return {
            "counts": dict(self.counts),
            "breaker": self.gateway.breaker_state,
            "records": [record.__dict__ for record in self.records],
        }

    # ---------------------------------------------------------------- primitives

    def choice(
        self,
        definition_key: str,
        *,
        candidate_ids: Sequence[str],
        candidate_labels: dict[str, str] | None = None,
        state: dict[str, Any],
        cache_scope: LayaScope,
        deterministic: str,
    ) -> DecisionOutcome:
        definition = self.catalog.get(definition_key)
        labels = candidate_labels or {}
        criteria = {str(cid): labels.get(str(cid), "") for cid in candidate_ids}
        return self._decide(definition, criteria=criteria, state=state,
                            cache_scope=cache_scope, deterministic=deterministic)

    def score(
        self,
        definition_key: str,
        *,
        state: dict[str, Any],
        cache_scope: LayaScope,
        deterministic: Any = None,
    ) -> DecisionOutcome:
        definition = self.catalog.get(definition_key)
        return self._decide(definition, criteria=None, state=state,
                            cache_scope=cache_scope, deterministic=deterministic)

    def noul(
        self,
        definition_key: str,
        *,
        state: dict[str, Any],
        cache_scope: LayaScope,
    ) -> DecisionOutcome:
        definition = self.catalog.get(definition_key)
        return self._decide(definition, criteria=None, state=state,
                            cache_scope=cache_scope, deterministic=None)

    # ------------------------------------------------------------ retrieval re-rank

    def rerank_retrieval(
        self,
        entries: Sequence[Any],
        *,
        query: str,
        cache_scope: LayaScope,
        max_candidates: int = DEFAULT_MAX_EVAL_CANDIDATES,
    ) -> list[Any]:
        """Optionally reorder already-authorized candidates by Laya support score.

        Exact-target hits keep their slot and are never added or dropped. In
        ``off``/``shadow``/``advisory``/failed the original deterministic fused
        order is returned unchanged (shadow still records suggestions).
        """
        ordered = list(entries)
        if not ordered:
            return ordered
        non_exact = [
            (index, entry)
            for index, entry in enumerate(ordered)
            if not getattr(entry, "exact", False)
        ]
        if not non_exact:
            return ordered
        results: dict[int, DecisionOutcome] = {}
        used_laya = False
        for index, entry in non_exact[:max_candidates]:
            result = self.score(
                "retrieval.support.v1",
                state=self._candidate_state(entry, query),
                cache_scope=cache_scope,
            )
            results[index] = result
            used_laya = used_laya or result.used_laya
        if not used_laya:
            return ordered
        non_exact_indices = [index for index, _ in non_exact]
        sorted_non_exact = [
            entry
            for _, entry in sorted(
                non_exact,
                key=lambda item: (
                    -self._level(results.get(item[0])),
                    -float(getattr(item[1], "score", 0.0) or 0.0),
                    item[0],
                ),
            )
        ]
        for index, entry in zip(non_exact_indices, sorted_non_exact):
            ordered[index] = entry
        return ordered

    # -------------------------------------------------------- citation support

    def supports_claim(
        self,
        *,
        claim: str,
        source_span: str,
        source_version: str,
        task_scope: str,
        cache_scope: LayaScope,
    ) -> DecisionOutcome:
        """source.supports_claim.v1 (noul): does this span support this claim."""
        return self.noul(
            "source.supports_claim.v1",
            state={
                "claim": claim,
                "source_span": source_span,
                "source_version": source_version,
                "task_scope": task_scope,
            },
            cache_scope=cache_scope,
        )

    def select_span(
        self,
        *,
        claim: str,
        candidate_spans: Sequence[str],
        cache_scope: LayaScope,
        deterministic: str = "NO_SUPPORT",
    ) -> DecisionOutcome:
        """source.select_span.v1 (choice): select a supplied span id only."""
        ids = [str(span) for span in candidate_spans]
        return self.choice(
            "source.select_span.v1",
            candidate_ids=("NO_SUPPORT", *ids),
            state={"claim": claim, "candidate_spans": ids},
            cache_scope=cache_scope,
            deterministic=deterministic,
        )

    # -------------------------------------------------------------- context keep

    def keep_segment(
        self,
        *,
        segment: str,
        current_task: str,
        fixed_anchor: dict[str, Any],
        remaining_scope: str,
        cache_scope: LayaScope,
    ) -> bool:
        """context.keep_segment.v1 (noul): keep an optional history segment.

        Only *optional* history is ever offered; the fixed anchor set is outside
        this selector and is never dropped. Fallback keeps the segment.
        """
        result = self.noul(
            "context.keep_segment.v1",
            state={
                "segment": segment,
                "current_task": current_task,
                "fixed_anchor": fixed_anchor,
                "remaining_scope": remaining_scope,
            },
            cache_scope=cache_scope,
        )
        if result.used_laya and isinstance(result.value, float):
            return result.value >= 0.5
        return True  # deterministic: keep fixed anchors + bounded recent history

    # ------------------------------------------------------------ intent routing

    def next_action(
        self,
        *,
        message: str,
        fixed_anchor: dict[str, Any],
        current_mode: str,
        active_assessment: str | None,
        cache_scope: LayaScope,
        deterministic: str = "OTHER",
    ) -> DecisionOutcome:
        """intent.next_action.v1 (choice): classify ambiguous follow-ups only."""
        return self.choice(
            "intent.next_action.v1",
            candidate_ids=_INTENT_ACTIONS,
            state={
                "message": message,
                "fixed_anchor": fixed_anchor,
                "current_mode": current_mode,
                "active_assessment": active_assessment,
            },
            cache_scope=cache_scope,
            deterministic=deterministic,
        )

    # ----------------------------------------------------------------- pedagogy

    def next_method(
        self,
        *,
        learner_request: str,
        known_prior_evidence: Any,
        topic: str,
        template_profile: Any,
        current_step: str,
        cache_scope: LayaScope,
        deterministic: str = "CONTINUE",
    ) -> DecisionOutcome:
        """pedagogy.next_method.v1 (choice): presentation strategy, not a grade."""
        return self.choice(
            "pedagogy.next_method.v1",
            candidate_ids=_PEDAGOGY_METHODS,
            state={
                "learner_request": learner_request,
                "known_prior_evidence": known_prior_evidence,
                "topic": topic,
                "template_profile": template_profile,
                "current_step": current_step,
            },
            cache_scope=cache_scope,
            deterministic=deterministic,
        )

    # ----------------------------------------------------------- coverage support

    def item_support(
        self,
        items: Sequence[dict[str, Any]],
        *,
        content: str,
        spec_version: int | str,
        cache_scope: LayaScope,
    ) -> dict[str, str]:
        """coverage.item_support.v1 signals; never claims coverage itself."""
        signals: dict[str, str] = {}
        for item in items:
            state = {
                "saved_delivery": content,
                "required_item": item,
                "valid_spans": [],
                "node_spec_version": str(spec_version),
            }
            result = self.choice(
                "coverage.item_support.v1",
                candidate_ids=_COVERAGE_SIGNALS,
                state=state,
                cache_scope=cache_scope,
                deterministic="UNCERTAIN",
            )
            signals[str(item["item_id"])] = result.value
        return signals

    # ------------------------------------------------------- assessment review

    def criterion_review(
        self,
        *,
        frozen_question: dict[str, Any],
        criterion: dict[str, Any],
        reference_solution: str,
        student_answer: str,
        deterministic_verification: str,
        candidate_answer_spans: list[str],
        cache_scope: LayaScope,
        deterministic: str = "NEEDS_REVIEW",
    ) -> DecisionOutcome:
        """assessment.criterion_review.v1 (choice): judge criterion support only."""
        return self.choice(
            "assessment.criterion_review.v1",
            candidate_ids=_CRITERION_VERDICTS,
            state={
                "frozen_question": frozen_question,
                "frozen_rubric_criterion": criterion,
                "reference_solution": reference_solution,
                "student_answer": student_answer,
                "deterministic_verification": deterministic_verification,
                "candidate_answer_spans": candidate_answer_spans,
            },
            cache_scope=cache_scope,
            deterministic=deterministic,
        )

    # -------------------------------------------------------------- classification

    def match_template(
        self,
        templates: Sequence[TemplateOption],
        *,
        state: dict[str, Any],
        cache_scope: LayaScope,
        deterministic: str = "OTHER",
    ) -> DecisionOutcome:
        """template.match.v1 (choice): hierarchical coarse-to-fine classification.

        Never sends the 14 professional templates as one flat option list: stage 1
        picks the domain/level, stage 2 the template within it. "cannot decide"
        returns OTHER rather than forcing one of the templates.
        """
        definition = self.catalog.get("template.match.v1")
        try:
            hierarchical = build_hierarchical_template_decision(
                templates=list(templates),
                state=state,
                decision_key="template.match.v1",
            )
        except LayaCompileError as exc:
            return self._degraded(definition, deterministic, exc.kind, 0.0)

        stage1 = self._decide_compiled(definition, hierarchical.stage1, state,
                                       cache_scope, deterministic=deterministic)
        domain = stage1.value
        if not stage1.used_laya or domain == hierarchical.other_label:
            return stage1
        stage2_decision = hierarchical.stage2.get(domain)
        if stage2_decision is None:
            return stage1
        stage2 = self._decide_compiled(definition, stage2_decision, state,
                                       cache_scope, deterministic="OTHER")
        if stage2.used_laya and stage2.value != hierarchical.other_label:
            return stage2
        # Stage 2 fell back or said OTHER: return OTHER as the business value,
        # keeping stage1/stage2 receipts + telemetry for the audit trail.
        return self._degraded(definition, deterministic, "other", stage2.latency_ms)

    # ---------------------------------------------------------- exercise prototype

    def exercise_prototype(
        self,
        *,
        node: Any,
        eligible_prototypes: Sequence[str],
        recent_exposures: Any,
        learning_evidence: Any,
        cache_scope: LayaScope,
        deterministic: str = "NONE",
    ) -> DecisionOutcome:
        """exercise.prototype.v1 (choice): a real authorized prototype id only."""
        ids = [str(p) for p in eligible_prototypes]
        return self.choice(
            "exercise.prototype.v1",
            candidate_ids=("NONE", *ids),
            state={
                "node": node,
                "eligible_prototypes": ids,
                "recent_exposures": recent_exposures,
                "learning_evidence": learning_evidence,
            },
            cache_scope=cache_scope,
            deterministic=deterministic,
        )

    # ----------------------------------------------------------------- prerequisite

    def prerequisite(
        self,
        *,
        current_node: str,
        error: str,
        allowed_predecessor_nodes: Sequence[str],
        cache_scope: LayaScope,
        deterministic: str = "NONE",
    ) -> DecisionOutcome:
        """graph.prerequisite.v1 (choice): legal neighbours only, never a new tree."""
        ids = [str(n) for n in allowed_predecessor_nodes]
        return self.choice(
            "graph.prerequisite.v1",
            candidate_ids=("NONE", *ids),
            state={
                "current_node": current_node,
                "error": error,
                "allowed_predecessor_nodes": ids,
            },
            cache_scope=cache_scope,
            deterministic=deterministic,
        )

    # -------------------------------------------------------------- corpus quality

    def corpus_quality(
        self,
        *,
        document_fragment: str,
        source_metadata: dict[str, Any],
        parse_flags: list[str],
        cache_scope: LayaScope,
        deterministic: int = 1,
    ) -> DecisionOutcome:
        """corpus.quality.v1 (score 0..3): offline evidence suitability only."""
        result = self.score(
            "corpus.quality.v1",
            state={
                "document_fragment": document_fragment,
                "source_metadata": source_metadata,
                "parse_flags": parse_flags,
            },
            cache_scope=cache_scope,
            deterministic=deterministic,
        )
        if result.used_laya and isinstance(result.value, (int, float)):
            return DecisionOutcome(
                value=int(round(result.value)),
                path=result.path,
                used_laya=result.used_laya,
                mode=result.mode,
                definition_id=result.definition_id,
                definition_version=result.definition_version,
                receipt_id=result.receipt_id,
                confidence=result.confidence,
                probabilities=result.probabilities,
                fallback_reason=result.fallback_reason,
                latency_ms=result.latency_ms,
                suggestion=result.suggestion,
            )
        return result

    # ------------------------------------------------------------------ internals

    def _deadline_ms(self) -> int:
        return int(time.time() * 1000) + int(self.config.timeout_seconds * 1000)

    @staticmethod
    def _kind(definition: DecisionDefinition) -> str:
        return _PRIMITIVE_KIND[definition.primitive]

    def _compile(
        self,
        definition: DecisionDefinition,
        *,
        criteria: dict[str, str] | None,
        state: dict[str, Any],
    ) -> tuple[CompiledDecision, LayaQuestion]:
        kind = self._kind(definition)
        if kind == "choice":
            crit: dict[str, str] | list[str] | None = dict(criteria or {})
        elif kind == "score":
            crit = [definition.criteria[level] for level in definition.score_levels]
        else:
            crit = None
        text = definition.instructions
        compiled = compile_decision(
            primitive=kind,
            instructions=text,
            criteria=crit,
            state=state,
            decision_key=definition.key,
        )
        question = LayaQuestion(kind=kind, instructions=text, criteria=crit)
        return compiled, question

    def _decide(
        self,
        definition: DecisionDefinition,
        *,
        criteria: dict[str, str] | None,
        state: dict[str, Any],
        cache_scope: LayaScope,
        deterministic: Any,
    ) -> DecisionOutcome:
        started = time.perf_counter()
        try:
            compiled, question = self._compile(definition, criteria=criteria, state=state)
        except LayaCompileError as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            return self._degraded(definition, deterministic, exc.kind, latency_ms)
        return self._decide_compiled(
            definition, compiled, state, cache_scope, deterministic, question=question
        )

    def _decide_compiled(
        self,
        definition: DecisionDefinition,
        compiled: CompiledDecision,
        state: dict[str, Any],
        cache_scope: LayaScope,
        deterministic: Any,
        *,
        question: LayaQuestion | None = None,
    ) -> DecisionOutcome:
        question = question or LayaQuestion(
            kind=compiled.primitive,
            instructions=compiled.instructions,
            criteria=compiled.criteria,
        )
        request = LayaRequest(
            definition_id=definition.key,
            definition_version=self.catalog.version,
            state=state,
            questions={definition.key: question},
            deadline_ms=self._deadline_ms(),
            request_id=uuid4().hex,
            compiler_version=self.config.compiler_version,
            model_revision=self.config.model_revision,
        )
        decision = self.gateway.decide(request, scope=cache_scope, fallback=deterministic)
        return self._outcome(definition, decision)

    def _outcome(self, definition: DecisionDefinition, decision: LayaDecision) -> DecisionOutcome:
        used = decision.used_laya
        path = "laya" if used else f"fallback:{decision.fallback_reason or decision.mode}"
        self._record(definition, decision, path)
        suggestion = None
        if decision.answer is not None:
            answer = decision.answer
            suggestion = (
                answer.choice if answer.kind == "choice"
                else answer.score if answer.kind == "score"
                else answer.noul
            )
        return DecisionOutcome(
            value=decision.value,
            path=path,
            used_laya=used,
            mode=decision.mode,
            definition_id=definition.key,
            definition_version=self.catalog.version,
            receipt_id=decision.receipt_id,
            confidence=decision.confidence,
            probabilities=decision.probabilities,
            fallback_reason=decision.fallback_reason,
            latency_ms=decision.latency_ms,
            suggestion=suggestion,
        )

    def _degraded(
        self,
        definition: DecisionDefinition,
        deterministic: Any,
        reason: str,
        latency_ms: float,
    ) -> DecisionOutcome:
        path = f"fallback:{reason}"
        self.records.append(
            DecisionRecord(
                definition_id=definition.key,
                definition_version=self.catalog.version,
                mode="off",
                path=path,
                latency_ms=latency_ms,
                concentration=None,
                receipt_id=None,
                fallback_reason=reason,
            )
        )
        self.counts[f"{definition.key}::{path}"] = self.counts.get(f"{definition.key}::{path}", 0) + 1
        return DecisionOutcome(
            value=deterministic,
            path=path,
            used_laya=False,
            mode="off",
            definition_id=definition.key,
            definition_version=self.catalog.version,
            receipt_id=None,
            confidence=None,
            probabilities={},
            fallback_reason=reason,
            latency_ms=latency_ms,
        )

    def _record(self, definition: DecisionDefinition, decision: LayaDecision, path: str) -> None:
        self.records.append(
            DecisionRecord(
                definition_id=definition.key,
                definition_version=self.catalog.version,
                mode=decision.mode,
                path=path,
                latency_ms=decision.latency_ms,
                concentration=decision.confidence,
                receipt_id=decision.receipt_id,
                fallback_reason=decision.fallback_reason,
            )
        )
        self.counts[f"{definition.key}::{path}"] = self.counts.get(f"{definition.key}::{path}", 0) + 1

    @staticmethod
    def _level(result: DecisionOutcome | None) -> float:
        value = result.value if result is not None else None
        return value if isinstance(value, (int, float)) else -1.0

    @staticmethod
    def _candidate_state(entry: Any, query: str) -> dict[str, Any]:
        hit = getattr(entry, "hit", entry)
        content = str(getattr(hit, "content", "") or "")[:4000]
        return {
            "query": query,
            "exact_target": bool(getattr(entry, "exact", False)),
            "candidate_id": str(getattr(entry, "chunk_id", "") or getattr(hit, "chunk_id", "") or ""),
            "candidate_text": content,
            "source_metadata": {
                "scopes": list(getattr(entry, "scopes", ())),
                "filename": str(getattr(hit, "filename", "") or ""),
                "locator": f"{getattr(hit, 'locator_type', '')}:{getattr(hit, 'locator_value', '')}",
            },
        }


def build_laya_service(
    settings: Any,
    *,
    database: Any = None,
    transport: Any = None,
    modes: dict[str, str] | None = None,
) -> LayaDecisionService:
    """Construct the gateway + facade from a Settings-like object.

    ``transport`` overrides the HTTP transport (tests pass ``FakeLayaTransport``;
    production, when ``laya_base_url`` is configured, uses the HTTP transport).
    ``database`` enables the persisted receipt store (``SqlLayaReceiptStore``).
    """
    from app.jev.catalog import load_catalog
    from app.laya.adapter import HttpLayaTransport, LayaConfig, LayaGateway
    from app.laya.receipt_store import SqlLayaReceiptStore

    config = LayaConfig.from_settings(settings)
    catalog = load_catalog()
    resolved_transport = transport
    if resolved_transport is None and config.base_url:
        resolved_transport = HttpLayaTransport(config)
    store = SqlLayaReceiptStore(database) if database is not None else None
    gateway = LayaGateway(
        transport=resolved_transport,
        catalog=catalog,
        modes=modes,
        receipt_store=store,
        config=config,
    )
    return LayaDecisionService(gateway, config=config)


__all__ = [
    "DEFAULT_MAX_EVAL_CANDIDATES",
    "DecisionOutcome",
    "DecisionRecord",
    "LayaDecisionService",
    "build_laya_service",
]
