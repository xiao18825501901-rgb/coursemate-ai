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
from test_question_persistence import (  # noqa: E402 - shared fixture builder
    COURSE,
    NODE,
    OWNER,
    PRIVATE_COURSE,
    SPEC_HASH,
    WORKSPACE,
    database_with_objective,
)

from app.learning.blind_solve import run_blind_solve
from app.learning.deepseek_reviewer import DeepSeekStrongReviewer
from app.learning.hybrid_quality import (
    QUALIFICATION_TTL_DAYS,
    HybridQualificationStore,
    HybridQualityService,
    review_domain,
    review_language,
)
from app.learning.hybrid_review import (
    ALL_REVIEW_ROLES,
    CASE_AGREEMENT,
    CASE_AMBIGUITY,
    POLICY_REVISION,
    SPECIFICATION_AUDIT_ROLE,
    STRONG_REVIEW_ROLES,
)
from app.learning.provider import LearningProvider
from app.learning.question_author import (  # noqa: E402
    QUESTION_AUTHOR_PROMPT_VERSION,
    author_question,
)
from app.learning.question_blueprint import QuestionBlueprint, resolve_objective
from app.learning.question_evidence import EvidencePackAccess, build_evidence_pack
from app.learning.question_persistence import persist_question_candidate
from app.learning.question_validator import (
    collect_question_semantic_signals,
    validate_question_candidate,
)
from app.learning.sql_oracle import OracleCheck, check_equivalence, check_expected_rows

REQUIRED = (CASE_AMBIGUITY, CASE_AGREEMENT)


class StubJudgeProvider:
    """A deterministic stand-in for the DeepSeek reviewer transport."""

    def __init__(
        self, *, verdict: str = "PASS", fabricate: bool = False, block_specification: bool = False
    ) -> None:
        self.verdict = verdict
        self.fabricate = fabricate
        self.block_specification = block_specification
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
        run = {
            "model": "FAKE_TEST_ONLY",
            "provider": "deterministic",
            "protocol": "fixture",
            "region": "LOCAL_TEST",
            "role": role,
            "template_version": template_version,
            "schema_version": schema_version or "coursejesus-judge-findings.v3",
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
        if role == SPECIFICATION_AUDIT_ROLE:
            entry: dict[str, Any] = {
                "datum": "the two integers the task asks about",
                "stated_in_stem": True,
            }
            if self.block_specification:
                entry = {
                    "datum": "the value the answer is computed from",
                    "stated_in_stem": False,
                    "answer_changes_if_absent": True,
                    "consequence": "the stub states that a different value results",
                }
            return schema.model_validate({"dependencies": [entry]}), run

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
                    # A real refusal has to say what is wrong with the item; an
                    # unsubstantiated FAIL is downgraded to UNCERTAIN by the
                    # substantiation pass, so the stub supplies one.
                    "counterexample": (
                        "the stub found a concrete counterexample for " + case
                        if self.verdict == "FAIL"
                        else None
                    ),
                    "missing_conditions": [],
                    # An ambiguity PASS must be backed by an enumeration, so the
                    # stub lists the datum it checked and marks it stated.
                    "dependencies": (
                        [
                            {
                                "datum": "the two integers the task asks about",
                                "stated_in_stem": True,
                            }
                        ]
                        if case == CASE_AMBIGUITY
                        else []
                    ),
                }
            )
        return schema.model_validate({"findings": findings}), run


def _pipeline(tmp_path: Path, *, with_contract: bool = True) -> dict[str, Any]:
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
        prompt_versions={"question_author": QUESTION_AUTHOR_PROMPT_VERSION},
        generation_policy_version="question-generation-policy-v1",
    )
    provider = LearningProvider(config)
    candidate = author_question(provider, blueprint=blueprint, evidence=evidence)
    if not with_contract:
        # An item whose author produced no student-visible contract has no positive
        # completeness evidence, which is the state the human-card path exists for.
        candidate = candidate.model_copy(update={"task_contract": None})
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
    context: dict[str, Any],
    *,
    verdict: str = "PASS",
    fabricate: bool = False,
    block_specification: bool = False,
) -> tuple[HybridQualityService, StubJudgeProvider]:
    provider = StubJudgeProvider(
        verdict=verdict, fabricate=fabricate, block_specification=block_specification
    )
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


def _persist(context: dict[str, Any], result, *, oracle_checks=()) -> Any:
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
            oracle_checks=oracle_checks,
        ),
        semantic_decisions=None,
    )


