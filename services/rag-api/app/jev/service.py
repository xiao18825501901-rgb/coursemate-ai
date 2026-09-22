"""Thin per-decision helpers over :class:`JevGateway`.

Every helper:

* builds legal candidates ONLY from server-side authorized data (the caller
  passes the authorized ids/spans/items — the model may only *select* one);
* never lets the model create a candidate id: a Choice must return one of the
  supplied ids, and a Score/Noul returns a signal, never a grade;
* applies a deterministic fallback in ``off``/``shadow``/failed — in ``shadow``
  the deterministic result is returned and the Jev suggestion is recorded in the
  receipt only (``used_jev`` stays False);
* bounds the state payload per definition (rule 12) and keeps the decisive
  fields (current question, key conditions, numbers, units) instead of blindly
  truncating the tail; if the decisive content does not fit, it falls back
  deterministically rather than sending a half-question;
* returns a :class:`DecisionResult` carrying the value to use, whether Jev was
  actually used, the mode, the receipt id, a concentration/confidence estimate,
  the definition key + version, and a ``path`` of ``jev`` or ``fallback:<reason>``;
* never writes DB state, grades, LEARNED or budgets — the only side effect is a
  ``jev_decision_receipts`` row plus this service's in-memory telemetry
  (:meth:`summary`), which exists so a test can assert the counts.

The business layer imports :mod:`app.jev.callsites` (the 12 call-site functions),
not this module directly; the callsites apply their own ``used_jev`` guard before
acting on a value.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.jev.catalog import DecisionDefinition
from app.jev.gateway import DecisionRequest, JevGateway
from app.jev.models import CacheScope, owner_scope_hash

# Retrieval re-rank candidate cap (the owner's bound: at most 12-16 authorized
# fused candidates; more is never sent to Jev).
DEFAULT_MAX_EVAL_CANDIDATES = 16

# Per-definition state payload budget (characters). The gateway's global
# 40k-char bound still applies; these are the tighter, per-definition caps so a
# single oversized field can never push the whole question past the sensible
# evidence window. Tokens are estimated at ~4 chars/token for accounting only.
_DEFAULT_MAX_STATE_CHARS = 6_000
_STATE_BUDGETS: dict[str, int] = {
    "coverage.item_support.v1": 16_000,
    "assessment.criterion_review.v1": 12_000,
    "template.match.v1": 12_000,
    "corpus.quality.v1": 10_000,
    "context.keep_segment.v1": 8_000,
}

# The decisive fields per definition: retained verbatim before any optional
# field is added. Never a tail-blind truncation that would drop the question itself.
_MUST_KEEP: dict[str, tuple[str, ...]] = {
    "retrieval.support.v1": ("query", "candidate_id", "candidate_text"),
    "source.supports_claim.v1": ("claim", "source_span"),
    "source.select_span.v1": ("claim", "candidate_spans"),
    "context.keep_segment.v1": ("segment", "current_task", "fixed_anchor"),
    "intent.next_action.v1": ("message", "fixed_anchor"),
    "pedagogy.next_method.v1": ("learner_request", "topic", "current_step"),
    "coverage.item_support.v1": ("saved_delivery", "required_item", "node_spec_version"),
    "assessment.criterion_review.v1": (
        "frozen_question", "frozen_rubric_criterion", "reference_solution", "student_answer",
    ),
    "template.match.v1": (
        "course_title", "curriculum_samples", "materials_revision", "known_course_level",
    ),
    "exercise.prototype.v1": ("node", "eligible_prototypes"),
    "graph.prerequisite.v1": ("current_node", "allowed_predecessor_nodes"),
    "corpus.quality.v1": ("document_fragment", "parse_flags"),
    "extraction.field_grounded.v1": (
        "candidate_value", "supplied_text", "field_name", "question_id",
    ),
}


class InputBudgetExceeded(Exception):
    """The decisive fields alone exceed the per-definition state budget."""

    def __init__(self, definition_key: str, *, retained_chars: int, max_chars: int) -> None:
        super().__init__(
            f"{definition_key}: decisive fields ({retained_chars} chars) exceed the "
            f"{max_chars}-char state budget; falling back rather than half-sending"
        )
        self.definition_key = definition_key
        self.retained_chars = retained_chars
        self.max_chars = max_chars


@dataclass(frozen=True)
class BudgetProvenance:
    """Per-call input-budget accounting (rule 12)."""

    definition_key: str
    definition_version: str
    max_chars: int
    state_chars: int
    retained_fields: tuple[str, ...]
    dropped_fields: tuple[str, ...]
    candidate_count: int
    input_token_estimate: int
    trimmed: bool
    fit: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "definition_key": self.definition_key,
            "definition_version": self.definition_version,
            "max_chars": self.max_chars,
            "state_chars": self.state_chars,
            "retained_fields": list(self.retained_fields),
            "dropped_fields": list(self.dropped_fields),
            "candidate_count": self.candidate_count,
            "input_token_estimate": self.input_token_estimate,
            "trimmed": self.trimmed,
            "fit": self.fit,
        }


@dataclass
class DecisionResult:
    """The value to use plus the (recorded) Jev suggestion.

    ``value`` is already the *final* value the caller should use: the validated
    Jev suggestion when ``mode == "on"`` and it validated, otherwise the
    deterministic fallback. ``used_jev`` is True only in the first case, so a
    caller that must not change behaviour on a fallback checks ``used_jev``
    before acting on ``value``.
    """

    value: Any
    suggestion: Any
    used_jev: bool
    mode: str
    outcome: str
    receipt_id: str | None
    input_hash: str | None
    path: str = "fallback:off"  # "jev" | "fallback:<reason>"
    fallback_reason: str | None = None
    confidence: float | None = None
    definition_key: str = ""
    definition_version: str = ""


@dataclass(frozen=True)
class TemplateOption:
    """One professional template the model may choose (id + label + degree level)."""

    id: str
    label: str
    level: str  # "graduate" | "undergraduate" | "unknown"


@dataclass
class DecisionRecord:
    """One per-call telemetry record, keyed like a receipt row (in-memory only)."""

    definition_key: str
    definition_version: str
    mode: str
    path: str
    outcome: str
    latency_ms: float | None
    confidence: float | None
    receipt_id: str | None
    fallback_reason: str | None = None


class SemanticDecisionService:
    """Non-authoritative semantic-decision layer."""

    def __init__(self, gateway: JevGateway) -> None:
        self.gateway = gateway
        self.catalog = gateway.catalog
        self.records: list[DecisionRecord] = []
        self.budget_records: dict[str, dict[str, Any]] = {}

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

    # ------------------------------------------------------------ observability

    def summary(self) -> dict[str, Any]:
        """Counts per ``definition_key::path`` plus records and budget provenance."""
        counts: dict[str, int] = {}
        for record in self.records:
            counts[f"{record.definition_key}::{record.path}"] = (
                counts.get(f"{record.definition_key}::{record.path}", 0) + 1
            )
        return {
            "counts": counts,
            "records": [record.__dict__ for record in self.records],
            "budgets": dict(self.budget_records),
        }

    def record_budget(self, key: str | None, provenance: dict[str, Any]) -> None:
        """Attach per-call input-budget provenance (rule 12) to a decision."""
        if key is None:
            return
        self.budget_records[key] = dict(provenance)

    # -------------------------------------------------------------- input budget

    def bound_state(
        self,
        definition_key: str,
        fields: dict[str, Any],
        *,
        must_keep: Sequence[str] = (),
        max_chars: int | None = None,
        candidate_count: int = 0,
    ) -> tuple[dict[str, Any], BudgetProvenance]:
        """Bound a state payload by keeping decisive fields first.

        ``must_keep`` fields are retained verbatim (in the order given); the
        remaining fields are appended only while they fit. If a ``must_keep``
        field alone does not fit, :class:`InputBudgetExceeded` is raised so the
        caller can fall back deterministically instead of sending a half-question.
        """
        definition = self.catalog.get(definition_key)
        cap = (
            max_chars
            if max_chars is not None
            else _STATE_BUDGETS.get(definition_key, _DEFAULT_MAX_STATE_CHARS)
        )

        def _chars(payload: dict[str, Any]) -> int:
            return len(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))

        total_chars = _chars(fields)
        retained: dict[str, Any] = {}
        for key in must_keep:
            if key not in fields:
                continue
            candidate = {**retained, key: fields[key]}
            if _chars(candidate) > cap:
                prov = BudgetProvenance(
                    definition_key=definition.key,
                    definition_version=self.catalog.version,
                    max_chars=cap,
                    state_chars=_chars(candidate),
                    retained_fields=tuple(retained),
                    dropped_fields=tuple(k for k in fields if k not in retained),
                    candidate_count=candidate_count,
                    input_token_estimate=max(0, total_chars // 4),
                    trimmed=True,
                    fit=False,
                )
                self.record_budget(f"fallback:{definition_key}", prov.as_dict())
                raise InputBudgetExceeded(
                    definition_key, retained_chars=_chars(candidate), max_chars=cap
                )
            retained[key] = fields[key]

        dropped: list[str] = []
        for key in fields:
            if key in must_keep:
                continue
            candidate = {**retained, key: fields[key]}
            if _chars(candidate) > cap:
                dropped.append(key)
            else:
                retained[key] = fields[key]

        state_chars = _chars(retained)
        prov = BudgetProvenance(
            definition_key=definition.key,
            definition_version=self.catalog.version,
            max_chars=cap,
            state_chars=state_chars,
            retained_fields=tuple(retained),
            dropped_fields=tuple(dropped),
            candidate_count=candidate_count,
            input_token_estimate=max(0, state_chars // 4),
            trimmed=bool(dropped),
            fit=True,
        )
        return retained, prov

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
        criteria = {str(cid): labels.get(str(cid), "") for cid in candidate_ids}
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
        deterministic: Any = None,
    ) -> DecisionResult:
        definition = self.catalog.get(definition_key)
        request = DecisionRequest(
            definition=definition,
            state=state,
            caller_role=caller_role,
            cache_scope=cache_scope,
            criteria=None,
        )
        return self._decide(request, deterministic)

    def noul(
        self,
        definition_key: str,
        *,
        state: dict[str, Any],
        caller_role: str,
        cache_scope: CacheScope,
        deterministic: Any = None,
    ) -> DecisionResult:
        definition = self.catalog.get(definition_key)
        request = DecisionRequest(
            definition=definition,
            state=state,
            caller_role=caller_role,
            cache_scope=cache_scope,
            criteria=None,
        )
        return self._decide(request, deterministic)

    # ------------------------------------------------------- bounded primitives

    def _choice_bounded(
        self,
        definition_key: str,
        *,
        fields: dict[str, Any],
        candidate_ids: Sequence[str],
        candidate_labels: dict[str, str] | None,
        caller_role: str,
        cache_scope: CacheScope,
        deterministic: str,
        max_chars: int | None = None,
    ) -> DecisionResult:
        try:
            state, prov = self.bound_state(
                definition_key,
                fields,
                must_keep=_MUST_KEEP.get(definition_key, ()),
                max_chars=max_chars,
                candidate_count=len(candidate_ids),
            )
        except InputBudgetExceeded:
            return self.degraded(definition_key, deterministic, "input_too_long")
        result = self.choice(
            definition_key,
            candidate_ids=candidate_ids,
            candidate_labels=candidate_labels,
            state=state,
            caller_role=caller_role,
            cache_scope=cache_scope,
            deterministic=deterministic,
        )
        self.record_budget(result.input_hash, prov.as_dict())
        return result

    def _score_bounded(
        self,
        definition_key: str,
        *,
        fields: dict[str, Any],
        caller_role: str,
        cache_scope: CacheScope,
        deterministic: Any = None,
        max_chars: int | None = None,
    ) -> DecisionResult:
        levels = len(self.catalog.get(definition_key).score_levels)
        try:
            state, prov = self.bound_state(
                definition_key,
                fields,
                must_keep=_MUST_KEEP.get(definition_key, ()),
                max_chars=max_chars,
                candidate_count=levels,
            )
        except InputBudgetExceeded:
            return self.degraded(definition_key, deterministic, "input_too_long")
        result = self.score(
            definition_key,
            state=state,
            caller_role=caller_role,
            cache_scope=cache_scope,
            deterministic=deterministic,
        )
        self.record_budget(result.input_hash, prov.as_dict())
        return result

    def _noul_bounded(
        self,
        definition_key: str,
        *,
        fields: dict[str, Any],
        caller_role: str,
        cache_scope: CacheScope,
        deterministic: Any = None,
        max_chars: int | None = None,
    ) -> DecisionResult:
        try:
            state, prov = self.bound_state(
                definition_key,
                fields,
                must_keep=_MUST_KEEP.get(definition_key, ()),
                max_chars=max_chars,
                candidate_count=2,
            )
        except InputBudgetExceeded:
            return self.degraded(definition_key, deterministic, "input_too_long")
        result = self.noul(
            definition_key,
            state=state,
            caller_role=caller_role,
            cache_scope=cache_scope,
            deterministic=deterministic,
        )
        self.record_budget(result.input_hash, prov.as_dict())
        return result

    # ------------------------------------------------------------ retrieval re-rank

    def retrieval_support(
        self,
        entry: Any,
        *,
        query: str,
        caller_role: str,
        cache_scope: CacheScope,
    ) -> DecisionResult:
        """retrieval.support.v1 (score 0..4) for one already-authorized candidate."""
        fields = self._candidate_state(entry, query)
        return self._score_bounded(
            "retrieval.support.v1",
            fields=fields,
            caller_role=caller_role,
            cache_scope=cache_scope,
        )

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
        non_exact = [
            (index, entry)
            for index, entry in enumerate(ordered)
            if not getattr(entry, "exact", False)
        ]
        if not non_exact:
            return ordered
        results: dict[int, DecisionResult] = {}
        used_jev = False
        for index, entry in non_exact[:max_candidates]:
            result = self.retrieval_support(
                entry, query=query, caller_role=caller_role, cache_scope=cache_scope
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
        for index, entry in zip(non_exact_indices, sorted_non_exact, strict=True):
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
        caller_role: str,
        cache_scope: CacheScope,
    ) -> DecisionResult:
        """source.supports_claim.v1 (noul): does this span support this claim."""
        return self._noul_bounded(
            "source.supports_claim.v1",
            fields={
                "claim": claim,
                "source_span": source_span,
                "source_version": source_version,
                "task_scope": task_scope,
            },
            caller_role=caller_role,
            cache_scope=cache_scope,
        )

    def select_span(
        self,
        *,
        claim: str,
        candidate_spans: Sequence[str],
        caller_role: str,
        cache_scope: CacheScope,
        deterministic: str = "NO_SUPPORT",
    ) -> DecisionResult:
        """source.select_span.v1 (choice): select a supplied span id only."""
        ids = [str(span) for span in candidate_spans]
        return self._choice_bounded(
            "source.select_span.v1",
            fields={"claim": claim, "candidate_spans": ids},
            candidate_ids=("NO_SUPPORT", *ids),
            candidate_labels=None,
            caller_role=caller_role,
            cache_scope=cache_scope,
            deterministic=deterministic,
        )

    # -------------------------------------------------------------- context keep

    def keep_segment_decision(
        self,
        *,
        segment: str,
        current_task: str,
        fixed_anchor: dict[str, Any],
        remaining_scope: str,
        caller_role: str,
        cache_scope: CacheScope,
    ) -> DecisionResult:
        """context.keep_segment.v1 (noul): keep an optional history segment.

        Only *optional* history is ever offered; the fixed anchor set is outside
        this selector and is never dropped.
        """
        return self._noul_bounded(
            "context.keep_segment.v1",
            fields={
                "segment": segment,
                "current_task": current_task,
                "fixed_anchor": fixed_anchor,
                "remaining_scope": remaining_scope,
            },
            caller_role=caller_role,
            cache_scope=cache_scope,
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
        result = self.keep_segment_decision(
            segment=segment,
            current_task=current_task,
            fixed_anchor=fixed_anchor,
            remaining_scope=remaining_scope,
            caller_role=caller_role,
            cache_scope=cache_scope,
        )
        if result.used_jev and isinstance(result.value, float):
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
        caller_role: str,
        cache_scope: CacheScope,
        deterministic: str = "OTHER",
    ) -> DecisionResult:
        return self._choice_bounded(
            "intent.next_action.v1",
            fields={
                "message": message,
                "fixed_anchor": fixed_anchor,
                "current_mode": current_mode,
                "active_assessment": active_assessment,
            },
            candidate_ids=(
                "CONTINUE", "ANSWER_AND_RESUME", "ANSWER_ONLY", "REPAIR_PREREQUISITE",
                "QUIZ_WAIT", "SUBMIT_ASSESSMENT", "PAUSE", "OTHER",
            ),
            candidate_labels=None,
            caller_role=caller_role,
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
        caller_role: str,
        cache_scope: CacheScope,
        deterministic: str = "CONTINUE",
    ) -> DecisionResult:
        """pedagogy.next_method.v1 (choice): presentation strategy, not a grade."""
        return self._choice_bounded(
            "pedagogy.next_method.v1",
            fields={
                "learner_request": learner_request,
                "known_prior_evidence": known_prior_evidence,
                "topic": topic,
                "template_profile": template_profile,
                "current_step": current_step,
            },
            candidate_ids=(
                "WORKED_EXAMPLE", "TRACE", "DEFINITION", "COUNTEREXAMPLE", "COMPARE", "CONTINUE",
            ),
            candidate_labels=None,
            caller_role=caller_role,
            cache_scope=cache_scope,
            deterministic=deterministic,
        )

    # ----------------------------------------------------------- coverage support

    def item_support_one(
        self,
        item: dict[str, Any],
        *,
        content: str,
        spec_version: int | str,
        caller_role: str,
        cache_scope: CacheScope,
    ) -> DecisionResult:
        """coverage.item_support.v1 (choice) for one REQUIRED item (signal only)."""
        return self._choice_bounded(
            "coverage.item_support.v1",
            fields={
                "saved_delivery": content,
                "required_item": item,
                "valid_spans": [],
                "node_spec_version": str(spec_version),
            },
            candidate_ids=("SUPPORTED", "PARTIAL", "UNSUPPORTED", "UNCERTAIN"),
            candidate_labels=None,
            caller_role=caller_role,
            cache_scope=cache_scope,
            deterministic="UNCERTAIN",
        )

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
            result = self.item_support_one(
                item,
                content=content,
                spec_version=spec_version,
                caller_role=caller_role,
                cache_scope=cache_scope,
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
        caller_role: str,
        cache_scope: CacheScope,
        deterministic: str = "NEEDS_REVIEW",
    ) -> DecisionResult:
        return self._choice_bounded(
            "assessment.criterion_review.v1",
            fields={
                "frozen_question": frozen_question,
                "frozen_rubric_criterion": criterion,
                "reference_solution": reference_solution,
                "student_answer": student_answer,
                "deterministic_verification": deterministic_verification,
                "candidate_answer_spans": candidate_answer_spans,
            },
            candidate_ids=("SATISFIED", "PARTIAL", "NOT_SATISFIED", "NEEDS_REVIEW"),
            candidate_labels=None,
            caller_role=caller_role,
            cache_scope=cache_scope,
            deterministic=deterministic,
        )

    # -------------------------------------------------------------- classification

    def match_template(
        self,
        *,
        templates: Sequence[TemplateOption],
        state: dict[str, Any],
        caller_role: str,
        cache_scope: CacheScope,
        deterministic: str = "OTHER",
    ) -> DecisionResult:
        """template.match.v1 (choice): hierarchical degree -> template matching.

        Never sends the full 14-template description list flat: stage 1 chooses
        the degree level, stage 2 the specific template within it. "cannot decide"
        returns OTHER. ``known_course_level`` (the course's own declared level)
        is an input hint, never an inference about the learner's degree.
        """
        options = list(templates)
        if not options:
            return self.degraded("template.match.v1", deterministic, "no_templates")
        levels = sorted({option.level for option in options if option.level != "unknown"})
        if not levels:
            return self.degraded("template.match.v1", deterministic, "no_levels")

        stage1 = self._choice_bounded(
            "template.match.v1",
            fields={**state, "stage": "degree"},
            candidate_ids=("OTHER", *levels),
            candidate_labels={
                "OTHER": "Cannot decide the degree level",
                **{level_name: level_name for level_name in levels},
            },
            caller_role=caller_role,
            cache_scope=cache_scope,
            deterministic=deterministic,
        )
        if not stage1.used_jev or stage1.value not in levels:
            return stage1
        level = stage1.value
        within = [option for option in options if option.level == level]
        if not within:
            return stage1
        stage2 = self._choice_bounded(
            "template.match.v1",
            fields={**state, "stage": "template", "degree": level},
            candidate_ids=("OTHER", *[option.id for option in within]),
            candidate_labels={
                "OTHER": "None of these templates matches",
                **{option.id: option.label for option in within},
            },
            caller_role=caller_role,
            cache_scope=cache_scope,
            deterministic=deterministic,
        )
        if stage2.used_jev and stage2.value in {option.id for option in within}:
            return stage2
        return stage2  # OTHER (deterministic) keeps the audit trail of both stages

    # ---------------------------------------------------------- exercise prototype

    def exercise_prototype(
        self,
        *,
        node: Any,
        eligible_prototypes: Sequence[str],
        recent_exposures: Any,
        learning_evidence: Any,
        caller_role: str,
        cache_scope: CacheScope,
        deterministic: str = "NONE",
    ) -> DecisionResult:
        """exercise.prototype.v1 (choice): a real authorized prototype id only."""
        ids = [str(prototype) for prototype in eligible_prototypes]
        return self._choice_bounded(
            "exercise.prototype.v1",
            fields={
                "node": node,
                "eligible_prototypes": ids,
                "recent_exposures": recent_exposures,
                "learning_evidence": learning_evidence,
            },
            candidate_ids=("NONE", *ids),
            candidate_labels=None,
            caller_role=caller_role,
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
        caller_role: str,
        cache_scope: CacheScope,
        deterministic: str = "NONE",
    ) -> DecisionResult:
        """graph.prerequisite.v1 (choice): legal neighbours only, never a new tree."""
        ids = [str(node) for node in allowed_predecessor_nodes]
        return self._choice_bounded(
            "graph.prerequisite.v1",
            fields={
                "current_node": current_node,
                "error": error,
                "allowed_predecessor_nodes": ids,
            },
            candidate_ids=("NONE", *ids),
            candidate_labels=None,
            caller_role=caller_role,
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
        caller_role: str,
        cache_scope: CacheScope,
        deterministic: int = 1,
    ) -> DecisionResult:
        """corpus.quality.v1 (score 0..3): offline evidence suitability only."""
        result = self._score_bounded(
            "corpus.quality.v1",
            fields={
                "document_fragment": document_fragment,
                "source_metadata": source_metadata,
                "parse_flags": parse_flags,
            },
            caller_role=caller_role,
            cache_scope=cache_scope,
            deterministic=deterministic,
        )
        if result.used_jev and isinstance(result.value, (int, float)):
            result.value = int(round(result.value))
        elif isinstance(result.value, str) and result.value.isdigit():
            result.value = int(result.value)
        return result

    # ------------------------------------------------------------- extraction

    def field_grounded(
        self,
        *,
        question_id: str,
        part_id: str | None,
        field_name: str,
        candidate_value: Any,
        unit: str | None,
        supplied_text: str,
        source_region: dict[str, Any],
        caller_role: str,
        cache_scope: CacheScope,
        deterministic: str = "UNCERTAIN",
    ) -> DecisionResult:
        """extraction.field_grounded.v1: does the already-read field belong here?

        The candidate vocabulary is read from the catalog entry itself, so a
        caller can neither widen nor rename it, and the deterministic fallback is
        ``UNCERTAIN`` — an unresolved field is never reported as accepted.
        """
        definition_key = "extraction.field_grounded.v1"
        criteria = dict(self.catalog.get(definition_key).criteria or {})
        return self._choice_bounded(
            definition_key,
            fields={
                "question_id": question_id,
                "part_id": part_id,
                "field_name": field_name,
                "candidate_value": candidate_value,
                "unit": unit,
                "supplied_text": supplied_text,
                "source_region": source_region,
            },
            candidate_ids=tuple(criteria),
            candidate_labels=criteria,
            caller_role=caller_role,
            cache_scope=cache_scope,
            deterministic=deterministic,
        )

    # ------------------------------------------------------------------ internals

    def degraded(self, definition_key: str, deterministic: Any, reason: str) -> DecisionResult:
        """Return a recorded deterministic fallback without any transport call."""
        self.records.append(
            DecisionRecord(
                definition_key=definition_key,
                definition_version=self.catalog.version,
                mode="off",
                path=f"fallback:{reason}",
                outcome="off",
                latency_ms=None,
                confidence=None,
                receipt_id=None,
                fallback_reason=reason,
            )
        )
        return DecisionResult(
            value=deterministic,
            suggestion=None,
            used_jev=False,
            mode="off",
            outcome="off",
            receipt_id=None,
            input_hash=None,
            path=f"fallback:{reason}",
            fallback_reason=reason,
            confidence=None,
            definition_key=definition_key,
            definition_version=self.catalog.version,
        )

    def _decide(self, request: DecisionRequest, deterministic: Any) -> DecisionResult:
        decision = self.gateway.evaluate(request)
        definition = request.definition
        suggestion = self._suggestion_value(definition, decision.suggestion)
        confidence = self._confidence(definition, decision.suggestion)
        used = decision.mode == "on" and decision.suggestion is not None
        if used:
            path = "jev"
            reason: str | None = None
            value = suggestion
        else:
            reason = decision.mode if decision.mode != "on" else decision.outcome
            path = f"fallback:{reason}"
            value = deterministic
        self.records.append(
            DecisionRecord(
                definition_key=definition.key,
                definition_version=self.catalog.version,
                mode=decision.mode,
                path=path,
                outcome=decision.outcome,
                latency_ms=decision.latency_ms,
                confidence=confidence,
                receipt_id=decision.receipt_id,
                fallback_reason=reason,
            )
        )
        return DecisionResult(
            value=value,
            suggestion=suggestion,
            used_jev=used,
            mode=decision.mode,
            outcome=decision.outcome,
            receipt_id=decision.receipt_id,
            input_hash=decision.input_hash,
            path=path,
            fallback_reason=reason,
            confidence=confidence,
            definition_key=definition.key,
            definition_version=self.catalog.version,
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
    def _confidence(definition: DecisionDefinition, suggestion: Any) -> float | None:
        """A concentration estimate, never a grade or a correctness probability.

        Noul: distance of the yes-probability from 0.5 (0 = maximally uncertain,
        1 = fully certain). Choice/Score: the transport's own ``confidence`` in
        ``raw`` when present, else None (the Jev contract does not guarantee one).
        """
        if suggestion is None:
            return None
        if definition.primitive == "Noul":
            probability = getattr(suggestion, "noul", None)
            if isinstance(probability, (int, float)) and not isinstance(probability, bool):
                return round(2 * abs(float(probability) - 0.5), 4)
            return None
        raw = getattr(suggestion, "raw", {}) or {}
        confidence = raw.get("confidence")
        if confidence is None:
            return None
        try:
            return round(float(confidence), 4)
        except (TypeError, ValueError):
            return None

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
            "candidate_id": str(
                getattr(entry, "chunk_id", "") or getattr(hit, "chunk_id", "") or ""
            ),
            "candidate_text": content,
            "source_metadata": {
                "scopes": list(getattr(entry, "scopes", ())),
                "filename": str(getattr(hit, "filename", "") or ""),
                "locator": (
                    f"{getattr(hit, 'locator_type', '')}:{getattr(hit, 'locator_value', '')}"
                ),
            },
        }


__all__ = [
    "BudgetProvenance",
    "DEFAULT_MAX_EVAL_CANDIDATES",
    "DecisionRecord",
    "DecisionResult",
    "InputBudgetExceeded",
    "SemanticDecisionService",
    "TemplateOption",
]
