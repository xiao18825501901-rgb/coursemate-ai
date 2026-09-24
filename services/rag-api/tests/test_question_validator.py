"""Stage 6 keeps deterministic hard gates separate from TypeSafe Jev signals."""

from __future__ import annotations

from typing import Any

from jev_fixtures import make_jev_database

from app.jev.catalog import load_catalog
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService
from app.learning.blind_solve import BlindSolveReceipt
from app.learning.question_author import (
    RULE_VIOLATION_POLICY_VERSION,
    AuthoredQuestionCandidate,
)
from app.learning.question_blueprint import QuestionBlueprint
from app.learning.question_evidence import EvidenceFragment, QuestionEvidencePack
from app.learning.question_validator import (
    QuestionSemanticSignals,
    SemanticSignal,
    collect_question_semantic_signals,
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
    specialized_dimension: str | None = None,
    specialized_verdict: str | None = None,
) -> QuestionSemanticSignals:
    specialized = (
        SemanticSignal(
            dimension=specialized_dimension,
            verdict=specialized_verdict,
            used_jev=used_jev,
            receipt_id="receipt-specialized" if used_jev else None,
            path="jev" if used_jev else "fallback:shadow",
        )
        if specialized_dimension is not None and specialized_verdict is not None
        else None
    )
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
        specialized_quality=specialized,
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
        misconception_targets=["Assumes every bounded point is a core point."],
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
            "distractor_rationales": [
                {
                    "option_index": 1,
                    "misconception": "Assumes every bounded point is a core point.",
                    "explanation": "The evidence requires the MinPts threshold.",
                    "source_refs": ["chunk-course"],
                }
            ],
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


def test_mcq_distractor_mapping_is_a_validator_hard_gate() -> None:
    mcq_blueprint = blueprint(
        question_type="MCQ_SINGLE",
        expected_answer_form="SINGLE_CHOICE",
        marks=10,
        misconception_targets=["Assumes every bounded point is a core point."],
    )
    private_solution = {
        "candidate_answer": "zero",
        "correct_option_index": 0,
        "distractor_rationales": [
            {
                "option_index": 1,
                "misconception": "Assumes every bounded point is a core point.",
                "explanation": "The evidence requires the MinPts threshold.",
                "source_refs": ["chunk-course"],
            }
        ],
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
    }
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
        private_solution=private_solution,
    )

    accepted = validate(
        candidate=mcq,
        blueprint=mcq_blueprint,
        semantic_signals=signals(
            specialized_dimension="MCQ_DISTRACTOR_QUALITY",
            specialized_verdict="ACCEPTABLE",
        ),
    )
    missing_quality_signal = validate(candidate=mcq, blueprint=mcq_blueprint)
    weak_quality_signal = validate(
        candidate=mcq,
        blueprint=mcq_blueprint,
        semantic_signals=signals(
            specialized_dimension="MCQ_DISTRACTOR_QUALITY",
            specialized_verdict="WEAK",
        ),
    )
    missing_mapping = validate(
        candidate=mcq.model_copy(
            update={
                "private_solution": mcq.private_solution.model_copy(
                    update={"distractor_rationales": []}
                )
            }
        ),
        blueprint=mcq_blueprint,
    )

    assert accepted.status == "VALIDATED"
    assert gate_status(accepted, "QUESTION_SHAPE") == "PASS"
    assert missing_quality_signal.status == "NEEDS_REVIEW"
    assert weak_quality_signal.status == "NEEDS_REVIEW"
    assert missing_mapping.status == "REJECTED"
    assert gate_status(missing_mapping, "QUESTION_SHAPE") == "FAIL"


