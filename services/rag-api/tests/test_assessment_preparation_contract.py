"""Targeted contracts for the extended five-question assessment service.

These tests exercise the pool-preparation path, the two verification channels,
the unified-answer mapping, draft resume, and grading-failure projection. They
never seed or relabel questions and never require a live model or image
transcription.
"""
import json
from pathlib import Path
from typing import Any

import pytest
from test_assessment_runtime import (
    current_revision,
    seed_assessment_pool,
    start_assessment,
    submit_assessment,
)
from test_learning_journey import setup_workspace
from test_learning_workspace import client_at
from test_question_runtime import decisions

from app.errors import ApiError
from app.learning.models import AssessmentAnswer, AssessmentSubmitInput
from app.learning.question_runtime import QuestionEngineRuntimeError


def _node_projection(client: Any, workspace_id: str, node_id: str) -> dict[str, Any]:
    knowledge = client.get(f"/api/learning/workspaces/{workspace_id}/knowledge").json()
    return next(item for item in knowledge["registry"] if item["id"] == node_id)


def enable_question_engine_assessment(
    client: Any, workspace: dict[str, Any], node: dict[str, Any]
) -> None:
    """Give this isolated node real cited evidence and labelled semantic fixtures."""

    base = f"/api/learning/workspaces/{workspace['id']}"
    uploaded = client.post(
        base + "/documents",
        files={
            "file": (
                "addition-evidence.txt",
                b"Addition combines the counts of disjoint groups into one total.",
                "text/plain",
            )
        },
    )
    assert uploaded.status_code == 202, uploaded.text
    with client.app.state.database.connect() as db:
        chunk = db.execute(
            "SELECT id FROM chunks WHERE course_id=? ORDER BY ordinal LIMIT 1",
            (workspace["private_course_id"],),
        ).fetchone()
    assert chunk is not None
    spec = client.post(
        base + f"/nodes/{node['id']}/specs",
        json={
            "operation_id": "assessment-evidence-spec",
            "revision": current_revision(client, workspace["id"]),
            "change_reason": "Bind the assessment objective to immutable test evidence",
            "items": [
                {
                    "item_id": "principle",
                    "requirement": "REQUIRED",
                    "objective": "Explain addition",
                    "acceptance": "Explain combining counts with an example",
                    "evidence_ids": [chunk["id"]],
                }
            ],
        },
    )
    assert spec.status_code == 200, spec.text

    semantic = decisions(client.app.state.database)
    learning = client.app.state.learning
    learning.jev = semantic
    learning.assessments.jev = semantic
    learning.question_engine.semantic_decisions = semantic


