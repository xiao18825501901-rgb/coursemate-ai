"""One real node reaches a READY, private, reusable exercise projection.

This is an offline contract test: the author and blind solver are the labelled
deterministic fixtures and TypeSafe Jev is an injected fake transport.  It
proves orchestration and persistence, not live model quality.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from test_question_persistence import (
    COURSE,
    NODE,
    OWNER,
    PRIVATE_COURSE,
    WORKSPACE,
    database_with_objective,
)

from app.jev.catalog import load_catalog
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.jev.receipt_store import SqlReceiptStore
from app.jev.service import SemanticDecisionService
from app.learning.provider import LearningProvider
from app.learning.question_runtime import QuestionEngineRuntime


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
