"""Question Engine stage 6: hard validation gates plus non-authoritative semantic signals.

No scalar quality score exists here.  Code proves identities, marks, conditions, source scope,
question shape and the current blind-solve receipt.  TypeSafe Jev may provide two base signals plus
one separately receipted module signal for MCQ distractors or rule-violation semantics. A fallback,
missing or uncertain signal can only keep a candidate under review, never upgrade it to VALIDATED.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, model_validator

from app.jev import callsites
from app.jev.models import CacheScope
from app.jev.service import DecisionResult, SemanticDecisionService
from app.learning.blind_solve import BlindSolveReceipt
from app.learning.models import Contract, Identifier
from app.learning.question_author import (
    RULE_VIOLATION_POLICY_VERSION,
    AuthoredQuestionCandidate,
)
from app.learning.question_blueprint import QuestionBlueprint
from app.learning.question_evidence import QuestionEvidencePack

AmbiguityVerdict = Literal["CLEAR", "AMBIGUOUS", "UNDER_SPECIFIED", "CONTRADICTORY", "UNCERTAIN"]
AgreementVerdict = Literal["AGREE", "DISAGREE", "AMBIGUOUS", "UNCERTAIN"]
McqDistractorVerdict = Literal["ACCEPTABLE", "WEAK", "AMBIGUOUS", "UNCERTAIN"]
RuleViolationVerdict = Literal["SUPPORTED", "UNSUPPORTED", "AMBIGUOUS", "UNCERTAIN"]
SemanticVerdict = (
    AmbiguityVerdict | AgreementVerdict | McqDistractorVerdict | RuleViolationVerdict
)
SemanticDimension = Literal[
    "AMBIGUITY",
    "AUTHOR_BLIND_AGREEMENT",
    "MCQ_DISTRACTOR_QUALITY",
    "RULE_VIOLATION_QUALITY",
]
HardGateName = Literal[
    "INPUT_IDENTITY",
    "MARKS_MATCH",
    "SOURCE_SCOPE",
    "CONDITIONS_PRESENT",
    "QUESTION_SHAPE",
    "BLIND_SOLVE_CURRENT",
]


class SemanticSignal(Contract):
    dimension: SemanticDimension
    verdict: SemanticVerdict
    used_jev: bool
    receipt_id: Identifier | None = None
    path: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def dimension_and_receipt_match(self) -> SemanticSignal:
        allowed = {
            "AMBIGUITY": {
                "CLEAR", "AMBIGUOUS", "UNDER_SPECIFIED", "CONTRADICTORY", "UNCERTAIN",
            },
            "AUTHOR_BLIND_AGREEMENT": {"AGREE", "DISAGREE", "AMBIGUOUS", "UNCERTAIN"},
            "MCQ_DISTRACTOR_QUALITY": {"ACCEPTABLE", "WEAK", "AMBIGUOUS", "UNCERTAIN"},
            "RULE_VIOLATION_QUALITY": {"SUPPORTED", "UNSUPPORTED", "AMBIGUOUS", "UNCERTAIN"},
        }[self.dimension]
        if self.verdict not in allowed:
            raise ValueError("semantic verdict does not belong to its dimension")
        if self.used_jev and (self.receipt_id is None or self.path != "jev"):
            raise ValueError("an acted-on Jev signal requires its receipt and jev path")
        if not self.used_jev and self.path == "jev":
            raise ValueError("a fallback signal cannot claim the jev path")
        return self


class QuestionSemanticSignals(Contract):
    ambiguity: SemanticSignal
    answer_agreement: SemanticSignal
    specialized_quality: SemanticSignal | None = None

    @model_validator(mode="after")
    def dimensions_are_fixed(self) -> QuestionSemanticSignals:
        if self.ambiguity.dimension != "AMBIGUITY":
            raise ValueError("the ambiguity slot requires an AMBIGUITY signal")
        if self.answer_agreement.dimension != "AUTHOR_BLIND_AGREEMENT":
            raise ValueError("the agreement slot requires an AUTHOR_BLIND_AGREEMENT signal")
        if self.specialized_quality is not None and self.specialized_quality.dimension not in {
            "MCQ_DISTRACTOR_QUALITY",
            "RULE_VIOLATION_QUALITY",
        }:
            raise ValueError("the specialized slot requires a module-specific quality signal")
        return self

    def ordered(self) -> list[SemanticSignal]:
        signals = [self.ambiguity, self.answer_agreement]
        if self.specialized_quality is not None:
            signals.append(self.specialized_quality)
        return signals


class HardGateResult(Contract):
    gate: HardGateName
    status: Literal["PASS", "FAIL"]
    reason: str = Field(min_length=1, max_length=300)


class QuestionValidationReport(Contract):
    schema_version: Literal["question-validation-report.v1"] = "question-validation-report.v1"
    question_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["VALIDATED", "NEEDS_REVIEW", "REJECTED"]
    hard_gates: list[HardGateResult] = Field(min_length=6, max_length=6)
    semantic_signals: list[SemanticSignal] = Field(min_length=2, max_length=3)

    @property
    def ready_eligible(self) -> bool:
        return self.status == "VALIDATED"


def _gate(gate: HardGateName, passed: bool, reason: str) -> HardGateResult:
    return HardGateResult(gate=gate, status="PASS" if passed else "FAIL", reason=reason)


def _compact(value: str) -> str:
    """Whitespace/punctuation-insensitive condition comparison, without semantic guessing."""
    return re.sub(r"[^\w]+", "", value.casefold(), flags=re.UNICODE)


def _input_identity_matches(
    candidate: AuthoredQuestionCandidate,
    blueprint: QuestionBlueprint,
    evidence: QuestionEvidencePack,
) -> bool:
    return (
        candidate.blueprint_id == blueprint.blueprint_id
        and candidate.blueprint_hash == blueprint.identity()
        and candidate.evidence_pack_hash == evidence.identity()
        and candidate.course_id == blueprint.course_id == evidence.course_id
        and candidate.node_id == blueprint.node_id == evidence.node_id
        and candidate.objective_id == blueprint.objective_id == evidence.objective_id
        and candidate.question_type == blueprint.question_type
        and blueprint.spec_version == evidence.spec_version
        and blueprint.spec_content_hash == evidence.spec_content_hash
        and blueprint.source_scope == evidence.source_scope()
    )


def _source_scope_matches(
    candidate: AuthoredQuestionCandidate, evidence: QuestionEvidencePack
) -> bool:
    allowed = set(evidence.evidence_ids)
    used = set(candidate.public_question.source_refs)
    used.update(candidate.private_solution.source_refs)
    used.update(
        ref for step in candidate.private_solution.solution_steps for ref in step.source_refs
    )
    used.update(
        ref
        for distractor in candidate.private_solution.distractor_rationales
        for ref in distractor.source_refs
    )
    rule_analysis = candidate.private_solution.rule_violation_analysis
    if rule_analysis is not None:
        used.add(rule_analysis.rule_source_ref)
    return bool(used) and used.issubset(allowed)


def _conditions_present(candidate: AuthoredQuestionCandidate, blueprint: QuestionBlueprint) -> bool:
    question = _compact(candidate.public_question.question_text)
    return all(_compact(condition) in question for condition in blueprint.conditions)


def _question_shape_matches(
    candidate: AuthoredQuestionCandidate,
    blueprint: QuestionBlueprint,
    evidence: QuestionEvidencePack,
) -> bool:
    options = candidate.public_question.options
    correct = candidate.private_solution.correct_option_index
    if blueprint.question_type == "MCQ_SINGLE":
        mappings = candidate.private_solution.distractor_rationales
        expected = set(range(len(options))) - ({correct} if correct is not None else set())
        actual = [item.option_index for item in mappings]
        base_shape = (
            len(options) >= 2
            and correct is not None
            and 0 <= correct < len(options)
            and len(actual) == len(set(actual))
            and set(actual) == expected
            and bool(blueprint.misconception_targets)
            and all(
                item.misconception in blueprint.misconception_targets for item in mappings
            )
        )
    else:
        base_shape = (
            not options
            and correct is None
            and not candidate.private_solution.distractor_rationales
        )
    rule_analysis = candidate.private_solution.rule_violation_analysis
    if blueprint.generation_policy_version != RULE_VIOLATION_POLICY_VERSION:
        return base_shape and rule_analysis is None
    if not base_shape or blueprint.question_type != "EXPLANATION" or rule_analysis is None:
        return False
    fragment_by_id = {fragment.evidence_id: fragment for fragment in evidence.fragments}
    rule_fragment = fragment_by_id.get(rule_analysis.rule_source_ref)
    return (
        rule_fragment is not None
        and rule_analysis.rule_source_ref in candidate.public_question.source_refs
        and rule_analysis.rule_quote in rule_fragment.content
        and rule_analysis.proposed_statement in candidate.public_question.question_text
    )


def _fallback_signal(dimension: SemanticDimension, *, reason: str) -> SemanticSignal:
    return SemanticSignal(
        dimension=dimension,
        verdict="UNCERTAIN",
        used_jev=False,
        receipt_id=None,
        path=f"fallback:{reason}",
    )


def _semantic_signal(dimension: SemanticDimension, result: DecisionResult) -> SemanticSignal:
    if result.used_jev and result.receipt_id is None:
        return _fallback_signal(dimension, reason="unreceipted")
    verdict = str(result.value) if result.used_jev else "UNCERTAIN"
    return SemanticSignal(
        dimension=dimension,
        verdict=verdict,
        used_jev=result.used_jev,
        receipt_id=result.receipt_id if result.used_jev else None,
        path=result.path,
    )


def question_semantic_input_fields(
    *,
    candidate: AuthoredQuestionCandidate,
    blueprint: QuestionBlueprint,
    evidence: QuestionEvidencePack,
    blind_receipt: BlindSolveReceipt,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the exact state fields used by the two receipted semantic calls."""
    allowed_rules = [
        {"evidence_id": fragment.evidence_id, "content": fragment.content}
        for fragment in evidence.fragments
    ]
    return (
        {
            "question_text": candidate.public_question.question_text,
            "question_type": blueprint.question_type,
            "expected_answer_form": blueprint.expected_answer_form,
            "blueprint_conditions": blueprint.conditions,
            "allowed_rules": allowed_rules,
        },
        {
            "question_text": candidate.public_question.question_text,
            "author_candidate_answer": candidate.private_solution.model_dump(mode="json"),
            "blind_solution": blind_receipt.output,
            "blueprint_conditions": blueprint.conditions,
        },
    )


