"""Advisory-only local (OpenJev) observation for the hybrid gate.

The self-hosted OpenJev candidate is a small, English, 512-token DeBERTa
classifier.  Its recorded qualification is ``UNSET``: a constant predictor that
scored exactly 0.50 on an exactly balanced oracle set, which is the arithmetic
of no signal rather than a measurement of 50% competence.  It therefore stays a
*local observation* and never a decision:

* a positive local result can never publish a question;
* a negative local result can never veto one;
* an outage, a timeout, an over-long input or a non-English item records a typed
  ``UNAVAILABLE``/``SKIPPED`` reason and the qualified strong review continues;
* nothing here deletes evidence, truncates an item, or triggers regeneration.

What it *is* good for, and what this class actually does, is producing a
recorded, reproducible, cheap signal on short English fragments -- so a
disagreement can point a deterministic check or a strong reviewer at a specific
span.  The check, not the probability, is what can block publication.

Input discipline: the exact encoded size is measured by the pinned service, not
estimated here, and the service itself rejects anything that would not fit
(``truncation`` is the string ``"error"``, and an over-long state is refused
rather than cut).  A refused item is recorded as ``SKIPPED`` with its reason --
it is never silently shortened until it fits.
"""

from __future__ import annotations

from typing import Any

from app.learning.deepseek_reviewer import LocalObservation, ReviewerInputs

# The four question kinds the local candidate may comment on.  Keys match the
# server-selected case ids so an observation can never be attached to a case the
# plan did not require.
_CASE_TO_DEFINITION = {
    "question.ambiguity.v1": "question.ambiguity.v1",
    "question.answer_agreement.v1": "question.answer_agreement.v1",
    "question.mcq_distractor_quality.v1": "question.mcq_distractor_quality.v1",
    "question.rule_violation_quality.v1": "question.rule_violation_quality.v1",
}

# The candidate is documented as an English, short-context model.  A local
# observation on a Chinese or mixed item would be an observation about a
# translated/compressed surrogate, so those items are skipped explicitly instead
# of being quietly translated.
_LOCAL_LANGUAGES = frozenset({"en"})

MAX_LOCAL_OBSERVATIONS = 4


class OpenJevLocalObserver:
    """Records advisory local observations; it owns no acceptance decision."""

    qualification = "UNQUALIFIED_ADVISORY"

    def __init__(self, service: Any | None) -> None:
        self.service = service

    @property
    def unavailable_reason(self) -> str | None:
        if self.service is None:
            return "NO_LOCAL_SERVICE"
        return None

    def observe(self, inputs: ReviewerInputs) -> list[LocalObservation]:
        """Return one advisory observation per required case.

        Never raises: every failure mode becomes a typed ``SKIPPED`` or
        ``UNAVAILABLE`` observation so the caller's strong review is unaffected.
        """
        if self.service is None:
            return [
                LocalObservation(case=case, status="UNAVAILABLE", reason="NO_LOCAL_SERVICE")
                for case in inputs.required_cases
            ]
        if inputs.language not in _LOCAL_LANGUAGES:
            return [
                LocalObservation(
                    case=case,
                    status="SKIPPED",
                    reason=f"LOCAL_LANGUAGE_OUT_OF_SCOPE:{inputs.language}",
                )
                for case in inputs.required_cases
            ]
        observations: list[LocalObservation] = []
        for case in inputs.required_cases[:MAX_LOCAL_OBSERVATIONS]:
            observations.append(self._one(case, inputs))
        return observations

    def _one(self, case: str, inputs: ReviewerInputs) -> LocalObservation:
        definition = _CASE_TO_DEFINITION.get(case)
        if definition is None:
            return LocalObservation(
                case=case, status="SKIPPED", reason="LOCAL_CASE_NOT_LOCAL_ELIGIBLE"
            )
        try:
            result = self._ask(definition, inputs)
        except Exception as error:  # noqa: BLE001 - a local observer may never block
            # Provider exception text is never reflected: only the local class
            # name, which is a stable local fact rather than upstream content.
            return LocalObservation(
                case=case,
                status="UNAVAILABLE",
                reason=f"LOCAL_OBSERVER_{type(error).__name__.upper()[:40]}",
            )
        if result is None:
            return LocalObservation(
                case=case, status="UNAVAILABLE", reason="LOCAL_NOT_CONFIGURED"
            )
        used = bool(getattr(result, "used_jev", False))
        if not used:
            return LocalObservation(
                case=case,
                status="UNAVAILABLE",
                reason=str(getattr(result, "path", "fallback:unknown"))[:120],
            )
        raw = getattr(result, "raw", None) or {}
        probabilities = {}
        if isinstance(raw, dict):
            distribution = raw.get("probabilities")
            if isinstance(distribution, dict):
                probabilities = {
                    str(key): float(value)
                    for key, value in distribution.items()
                    if isinstance(value, (int, float))
                }
        return LocalObservation(
            case=case,
            status="OBSERVED",
            verdict=str(getattr(result, "value", None) or "") or None,
            probabilities=probabilities,
            input_hash=getattr(result, "input_hash", None),
            qualification=self.qualification,
        )

    def _ask(self, definition: str, inputs: ReviewerInputs) -> Any:
        """Ask the local service through the existing receipted callsite."""
        from app.jev import callsites
        from app.jev.models import CacheScope

        # An advisory observation is deliberately not cached under the
        # publication scope: it must not be able to satisfy the durable-receipt
        # check that a real semantic decision has to pass.
        scope = CacheScope(
            owner_scope_hash=None,
            course_id=inputs.course_id,
            workspace_id=None,
            node_id=inputs.node_id,
            spec_version=str(inputs.spec_version),
            question_hash=inputs.question_revision,
            input_hash=None,
        )
        allowed_rules = [
            {"evidence_id": fragment["evidence_id"], "content": fragment["content"]}
            for fragment in inputs.evidence
        ]
        if definition == "question.ambiguity.v1":
            return callsites.review_question_ambiguity(
                self.service,
                question_text=inputs.question_text,
                question_type=inputs.question_type,
                expected_answer_form="short_answer",
                blueprint_conditions=list(inputs.rubric),
                allowed_rules=allowed_rules,
                scope=scope,
            )
        if definition == "question.answer_agreement.v1":
            return callsites.review_question_answer_agreement(
                self.service,
                question_text=inputs.question_text,
                author_candidate_answer=dict(inputs.solution_a),
                blind_solution=str(inputs.solution_b),
                blueprint_conditions=list(inputs.rubric),
                scope=scope,
            )
        if definition == "question.mcq_distractor_quality.v1":
            return callsites.review_mcq_distractor_quality(
                self.service,
                question_text=inputs.question_text,
                options=list(inputs.options),
                correct_option_index=inputs.solution_a.get("correct_option_index"),
                distractor_rationales=list(
                    inputs.solution_a.get("distractor_rationales") or []
                ),
                misconception_targets=[],
                allowed_rules=allowed_rules,
                scope=scope,
            )
        return callsites.review_rule_violation_quality(
            self.service,
            question_text=inputs.question_text,
            rule_violation_analysis=inputs.solution_a.get("rule_violation_analysis"),
            allowed_rules=allowed_rules,
            scope=scope,
        )