def test_pool_preparation_idempotent_and_marks_verification_channels(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        enable_question_engine_assessment(client, workspace, node)
        base = f"/api/learning/workspaces/{workspace['id']}"

        first = client.post(
            base + "/assessments",
            json={
                "operation_id": "prep-1",
                "revision": current_revision(client, workspace["id"]),
                "node_id": node["id"],
            },
        )
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "READY"
        assert first.json()["preparation_job_id"]

        with client.app.state.database.connect() as db:
            jobs = db.execute("SELECT * FROM assessment_preparation_jobs").fetchall()
            questions = db.execute(
                "SELECT family_id,question_type,verification_method,validation_status "
                "FROM assessment_question_revisions ORDER BY rowid"
            ).fetchall()
            reservations = db.execute(
                "SELECT role,status FROM learning_model_call_reservations "
                "ORDER BY created_at,id"
            ).fetchall()
            runs = db.execute(
                "SELECT role,status FROM learning_model_run_evidence "
                "ORDER BY started_at,id"
            ).fetchall()
        # Idempotent per owner/node/spec: exactly one preparation job exists.
        assert len(jobs) == 1
        assert jobs[0]["status"] == "READY"
        assert {row["question_type"] for row in questions} == {
            "MCQ_SINGLE",
            "SHORT_TEXT",
            "EXPLANATION",
        }
        assert all(row["verification_method"] == "AI_REVIEWED" for row in questions)
        assert all(row["validation_status"] == "VALIDATED" for row in questions)
        reservation_roles = [row["role"] for row in reservations]
        assert len(reservation_roles) == 10
        assert reservation_roles.count("QUESTION_AUTHOR") == 5
        assert reservation_roles.count("QUESTION_BLIND_SOLVER") == 5
        assert all(row["status"] == "COMPLETED" for row in reservations)
        run_roles = [row["role"] for row in runs]
        assert len(run_roles) == 10
        assert run_roles.count("QUESTION_AUTHOR") == 5
        assert run_roles.count("QUESTION_BLIND_SOLVER") == 5
        assert all(row["status"] == "COMPLETED" for row in runs)

        # The prepared pool is now sufficient: a real session starts.
        session = client.post(
            base + "/assessments",
            json={
                "operation_id": "start-after-prep",
                "revision": current_revision(client, workspace["id"]),
                "node_id": node["id"],
            },
        )
        assert session.status_code == 200, session.text
        assert session.json()["status"] == "IN_PROGRESS"
        assert len(session.json()["questions"]) == 5


def test_blocked_preparation_recovers_when_the_compatible_ready_pool_reaches_five(
    tmp_path: Path,
) -> None:
    """A late provider failure must not strand five already-compatible questions."""

    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        learning = client.app.state.learning

        def completes_pool_then_reports_blocked(**_kwargs: Any) -> list[dict[str, Any]]:
            seed_assessment_pool(client, node, prefix="late-ready-")
            raise QuestionEngineRuntimeError(
                "AUTHOR_PROVIDER_BLOCKED",
                "Synthetic final provider call failed after five compatible rows were ready.",
            )

        learning.question_engine.generate_assessment_set = completes_pool_then_reports_blocked
        base = f"/api/learning/workspaces/{workspace['id']}"
        prepared = client.post(
            base + "/assessments",
            json={
                "operation_id": "late-ready-preparation",
                "revision": current_revision(client, workspace["id"]),
                "node_id": node["id"],
            },
        )

        assert prepared.status_code == 200, prepared.text
        assert prepared.json()["status"] == "BLOCKED"
        assert prepared.json()["eligible_families"] == 5
        assert prepared.json()["can_start_from_ready_pool"] is True
        assert prepared.json()["error_code"] == "AUTHOR_PROVIDER_BLOCKED"

        started = client.post(
            base + "/assessments",
            json={
                "operation_id": "late-ready-start",
                "revision": current_revision(client, workspace["id"]),
                "node_id": node["id"],
            },
        )
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "IN_PROGRESS"
        assert len(started.json()["questions"]) == 5


def test_model_only_never_becomes_validated(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        with client.app.state.database.connect() as db:
            db.execute(
                "INSERT INTO assessment_question_revisions("
                "id,course_id,owner_user_id,family_id,revision,source_kind,"
                "question_type,difficulty,prompt_text,options_json,answer_json,"
                "validation_status,verification_method,content_hash,created_by_user_id) "
                "VALUES('model-only-q','cs3481','a','family_model_only',1,'MODEL_GENERATED',"
                "'EXPLANATION',1,'Explain.','[]','{\"reference_answer\":\"x\"}',"
                "'VALIDATED','MODEL_ONLY',"
                "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','a')",
            )
            db.execute(
                "INSERT INTO assessment_rubric_criteria("
                "question_revision_id,criterion_id,node_id,spec_version,item_id,"
                "dimension,max_fraction,description,deterministic_rule_json) "
                "VALUES('model-only-q','c',?,1,'principle','CONCEPT',100,'x','{}')",
                (node["id"],),
            )
        orch = client.app.state.learning
        with client.app.state.database.connect() as db:
            ws = db.execute(
                "SELECT * FROM learning_workspaces WHERE id=?", (workspace["id"],)
            ).fetchone()
            node_row = orch.assessments._atomic_node(db, ws, node["id"])
            families = orch.assessments.distinct_families(db, ws, node_row)
        assert "family_model_only" not in families


def test_short_text_without_enumeration_uses_semantic_grader(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        seed_assessment_pool(client, node)
        # A concept SHORT_TEXT with no finite enumeration must NOT be deterministic.
        orch = client.app.state.learning
        with client.app.state.database.connect() as db:
            question = {
                "question_type": "SHORT_TEXT",
                "answer_key": {"reference_answer": "Addition combines disjoint counts."},
            }
            assert orch.assessments._is_deterministic(question) is False
            finite = {
                "question_type": "SHORT_TEXT",
                "answer_key": {"accepted": ["2", "two"], "case_sensitive": False},
            }
            assert orch.assessments._is_deterministic(finite) is True


def test_unified_answer_maps_exactly_five_blueprint_ids(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        seed_assessment_pool(client, node)
        assessment = start_assessment(client, workspace["id"], node["id"], "map-unified")
        orch = client.app.state.learning
        unified = (
            "1. five\n"
            "2. seven\n"
            "第3题 two\n"
            "4) nine\n"
            "5、zero\n"
        )
        with client.app.state.database.connect() as db:
            mapped = orch.assessments.map_unified_answers(
                db, assessment["id"], unified, []
            )
        assert len(mapped) == 5
        by_item = {a.blueprint_item_id: a.answer for a in mapped}
        question_by_ordinal = {
            q["ordinal"]: q for q in assessment["questions"]
        }
        assert by_item[question_by_ordinal[1]["id"]] == "five"
        assert by_item[question_by_ordinal[2]["id"]] == "seven"
        assert by_item[question_by_ordinal[3]["id"]] == "two"
        assert by_item[question_by_ordinal[4]["id"]] == "nine"
        assert by_item[question_by_ordinal[5]["id"]] == "zero"

        # Low-confidence / unmapped must ask for confirmation, never guess.
        with pytest.raises(ApiError) as exc:
            with client.app.state.database.connect() as db:
                orch.assessments.map_unified_answers(
                    db, assessment["id"], "1. only one answer", []
                )
        assert exc.value.code == "ASSESSMENT_ANSWERS_NEED_CONFIRMATION"

        # Explicit confirmation records blank answers without guessing.
        with client.app.state.database.connect() as db:
            confirmed = orch.assessments.map_unified_answers(
                db,
                assessment["id"],
                "1. only one answer",
                [q["id"] for q in assessment["questions"][1:]],
            )
        assert len(confirmed) == 5
        assert {a.answer for a in confirmed[1:]} == {""}


def test_no_answer_leak_before_submit(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        seed_assessment_pool(client, node)
        assessment = start_assessment(client, workspace["id"], node["id"], "no-leak")
        assert all("review" not in q for q in assessment["questions"])
        assert all("reference_solution" not in q for q in assessment["questions"])
        wire = json.dumps(assessment).lower()
        for forbidden in ("correct_option", '"accepted"', '"tolerance"', "reference_solution"):
            assert forbidden not in wire

        # Explanation resolver refuses before grading.
        item = assessment["questions"][0]
        response = client.post(
            f"/api/learning/workspaces/{workspace['id']}/assessments/"
            f"{assessment['id']}/explain",
            json={
                "operation_id": "explain-before-grade",
                "revision": current_revision(client, workspace["id"]),
                "blueprint_item_id": item["id"],
                "step_id": "step_1",
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ASSESSMENT_NOT_GRADED"


def test_draft_resume_does_not_create_a_new_paid_set(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        seed_assessment_pool(client, node)
        assessment = start_assessment(client, workspace["id"], node["id"], "draft-set")
        base = f"/api/learning/workspaces/{workspace['id']}"

        with client.app.state.database.connect() as db:
            before_q = db.execute(
                "SELECT COUNT(*) FROM assessment_question_revisions"
            ).fetchone()[0]

        saved = client.post(
            base + f"/assessments/{assessment['id']}/draft",
            json={
                "operation_id": "draft-save",
                "revision": current_revision(client, workspace["id"]),
                "unified_answer": "1. five\n2. seven",
                "attachments": [],
            },
        )
        assert saved.status_code == 200, saved.text
        loaded = client.get(base + f"/assessments/{assessment['id']}/draft")
        assert loaded.status_code == 200, loaded.text
        assert loaded.json()["draft"]["unified_answer"] == "1. five\n2. seven"

        with client.app.state.database.connect() as db:
            after_q = db.execute(
                "SELECT COUNT(*) FROM assessment_question_revisions"
            ).fetchone()[0]
        assert after_q == before_q


def test_grading_failure_keeps_previous_result_and_marks_needs_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        answers = seed_assessment_pool(client, node, include_open=True)
        base = f"/api/learning/workspaces/{workspace['id']}"

        first = start_assessment(client, workspace["id"], node["id"], "grade-first")
        result = submit_assessment(
            client, workspace["id"], first, answers, "submit-first"
        )
        assert result.status_code == 200, result.text
        assert result.json()["raw_score"] == 100

        second = start_assessment(client, workspace["id"], node["id"], "grade-second")

        def failing_grader(schema: str, context: dict[str, Any]) -> dict[str, Any]:
            if schema == "AssessmentGradeProposal":
                raise ApiError(503, "MODEL_LIVE_BLOCKED", "Synthetic grader outage")
            raise AssertionError(schema)

        monkeypatch.setattr("app.learning.testing.fixture_output", failing_grader)
        failed = submit_assessment(
            client, workspace["id"], second, answers, "submit-failed"
        )
        assert failed.status_code == 200, failed.text
        assert failed.json()["status"] == "SUBMITTED"
        assert failed.json().get("needs_review") is True
        assert failed.json()["raw_score"] is None

        projection = _node_projection(client, workspace["id"], node["id"])
        assessment_state = projection["state"]["assessment"]
        # The previous valid 100 is preserved; no 0 was written.
        assert assessment_state["latest_result"]["raw_score"] == 100
        with client.app.state.database.connect() as db:
            snapshots = db.execute("SELECT COUNT(*) FROM grade_snapshots").fetchone()[0]
            receipts = db.execute(
                "SELECT COUNT(*) FROM assessment_grading_receipts"
            ).fetchone()[0]
        assert snapshots == 1
        assert receipts >= 1


def test_node_projection_updates_after_grading(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        answers = seed_assessment_pool(client, node)
        base = f"/api/learning/workspaces/{workspace['id']}"
        assessment = start_assessment(client, workspace["id"], node["id"], "project")
        result = submit_assessment(client, workspace["id"], assessment, answers, "project-submit")
        assert result.status_code == 200, result.text
        assert result.json()["raw_score"] == 100

        projection = _node_projection(client, workspace["id"], node["id"])
        assessment_state = projection["state"]["assessment"]
        assert assessment_state["status"] == "GRADED"
        assert assessment_state["raw_score"] == 100
        assert assessment_state["latest_result"]["raw_score"] == 100


def test_assessment_display_renders_raw_score_without_school_grade() -> None:
    from app.ui_extension.domain import _assessment_display

    assert _assessment_display({"status": "GRADED", "raw_score": 78}) == "78.0/100 · AI自测"
    assert (
        _assessment_display({"status": "GRADED", "raw_score": 78, "grade_label": "A"})
        == "A · 78.0/100"
    )
    assert _assessment_display({"status": "IN_PROGRESS", "raw_score": None}) == "测评进行中"
    assert _assessment_display({}) is None


def test_pool_preparation_cancel_and_resume(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        enable_question_engine_assessment(client, workspace, node)
        base = f"/api/learning/workspaces/{workspace['id']}"
        orch = client.app.state.learning
        with client.app.state.database.connect() as db:
            ws = db.execute(
                "SELECT * FROM learning_workspaces WHERE id=?", (workspace["id"],)
            ).fetchone()
            node_row = orch.assessments._atomic_node(db, ws, node["id"])
            job = orch.assessments.ensure_preparation_job(db, ws, node_row)
            job_id = job["id"]

        cancelled = client.post(
            base + f"/assessments/prepare/{job_id}/cancel",
            json={
                "operation_id": "prep-cancel",
                "revision": current_revision(client, workspace["id"]),
            },
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "CANCELLED"

        resumed = client.post(
            base + "/assessments/prepare/resume",
            json={
                "operation_id": "prep-resume",
                "revision": current_revision(client, workspace["id"]),
                "node_id": node["id"],
            },
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["status"] == "READY"
        assert resumed.json()["preparation_job_id"] == job_id
        with client.app.state.database.connect() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM assessment_question_revisions"
            ).fetchone()[0]
        assert count == 5


def test_submit_input_accepts_unified_payload_backward_compatibly() -> None:
    legacy = AssessmentSubmitInput(
        operation_id="op",
        revision=0,
        answers=[
            AssessmentAnswer(blueprint_item_id=f"bp{i}", answer=str(i))
            for i in range(1, 6)
        ],
    )
    assert len(legacy.answers) == 5

    unified = AssessmentSubmitInput(
        operation_id="op",
        revision=0,
        unified_answer="1. a\n2. b\n3. c\n4. d\n5. e",
    )
    assert unified.answers == []
    assert unified.unified_answer is not None

    with pytest.raises(ValueError):
        AssessmentSubmitInput(operation_id="op", revision=0)