def test_a_human_card_unblocks_the_case_the_reviewers_cannot_decide(
    tmp_path: Path,
) -> None:
    """The whole point of the card, measured end to end.

    The automatic specification pass raises an unstated-dependency doubt, and the
    item has no completeness certificate, so it is not publishable however the
    other reviewers vote.  A person's card on that exact revision decides the case,
    and the revision becomes READY -- with the card id recorded on the receipt and
    the other three cases still decided by the reviewers.

    The item is built without a contract deliberately: with a certificate that
    covers the profile required conventions, the doubt is answered by evidence
    rather than by a person, and the card is not the deciding instrument.
    """
    from datetime import UTC, datetime

    from app.learning.human_review_card import HumanReviewCard, HumanReviewStore

    context = _pipeline(tmp_path, with_contract=False)
    service, _ = _service(context, block_specification=True)
    _qualify(context, service)

    blocked = _review(context, service)
    assert blocked is not None
    assert blocked.accepted is False
    assert blocked.human_card_id is None
    assert "HYBRID_UNSTATED_DEPENDENCY:question.ambiguity.v1" in blocked.reasons

    card = HumanReviewCard(
        question_revision_hash=context["candidate"].question_revision,
        decision="PASS",
        dependencies=[
            {
                "datum": "the values the task gives in its own stem",
                "stated_in_stem": True,
            }
        ],
        reviewer_user_id="user-owner",
        reviewed_at=datetime.now(UTC).isoformat(),
        note="read the stem against the checklist",
    )
    card_id = HumanReviewStore(context["database"]).record(card, owner_user_id=OWNER)

    approved = _review(context, service)
    assert approved is not None and approved.accepted is True, approved.reasons
    assert approved.human_card_id == card_id
    persisted = _persist(context, approved)
    assert persisted.status == "READY"
    with context["database"].connect() as connection:
        row = connection.execute(
            "SELECT human_card_id,case_outcomes_json FROM hybrid_quality_receipts "
            "WHERE id=?",
            (approved.receipt_id,),
        ).fetchone()
    assert str(row["human_card_id"]) == card_id
    assert json.loads(str(row["case_outcomes_json"]))["question.ambiguity.v1"] == "PASS"


def test_a_card_arriving_after_a_negative_persist_needs_a_new_revision(
    tmp_path: Path,
) -> None:
    """Provenance is append-only, so a card cannot rewrite an existing verdict.

    Once a revision has been persisted as ``NEEDS_REVIEW`` the persistence layer
    is idempotent for that revision hash, which is exactly what keeps audit
    history honest.  A card that arrives afterwards therefore has to be applied
    to a later immutable revision of the same slot -- which the assessment-slot
    recovery path already does -- rather than silently rewriting the first one.
    """
    from datetime import UTC, datetime

    from app.learning.human_review_card import HumanReviewCard, HumanReviewStore

    context = _pipeline(tmp_path, with_contract=False)
    service, _ = _service(context, block_specification=True)
    _qualify(context, service)

    blocked = _review(context, service)
    assert blocked is not None and blocked.accepted is False
    assert _persist(context, blocked).status == "NEEDS_REVIEW"

    HumanReviewStore(context["database"]).record(
        HumanReviewCard(
            question_revision_hash=context["candidate"].question_revision,
            decision="PASS",
            dependencies=[
                {"datum": "the values the task gives", "stated_in_stem": True}
            ],
            reviewer_user_id="user-owner",
            reviewed_at=datetime.now(UTC).isoformat(),
        ),
        owner_user_id=OWNER,
    )
    approved = _review(context, service)
    assert approved is not None and approved.accepted is True
    # Same revision hash: the first verdict stands, and the audit row count is
    # unchanged rather than overwritten.
    again = _persist(context, approved)
    assert again.status == "NEEDS_REVIEW"
    assert again.idempotent is True


