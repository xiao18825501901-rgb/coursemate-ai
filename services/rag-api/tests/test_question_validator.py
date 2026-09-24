"""Stage 6 keeps deterministic hard gates separate from TypeSafe Jev signals."""

from __future__ import annotations

from typing import Any

from app.learning.blind_solve import BlindSolveReceipt
from app.learning.question_author import AuthoredQuestionCandidate
from app.learning.question_blueprint import QuestionBlueprint
from app.learning.question_evidence import EvidenceFragment, QuestionEvidencePack
from app.learning.question_validator import (
    QuestionSemanticSignals,
    SemanticSignal,
    validate_question_candidate,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
REVISION = "e" * 64


def evidence_pack() -> QuestionEvidencePack:
    return QuestionEvidencePack(
        course_id="cs3481",
        node_id="node-dbscan",
        spec_version=2,
        spec_content_hash=HASH_A,
        objective_id="objective-density",
        objective_text="计算 epsilon 邻域并区分核心点、边界点与噪声点",
        acceptance="所有点的分类与步骤均可由课程定义核验",
        evidence_ids=["chunk-course"],
        fragments=[
            EvidenceFragment(
                evidence_id="chunk-course",
                document_id="doc-course",
                document_version_id="doc-course-v3",
                document_version=3,
                document_sha256=HASH_B,
                filename="lecture.md",
                source_scope="OFFICIAL",
                ordinal=1,
                locator_type="page",
                locator_value="7",
                section="DBSCAN",
                content="A core point has at least MinPts points in its epsilon neighbourhood.",
                truncated=False,
                source_content_sha256=HASH_C,
                excerpt_sha256=HASH_C,
            )
        ],
    )


def blueprint(**overrides: Any) -> QuestionBlueprint:
    values: dict[str, Any] = {
        "blueprint_id": "blueprint-density-1",
        "course_id": "cs3481",
        "node_id": "node-dbscan",
        "spec_version": 2,
        "spec_content_hash": HASH_A,
        "objective_id": "objective-density",
        "objective_text": "计算 epsilon 邻域并区分核心点、边界点与噪声点",
        "source_scope": evidence_pack().source_scope(),
        "bloom_target": "APPLY",
        "target_difficulty": 3,
        "difficulty_features": ["STEPS", "COMPUTATION"],
        "question_type": "NUMERIC",
        "expected_answer_form": "NUMERIC_VALUE",
        "marks": 15,
        "scoring_criteria": ["邻域计数正确", "点类型判断正确"],
        "conditions": ["epsilon = 1.5", "MinPts = 3"],
        "question_family_id": "family-density",
        "prompt_versions": {"question_author": "question-author.v1"},
        "generation_policy_version": "question-generation-policy-v1",
    }
    values.update(overrides)
    return QuestionBlueprint(**values)


def candidate(**overrides: Any) -> AuthoredQuestionCandidate:
    bp = blueprint()
    evidence = evidence_pack()
    values: dict[str, Any] = {
        "blueprint_id": bp.blueprint_id,
        "blueprint_hash": bp.identity(),
        "evidence_pack_hash": evidence.identity(),
        "question_revision": REVISION,
        "course_id": bp.course_id,
        "node_id": bp.node_id,
        "objective_id": bp.objective_id,
        "question_type": bp.question_type,
        "marks": bp.marks,
        "public_question": {
            "question_text": (
                "For epsilon=1.5 and MinPts=3, count each point's neighbourhood and state "
                "how many core points remain."
            ),
            "options": [],
            "source_refs": ["chunk-course"],
            "answer_policy": "HIDDEN_UNTIL_REVEAL",
        },
        "private_solution": {
            "candidate_answer": "There are no core points.",
            "correct_option_index": None,
            "solution_steps": [
                {
                    "ordinal": 1,
                    "operation": "Count the neighbourhoods",
                    "result": "No count reaches three",
                    "explanation": "Each bounded neighbourhood has fewer than three points.",
                    "source_refs": ["chunk-course"],
                }
            ],
            "source_refs": ["chunk-course"],
        },
        "provider_run": {
            "model": "deepseek-flash",
            "provider": "DEEPSEEK_API",
            "protocol": "responses",
            "region": "ENDPOINT_DEEPSEEK",
            "role": "QUESTION_AUTHOR",
            "template_version": "question-author.v1",
            "schema_version": "question-author-output.v1",
            "input_hash": "d" * 64,
            "started_at": "2026-09-25T00:00:00Z",
            "finished_at": "2026-09-25T00:00:01Z",
            "latency_ms": 1000,
            "input_tokens": 500,
            "output_tokens": 250,
            "provider_response_id": "response-1",
            "status": "COMPLETED",
            "error_class": None,
        },
    }
    values.update(overrides)
    return AuthoredQuestionCandidate(**values)


def blind_receipt(**overrides: str) -> BlindSolveReceipt:
    values = {
        "input_hash": "f" * 64,
        "question_revision": REVISION,
        "model_version": "deepseek-flash",
        "output": "Independent result: no point reaches MinPts=3.",
        "status": "completed",
    }
    values.update(overrides)
    return BlindSolveReceipt(**values)


def signals(
    *,
    ambiguity: str = "CLEAR",
    agreement: str = "AGREE",
    used_jev: bool = True,
) -> QuestionSemanticSignals:
    return QuestionSemanticSignals(
        ambiguity=SemanticSignal(
            dimension="AMBIGUITY",
            verdict=ambiguity,
            used_jev=used_jev,
            receipt_id="receipt-ambiguity" if used_jev else None,
            path="jev" if used_jev else "fallback:shadow",
        ),
        answer_agreement=SemanticSignal(
            dimension="AUTHOR_BLIND_AGREEMENT",
            verdict=agreement,
            used_jev=used_jev,
            receipt_id="receipt-agreement" if used_jev else None,
            path="jev" if used_jev else "fallback:shadow",
        ),
    )


def validate(**overrides: Any):
    values = {
        "candidate": candidate(),
        "blueprint": blueprint(),
        "evidence": evidence_pack(),
        "blind_receipt": blind_receipt(),
        "semantic_signals": signals(),
    }
    values.update(overrides)
    return validate_question_candidate(**values)


def gate_status(report: Any, gate: str) -> str:
    return next(check.status for check in report.hard_gates if check.gate == gate)


def test_all_hard_gates_and_two_real_semantic_signals_make_candidate_validated() -> None:
    report = validate()

    assert report.status == "VALIDATED"
    assert report.ready_eligible is True
    assert all(check.status == "PASS" for check in report.hard_gates)
    assert [signal.dimension for signal in report.semantic_signals] == [
        "AMBIGUITY",
        "AUTHOR_BLIND_AGREEMENT",
    ]
    assert not hasattr(report, "quality_score")
    assert "quality_score" not in report.model_dump()


def test_missing_blueprint_condition_is_a_hard_rejection_even_if_jev_is_positive() -> None:
    altered = candidate()
    altered.public_question.question_text = "Count the points and state the number of core points."

    report = validate(candidate=altered)

    assert report.status == "REJECTED"
    assert report.ready_eligible is False
    assert gate_status(report, "CONDITIONS_PRESENT") == "FAIL"


def test_marks_or_source_identity_mismatch_is_a_hard_rejection() -> None:
    wrong_marks = validate(candidate=candidate(marks=20))
    wrong_source = validate(candidate=candidate(evidence_pack_hash="9" * 64))

    assert wrong_marks.status == "REJECTED"
    assert gate_status(wrong_marks, "MARKS_MATCH") == "FAIL"
    assert wrong_source.status == "REJECTED"
    assert gate_status(wrong_source, "INPUT_IDENTITY") == "FAIL"


def test_stale_or_failed_blind_solve_can_never_validate_current_revision() -> None:
    stale = validate(blind_receipt=blind_receipt(question_revision="1" * 64))
    failed = validate(blind_receipt=blind_receipt(status="failed"))

    assert stale.status == failed.status == "REJECTED"
    assert all(
        gate_status(report, "BLIND_SOLVE_CURRENT") == "FAIL"
        for report in (stale, failed)
    )


def test_ambiguity_or_author_blind_disagreement_requires_review_not_a_fake_score() -> None:
    ambiguous = validate(semantic_signals=signals(ambiguity="AMBIGUOUS"))
    disagreement = validate(semantic_signals=signals(agreement="DISAGREE"))

    assert ambiguous.status == disagreement.status == "NEEDS_REVIEW"
    assert ambiguous.ready_eligible is disagreement.ready_eligible is False
    assert {signal.verdict for signal in disagreement.semantic_signals} == {
        "CLEAR",
        "DISAGREE",
    }


def test_shadow_or_missing_jev_receipts_never_upgrade_a_candidate_to_validated() -> None:
    report = validate(semantic_signals=signals(used_jev=False))

    assert report.status == "NEEDS_REVIEW"
    assert report.ready_eligible is False
    assert all(signal.used_jev is False for signal in report.semantic_signals)


def test_mcq_single_correct_is_rechecked_as_a_hard_gate() -> None:
    mcq_blueprint = blueprint(
        question_type="MCQ_SINGLE",
        expected_answer_form="SINGLE_CHOICE",
        marks=10,
    )
    mcq = candidate(
        blueprint_hash=mcq_blueprint.identity(),
        question_type="MCQ_SINGLE",
        marks=10,
        public_question={
            "question_text": (
                "For epsilon=1.5 and MinPts=3, which option gives the number of core points?"
            ),
            "options": ["zero", "one"],
            "source_refs": ["chunk-course"],
            "answer_policy": "HIDDEN_UNTIL_REVEAL",
        },
        private_solution={
            "candidate_answer": "zero",
            "correct_option_index": 4,
            "solution_steps": [
                {
                    "ordinal": 1,
                    "operation": "Count neighbourhoods",
                    "result": "zero",
                    "explanation": "No bounded neighbourhood reaches the required three points.",
                    "source_refs": ["chunk-course"],
                }
            ],
            "source_refs": ["chunk-course"],
        },
    )

    report = validate(candidate=mcq, blueprint=mcq_blueprint)

    assert report.status == "REJECTED"
    assert gate_status(report, "QUESTION_SHAPE") == "FAIL"