def required_specialized_semantic_dimension(
    blueprint: QuestionBlueprint,
) -> Literal["MCQ_DISTRACTOR_QUALITY", "RULE_VIOLATION_QUALITY"] | None:
    if blueprint.question_type == "MCQ_SINGLE":
        return "MCQ_DISTRACTOR_QUALITY"
    if blueprint.generation_policy_version == RULE_VIOLATION_POLICY_VERSION:
        return "RULE_VIOLATION_QUALITY"
    return None


def question_specialized_semantic_input_fields(
    *,
    candidate: AuthoredQuestionCandidate,
    blueprint: QuestionBlueprint,
    evidence: QuestionEvidencePack,
) -> tuple[SemanticDimension, str, dict[str, Any], tuple[str, ...]] | None:
    """Return the exact private state for the applicable module signal, if any."""
    allowed_rules = [
        {"evidence_id": fragment.evidence_id, "content": fragment.content}
        for fragment in evidence.fragments
    ]
    dimension = required_specialized_semantic_dimension(blueprint)
    if dimension == "MCQ_DISTRACTOR_QUALITY":
        return (
            dimension,
            "question.mcq_distractor_quality.v1",
            {
                "question_text": candidate.public_question.question_text,
                "options": candidate.public_question.options,
                "correct_option_index": candidate.private_solution.correct_option_index,
                "distractor_rationales": [
                    item.model_dump(mode="json")
                    for item in candidate.private_solution.distractor_rationales
                ],
                "misconception_targets": blueprint.misconception_targets,
                "allowed_rules": allowed_rules,
            },
            ("ACCEPTABLE", "WEAK", "AMBIGUOUS", "UNCERTAIN"),
        )
    if dimension == "RULE_VIOLATION_QUALITY":
        analysis = candidate.private_solution.rule_violation_analysis
        return (
            dimension,
            "question.rule_violation_quality.v1",
            {
                "question_text": candidate.public_question.question_text,
                "rule_violation_analysis": (
                    analysis.model_dump(mode="json") if analysis is not None else None
                ),
                "allowed_rules": allowed_rules,
            },
            ("SUPPORTED", "UNSUPPORTED", "AMBIGUOUS", "UNCERTAIN"),
        )
    return None