def test_a_card_does_not_override_a_deterministic_or_oracle_failure(
    tmp_path: Path,
) -> None:
    """The card decides one semantic case; it is not a general bypass."""
    from datetime import UTC, datetime

    from app.learning.human_review_card import HumanReviewCard, HumanReviewStore

    context = _pipeline(tmp_path)
    service, _ = _service(context)
    _qualify(context, service)
    HumanReviewStore(context["database"]).record(
        HumanReviewCard(
            question_revision_hash=context["candidate"].question_revision,
            decision="PASS",
            dependencies=[
                {"datum": "the values the task gives", "stated_in_stem": True}
            ],
            reviewer_user_id="user-owner",
            reviewed_at=datetime.now(UTC).isoformat(),
        ),
        owner_user_id=OWNER,
    )
    result = _review(context, service)
    assert result is not None and result.accepted

    rejected = context["report"].model_copy(update={"status": "REJECTED"})
    assert (
        service.review(
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
        is None
    )
def test_an_executable_oracle_failure_rejects_the_candidate(tmp_path: Path) -> None:
    """A deterministic failure is produced by running the answer, not by asking.

    Both reviewers passed, the qualification covers the scope, and the candidate
    is still refused: a wrong query result is not a matter of opinion.
    """
    context = _pipeline(tmp_path)
    service, _ = _service(context)
    _qualify(context, service)
    result = _review(context, service)
    assert result is not None and result.accepted

    oracle_failure = check_equivalence(
        reference="SELECT id FROM t ORDER BY id",
        candidate="SELECT id FROM t WHERE 1 = 1 ORDER BY id DESC",
        schema="CREATE TABLE t(id INTEGER);",
        data="INSERT INTO t VALUES (1),(2);",
        comparison="ORDERED",
    )
    assert oracle_failure.status == "FAIL"

    persisted = _persist(context, result, oracle_checks=[oracle_failure])
    assert persisted.status == "REJECTED"
    assert persisted.verification_method == "MODEL_ONLY"
    with context["database"].connect() as connection:
        status = connection.execute(
            "SELECT publication_status FROM question_engine_provenance "
            "WHERE question_revision_id=?",
            (persisted.question_revision_id,),
        ).fetchone()
    assert str(status["publication_status"]) == "REJECTED"


def test_a_not_supported_oracle_does_not_pass_and_does_not_block(tmp_path: Path) -> None:
    """No applicable executable check is not the same as a passing one.

    It must not turn into approval, and it must not turn into refusal either: the
    semantic chain still has to carry the item, and it did.
    """
    context = _pipeline(tmp_path)
    service, _ = _service(context)
    _qualify(context, service)
    result = _review(context, service)
    assert result is not None and result.accepted

    unsupported = OracleCheck(
        check="sql_result_equivalence",
        status="NOT_SUPPORTED",
        method="ROW_COMPARISON",
        comparison=None,
        detail="the statement could not be executed on the supplied schema and rows",
    )
    persisted = _persist(context, result, oracle_checks=[unsupported])
    assert persisted.status == "READY"

    passing = check_expected_rows(
        candidate="SELECT id FROM t ORDER BY id",
        schema="CREATE TABLE t(id INTEGER);",
        data="INSERT INTO t VALUES (1),(2);",
        expected_rows=[[1], [2]],
        comparison="ORDERED",
    )
    assert passing.status == "PASS"
    assert _persist(context, result, oracle_checks=[passing]).status == "READY"


def test_three_isolated_calls_are_made_and_none_sees_another(tmp_path: Path) -> None:
    context = _pipeline(tmp_path)
    service, provider = _service(context)
    _qualify(context, service)
    result = _review(context, service)
    assert result is not None
    roles = [call["role"] for call in provider.calls]
    # Two case-deciding roles plus the dedicated specification pass.
    assert sorted(roles) == sorted(ALL_REVIEW_ROLES)
    first, second = provider.calls[0], provider.calls[1]
    assert first["context"]["anonymized_solutions"][0]["content"] == (
        second["context"]["anonymized_solutions"][1]["content"]
    )
    assert "findings" not in json.dumps(first["context"])
    assert "openjev" not in json.dumps(first["context"]).lower()
    specification = provider.calls[2]["context"]
    assert "anonymized_solutions" in specification
    assert specification["review_role"] == SPECIFICATION_AUDIT_ROLE


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
        assert {str(call["role"]) for call in calls} == set(ALL_REVIEW_ROLES)
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
            "SELECT role,references_verified FROM hybrid_review_calls "
            "WHERE question_revision_hash=?",
            (context["candidate"].question_revision,),
        ).fetchall()
    # The two case-deciding calls carry the fabricated references; the
    # specification pass cites nothing, so it has no reference to verify.
    deciding = [
        row for row in verified if str(row["role"]) in set(STRONG_REVIEW_ROLES)
    ]
    assert deciding and all(int(row["references_verified"]) == 0 for row in deciding)
    persisted = _persist(context, result)
    assert persisted.status == "NEEDS_REVIEW"


def test_a_fail_verdict_from_reviewers_cannot_publish(tmp_path: Path) -> None:
    """Every case the roles refuse fails; none of them can be voted up.

    The ambiguity case is now decided by evidence rather than by the roles' own
    verdicts, so a bare FAIL there is answered by the certificate.  The cases with
    a concrete defect -- agreement and the module-specific one -- keep the
    conjunctive rule exactly as it was, and the item still cannot publish.
    """
    context = _pipeline(tmp_path)
    service, _ = _service(context, verdict="FAIL")
    _qualify(context, service)
    result = _review(context, service)
    assert result is not None
    assert result.accepted is False
    assert result.case_outcomes["question.answer_agreement.v1"] == "FAIL"
    assert result.case_outcomes[CASE_AMBIGUITY] == "PASS"
    assert any("HYBRID_CASE_FAIL:" in reason for reason in result.reasons)
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

    with context["database"].connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE hybrid_quality_receipts SET status='QUALITY_ACCEPTED' WHERE id=?",
            (result.receipt_id,),
        )