def test_rule_violation_evidence_binding_is_a_validator_hard_gate() -> None:
    rule_blueprint = blueprint(
        bloom_target="ANALYZE",
        target_difficulty=4,
        difficulty_features=["CONCEPTS", "STEPS"],
        question_type="EXPLANATION",
        expected_answer_form="WORKED_STEPS",
        conditions=[],
        generation_policy_version=RULE_VIOLATION_POLICY_VERSION,
    )
    proposed = "Every point inside an epsilon neighbourhood is a core point."
    rule_candidate = candidate(
        blueprint_hash=rule_blueprint.identity(),
        question_type="EXPLANATION",
        public_question={
            "question_text": (
                f'A learner proposes: "{proposed}" Identify the violated rule and correct it.'
            ),
            "options": [],
            "source_refs": ["chunk-course"],
            "answer_policy": "HIDDEN_UNTIL_REVEAL",
        },
        private_solution={
            "candidate_answer": "The claim omits the MinPts threshold.",
            "correct_option_index": None,
            "rule_violation_analysis": {
                "proposed_statement": proposed,
                "rule_source_ref": "chunk-course",
                "rule_quote": (
                    "A core point has at least MinPts points in its epsilon neighbourhood."
                ),
                "correction": "Check MinPts before classifying the point as core.",
                "explanation": "Distance membership alone is insufficient under the cited rule.",
            },
            "solution_steps": [
                {
                    "ordinal": 1,
                    "operation": "Check the governing rule",
                    "result": "The proposal is invalid",
                    "explanation": "The stated proposal omits the required MinPts condition.",
                    "source_refs": ["chunk-course"],
                }
            ],
            "source_refs": ["chunk-course"],
        },
    )

    accepted = validate(
        candidate=rule_candidate,
        blueprint=rule_blueprint,
        semantic_signals=signals(
            specialized_dimension="RULE_VIOLATION_QUALITY",
            specialized_verdict="SUPPORTED",
        ),
    )
    missing_quality_signal = validate(candidate=rule_candidate, blueprint=rule_blueprint)
    unsupported_quality_signal = validate(
        candidate=rule_candidate,
        blueprint=rule_blueprint,
        semantic_signals=signals(
            specialized_dimension="RULE_VIOLATION_QUALITY",
            specialized_verdict="UNSUPPORTED",
        ),
    )
    missing_analysis = validate(
        candidate=rule_candidate.model_copy(
            update={
                "private_solution": rule_candidate.private_solution.model_copy(
                    update={"rule_violation_analysis": None}
                )
            }
        ),
        blueprint=rule_blueprint,
    )
    rule_analysis = rule_candidate.private_solution.rule_violation_analysis
    assert rule_analysis is not None
    fabricated_quote = validate(
        candidate=rule_candidate.model_copy(
            update={
                "private_solution": rule_candidate.private_solution.model_copy(
                    update={
                        "rule_violation_analysis": rule_analysis.model_copy(
                            update={"rule_quote": "A fabricated course rule."}
                        )
                    }
                )
            }
        ),
        blueprint=rule_blueprint,
    )

    assert accepted.status == "VALIDATED"
    assert gate_status(accepted, "QUESTION_SHAPE") == "PASS"
    assert missing_quality_signal.status == "NEEDS_REVIEW"
    assert unsupported_quality_signal.status == "NEEDS_REVIEW"
    assert missing_analysis.status == "REJECTED"
    assert gate_status(missing_analysis, "QUESTION_SHAPE") == "FAIL"
    assert fabricated_quote.status == "REJECTED"
    assert gate_status(fabricated_quote, "QUESTION_SHAPE") == "FAIL"


def jev_service(tmp_path: Any, *, mode: str = "on") -> tuple[SemanticDecisionService, Any]:
    database = make_jev_database(tmp_path)

    def responder(call: Any) -> JevResult:
        key = next(iter(call.questions))
        verdict = "CLEAR" if key == "question.ambiguity.v1" else "AGREE"
        return JevResult(answers={key: JevAnswer(choice=verdict)})

    transport = FakeTransport(responder)
    gateway = JevGateway(
        transport=transport,
        catalog=load_catalog(),
        modes={
            "question.ambiguity.v1": mode,
            "question.answer_agreement.v1": mode,
        },
        receipt_store=SqlReceiptStore(database),
    )
    return SemanticDecisionService(gateway), transport


