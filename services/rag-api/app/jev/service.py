"""Thin per-decision helpers over :class:`JevGateway`.

Every helper:

* builds legal candidates ONLY from server-side authorized data (the caller
  passes the authorized ids/spans/items — the model may only *select* one);
* never lets the model create a candidate id: a Choice must return one of the
  supplied ids, and a Score/Noul returns a signal, never a grade;
* applies a deterministic fallback in ``off``/``shadow``/failed — in ``shadow``
  the deterministic result is returned and the Jev suggestion is recorded in the
  receipt only (``used_jev`` stays False);
* never writes DB state, grades, LEARNED or budgets — the only side effect is a
  ``jev_decision_receipts`` row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from app.jev.catalog import DecisionDefinition, load_catalog
from app.jev.gateway import DecisionRequest, JevGateway
from app.jev.models import CacheScope, owner_scope_hash

DEFAULT_MAX_EVAL_CANDIDATES = 24


@dataclass
class DecisionResult:
    """The value to use plus the (recorded) Jev suggestion."""

    value: Any
    suggestion: Any
    used_jev: bool
    mode: str
    outcome: str
    receipt_id: str | None
    input_hash: str | None


class SemanticDecisionService:
    """Non-authoritative semantic-decision layer."""

    def __init__(self, gateway: JevGateway) -> None:
        self.gateway = gateway
        self.catalog = gateway.catalog

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
        provider_model_version: str | None = None,
    ) -> CacheScope:
        return CacheScope(
            owner_scope_hash=owner_scope_hash(owner_user_id, authorization_scope),
            course_id=course_id,
            workspace_id=workspace_id,
            material_revision=material_revision,
            node_id=node_id,
            spec_version=str(spec_version) if spec_version is not None else None,
            question_hash=question_hash,
            provider_model_version=provider_model_version,
        )

    # ---------------------------------------------------------------- primitives

    def choice(
        self,
        definition_key: str,
        *,
        candidate_ids: Sequence[str],
        candidate_labels: dict[str, str] | None = None,
        state: dict[str, Any],
        caller_role: str,
        cache_scope: CacheScope,
        deterministic: str,
    ) -> DecisionResult:
        definition = self.catalog.get(definition_key)
        labels = candidate_labels or {}
        criteria = {str(cid): labels.get(str(cid)) for cid in candidate_ids}
        request = DecisionRequest(
            definition=definition,
            state=state,
            caller_role=caller_role,
            cache_scope=cache_scope,
            criteria=criteria,
        )
        return self._decide(request, deterministic)

    def score(
        self,
        definition_key: str,
        *,
        state: dict[str, Any],
        caller_role: str,
        cache_scope: CacheScope,
    ) -> DecisionResult:
        definition = self.catalog.get(definition_key)
        request = DecisionRequest(
            definition=definition,
            state=state,
            caller_role=caller_role,
            cache_scope=cache_scope,
            criteria=None,
        )
        return self._decide(request, None)

    def noul(
        self,
        definition_key: str,
        *,
        state: dict[str, Any],
        caller_role: str,
        cache_scope: CacheScope,
    ) -> DecisionResult:
        definition = self.catalog.get(definition_key)
        request = DecisionRequest(
            definition=definition,
            state=state,
            caller_role=caller_role,
            cache_scope=cache_scope,
            criteria=None,
        )
        return self._decide(request, None)

    # ------------------------------------------------------------ retrieval re-rank

    def rerank_retrieval(
        self,
        entries: Sequence[Any],
        *,
        query: str,
        caller_role: str,
        cache_scope: CacheScope,
        max_candidates: int = DEFAULT_MAX_EVAL_CANDIDATES,
    ) -> list[Any]:
        """Optionally reorder already-authorized candidates by Jev support score.

        Exact-target hits keep their slot and are never added/dropped. In
        ``off``/``shadow``/failed the original deterministic fused order is
        returned unchanged (shadow still records suggestions).
        """

        ordered = list(entries)
        if not ordered:
            return ordered
        non_exact = [(index, entry) for index, entry in enumerate(ordered) if not getattr(entry, "exact", False)]
        if not non_exact:
            return ordered
        results: dict[int, DecisionResult] = {}
        used_jev = False
        for index, entry in non_exact[:max_candidates]:
            result = self.score(
                "retrieval.support.v1",
                state=self._candidate_state(entry, query),
                caller_role=caller_role,
                cache_scope=cache_scope,
            )
            results[index] = result
            used_jev = used_jev or result.used_jev
        if not used_jev:
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

    # ------------------------------------------------------------------- helpers

    def item_support(
        self,
        items: Sequence[dict[str, Any]],
        *,
        content: str,
        spec_version: int | str,
        caller_role: str,
        cache_scope: CacheScope,
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
                candidate_ids=("SUPPORTED", "PARTIAL", "UNSUPPORTED", "UNCERTAIN"),
                state=state,
                caller_role=caller_role,
                cache_scope=cache_scope,
                deterministic="UNCERTAIN",
            )
            signals[str(item["item_id"])] = result.value
        return signals

    def next_action(
        self,
        *,
        message: str,
        fixed_anchor: dict[str, Any],
        current_mode: str,
        active_assessment: str | None,
        caller_role: str,
        cache_scope: CacheScope,
        deterministic: str = "OTHER",
    ) -> DecisionResult:
        return self.choice(
            "intent.next_action.v1",
            candidate_ids=(
                "CONTINUE", "ANSWER_AND_RESUME", "ANSWER_ONLY", "REPAIR_PREREQUISITE",
                "QUIZ_WAIT", "SUBMIT_ASSESSMENT", "PAUSE", "OTHER",
            ),
            state={
                "message": message,
                "fixed_anchor": fixed_anchor,
                "current_mode": current_mode,
                "active_assessment": active_assessment,
            },
            caller_role=caller_role,
            cache_scope=cache_scope,
            deterministic=deterministic,
        )

    def keep_segment(
        self,
        *,
        segment: str,
        current_task: str,
        fixed_anchor: dict[str, Any],
        remaining_scope: str,
        caller_role: str,
        cache_scope: CacheScope,
    ) -> bool:
        result = self.noul(
            "context.keep_segment.v1",
            state={
                "segment": segment,
                "current_task": current_task,
                "fixed_anchor": fixed_anchor,
                "remaining_scope": remaining_scope,
            },
            caller_role=caller_role,
            cache_scope=cache_scope,
        )
        if result.used_jev and isinstance(result.value, float):
            return result.value >= 0.5
        return True  # deterministic: keep fixed anchors + bounded recent history

    def criterion_review(
        self,
        *,
        frozen_question: dict[str, Any],
        criterion: dict[str, Any],
        reference_solution: str,
        student_answer: str,
        deterministic_verification: str,
        candidate_answer_spans: list[str],
        caller_role: str,
        cache_scope: CacheScope,
        deterministic: str = "NEEDS_REVIEW",
    ) -> DecisionResult:
        return self.choice(
            "assessment.criterion_review.v1",
            candidate_ids=("SATISFIED", "PARTIAL", "NOT_SATISFIED", "NEEDS_REVIEW"),
            state={
                "frozen_question": frozen_question,
                "frozen_rubric_criterion": criterion,
                "reference_solution": reference_solution,
                "student_answer": student_answer,
                "deterministic_verification": deterministic_verification,
                "candidate_answer_spans": candidate_answer_spans,
            },
            caller_role=caller_role,
            cache_scope=cache_scope,
            deterministic=deterministic,
        )

    # ------------------------------------------------------------------ internals

    def _decide(self, request: DecisionRequest, deterministic: Any) -> DecisionResult:
        decision = self.gateway.evaluate(request)
        suggestion = self._suggestion_value(request.definition, decision.suggestion)
        if decision.mode == "on" and decision.suggestion is not None:
            return DecisionResult(
                value=suggestion,
                suggestion=suggestion,
                used_jev=True,
                mode=decision.mode,
                outcome=decision.outcome,
                receipt_id=decision.receipt_id,
                input_hash=decision.input_hash,
            )
        return DecisionResult(
            value=deterministic,
            suggestion=suggestion,
            used_jev=False,
            mode=decision.mode,
            outcome=decision.outcome,
            receipt_id=decision.receipt_id,
            input_hash=decision.input_hash,
        )

    @staticmethod
    def _suggestion_value(definition: DecisionDefinition, suggestion: Any) -> Any:
        if suggestion is None:
            return None
        if definition.primitive == "Choice":
            return getattr(suggestion, "choice", None)
        if definition.primitive == "Score":
            score = getattr(suggestion, "score", None)
            return int(score) if score is not None else None
        return getattr(suggestion, "noul", None)

    @staticmethod
    def _level(result: DecisionResult | None) -> int:
        value = result.value if result is not None else None
        return value if isinstance(value, int) else -1

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
