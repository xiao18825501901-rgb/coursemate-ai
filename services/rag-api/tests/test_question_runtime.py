"""One real node reaches a READY, private, reusable exercise projection.

This is an offline contract test: the author and blind solver are the labelled
deterministic fixtures and TypeSafe Jev is an injected fake transport.  It
proves orchestration and persistence, not live model quality.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_question_persistence import (
    COURSE,
    NODE,
    OWNER,
    PRIVATE_COURSE,
    WORKSPACE,
    database_with_objective,
)

from app.errors import ApiError
from app.jev.catalog import load_catalog
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService
from app.learning.provider import LearningProvider, ProviderCallFailure
from app.learning.question_author import RULE_VIOLATION_POLICY_VERSION
from app.learning.question_runtime import (
    QuestionEngineRuntime,
    QuestionEngineRuntimeError,
)


def decisions(
    database: Any, *, prototype_id: str = "worked_application"
) -> SemanticDecisionService:
    def responder(call: Any) -> JevResult:
        key = next(iter(call.questions))
        verdict = {
            "exercise.prototype.v1": prototype_id,
            "question.ambiguity.v1": "CLEAR",
            "question.answer_agreement.v1": "AGREE",
            "question.mcq_distractor_quality.v1": "ACCEPTABLE",
            "question.rule_violation_quality.v1": "SUPPORTED",
        }[key]
        return JevResult(answers={key: JevAnswer(choice=verdict)})

    return SemanticDecisionService(
        JevGateway(
            transport=FakeTransport(responder),
            catalog=load_catalog(),
            modes={
                "exercise.prototype.v1": "on",
                "question.ambiguity.v1": "on",
                "question.answer_agreement.v1": "on",
                "question.mcq_distractor_quality.v1": "on",
                "question.rule_violation_quality.v1": "on",
            },
            receipt_store=SqlReceiptStore(database),
        )
    )


def test_runtime_generates_ready_private_exercise_for_exact_workspace_node(
    tmp_path: Path,
) -> None:
    database, config = database_with_objective(tmp_path)
    runtime = QuestionEngineRuntime(
        database=database,
        provider=LearningProvider(config),
        semantic_decisions=decisions(database),
    )

    result = runtime.generate_one(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        operation_id="do-one-question-0001",
    )

    assert result["status"] == "READY"
    assert result["verification_status"] == "AI_REVIEWED"
    assert result["generation_version"] == "exercise.v2+question-engine.v1"
    assert result["prototype_id"] == "worked_application"
    assert result["public"]["schema_version"] == "exercise.v2"
    assert "answer" not in result["public"]
    assert "solution" not in result["public"]
    assert result["private"]["answer"]
    assert result["private"]["steps"][0]["step_id"] == "step_1"
    assert result["private"]["steps"][0]["title"]
    assert result["private"]["steps"][0]["text"]
    assert result["references"][0]["id"] == "chunk-course"
    assert "content" not in result["references"][0]

    with database.connect() as connection:
        provenance = connection.execute(
            "SELECT * FROM question_engine_provenance WHERE question_revision_id=?",
            (result["question_revision_id"],),
        ).fetchone()
        question = connection.execute(
            "SELECT owner_user_id FROM assessment_question_revisions WHERE id=?",
            (result["question_revision_id"],),
        ).fetchone()
    assert provenance["workspace_id"] == WORKSPACE
    assert provenance["publication_status"] == "READY"
    assert question["owner_user_id"] == OWNER


def test_generate_one_routes_author_and_blind_solver_through_metered_operation(
    tmp_path: Path,
) -> None:
    database, config = database_with_objective(tmp_path)
    provider = LearningProvider(config)
    calls: list[tuple[str, str, str]] = []

    def metered_generate(
        workspace_id: str,
        operation_id: str,
        schema: type[Any],
        **kwargs: Any,
    ) -> tuple[Any, dict[str, Any]]:
        calls.append((workspace_id, operation_id, str(kwargs["role"])))
        return provider.generate(schema, **kwargs)

    semantic_decisions = decisions(database)
    semantic_decisions.gateway.modes["exercise.prototype.v1"] = "off"
    runtime = QuestionEngineRuntime(
        database=database,
        provider=provider,
        semantic_decisions=semantic_decisions,
        metered_generate=metered_generate,
    )

    runtime.generate_one(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        operation_id="metered-do-one-question-0001",
    )

    assert calls == [
        (WORKSPACE, "metered-do-one-question-0001", "QUESTION_AUTHOR"),
        (WORKSPACE, "metered-do-one-question-0001", "QUESTION_BLIND_SOLVER"),
    ]
    with database.connect() as connection:
        operation = connection.execute(
            "SELECT kind,status,result_json FROM learning_operations "
            "WHERE workspace_id=? AND id=?",
            (WORKSPACE, "metered-do-one-question-0001"),
        ).fetchone()
    assert operation["kind"] == "QUESTION_GENERATION"
    assert operation["status"] == "COMPLETED"
    assert json.loads(operation["result_json"])["status"] == "READY"

    with pytest.raises(QuestionEngineRuntimeError) as replayed:
        runtime.generate_one(
            owner_user_id=OWNER,
            workspace_id=WORKSPACE,
            course_id=COURSE,
            private_course_id=PRIVATE_COURSE,
            node_id=NODE,
            operation_id="metered-do-one-question-0001",
        )
    assert replayed.value.code == "QUESTION_OPERATION_REPLAY"
    assert len(calls) == 2


def test_invalid_blueprint_fails_static_preflight_before_parent_or_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, config = database_with_objective(tmp_path)
    provider = LearningProvider(config)
    calls: list[str] = []

    def metered_generate(*_args: Any, **kwargs: Any) -> tuple[Any, dict[str, Any]]:
        calls.append(str(kwargs["role"]))
        return provider.generate(_args[2], **kwargs)

    runtime = QuestionEngineRuntime(
        database=database,
        provider=provider,
        semantic_decisions=decisions(database),
        metered_generate=metered_generate,
    )
    original_blueprint = runtime._blueprint

    def invalid_blueprint(**kwargs: Any) -> Any:
        kwargs["objective"] = replace(
            kwargs["objective"], objective="Density clustering"
        )
        return original_blueprint(**kwargs)

    monkeypatch.setattr(runtime, "_blueprint", invalid_blueprint)

    with pytest.raises(QuestionEngineRuntimeError) as refused:
        runtime.generate_one(
            owner_user_id=OWNER,
            workspace_id=WORKSPACE,
            course_id=COURSE,
            private_course_id=PRIVATE_COURSE,
            node_id=NODE,
            operation_id="invalid-blueprint-operation",
        )

    assert refused.value.code == "QUESTION_BLUEPRINT_INVALID"
    assert calls == []
    with database.connect() as connection:
        operation = connection.execute(
            "SELECT status FROM learning_operations WHERE workspace_id=? AND id=?",
            (WORKSPACE, "invalid-blueprint-operation"),
        ).fetchone()
        reservations = connection.execute(
            "SELECT COUNT(*) FROM learning_model_call_reservations "
            "WHERE workspace_id=? AND operation_id=?",
            (WORKSPACE, "invalid-blueprint-operation"),
        ).fetchone()[0]
    assert operation is None
    assert reservations == 0


def test_static_preflight_builds_the_real_blueprint_without_claiming_or_calling(
    tmp_path: Path,
) -> None:
    database, config = database_with_objective(tmp_path)
    semantic_decisions = decisions(database)
    transport = semantic_decisions.gateway.transport
    runtime = QuestionEngineRuntime(
        database=database,
        provider=LearningProvider(config),
        semantic_decisions=semantic_decisions,
        metered_generate=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("static preflight attempted a model call")
        ),
    )

    result = runtime.preflight_generate_one(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        operation_id="static-preflight-question-0001",
    )

    assert result["status"] == "STATIC_PREFLIGHT_PASSED"
    assert result["blueprint"]["schema_version"] == "question-blueprint.v1"
    assert result["blueprint"]["objective_id"] == "objective-density"
    assert result["blueprint_hash"]
    assert result["evidence_pack_hash"]
    assert getattr(transport, "calls", []) == []
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM learning_operations WHERE id=?",
            ("static-preflight-question-0001",),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM learning_model_call_reservations WHERE operation_id=?",
            ("static-preflight-question-0001",),
        ).fetchone()[0] == 0


def test_invalid_objective_is_refused_before_operation_claim_and_jev(
    tmp_path: Path,
) -> None:
    database, config = database_with_objective(tmp_path)
    invalid_node = "node-invalid-objective"
    invalid_item = {
        "item_id": "objective-invalid",
        "requirement": "REQUIRED",
        "objective": "Density clustering",
        "acceptance": "Describe the supplied rule accurately",
        "evidence_ids": ["chunk-course"],
    }
    invalid_spec = json.dumps([invalid_item], ensure_ascii=False)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO knowledge_nodes(id,course_id,owner_user_id,title,description,major,kind,status) "
            "VALUES(?,?,?,'Invalid objective','Synthetic','CS','ATOMIC','PRIVATE')",
            (invalid_node, COURSE, OWNER),
        )
        connection.execute(
            "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) VALUES(?,1,?,?)",
            (invalid_node, invalid_spec, __import__("hashlib").sha256(invalid_spec.encode()).hexdigest()),
        )
    semantic_decisions = decisions(database)
    transport = semantic_decisions.gateway.transport
    runtime = QuestionEngineRuntime(
        database=database,
        provider=LearningProvider(config),
        semantic_decisions=semantic_decisions,
        metered_generate=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid local input attempted a model call")
        ),
    )

    with pytest.raises(QuestionEngineRuntimeError) as refusal:
        runtime.generate_one(
            owner_user_id=OWNER,
            workspace_id=WORKSPACE,
            course_id=COURSE,
            private_course_id=PRIVATE_COURSE,
            node_id=invalid_node,
            operation_id="invalid-objective-preflight-0001",
        )

    assert refusal.value.code == "QUESTION_BLUEPRINT_INVALID"
    assert getattr(transport, "calls", []) == []
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM learning_operations WHERE id=?",
            ("invalid-objective-preflight-0001",),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM learning_model_call_reservations WHERE operation_id=?",
            ("invalid-objective-preflight-0001",),
        ).fetchone()[0] == 0


def test_runtime_rule_violation_prototype_persists_an_exact_course_rule(
    tmp_path: Path,
) -> None:
    database, config = database_with_objective(tmp_path)
    runtime = QuestionEngineRuntime(
        database=database,
        provider=LearningProvider(config),
        semantic_decisions=decisions(database, prototype_id="rule_violation_analysis"),
    )

    result = runtime.generate_one(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        operation_id="rule-violation-question-0001",
    )

    assert result["status"] == "READY"
    assert result["prototype_id"] == "rule_violation_analysis"
    assert "violated rule" in result["public"]["question_text"]
    assert "rule_violation_analysis" not in result["public"]
    with database.connect() as connection:
        row = connection.execute(
            "SELECT provenance.blueprint_json,provenance.validation_report_json,"
            "question.answer_json "
            "FROM question_engine_provenance AS provenance "
            "JOIN assessment_question_revisions AS question "
            "ON question.id=provenance.question_revision_id "
            "WHERE provenance.question_revision_id=?",
            (result["question_revision_id"],),
        ).fetchone()
    blueprint = json.loads(row["blueprint_json"])
    validation_report = json.loads(row["validation_report_json"])
    answer = json.loads(row["answer_json"])
    analysis = answer["rule_violation_analysis"]
    assert blueprint["generation_policy_version"] == RULE_VIOLATION_POLICY_VERSION
    assert analysis["rule_source_ref"] == "chunk-course"
    assert analysis["rule_quote"] == (
        "A core point has at least MinPts points in its epsilon neighbourhood."
    )
    assert analysis["proposed_statement"] in result["public"]["question_text"]
    assert [signal["dimension"] for signal in validation_report["semantic_signals"]] == [
        "AMBIGUITY",
        "AUTHOR_BLIND_AGREEMENT",
        "RULE_VIOLATION_QUALITY",
    ]
    assert validation_report["semantic_signals"][2]["verdict"] == "SUPPORTED"


def test_rule_quality_shadow_signal_cannot_publish_a_question(tmp_path: Path) -> None:
    database, config = database_with_objective(tmp_path)
    semantic_decisions = decisions(database, prototype_id="rule_violation_analysis")
    semantic_decisions.gateway.modes["question.rule_violation_quality.v1"] = "shadow"
    runtime = QuestionEngineRuntime(
        database=database,
        provider=LearningProvider(config),
        semantic_decisions=semantic_decisions,
    )

    with pytest.raises(QuestionEngineRuntimeError) as raised:
        runtime.generate_one(
            owner_user_id=OWNER,
            workspace_id=WORKSPACE,
            course_id=COURSE,
            private_course_id=PRIVATE_COURSE,
            node_id=NODE,
            operation_id="rule-violation-shadow-quality",
        )

    assert raised.value.code == "QUESTION_NOT_READY"
    with database.connect() as connection:
        status = connection.execute(
            "SELECT publication_status FROM question_engine_provenance"
        ).fetchone()["publication_status"]
    assert status == "NEEDS_REVIEW"


def test_runtime_repractice_uses_a_new_family_without_changing_the_objective(
    tmp_path: Path,
) -> None:
    database, config = database_with_objective(tmp_path)
    runtime = QuestionEngineRuntime(
        database=database,
        provider=LearningProvider(config),
        semantic_decisions=decisions(database),
    )

    first = runtime.generate_one(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        operation_id="do-one-question-variant-a",
    )
    second = runtime.generate_one(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        operation_id="do-one-question-variant-b",
    )

    assert first["question_revision_id"] != second["question_revision_id"]
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT question.family_id,provenance.objective_id "
            "FROM assessment_question_revisions AS question "
            "JOIN question_engine_provenance AS provenance "
            "ON provenance.question_revision_id=question.id ORDER BY question.rowid"
        ).fetchall()
    assert len({row["family_id"] for row in rows}) == 2
    assert {row["objective_id"] for row in rows} == {"objective-density"}


def test_practice_hint_and_attempt_are_owner_scoped_idempotent_and_not_grades(
    tmp_path: Path,
) -> None:
    database, config = database_with_objective(tmp_path)
    provider = LearningProvider(config)
    runtime = QuestionEngineRuntime(
        database=database,
        provider=provider,
        semantic_decisions=decisions(database),
    )
    generated = runtime.generate_one(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        operation_id="practice-interaction-question",
    )
    question_id = generated["question_revision_id"]

    calls: list[str] = []
    metered_calls: list[tuple[str, str, str]] = []
    original_generate = provider.generate

    def counted_generate(schema: Any, **kwargs: Any) -> Any:
        calls.append(schema.__name__)
        return original_generate(schema, **kwargs)

    provider.generate = counted_generate  # type: ignore[method-assign]

    def metered_generate(
        workspace_id: str,
        operation_id: str,
        schema: Any,
        **kwargs: Any,
    ) -> Any:
        metered_calls.append((workspace_id, operation_id, kwargs["role"]))
        return provider.generate(schema, **kwargs)

    runtime.metered_generate = metered_generate
    hint = runtime.generate_hint(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        question_revision_id=question_id,
        operation_id="practice-hint-operation",
    )
    replayed_hint = runtime.generate_hint(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        question_revision_id=question_id,
        operation_id="practice-hint-operation",
    )
    attempt = runtime.grade_practice_attempt(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        question_revision_id=question_id,
        operation_id="practice-attempt-operation",
        submitted_answer="A learner-specific synthetic answer.",
        answer_revealed=False,
    )
    replayed_attempt = runtime.grade_practice_attempt(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        question_revision_id=question_id,
        operation_id="practice-attempt-operation",
        submitted_answer="A learner-specific synthetic answer.",
        answer_revealed=False,
    )

    assert hint == replayed_hint
    assert attempt == replayed_attempt
    assert calls == ["PracticeHintOutput", "PracticeFeedbackOutput"]
    assert metered_calls == [
        (WORKSPACE, "practice-hint-operation", "PRACTICE_HINT"),
        (WORKSPACE, "practice-attempt-operation", "PRACTICE_FEEDBACK"),
    ]
    assert hint["assistance"] == "HINT"
    assert "Synthetic candidate answer" not in hint["hint"]
    assert attempt["assistance"] == "HINT"
    assert attempt["verdict"] in {"CORRECT", "PARTIAL", "INCORRECT", "NEEDS_REVIEW"}
    assert attempt["feedback"]

    with database.connect() as connection:
        stored_hint = connection.execute(
            "SELECT * FROM practice_hint_events WHERE operation_id=?",
            ("practice-hint-operation",),
        ).fetchone()
        stored_attempt = connection.execute(
            "SELECT * FROM practice_question_attempts WHERE operation_id=?",
            ("practice-attempt-operation",),
        ).fetchone()
        grade_count = connection.execute("SELECT COUNT(*) FROM grade_snapshots").fetchone()[0]
        evidence_count = connection.execute(
            "SELECT COUNT(*) FROM performance_evidence"
        ).fetchone()[0]
        coverage_count = connection.execute(
            "SELECT COUNT(*) FROM learning_coverage"
        ).fetchone()[0]
        guards = connection.execute(
            "SELECT operation_id,guard_version FROM practice_operation_metering_guards "
            "ORDER BY operation_id"
        ).fetchall()
    assert stored_hint["owner_user_id"] == OWNER
    assert stored_attempt["owner_user_id"] == OWNER
    assert stored_attempt["assistance"] == "HINT"
    assert [tuple(row) for row in guards] == [
        ("practice-attempt-operation", "metered-practice.v1"),
        ("practice-hint-operation", "metered-practice.v1"),
    ]
    assert grade_count == evidence_count == coverage_count == 0


def test_practice_attempt_after_reveal_is_never_independent(tmp_path: Path) -> None:
    database, config = database_with_objective(tmp_path)
    runtime = QuestionEngineRuntime(
        database=database,
        provider=LearningProvider(config),
        semantic_decisions=decisions(database),
    )
    generated = runtime.generate_one(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        operation_id="revealed-practice-question",
    )

    result = runtime.grade_practice_attempt(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        question_revision_id=generated["question_revision_id"],
        operation_id="revealed-practice-attempt",
        submitted_answer="Answer written after the reference solution was shown.",
        answer_revealed=True,
    )

    assert result["assistance"] == "ANSWER_REVEALED"
    assert result["independent"] is False


def test_failed_practice_operation_is_not_billed_again_on_replay(tmp_path: Path) -> None:
    database, config = database_with_objective(tmp_path)
    provider = LearningProvider(config)
    runtime = QuestionEngineRuntime(
        database=database,
        provider=provider,
        semantic_decisions=decisions(database),
    )
    generated = runtime.generate_one(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        operation_id="failed-practice-question",
    )
    calls = 0

    def blocked_generate(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise ProviderCallFailure(
            ApiError(503, "MODEL_LIVE_BLOCKED", "synthetic blocked provider"), {}
        )

    provider.generate = blocked_generate  # type: ignore[method-assign]
    for _ in range(2):
        with pytest.raises(QuestionEngineRuntimeError) as raised:
            runtime.generate_hint(
                owner_user_id=OWNER,
                workspace_id=WORKSPACE,
                question_revision_id=generated["question_revision_id"],
                operation_id="blocked-practice-hint",
            )
        assert raised.value.code == "PRACTICE_HINT_PROVIDER_BLOCKED"
    assert calls == 1


def test_metered_practice_refusal_is_terminal_and_not_retried(tmp_path: Path) -> None:
    database, config = database_with_objective(tmp_path)
    runtime = QuestionEngineRuntime(
        database=database,
        provider=LearningProvider(config),
        semantic_decisions=decisions(database),
    )
    generated = runtime.generate_one(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        operation_id="metered-refusal-question",
    )
    calls = 0

    def refused_generate(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise ApiError(429, "DAILY_MODEL_CALL_QUOTA", "synthetic quota refusal")

    runtime.metered_generate = refused_generate
    for _ in range(2):
        with pytest.raises(QuestionEngineRuntimeError) as raised:
            runtime.generate_hint(
                owner_user_id=OWNER,
                workspace_id=WORKSPACE,
                question_revision_id=generated["question_revision_id"],
                operation_id="metered-refusal-hint",
            )
        assert raised.value.code == "PRACTICE_HINT_PROVIDER_BLOCKED"
    assert calls == 1


def test_hint_strategy_cannot_leak_the_hidden_reference_answer(tmp_path: Path) -> None:
    database, config = database_with_objective(tmp_path)
    provider = LearningProvider(config)
    runtime = QuestionEngineRuntime(
        database=database,
        provider=provider,
        semantic_decisions=decisions(database),
    )
    generated = runtime.generate_one(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        operation_id="hint-leak-practice-question",
    )
    original_generate = provider.generate

    def leaking_strategy(schema: Any, **kwargs: Any) -> Any:
        output, run = original_generate(schema, **kwargs)
        if schema.__name__ == "PracticeHintOutput":
            output = output.model_copy(
                update={"strategy": "[FAKE TEST FIXTURE] Synthetic candidate answer."}
            )
        return output, run

    provider.generate = leaking_strategy  # type: ignore[method-assign]
    with pytest.raises(QuestionEngineRuntimeError) as raised:
        runtime.generate_hint(
            owner_user_id=OWNER,
            workspace_id=WORKSPACE,
            question_revision_id=generated["question_revision_id"],
            operation_id="hint-strategy-leak-operation",
        )
    assert raised.value.code == "PRACTICE_HINT_ANSWER_LEAK"


def test_hint_event_must_match_its_claimed_hint_operation(tmp_path: Path) -> None:
    database, config = database_with_objective(tmp_path)
    runtime = QuestionEngineRuntime(
        database=database,
        provider=LearningProvider(config),
        semantic_decisions=decisions(database),
    )
    generated = runtime.generate_one(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        operation_id="hint-operation-correlation-question",
    )
    question_id = generated["question_revision_id"]
    input_hash = "a" * 64

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO practice_interaction_operations(
                workspace_id,operation_id,question_revision_id,owner_user_id,
                kind,input_hash,status
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                WORKSPACE,
                "mismatched-attempt-operation",
                question_id,
                OWNER,
                "ATTEMPT",
                input_hash,
                "CLAIMED",
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="Practice hint does not match"):
            connection.execute(
                """
                INSERT INTO practice_hint_events(
                    id,workspace_id,question_revision_id,owner_user_id,
                    operation_id,input_hash,hint_json,provider_run_json
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    "invalid-hint-event",
                    WORKSPACE,
                    question_id,
                    OWNER,
                    "mismatched-attempt-operation",
                    input_hash,
                    "{}",
                    "{}",
                ),
            )