def test_typesafe_jev_signals_are_receipted_separate_and_feed_the_validator(tmp_path: Any) -> None:
    service, transport = jev_service(tmp_path)
    scope = service.scope(
        owner_user_id="user-a",
        authorization_scope="question_validation",
        course_id="cs3481",
        node_id="node-dbscan",
        spec_version=2,
        question_hash=REVISION,
    )

    semantic = collect_question_semantic_signals(
        service,
        candidate=candidate(),
        blueprint=blueprint(),
        evidence=evidence_pack(),
        blind_receipt=blind_receipt(),
        scope=scope,
    )
    report = validate(semantic_signals=semantic)

    assert report.status == "VALIDATED"
    assert semantic.ambiguity.verdict == "CLEAR"
    assert semantic.answer_agreement.verdict == "AGREE"
    assert semantic.ambiguity.receipt_id != semantic.answer_agreement.receipt_id
    assert len(transport.calls) == 2
    ambiguity_state, agreement_state = (call.state for call in transport.calls)
    assert set(ambiguity_state) == {
        "question_text",
        "question_type",
        "expected_answer_form",
        "blueprint_conditions",
        "allowed_rules",
    }
    assert "author_candidate_answer" not in ambiguity_state
    assert set(agreement_state) == {
        "question_text",
        "author_candidate_answer",
        "blind_solution",
        "blueprint_conditions",
    }
    assert all(
        "marks" not in state and "grade" not in state
        for state in (ambiguity_state, agreement_state)
    )


def test_shadow_or_absent_typesafe_signals_stay_uncertain_and_never_ready(tmp_path: Any) -> None:
    service, _ = jev_service(tmp_path, mode="shadow")
    scope = service.scope(
        owner_user_id="user-a",
        authorization_scope="question_validation",
        course_id="cs3481",
        node_id="node-dbscan",
        spec_version=2,
        question_hash=REVISION,
    )
    shadow = collect_question_semantic_signals(
        service,
        candidate=candidate(),
        blueprint=blueprint(),
        evidence=evidence_pack(),
        blind_receipt=blind_receipt(),
        scope=scope,
    )
    absent = collect_question_semantic_signals(
        None,
        candidate=candidate(),
        blueprint=blueprint(),
        evidence=evidence_pack(),
        blind_receipt=blind_receipt(),
        scope=scope,
    )

    assert {item.verdict for item in shadow.ordered()} == {"UNCERTAIN"}
    assert {item.verdict for item in absent.ordered()} == {"UNCERTAIN"}
    assert validate(semantic_signals=shadow).status == "NEEDS_REVIEW"
    assert validate(semantic_signals=absent).status == "NEEDS_REVIEW"


def test_unreceipted_jev_answer_is_not_allowed_to_validate_a_candidate() -> None:
    def responder(call: Any) -> JevResult:
        key = next(iter(call.questions))
        verdict = "CLEAR" if key == "question.ambiguity.v1" else "AGREE"
        return JevResult(answers={key: JevAnswer(choice=verdict)})

    service = SemanticDecisionService(
        JevGateway(
            transport=FakeTransport(responder),
            catalog=load_catalog(),
            modes={
                "question.ambiguity.v1": "on",
                "question.answer_agreement.v1": "on",
            },
            receipt_store=None,
        )
    )
    scope = service.scope(
        owner_user_id="user-a",
        authorization_scope="question_validation",
        course_id="cs3481",
        question_hash=REVISION,
    )

    semantic = collect_question_semantic_signals(
        service,
        candidate=candidate(),
        blueprint=blueprint(),
        evidence=evidence_pack(),
        blind_receipt=blind_receipt(),
        scope=scope,
    )

    assert all(signal.used_jev is False for signal in semantic.ordered())
    assert {signal.path for signal in semantic.ordered()} == {"fallback:unreceipted"}
    assert validate(semantic_signals=semantic).status == "NEEDS_REVIEW"
