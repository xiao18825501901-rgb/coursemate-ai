"""Five complementary assessment slots use the existing Question Engine and AssessmentService."""

from __future__ import annotations

import json
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
from test_question_runtime import decisions

from app.errors import ApiError
from app.learning.assessment_question_slots import default_assessment_question_slots
from app.learning.assessments import AssessmentService
from app.learning.provider import LearningProvider, ProviderCallFailure
from app.learning.question_runtime import (
    QuestionEngineRuntime,
    QuestionEngineRuntimeError,
)


def test_default_question_slots_are_five_complementary_unequal_targets() -> None:
    slots = default_assessment_question_slots()

    assert [slot.ordinal for slot in slots] == [1, 2, 3, 4, 5]
    assert [slot.marks for slot in slots] == [10, 15, 20, 25, 30]
    assert sum(slot.marks for slot in slots) == 100
    assert len({slot.slot_key for slot in slots}) == 5
    assert len({slot.bloom_target for slot in slots}) == 5
    assert len({slot.question_type for slot in slots}) >= 3
    assert all(slot.empirical_difficulty is None for slot in slots)


def test_integrated_runtime_refuses_unmetered_assessment_generation(tmp_path: Any) -> None:
    database, config = database_with_objective(tmp_path)
    called = False

    def metered_generate(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        return LearningProvider(config).generate(*args[2:], **kwargs)

    runtime = QuestionEngineRuntime(
        database=database,
        provider=LearningProvider(config),
        semantic_decisions=decisions(database),
        metered_generate=metered_generate,
    )

    with pytest.raises(QuestionEngineRuntimeError) as raised:
        runtime.generate_assessment_set(
            owner_user_id=OWNER,
            workspace_id=WORKSPACE,
            course_id=COURSE,
            private_course_id=PRIVATE_COURSE,
            node_id=NODE,
            preparation_key="assessment-preparation-without-operation",
        )

    assert raised.value.code == "QUESTION_METERING_REQUIRED"
    assert called is False


def test_five_slots_run_the_question_engine_then_freeze_one_assessment(
    tmp_path: Any,
) -> None:
    database, config = database_with_objective(tmp_path)
    provider = LearningProvider(config)
    runtime = QuestionEngineRuntime(
        database=database,
        provider=provider,
        semantic_decisions=decisions(database),
    )
    calls: list[str] = []
    original_generate = provider.generate

    def counted_generate(schema: Any, **kwargs: Any) -> Any:
        calls.append(schema.__name__)
        return original_generate(schema, **kwargs)

    provider.generate = counted_generate  # type: ignore[method-assign]
    assessments = AssessmentService(database)
    with database.connect() as connection:
        workspace = connection.execute(
            "SELECT * FROM learning_workspaces WHERE id=?", (WORKSPACE,)
        ).fetchone()
        node = assessments._atomic_node(connection, workspace, NODE)
        preparation_key = assessments.ensure_preparation_job(connection, workspace, node)["id"]
        connection.execute(
            "INSERT INTO assessment_question_revisions("
            "id,course_id,owner_user_id,family_id,revision,source_kind,question_type,"
            "difficulty,prompt_text,options_json,answer_json,validation_status,"
            "verification_method,content_hash,created_by_user_id) "
            "VALUES('legacy-official-question',?,NULL,'legacy-official-family',1,'OFFICIAL',"
            "'MCQ_SINGLE',1,'Legacy question','[\"A\",\"B\"]',"
            "'{\"correct_option\":\"A\"}','VALIDATED','OFFICIAL',?, 'admin')",
            (COURSE, "f" * 64),
        )
        connection.execute(
            "INSERT INTO assessment_rubric_criteria("
            "question_revision_id,criterion_id,node_id,spec_version,item_id,dimension,"
            "max_fraction,description,deterministic_rule_json) "
            "VALUES('legacy-official-question','legacy-correct',?,1,'objective-density',"
            "'CONCEPT',100,'Select the official answer.','{}')",
            (NODE,),
        )
    first = runtime.generate_assessment_set(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        preparation_key=preparation_key,
    )
    replay = runtime.generate_assessment_set(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        preparation_key=preparation_key,
    )

    assert first == replay
    assert len(first) == 5
    assert [item["ordinal"] for item in first] == [1, 2, 3, 4, 5]
    assert [item["marks"] for item in first] == [10, 15, 20, 25, 30]
    assert len({item["question_revision_id"] for item in first}) == 5
    assert len({item["family_id"] for item in first}) == 5
    assert calls == ["QuestionAuthorOutput", "BlindSolveOutput"] * 5

    with database.connect() as connection:
        workspace = connection.execute(
            "SELECT * FROM learning_workspaces WHERE id=?", (WORKSPACE,)
        ).fetchone()
        AssessmentService.mark_preparation_job(
            connection, preparation_key, "READY", channel="AI_REVIEWED"
        )
        session = assessments.start(connection, workspace, NODE)
        provenance_count = connection.execute(
            "SELECT COUNT(*) FROM question_engine_provenance WHERE workspace_id=? ",
            (WORKSPACE,),
        ).fetchone()[0]
        mcq_private_answer = json.loads(
            connection.execute(
                "SELECT answer_json FROM assessment_question_revisions WHERE id=?",
                (first[0]["question_revision_id"],),
            ).fetchone()["answer_json"]
        )
        mcq_validation_report = json.loads(
            connection.execute(
                "SELECT validation_report_json FROM question_engine_provenance "
                "WHERE question_revision_id=?",
                (first[0]["question_revision_id"],),
            ).fetchone()["validation_report_json"]
        )

    assert provenance_count == 5
    assert session["status"] == "IN_PROGRESS"
    assert len(session["questions"]) == 5
    assert {question["question_revision_id"] for question in session["questions"]} == {
        item["question_revision_id"] for item in first
    }
    assert all(
        question["question_revision_id"] != "legacy-official-question"
        for question in session["questions"]
    )
    assert [question["marks"] for question in session["questions"]] == [10, 15, 20, 25, 30]
    assert all("answer_key" not in question for question in session["questions"])
    assert all("reference_solution" not in question for question in session["questions"])
    assert mcq_private_answer["distractor_rationales"] == [
        {
            "option_index": 0,
            "misconception": default_assessment_question_slots()[0].misconception_target,
            "explanation": (
                "[FAKE TEST FIXTURE] This distractor represents the exact "
                "server-authorized misconception target."
            ),
            "source_refs": ["chunk-course"],
        }
    ]
    assert [signal["dimension"] for signal in mcq_validation_report["semantic_signals"]] == [
        "AMBIGUITY",
        "AUTHOR_BLIND_AGREEMENT",
        "MCQ_DISTRACTOR_QUALITY",
    ]
    assert mcq_validation_report["semantic_signals"][2]["verdict"] == "ACCEPTABLE"
    assert all(
        "distractor_rationales" not in question for question in session["questions"]
    )


def test_resume_reuses_completed_slots_after_a_bounded_provider_failure(tmp_path: Any) -> None:
    database, config = database_with_objective(tmp_path)
    provider = LearningProvider(config)
    runtime = QuestionEngineRuntime(
        database=database,
        provider=provider,
        semantic_decisions=decisions(database),
    )
    assessments = AssessmentService(database)
    with database.connect() as connection:
        workspace = connection.execute(
            "SELECT * FROM learning_workspaces WHERE id=?", (WORKSPACE,)
        ).fetchone()
        node = assessments._atomic_node(connection, workspace, NODE)
        preparation_key = assessments.ensure_preparation_job(connection, workspace, node)["id"]

    calls: list[str] = []
    original_generate = provider.generate
    fail_once = True

    def interrupted_generate(schema: Any, **kwargs: Any) -> Any:
        nonlocal fail_once
        calls.append(schema.__name__)
        author_calls = calls.count("QuestionAuthorOutput")
        if schema.__name__ == "QuestionAuthorOutput" and author_calls == 3 and fail_once:
            fail_once = False
            raise ProviderCallFailure(
                ApiError(503, "MODEL_LIVE_BLOCKED", "Synthetic pre-call block"), {}
            )
        return original_generate(schema, **kwargs)

    provider.generate = interrupted_generate  # type: ignore[method-assign]
    with pytest.raises(QuestionEngineRuntimeError) as raised:
        runtime.generate_assessment_set(
            owner_user_id=OWNER,
            workspace_id=WORKSPACE,
            course_id=COURSE,
            private_course_id=PRIVATE_COURSE,
            node_id=NODE,
            preparation_key=preparation_key,
        )
    assert raised.value.code == "AUTHOR_PROVIDER_BLOCKED"
    with database.connect() as connection:
        before = connection.execute(
            "SELECT ordinal,question_revision_id FROM assessment_preparation_questions "
            "WHERE preparation_job_id=? ORDER BY ordinal",
            (preparation_key,),
        ).fetchall()
    assert [row["ordinal"] for row in before] == [1, 2]

    completed = runtime.generate_assessment_set(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        preparation_key=preparation_key,
    )

    assert len(completed) == 5
    assert calls.count("QuestionAuthorOutput") == 6  # five successes plus one blocked pre-call
    assert calls.count("BlindSolveOutput") == 5
    assert [item["question_revision_id"] for item in completed[:2]] == [
        row["question_revision_id"] for row in before
    ]


@pytest.mark.parametrize(
    "dimension",
    ["AMBIGUITY", "MCQ_DISTRACTOR_QUALITY"],
)
def test_resume_refuses_a_saved_slot_after_its_semantic_receipt_is_removed(
    tmp_path: Any,
    dimension: str,
) -> None:
    database, config = database_with_objective(tmp_path)
    runtime = QuestionEngineRuntime(
        database=database,
        provider=LearningProvider(config),
        semantic_decisions=decisions(database),
    )
    assessments = AssessmentService(database)
    with database.connect() as connection:
        workspace = connection.execute(
            "SELECT * FROM learning_workspaces WHERE id=?", (WORKSPACE,)
        ).fetchone()
        node = assessments._atomic_node(connection, workspace, NODE)
        preparation_key = assessments.ensure_preparation_job(connection, workspace, node)["id"]

    runtime.generate_assessment_set(
        owner_user_id=OWNER,
        workspace_id=WORKSPACE,
        course_id=COURSE,
        private_course_id=PRIVATE_COURSE,
        node_id=NODE,
        preparation_key=preparation_key,
    )
    with database.connect() as connection:
        provenance = connection.execute(
            "SELECT provenance.validation_report_json "
            "FROM assessment_preparation_questions AS slot "
            "JOIN question_engine_provenance AS provenance "
            "ON provenance.question_revision_id=slot.question_revision_id "
            "WHERE slot.preparation_job_id=? AND slot.ordinal=1",
            (preparation_key,),
        ).fetchone()
        signals = json.loads(provenance["validation_report_json"])["semantic_signals"]
        receipt_id = next(
            signal["receipt_id"] for signal in signals if signal["dimension"] == dimension
        )
        connection.execute("DELETE FROM jev_decision_receipts WHERE id=?", (receipt_id,))

    with pytest.raises(QuestionEngineRuntimeError) as raised:
        runtime.generate_assessment_set(
            owner_user_id=OWNER,
            workspace_id=WORKSPACE,
            course_id=COURSE,
            private_course_id=PRIVATE_COURSE,
            node_id=NODE,
            preparation_key=preparation_key,
        )

    assert raised.value.code == "ASSESSMENT_SLOT_RECEIPT_INVALID"