def collect_question_semantic_signals(
    service: SemanticDecisionService | None,
    *,
    candidate: AuthoredQuestionCandidate,
    blueprint: QuestionBlueprint,
    evidence: QuestionEvidencePack,
    blind_receipt: BlindSolveReceipt,
    scope: CacheScope,
) -> QuestionSemanticSignals:
    """Collect bounded TypeSafe signals; invalid prerequisites spend zero calls."""
    specialized_dimension = required_specialized_semantic_dimension(blueprint)
    reason: str | None = None
    if service is None:
        reason = "no_service"
    elif not _input_identity_matches(candidate, blueprint, evidence):
        reason = "input_mismatch"
    elif not blind_receipt.is_current_for(candidate.question_revision):
        reason = "stale_blind_solve"
    if reason is not None:
        return QuestionSemanticSignals(
            ambiguity=_fallback_signal("AMBIGUITY", reason=reason),
            answer_agreement=_fallback_signal("AUTHOR_BLIND_AGREEMENT", reason=reason),
            specialized_quality=(
                _fallback_signal(specialized_dimension, reason=reason)
                if specialized_dimension is not None
                else None
            ),
        )
    assert service is not None  # narrowed above; no-service returned fallback signals

    ambiguity_fields, agreement_fields = question_semantic_input_fields(
        candidate=candidate,
        blueprint=blueprint,
        evidence=evidence,
        blind_receipt=blind_receipt,
    )
    ambiguity = callsites.review_question_ambiguity(
        service,
        **ambiguity_fields,
        scope=scope,
    )
    agreement = callsites.review_question_answer_agreement(
        service,
        **agreement_fields,
        scope=scope,
    )
    specialized: SemanticSignal | None = None
    specialized_fields = question_specialized_semantic_input_fields(
        candidate=candidate,
        blueprint=blueprint,
        evidence=evidence,
    )
    if specialized_fields is not None:
        dimension, _, fields, _ = specialized_fields
        if dimension == "MCQ_DISTRACTOR_QUALITY":
            result = callsites.review_mcq_distractor_quality(service, **fields, scope=scope)
        else:
            result = callsites.review_rule_violation_quality(service, **fields, scope=scope)
        specialized = _semantic_signal(dimension, result)
    return QuestionSemanticSignals(
        ambiguity=_semantic_signal("AMBIGUITY", ambiguity),
        answer_agreement=_semantic_signal("AUTHOR_BLIND_AGREEMENT", agreement),
        specialized_quality=specialized,
    )


