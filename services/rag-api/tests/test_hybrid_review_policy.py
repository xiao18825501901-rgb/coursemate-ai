"""Hybrid-strict-v1 policy and gate contracts.

These tests pin the *policy*, not a model: no provider is called, no network is
used and no credential is read.  They assert the properties a weaker gate would
silently lose:

* the required case set comes from the server-side question contract;
* both reviewer roles must be present and distinct;
* one concrete ``FAIL`` is never outvoted by the other role's ``PASS``;
* a fabricated source span, a paraphrased "quote" or an unknown step id makes a
  review unverifiable, and an unverifiable review cannot publish;
* the anonymised solution order is frozen from the revision hash before any
  answer is observed, and is reversed (not re-chosen) for the second role;
* the local advisory observation has no field that grants or vetoes a decision.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.learning.deepseek_reviewer import (
    ADVERSARIAL_AUDIT_ROLE,
    EVIDENCE_AUDIT_ROLE,
    LocalObservation,
    ReviewerInputs,
    reviewer_context,
)
from app.learning.hybrid_quality import HybridQualification
from app.learning.hybrid_review import (
    CASE_AGREEMENT,
    CASE_AMBIGUITY,
    CASE_DISTRACTORS,
    CASE_RULE,
    STRONG_REVIEW_ROLES,
    JudgeDependency,
    JudgeFinding,
    JudgeFindings,
    JudgeSourceRef,
    balanced_solution_order,
    case_set_for_blueprint,
    combine_case_verdicts,
    method_identity,
    project_case_verdicts,
    substantiated_case_verdicts,
    verify_references,
)


def _finding(case: str, verdict: str, **overrides) -> JudgeFinding:
    payload = {
        "case": case,
        "verdict": verdict,
        "assertion": f"checked {case}",
        "evidence_refs": [],
        "solution_step_ids": [],
        "counterexample": None,
        "missing_conditions": [],
    }
    payload.update(overrides)
    return JudgeFinding(**payload)


def _inputs(**overrides) -> ReviewerInputs:
    payload = {
        "question_revision": "a" * 64,
        "blueprint_hash": "b" * 64,
        "evidence_pack_hash": "c" * 64,
        "course_id": "course-1",
        "node_id": "node-1",
        "spec_version": 1,
        "objective_id": "obj-1",
        "language": "en",
        "domain": "OFFICIAL",
        "required_cases": (CASE_AMBIGUITY, CASE_AGREEMENT),
        "question_text": "Compute 2 + 3 and give the result as a base-ten integer.",
        "question_type": "NUMERIC",
        "options": (),
        "solution_a": {
            "candidate_answer": {"value": 5},
            "solution_steps": [{"ordinal": 1}, {"ordinal": 2}],
        },
        "solution_b": {"steps": [{"ordinal": 1}]},
        "rubric": ("full marks for the exact integer",),
        "evidence": (
            {"evidence_id": "ev-1", "content": "Addition of two integers yields their sum."},
        ),
        "deterministic": {"INPUT_IDENTITY": "PASS", "MARKS_MATCH": "PASS"},
    }
    payload.update(overrides)
    return ReviewerInputs(**payload)


# --------------------------------------------------------------- case mapping


def test_required_cases_come_from_the_question_contract_not_the_model() -> None:
    assert case_set_for_blueprint(question_type="NUMERIC", rule_policy=False) == (
        CASE_AMBIGUITY,
        CASE_AGREEMENT,
    )
    assert case_set_for_blueprint(question_type="MCQ_SINGLE", rule_policy=False) == (
        CASE_AMBIGUITY,
        CASE_AGREEMENT,
        CASE_DISTRACTORS,
    )
    assert case_set_for_blueprint(question_type="EXPLANATION", rule_policy=True) == (
        CASE_AMBIGUITY,
        CASE_AGREEMENT,
        CASE_RULE,
    )
    assert case_set_for_blueprint(question_type="MCQ_SINGLE", rule_policy=True) == (
        CASE_AMBIGUITY,
        CASE_AGREEMENT,
        CASE_DISTRACTORS,
        CASE_RULE,
    )


def test_projection_keeps_the_original_four_quality_vocabulary() -> None:
    projected = project_case_verdicts(
        {
            CASE_AMBIGUITY: "PASS",
            CASE_AGREEMENT: "PASS",
            CASE_DISTRACTORS: "FAIL",
            CASE_RULE: "UNCERTAIN",
        }
    )
    assert projected == {
        "AMBIGUITY": "CLEAR",
        "AUTHOR_BLIND_AGREEMENT": "AGREE",
        "MCQ_DISTRACTOR_QUALITY": "WEAK",
        "RULE_VIOLATION_QUALITY": "UNCERTAIN",
    }


# ------------------------------------------------------------- combination


def test_both_roles_must_pass_for_a_case_to_pass() -> None:
    combined, reasons = combine_case_verdicts(
        required_cases=(CASE_AMBIGUITY, CASE_AGREEMENT),
        by_role={
            EVIDENCE_AUDIT_ROLE: {CASE_AMBIGUITY: "PASS", CASE_AGREEMENT: "PASS"},
            ADVERSARIAL_AUDIT_ROLE: {CASE_AMBIGUITY: "PASS", CASE_AGREEMENT: "PASS"},
        },
    )
    assert combined == {CASE_AMBIGUITY: "PASS", CASE_AGREEMENT: "PASS"}
    assert reasons == []


def test_one_concrete_failure_is_not_outvoted_by_the_other_role() -> None:
    combined, reasons = combine_case_verdicts(
        required_cases=(CASE_AMBIGUITY, CASE_AGREEMENT),
        by_role={
            EVIDENCE_AUDIT_ROLE: {CASE_AMBIGUITY: "FAIL", CASE_AGREEMENT: "PASS"},
            ADVERSARIAL_AUDIT_ROLE: {CASE_AMBIGUITY: "PASS", CASE_AGREEMENT: "PASS"},
        },
    )
    assert combined[CASE_AMBIGUITY] == "FAIL"
    assert combined[CASE_AGREEMENT] == "PASS"
    assert "HYBRID_CASE_FAIL:" + CASE_AMBIGUITY in reasons


def test_uncertain_never_becomes_pass() -> None:
    combined, reasons = combine_case_verdicts(
        required_cases=(CASE_AMBIGUITY,),
        by_role={
            EVIDENCE_AUDIT_ROLE: {CASE_AMBIGUITY: "PASS"},
            ADVERSARIAL_AUDIT_ROLE: {CASE_AMBIGUITY: "UNCERTAIN"},
        },
    )
    assert combined[CASE_AMBIGUITY] == "UNCERTAIN"
    assert any(reason.startswith("HYBRID_CASE_UNCERTAIN") for reason in reasons)


def test_a_missing_role_is_a_refusal() -> None:
    combined, reasons = combine_case_verdicts(
        required_cases=(CASE_AMBIGUITY,),
        by_role={EVIDENCE_AUDIT_ROLE: {CASE_AMBIGUITY: "PASS"}},
    )
    assert combined[CASE_AMBIGUITY] == "UNCERTAIN"
    assert "HYBRID_REQUIRES_TWO_DISTINCT_ROLES" in reasons


def test_an_extra_case_a_reviewer_invented_is_recorded_as_a_refusal() -> None:
    _, reasons = combine_case_verdicts(
        required_cases=(CASE_AMBIGUITY,),
        by_role={
            EVIDENCE_AUDIT_ROLE: {CASE_AMBIGUITY: "PASS", CASE_DISTRACTORS: "PASS"},
            ADVERSARIAL_AUDIT_ROLE: {CASE_AMBIGUITY: "PASS"},
        },
    )
    assert "HYBRID_CASE_NOT_REQUIRED:" + CASE_DISTRACTORS in reasons


# ------------------------------------------------------- reference verification


def test_fabricated_span_and_paraphrased_quote_are_not_verifiable() -> None:
    findings = JudgeFindings(
        findings=[
            _finding(
                CASE_AMBIGUITY,
                "PASS",
                evidence_refs=[
                    JudgeSourceRef(source_span_id="ev-404", quote="anything"),
                    JudgeSourceRef(
                        source_span_id="ev-1",
                        quote="two integers multiply to give their product",
                    ),
                ],
                solution_step_ids=["step_9"],
            ),
            _finding(CASE_AGREEMENT, "PASS"),
        ]
    )
    verification = verify_references(
        findings,
        required_cases=(CASE_AMBIGUITY, CASE_AGREEMENT),
        span_ids={"ev-1"},
        span_text_by_id={"ev-1": "Addition of two integers yields their sum."},
        solution_step_ids={"step_1", "step_2"},
    )
    assert verification.case_set_exact is True
    assert verification.quotes_traceable is False
    assert verification.steps_exist is False
    assert verification.unknown_span_ids == ["ev-404"]
    assert verification.unknown_step_ids == ["step_9"]
    assert verification.complete is False


def test_exact_verbatim_quote_and_real_step_are_verifiable() -> None:
    findings = JudgeFindings(
        findings=[
            _finding(
                CASE_AMBIGUITY,
                "PASS",
                evidence_refs=[
                    JudgeSourceRef(
                        source_span_id="ev-1",
                        quote="Addition of two integers yields their sum.",
                    )
                ],
                solution_step_ids=["step_1"],
            ),
            _finding(CASE_AGREEMENT, "PASS"),
        ]
    )
    verification = verify_references(
        findings,
        required_cases=(CASE_AMBIGUITY, CASE_AGREEMENT),
        span_ids={"ev-1"},
        span_text_by_id={"ev-1": "Addition of two integers yields their sum."},
        solution_step_ids={"step_1", "step_2"},
    )
    assert verification.complete is True


def test_a_reviewer_cannot_omit_a_required_case() -> None:
    # The schema already refuses a one-item answer; the policy layer must also
    # refuse a two-item answer that silently drops a third required case.
    findings = JudgeFindings(
        findings=[_finding(CASE_AMBIGUITY, "PASS"), _finding(CASE_AGREEMENT, "PASS")]
    )
    verification = verify_references(
        findings,
        required_cases=(CASE_AMBIGUITY, CASE_AGREEMENT, CASE_DISTRACTORS),
        span_ids={"ev-1"},
        span_text_by_id={"ev-1": "x"},
        solution_step_ids=set(),
    )
    assert verification.case_set_exact is False
    assert verification.complete is False


def test_an_unsubstantiated_fail_is_not_a_defect_finding() -> None:
    """A bare FAIL is not evidence, and must not be able to block a sound item."""
    findings = JudgeFindings(
        findings=[_finding(CASE_AMBIGUITY, "FAIL"), _finding(CASE_AGREEMENT, "PASS")]
    )
    verdicts, reasons = substantiated_case_verdicts(findings)
    assert verdicts[CASE_AMBIGUITY] == "UNCERTAIN"
    assert verdicts[CASE_AGREEMENT] == "PASS"
    assert "HYBRID_UNSUBSTANTIATED_FAIL:" + CASE_AMBIGUITY in reasons


def test_a_fail_with_a_counterexample_or_a_missing_condition_stands() -> None:
    with_counterexample = JudgeFindings(
        findings=[
            _finding(
                CASE_AMBIGUITY,
                "FAIL",
                counterexample="With the same wording, 3 and 4 both satisfy the rule.",
            ),
            _finding(CASE_AGREEMENT, "PASS"),
        ]
    )
    verdicts, _ = substantiated_case_verdicts(with_counterexample)
    assert verdicts[CASE_AMBIGUITY] == "FAIL"

    with_missing = JudgeFindings(
        findings=[
            _finding(
                CASE_AMBIGUITY,
                "FAIL",
                missing_conditions=["the value of epsilon is never stated"],
            ),
            _finding(CASE_AGREEMENT, "PASS"),
        ]
    )
    verdicts, _ = substantiated_case_verdicts(with_missing)
    assert verdicts[CASE_AMBIGUITY] == "FAIL"


def test_a_pass_that_names_a_missing_condition_contradicts_itself() -> None:
    findings = JudgeFindings(
        findings=[
            _finding(
                CASE_AMBIGUITY,
                "PASS",
                missing_conditions=["the rounding convention is not stated"],
            ),
            _finding(CASE_AGREEMENT, "PASS"),
        ]
    )
    verdicts, reasons = substantiated_case_verdicts(findings)
    assert verdicts[CASE_AMBIGUITY] == "UNCERTAIN"
    assert "HYBRID_SELF_CONTRADICTED_PASS:" + CASE_AMBIGUITY in reasons


def test_substantiation_never_produces_a_pass() -> None:
    for verdict in ("PASS", "FAIL", "UNCERTAIN"):
        findings = JudgeFindings(
            findings=[
                _finding(CASE_AMBIGUITY, verdict),
                _finding(CASE_AGREEMENT, verdict),
            ]
        )
        resolved, _ = substantiated_case_verdicts(findings)
        if verdict != "PASS":
            assert resolved[CASE_AMBIGUITY] != "PASS"


def test_a_missing_dependency_that_changes_the_answer_fails_the_item() -> None:
    """The reviewer's own enumeration is the strongest thing it can report.

    This is the rule that turns "the reviewers never noticed the removed
    requirement" into a refusal: if the reviewer lists a datum whose absence
    changes the answer and marks it unstated, the case is FAIL whatever verdict
    it also wrote.
    """
    findings = JudgeFindings(
        findings=[
            _finding(
                CASE_AMBIGUITY,
                "PASS",
                dependencies=[
                    {
                        "datum": "the value of epsilon",
                        "stated_in_stem": False,
                        "answer_changes_if_absent": True,
                        "consequence": (
                            "a different epsilon counts a different number of "
                            "neighbours, so a different point becomes a core point"
                        ),
                    },
                    {"datum": "whether the point itself counts", "stated_in_stem": True},
                ],
            ),
            _finding(CASE_AGREEMENT, "PASS"),
        ]
    )
    verdicts, reasons = substantiated_case_verdicts(findings)
    assert verdicts[CASE_AMBIGUITY] == "FAIL"
    assert "HYBRID_UNSTATED_DEPENDENCY:" + CASE_AMBIGUITY in reasons


def test_a_missing_convention_that_changes_nothing_is_not_a_defect() -> None:
    """This is the rule that keeps the gate usable.

    The first enumeration version failed an item whenever any entry was
    unstated, and refused more than half of the sound controls because reviewers
    listed conventions a competent reader supplies.  A convention whose absence
    changes no answer must be recorded and ignored.
    """
    findings = JudgeFindings(
        findings=[
            _finding(
                CASE_AMBIGUITY,
                "PASS",
                dependencies=[
                    {
                        "datum": "the output is expressed in base ten",
                        "stated_in_stem": False,
                        "answer_changes_if_absent": False,
                    },
                    {"datum": "the two integers in the stem", "stated_in_stem": True},
                ],
            ),
            _finding(CASE_AGREEMENT, "PASS"),
        ]
    )
    verdicts, reasons = substantiated_case_verdicts(findings)
    assert verdicts[CASE_AMBIGUITY] == "PASS"
    assert reasons == []


def test_an_answer_changing_dependency_requires_a_stated_consequence() -> None:
    with pytest.raises(ValueError):
        JudgeDependency(
            datum="the value of epsilon",
            stated_in_stem=False,
            answer_changes_if_absent=True,
        )
    with pytest.raises(ValueError):
        JudgeDependency(
            datum="the output convention",
            stated_in_stem=True,
            answer_changes_if_absent=False,
            consequence="nothing would change",
        )


def test_a_stated_dependency_never_blocks_even_if_it_would_change_the_answer() -> None:
    findings = JudgeFindings(
        findings=[
            _finding(
                CASE_AMBIGUITY,
                "PASS",
                dependencies=[
                    {
                        "datum": "the value of epsilon",
                        "stated_in_stem": True,
                        "answer_changes_if_absent": True,
                        "consequence": "a different epsilon changes the count",
                    }
                ],
            ),
            _finding(CASE_AGREEMENT, "PASS"),
        ]
    )
    verdicts, _ = substantiated_case_verdicts(findings)
    assert verdicts[CASE_AMBIGUITY] == "PASS"


def test_a_clear_claim_without_an_enumeration_is_only_an_abstention() -> None:
    findings = JudgeFindings(
        findings=[_finding(CASE_AMBIGUITY, "PASS"), _finding(CASE_AGREEMENT, "PASS")]
    )
    verdicts, reasons = substantiated_case_verdicts(findings)
    assert verdicts[CASE_AMBIGUITY] == "UNCERTAIN"
    assert "HYBRID_AMBIGUITY_NOT_ENUMERATED:" + CASE_AMBIGUITY in reasons


def test_a_fully_stated_enumeration_permits_clear() -> None:
    findings = JudgeFindings(
        findings=[
            _finding(
                CASE_AMBIGUITY,
                "PASS",
                dependencies=[
                    {"datum": "the two integers", "stated_in_stem": True},
                    {"datum": "base-ten output convention", "stated_in_stem": True},
                ],
            ),
            _finding(CASE_AGREEMENT, "PASS"),
        ]
    )
    verdicts, reasons = substantiated_case_verdicts(findings)
    assert verdicts[CASE_AMBIGUITY] == "PASS"
    assert reasons == []


def test_the_enumeration_rule_applies_to_other_cases_too_but_never_creates_a_pass() -> None:
    findings = JudgeFindings(
        findings=[
            _finding(
                CASE_AMBIGUITY,
                "PASS",
                dependencies=[{"datum": "the stated values", "stated_in_stem": True}],
            ),
            _finding(
                CASE_AGREEMENT,
                "PASS",
                dependencies=[
                    {
                        "datum": "the shared result",
                        "stated_in_stem": False,
                        "answer_changes_if_absent": True,
                        "consequence": "the two solutions would then disagree",
                    }
                ],
            ),
        ]
    )
    verdicts, _ = substantiated_case_verdicts(findings)
    assert verdicts[CASE_AGREEMENT] == "FAIL"
    assert verdicts[CASE_AMBIGUITY] == "PASS"


def test_a_single_case_set_cannot_be_answered_with_one_finding() -> None:
    with pytest.raises(ValueError):
        JudgeFindings(findings=[_finding(CASE_AMBIGUITY, "PASS")])


def test_duplicate_cases_are_refused_by_the_schema() -> None:
    with pytest.raises(ValueError):
        JudgeFindings(
            findings=[_finding(CASE_AMBIGUITY, "PASS"), _finding(CASE_AMBIGUITY, "FAIL")]
        )


# ------------------------------------------------------------------ blinding


def test_solution_order_is_frozen_before_any_answer_is_observed() -> None:
    first = balanced_solution_order(revision_hash="0f" + "0" * 62)
    second = balanced_solution_order(revision_hash="0e" + "0" * 62)
    assert first != second
    # Reproducible: the same revision always yields the same order.
    assert balanced_solution_order(revision_hash="0f" + "0" * 62) == first


def test_role_b_receives_the_reversed_order_and_no_peer_verdict() -> None:
    inputs = _inputs(question_revision="00" + "a" * 62)
    a = reviewer_context(inputs, role=EVIDENCE_AUDIT_ROLE)
    b = reviewer_context(inputs, role=ADVERSARIAL_AUDIT_ROLE)
    assert [item["label"] for item in a["anonymized_solutions"]] == ["X", "Y"]
    assert [item["label"] for item in b["anonymized_solutions"]] == ["X", "Y"]
    assert a["anonymized_solutions"][0]["content"] == b["anonymized_solutions"][1]["content"]
    assert a["anonymized_solutions"][1]["content"] == b["anonymized_solutions"][0]["content"]
    for context in (a, b):
        serialized = repr(context)
        assert "verdict" not in serialized
        assert "openjev" not in serialized.lower()
        assert "local" not in serialized.lower()


def test_the_two_roles_are_distinct_strong_review_roles() -> None:
    assert set(STRONG_REVIEW_ROLES) == {EVIDENCE_AUDIT_ROLE, ADVERSARIAL_AUDIT_ROLE}


def test_method_identity_changes_with_a_prompt_revision() -> None:
    base = dict(
        model_alias="deepseek-flash",
        provider="DEEPSEEK_API",
        protocol="responses",
        evidence_prompt_version="judge-evidence-audit.v1",
        adversarial_prompt_version="judge-adversarial-audit.v1",
        schema_version="coursejesus-judge-findings.v1",
    )
    identity = method_identity(**base)
    assert len(identity) == 64
    changed = method_identity(**{**base, "evidence_prompt_version": "judge-evidence-audit.v2"})
    assert changed != identity


# -------------------------------------------------------------- qualification


def _qualification(**overrides) -> HybridQualification:
    payload = {
        "id": "hybrid-qual-1",
        "policy_revision": "hybrid-strict-v1",
        "method_identity": "d" * 64,
        "status": "SCOPED_QUALITY_ACCEPTED",
        "reviewer_label": "SCOPED_QUALITY_ACCEPTED",
        "languages": ["en"],
        "domains": ["OFFICIAL"],
        "cases": [CASE_AMBIGUITY, CASE_AGREEMENT],
        "roles": list(STRONG_REVIEW_ROLES),
        "sample_counts": {"independent_negatives": 0},
        "metrics": {},
        "evidence_manifest_digest": "e" * 64,
        "observed_model_facts": {},
        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    payload.update(overrides)
    return HybridQualification(**payload)


def test_qualification_scope_is_enforced_field_by_field() -> None:
    now = datetime.now(UTC)
    qualification = _qualification()

    def covers(**overrides):
        payload = {
            "policy_revision": "hybrid-strict-v1",
            "method_identity": "d" * 64,
            "language": "en",
            "domain": "OFFICIAL",
            "cases": (CASE_AMBIGUITY, CASE_AGREEMENT),
            "now": now,
        }
        payload.update(overrides)
        return qualification.covers(**payload)

    assert covers() == (True, "")
    assert covers(language="zh")[1] == "QUALIFICATION_LANGUAGE_OUT_OF_SCOPE"
    assert covers(domain="WORKSPACE_PRIVATE")[1] == "QUALIFICATION_DOMAIN_OUT_OF_SCOPE"
    assert covers(cases=(CASE_AMBIGUITY, CASE_AGREEMENT, CASE_RULE))[1] == (
        "QUALIFICATION_CASE_OUT_OF_SCOPE"
    )
    assert covers(method_identity="f" * 64)[1] == "QUALIFICATION_METHOD_MISMATCH"
    assert covers(policy_revision="hybrid-strict-v2")[1] == "QUALIFICATION_POLICY_MISMATCH"


def test_an_expired_or_withdrawn_qualification_cannot_publish() -> None:
    now = datetime.now(UTC)
    expired = _qualification(expires_at=(now - timedelta(seconds=1)).isoformat())
    assert expired.covers(
        policy_revision="hybrid-strict-v1",
        method_identity="d" * 64,
        language="en",
        domain="OFFICIAL",
        cases=(CASE_AMBIGUITY,),
        now=now,
    ) == (False, "QUALIFICATION_EXPIRED")
    withdrawn = _qualification(status="WITHDRAWN", reviewer_label="SCOPED_QUALITY_ACCEPTED")
    assert withdrawn.covers(
        policy_revision="hybrid-strict-v1",
        method_identity="d" * 64,
        language="en",
        domain="OFFICIAL",
        cases=(CASE_AMBIGUITY,),
        now=now,
    ) == (False, "QUALIFICATION_NOT_ACCEPTED")


def test_a_draft_qualification_cannot_claim_the_accepted_label() -> None:
    with pytest.raises(ValueError):
        _qualification(status="SCOPED_QUALITY_ACCEPTED", reviewer_label="PROVEN_IDENTICAL_TO_JEV")


# ------------------------------------------------------------ local advisory


def test_a_local_observation_has_no_field_that_grants_a_decision() -> None:
    observation = LocalObservation(case=CASE_AMBIGUITY, status="OBSERVED", verdict="CLEAR")
    receipt = observation.as_receipt()
    assert "accept" not in receipt
    assert "ready" not in receipt
    assert "veto" not in receipt
    assert receipt["qualification"] == "UNQUALIFIED_ADVISORY"
