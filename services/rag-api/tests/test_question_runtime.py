"""One real node reaches a READY, private, reusable exercise projection.

This is an offline contract test: the author and blind solver are the labelled
deterministic fixtures and TypeSafe Jev is an injected fake transport.  It
proves orchestration and persistence, not live model quality.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from app.errors import ApiError
from app.jev.catalog import load_catalog
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService
from app.learning.provider import LearningProvider, ProviderCallFailure
from app.learning.question_runtime import (
    QuestionEngineRuntime,
    QuestionEngineRuntimeError,
)
from test_question_persistence import (
    COURSE,
    NODE,
    OWNER,
    PRIVATE_COURSE,
    WORKSPACE,
    database_with_objective,
)


def decisions(database: Any) -> SemanticDecisionService:
    def responder(call: Any) -> JevResult:
        key = next(iter(call.questions))
        verdict = {
            "exercise.prototype.v1": "worked_application",
            "question.ambiguity.v1": "CLEAR",
            "question.answer_agreement.v1": "AGREE",
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
    original_generate = provider.generate

    def counted_generate(schema: Any, **kwargs: Any) -> Any:
        calls.append(schema.__name__)
        return original_generate(schema, **kwargs)

    provider.generate = counted_generate  # type: ignore[method-assign]
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
    assert stored_hint["owner_user_id"] == OWNER
    assert stored_attempt["owner_user_id"] == OWNER
    assert stored_attempt["assistance"] == "HINT"
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