def validate_question_candidate(
    *,
    candidate: AuthoredQuestionCandidate,
    blueprint: QuestionBlueprint,
    evidence: QuestionEvidencePack,
    blind_receipt: BlindSolveReceipt,
    semantic_signals: QuestionSemanticSignals,
) -> QuestionValidationReport:
    """Evaluate six hard gates and the applicable independently receipted semantic dimensions."""
    identity = _input_identity_matches(candidate, blueprint, evidence)
    marks = candidate.marks == blueprint.marks
    sources = _source_scope_matches(candidate, evidence)
    conditions = _conditions_present(candidate, blueprint)
    shape = _question_shape_matches(candidate, blueprint, evidence)
    blind = blind_receipt.is_current_for(candidate.question_revision)
    hard_gates = [
        _gate("INPUT_IDENTITY", identity, "candidate is bound to the exact blueprint/evidence"),
        _gate("MARKS_MATCH", marks, "marks remain server-authored by the blueprint"),
        _gate("SOURCE_SCOPE", sources, "all question and solution refs are in the evidence pack"),
        _gate("CONDITIONS_PRESENT", conditions, "all explicit blueprint conditions are stated"),
        _gate("QUESTION_SHAPE", shape, "question/options/answer index match the blueprint type"),
        _gate("BLIND_SOLVE_CURRENT", blind, "blind solve is completed for this exact revision"),
    ]
    hard_failure = any(gate.status == "FAIL" for gate in hard_gates)
    ambiguity = semantic_signals.ambiguity
    agreement = semantic_signals.answer_agreement
    base_semantic_pass = (
        ambiguity.used_jev
        and ambiguity.verdict == "CLEAR"
        and agreement.used_jev
        and agreement.verdict == "AGREE"
    )
    expected_specialized = required_specialized_semantic_dimension(blueprint)
    specialized = semantic_signals.specialized_quality
    specialized_pass = (
        specialized is None
        if expected_specialized is None
        else (
            specialized is not None
            and specialized.dimension == expected_specialized
            and specialized.used_jev
            and specialized.verdict
            == {
                "MCQ_DISTRACTOR_QUALITY": "ACCEPTABLE",
                "RULE_VIOLATION_QUALITY": "SUPPORTED",
            }[expected_specialized]
        )
    )
    semantic_pass = base_semantic_pass and specialized_pass
    status = "REJECTED" if hard_failure else "VALIDATED" if semantic_pass else "NEEDS_REVIEW"
    return QuestionValidationReport(
        question_revision=candidate.question_revision,
        status=status,
        hard_gates=hard_gates,
        semantic_signals=semantic_signals.ordered(),
    )
