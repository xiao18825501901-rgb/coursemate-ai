"""End-to-end hybrid-strict-v1 publication contracts.

The reviewer provider here is a local stub: no network, no credential and no
billable call.  What is exercised is the *gate* -- the durable receipt chain,
the qualified/unqualified boundary, and the rule that a deterministic hard-gate
failure is never voted back to READY.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.learning.blind_solve import run_blind_solve
from app.learning.deepseek_reviewer import DeepSeekStrongReviewer
from app.learning.hybrid_quality import (
    HybridQualificationStore,
    HybridQualityService,
    QUALIFICATION_TTL_DAYS,
    review_domain,
    review_language,
)
from app.learning.hybrid_review import (
    CASE_AGREEMENT,
    CASE_AMBIGUITY,
    POLICY_REVISION,
    STRONG_REVIEW_ROLES,
)
from app.learning.provider import LearningProvider
from app.learning.question_author import author_question
from app.learning.question_blueprint import QuestionBlueprint, resolve_objective
from app.learning.question_evidence import EvidencePackAccess, build_evidence_pack
from app.learning.question_persistence import persist_question_candidate
from app.learning.question_validator import (
    collect_question_semantic_signals,
    validate_question_candidate,
)

from test_question_persistence import (  # noqa: E402 - shared fixture builder
    COURSE,
    NODE,
    OWNER,
    PRIVATE_COURSE,
    SPEC_HASH,
    WORKSPACE,
    database_with_objective,
)

REQUIRED = (CASE_AMBIGUITY, CASE_AGREEMENT)


class StubJudgeProvider:
    """A deterministic stand-in for the DeepSeek reviewer transport."""

    def __init__(self, *, verdict: str = "PASS", fabricate: bool = False) -> None:
        self.verdict = verdict
        self.fabricate = fabricate
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        schema: type[Any],
        *,
        instructions: str,
        context: dict[str, Any],
        role: str,
        template_version: str = "unversioned",
        schema_version: str | None = None,
        max_output_tokens: int | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        self.calls.append(
            {
                "role": role,
                "context": context,
                "instructions": instructions,
                "template_version": template_version,
            }
        )
        spans = [item["source_span_id"] for item in context["source_spans"]]
        findings = []
        for case in context["required_cases"]:
            refs = []
            if spans:
                content = context["source_spans"][0]["content"]
                refs = [
                    {
                        "source_span_id": spans[0] if not self.fabricate else "ev-does-not-exist",
                        "quote": (
                            " ".join(content.split())[:120]
                            if not self.fabricate
                            else "a quotation that appears in no supplied span"
                        ),
                    }
                ]
            findings.append(
                {
                    "case": case,
                    "verdict": self.verdict,
                    "assertion": f"stub checked {case}",
                    "evidence_refs": refs,
                    "solution_step_ids": [],
                    "counterexample": None,
                    "missing_conditions": [],
                }
            )
        output = schema.model_validate({"findings": findings})
        run = {
            "model": "FAKE_TEST_ONLY",
            "provider": "deterministic",
            "protocol": "fixture",
            "region": "LOCAL_TEST",
            "role": role,
            "template_version": template_version,
            "schema_version": schema_version or "coursejesus-judge-findings.v1",
            "input_hash": "0" * 63 + str(len(self.calls)),
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "latency_ms": 1,
            "input_tokens": 10,
            "output_tokens": 10,
            "provider_response_id": f"stub-{role}-{len(self.calls)}",
            "status": "COMPLETED",
            "error_class": None,
        }
        return output, run


def _pipeline(tmp_path: Path) -> dict[str, Any]:
    database, config = database_with_objective(tmp_path)
    with database.connect() as connection:
        objective = resolve_objective(connection, node_id=NODE)
    evidence = build_evidence_pack(
        database,
        objective=objective,
        access=EvidencePackAccess(
            owner_user_id=OWNER, course_id=COURSE, private_course_id=PRIVATE_COURSE
        ),
    )
    blueprint = QuestionBlueprint(
        blueprint_id="blueprint-hybrid-1",
        course_id=COURSE,
        node_id=NODE,
        spec_version=1,
        spec_content_hash=SPEC_HASH,
        objective_id=objective.item_id,
        objective_text=objective.objective,
        source_scope=evidence.source_scope(),
        bloom_target="APPLY",
        target_difficulty=3,
        difficulty_features=["STEPS"],
        question_type="NUMERIC",
        expected_answer_form="NUMERIC_VALUE",
        marks=15,
        scoring_criteria=["criterion one", "criterion two"],
        question_family_id="family-hybrid",
        prompt_versions={"question_author": "question-author.v3"},
        generation_policy_version="question-generation-policy-v1",
    )
    provider = LearningProvider(config)
    candidate = author_question(provider, blueprint=blueprint, evidence=evidence)
    blind = run_blind_solve(provider, candidate=candidate, evidence=evidence)
    # The local/TypeSafe chain is deliberately absent: this test proves the
    # hybrid chain alone can carry a publication when it is qualified.
    semantic = collect_question_semantic_signals(
        None,
        candidate=candidate,
        blueprint=blueprint,
        evidence=evidence,
        blind_receipt=blind,
        scope=None,
    )
    report = validate_question_candidate(
        candidate=candidate,
        blueprint=blueprint,
        evidence=evidence,
        blind_receipt=blind,
        semantic_signals=semantic,
    )
    assert report.status == "NEEDS_REVIEW"
    return {
        "database": database,
        "config": config,
        "blueprint": blueprint,
        "evidence": evidence,
        "candidate": candidate,
        "blind": blind,
        "report": report,
        "objective": objective,
    }


def _service(
    context: dict[str, Any], *, verdict: str = "PASS", fabricate: bool = False
) -> tuple[HybridQualityService, StubJudgeProvider]:
    provider = StubJudgeProvider(verdict=verdict, fabricate=fabricate)
    reviewer = DeepSeekStrongReviewer(provider, model_alias="deepseek-flash")
    return HybridQualityService(context["database"], reviewer), provider


def _review(context: dict[str, Any], service: HybridQualityService):
    return service.review(
        candidate=context["candidate"],
        blueprint=context["blueprint"],
        evidence=context["evidence"],
        blind_receipt=context["blind"],
        deterministic_report=context["report"],
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        node_id=NODE,
        spec_version=1,
    )


def _scope_of(context: dict[str, Any]) -> tuple[str, str]:
    """The real detected scope of this fixture, not a hand-written assumption."""
    return (
        review_language(context["blueprint"], context["evidence"]),
        review_domain(context["evidence"]),
    )


def _qualify(
    context: dict[str, Any], service: HybridQualityService, **overrides
) -> str:
    language, domain = _scope_of(context)
    store = HybridQualificationStore(context["database"])
    qualification_id = overrides.pop("qualification_id", "hybrid-qual-accepted")
    payload: dict[str, Any] = {
        "qualification_id": qualification_id,
        "policy_revision": POLICY_REVISION,
        "method_identity": service.method_identity,
        "status": "SCOPED_QUALITY_ACCEPTED",
        "reviewer_label": "SCOPED_QUALITY_ACCEPTED",
        "languages": [language],
        "domains": [domain],
        "cases": [CASE_AMBIGUITY, CASE_AGREEMENT],
        "roles": list(STRONG_REVIEW_ROLES),
        "sample_counts": {"items": 40, "independent_negatives": 0},
        "metrics": {},
        "evidence_manifest_digest": "e" * 64,
        "observed_model_facts": {"served_model_revision": "OBSERVED_UNPINNED"},
        "expires_at": (
            datetime.now(UTC) + timedelta(days=QUALIFICATION_TTL_DAYS)
        ).isoformat(),
    }
    payload.update(overrides)
    store.record(**payload)
    return qualification_id


def _persist(context: dict[str, Any], result) -> Any:
    return persist_question_candidate(
        database=context["database"],
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        blueprint=context["blueprint"],
        evidence=context["evidence"],
        candidate=context["candidate"],
        blind_receipt=context["blind"],
        validation_report=validate_question_candidate(
            candidate=context["candidate"],
            blueprint=context["blueprint"],
            evidence=context["evidence"],
            blind_receipt=context["blind"],
            semantic_signals=result.signals,
        ),
    )


def test_two_isolated_calls_are_made_and_neither_sees_the_other(tmp_path: Path) -> None:
    context = _pipeline(tmp_path)
    service, provider = _service(context)
    _qualify(context, service)
    result = _review(context, service)
    assert result is not None
    roles = [call["role"] for call in provider.calls]
    assert sorted(roles) == sorted(STRONG_REVIEW_ROLES)
    first, second = provider.calls
    assert first["context"]["anonymized_solutions"][0]["content"] == (
        second["context"]["anonymized_solutions"][1]["content"]
    )
    assert "findings" not in json.dumps(first["context"])
    assert "openjev" not in json.dumps(first["context"]).lower()


def test_without_a_qualification_the_hybrid_receipt_cannot_accept(tmp_path: Path) -> None:
    context = _pipeline(tmp_path)
    service, _ = _service(context)
    result = _review(context, service)
    assert result is not None
    assert result.accepted is False
    assert "HYBRID_QUALIFICATION_MISSING" in result.reasons
    persisted = _persist(context, result)
    assert persisted.status == "NEEDS_REVIEW"
    assert persisted.verification_method == "MODEL_ONLY"


def test_an_out_of_scope_qualification_cannot_accept(tmp_path: Path) -> None:
    context = _pipeline(tmp_path)
    service, _ = _service(context)
    _qualify(
        context,
        service,
        qualification_id="hybrid-qual-wrong-scope",
        languages=["zh"],
        domains=["OFFICIAL"],
    )
    result = _review(context, service)
    assert result is not None
    assert result.accepted is False
    assert any(reason.startswith("HYBRID_QUALIFICATION_") for reason in result.reasons)


def test_a_qualified_hybrid_review_publishes_ready(tmp_path: Path) -> None:
    context = _pipeline(tmp_path)
    service, _ = _service(context)
    qualification_id = _qualify(context, service)
    result = _review(context, service)
    assert result is not None and result.accepted is True, result.reasons
    assert result.qualification_id == qualification_id
    persisted = _persist(context, result)
    assert persisted.status == "READY"
    assert persisted.verification_method == "AI_REVIEWED"
    with context["database"].connect() as connection:
        row = connection.execute(
            "SELECT * FROM hybrid_quality_receipts WHERE id=?", (result.receipt_id,)
        ).fetchone()
        assert row is not None
        assert str(row["status"]) == "QUALITY_ACCEPTED"
        assert str(row["policy_revision"]) == POLICY_REVISION
        calls = connection.execute(
            "SELECT role,references_verified,terminal FROM hybrid_review_calls "
            "WHERE question_revision_hash=?",
            (context["candidate"].question_revision,),
        ).fetchall()
        assert {str(call["role"]) for call in calls} == set(STRONG_REVIEW_ROLES)
        assert all(int(call["references_verified"]) == 1 for call in calls)
        status = connection.execute(
            "SELECT publication_status FROM question_engine_provenance "
            "WHERE question_revision_id=?",
            (persisted.question_revision_id,),
        ).fetchone()
        assert str(status["publication_status"]) == "READY"


def test_a_withdrawn_qualification_blocks_publication(tmp_path: Path) -> None:
    context = _pipeline(tmp_path)
    service, _ = _service(context)
    qualification_id = _qualify(context, service)
    result = _review(context, service)
    assert result is not None and result.accepted
    # The scope is withdrawn between the review and the publication transaction.
    with context["database"].connect() as connection:
        connection.execute(
            "UPDATE hybrid_qualifications SET status='WITHDRAWN' WHERE id=?",
            (qualification_id,),
        )
    persisted = _persist(context, result)
    assert persisted.status == "NEEDS_REVIEW"
    assert persisted.readiness_reason == "JEV_RECEIPT_NOT_DURABLE_OR_SCOPED"


def test_an_unverifiable_review_reference_blocks_publication(tmp_path: Path) -> None:
    context = _pipeline(tmp_path)
    service, _ = _service(context, fabricate=True)
    _qualify(context, service)
    result = _review(context, service)
    assert result is not None
    # A fabricated span id and a paraphrased quotation must not survive the
    # server-side reference check, so the receipt is refused at review time.
    assert result.accepted is False
    assert any(
        reason.startswith("HYBRID_REVIEW_REFERENCES_UNVERIFIED") for reason in result.reasons
    )
    with context["database"].connect() as connection:
        verified = connection.execute(
            "SELECT references_verified FROM hybrid_review_calls "
            "WHERE question_revision_hash=?",
            (context["candidate"].question_revision,),
        ).fetchall()
    assert verified and all(int(row["references_verified"]) == 0 for row in verified)
    persisted = _persist(context, result)
    assert persisted.status == "NEEDS_REVIEW"


def test_a_fail_verdict_from_reviewers_cannot_publish(tmp_path: Path) -> None:
    context = _pipeline(tmp_path)
    service, _ = _service(context, verdict="FAIL")
    _qualify(context, service)
    result = _review(context, service)
    assert result is not None
    assert result.accepted is False
    assert all(verdict == "FAIL" for verdict in result.case_outcomes.values())
    persisted = _persist(context, result)
    assert persisted.status == "NEEDS_REVIEW"


def test_a_deterministic_hard_gate_failure_is_never_sent_to_the_reviewers(
    tmp_path: Path,
) -> None:
    context = _pipeline(tmp_path)
    service, provider = _service(context)
    _qualify(context, service)
    rejected = context["report"].model_copy(update={"status": "REJECTED"})
    result = service.review(
        candidate=context["candidate"],
        blueprint=context["blueprint"],
        evidence=context["evidence"],
        blind_receipt=context["blind"],
        deterministic_report=rejected,
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        node_id=NODE,
        spec_version=1,
    )
    assert result is None
    assert provider.calls == []


def test_the_local_observation_is_recorded_but_never_decides(tmp_path: Path) -> None:
    context = _pipeline(tmp_path)
    provider = StubJudgeProvider()
    reviewer = DeepSeekStrongReviewer(provider, model_alias="deepseek-flash")

    class ExplodingObserver:
        def observe(self, inputs):
            raise RuntimeError("local model is down")

    service = HybridQualityService(
        context["database"], reviewer, local_observer=ExplodingObserver()
    )
    _qualify(context, service, qualification_id="hybrid-qual-local-down")
    result = _review(context, service)
    assert result is not None
    # An unavailable local observer neither blocks nor vetoes the strong path.
    assert result.accepted is True, result.reasons
    assert result.local_status in {"PARTIAL", "NOT_APPLICABLE"}
    with context["database"].connect() as connection:
        rows = connection.execute(
            "SELECT status,reason FROM hybrid_local_observations "
            "WHERE question_revision_hash=?",
            (context["candidate"].question_revision,),
        ).fetchall()
    assert rows
    assert {str(row["status"]) for row in rows} == {"UNAVAILABLE"}
    assert {str(row["reason"]) for row in rows} == {"LOCAL_OBSERVER_FAILED"}


def test_hybrid_receipts_are_immutable(tmp_path: Path) -> None:
    context = _pipeline(tmp_path)
    service, _ = _service(context)
    _qualify(context, service)
    result = _review(context, service)
    assert result is not None
    import sqlite3

    with context["database"].connect() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE hybrid_quality_receipts SET status='QUALITY_ACCEPTED' WHERE id=?",
                (result.receipt_id,),
            )
