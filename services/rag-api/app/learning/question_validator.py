"""Question Engine stage 6: hard validation gates plus non-authoritative semantic signals.

No scalar quality score exists here.  Code proves identities, marks, conditions, source scope,
question shape and the current blind-solve receipt.  TypeSafe Jev may provide two separately
receipted semantic signals (ambiguity and author/blind agreement); a fallback or uncertain signal
can only keep a candidate under review, never upgrade it to VALIDATED.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, model_validator

from app.jev import callsites
from app.jev.models import CacheScope
from app.jev.service import DecisionResult, SemanticDecisionService
from app.learning.blind_solve import BlindSolveReceipt
from app.learning.models import Contract, Identifier
from app.learning.question_author import AuthoredQuestionCandidate
from app.learning.question_blueprint import QuestionBlueprint
from app.learning.question_evidence import QuestionEvidencePack

AmbiguityVerdict = Literal["CLEAR", "AMBIGUOUS", "UNDER_SPECIFIED", "CONTRADICTORY", "UNCERTAIN"]
AgreementVerdict = Literal["AGREE", "DISAGREE", "AMBIGUOUS", "UNCERTAIN"]
SemanticVerdict = AmbiguityVerdict | AgreementVerdict
SemanticDimension = Literal["AMBIGUITY", "AUTHOR_BLIND_AGREEMENT"]
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
        allowed = (
            {"CLEAR", "AMBIGUOUS", "UNDER_SPECIFIED", "CONTRADICTORY", "UNCERTAIN"}
            if self.dimension == "AMBIGUITY"
            else {"AGREE", "DISAGREE", "AMBIGUOUS", "UNCERTAIN"}
        )
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

    @model_validator(mode="after")
    def dimensions_are_fixed(self) -> QuestionSemanticSignals:
        if self.ambiguity.dimension != "AMBIGUITY":
            raise ValueError("the ambiguity slot requires an AMBIGUITY signal")
        if self.answer_agreement.dimension != "AUTHOR_BLIND_AGREEMENT":
            raise ValueError("the agreement slot requires an AUTHOR_BLIND_AGREEMENT signal")
        return self

    def ordered(self) -> list[SemanticSignal]:
        return [self.ambiguity, self.answer_agreement]


class HardGateResult(Contract):
    gate: HardGateName
    status: Literal["PASS", "FAIL"]
    reason: str = Field(min_length=1, max_length=300)


class QuestionValidationReport(Contract):
    schema_version: Literal["question-validation-report.v1"] = "question-validation-report.v1"
    question_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["VALIDATED", "NEEDS_REVIEW", "REJECTED"]
    hard_gates: list[HardGateResult] = Field(min_length=6, max_length=6)
    semantic_signals: list[SemanticSignal] = Field(min_length=2, max_length=2)

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
    return bool(used) and used.issubset(allowed)


def _conditions_present(candidate: AuthoredQuestionCandidate, blueprint: QuestionBlueprint) -> bool:
    question = _compact(candidate.public_question.question_text)
    return all(_compact(condition) in question for condition in blueprint.conditions)


def _question_shape_matches(
    candidate: AuthoredQuestionCandidate, blueprint: QuestionBlueprint
) -> bool:
    options = candidate.public_question.options
    correct = candidate.private_solution.correct_option_index
    if blueprint.question_type == "MCQ_SINGLE":
        return len(options) >= 2 and correct is not None and 0 <= correct < len(options)
    return not options and correct is None


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


def collect_question_semantic_signals(
    service: SemanticDecisionService | None,
    *,
    candidate: AuthoredQuestionCandidate,
    blueprint: QuestionBlueprint,
    evidence: QuestionEvidencePack,
    blind_receipt: BlindSolveReceipt,
    scope: CacheScope,
) -> QuestionSemanticSignals:
    """Collect two bounded TypeSafe signals; invalid prerequisites spend zero calls."""
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
        )
    assert service is not None  # narrowed above; no-service returned fallback signals

    allowed_rules = [
        {"evidence_id": fragment.evidence_id, "content": fragment.content}
        for fragment in evidence.fragments
    ]
    ambiguity = callsites.review_question_ambiguity(
        service,
        question_text=candidate.public_question.question_text,
        question_type=blueprint.question_type,
        expected_answer_form=blueprint.expected_answer_form,
        blueprint_conditions=blueprint.conditions,
        allowed_rules=allowed_rules,
        scope=scope,
    )
    agreement = callsites.review_question_answer_agreement(
        service,
        question_text=candidate.public_question.question_text,
        author_candidate_answer=candidate.private_solution.model_dump(mode="json"),
        blind_solution=blind_receipt.output,
        blueprint_conditions=blueprint.conditions,
        scope=scope,
    )
    return QuestionSemanticSignals(
        ambiguity=_semantic_signal("AMBIGUITY", ambiguity),
        answer_agreement=_semantic_signal("AUTHOR_BLIND_AGREEMENT", agreement),
    )


def validate_question_candidate(
    *,
    candidate: AuthoredQuestionCandidate,
    blueprint: QuestionBlueprint,
    evidence: QuestionEvidencePack,
    blind_receipt: BlindSolveReceipt,
    semantic_signals: QuestionSemanticSignals,
) -> QuestionValidationReport:
    """Evaluate six independent hard gates and two independently reported semantic dimensions."""
    identity = _input_identity_matches(candidate, blueprint, evidence)
    marks = candidate.marks == blueprint.marks
    sources = _source_scope_matches(candidate, evidence)
    conditions = _conditions_present(candidate, blueprint)
    shape = _question_shape_matches(candidate, blueprint)
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
    semantic_pass = (
        ambiguity.used_jev
        and ambiguity.verdict == "CLEAR"
        and agreement.used_jev
        and agreement.verdict == "AGREE"
    )
    status = "REJECTED" if hard_failure else "VALIDATED" if semantic_pass else "NEEDS_REVIEW"
    return QuestionValidationReport(
        question_revision=candidate.question_revision,
        status=status,
        hard_gates=hard_gates,
        semantic_signals=semantic_signals.ordered(),
    )
