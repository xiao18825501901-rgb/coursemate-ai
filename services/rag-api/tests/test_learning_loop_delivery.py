from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_question_persistence import NODE, OWNER, WORKSPACE, persist, pipeline

from app.learning.learning_loop import LearningLoopError, LearningLoopService
from app.learning.learning_loop_reporting import current_observation
from app.learning.learning_loop_seeds import apply_seed, plan_seed


def _activate_pack(database, question_revision_id: str) -> str:
    with database.connect() as connection:
        provenance = connection.execute(
            "SELECT node_id,spec_version,objective_id FROM question_engine_provenance "
            "WHERE question_revision_id=?",
            (question_revision_id,),
        ).fetchone()
        source_refs = [
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT document_version_id FROM material_evidence "
                "WHERE node_id=? AND status='ACTIVE' ORDER BY document_version_id",
                (provenance["node_id"],),
            )
        ]
        if not source_refs:
            source_refs = [
                str(row[0])
                for row in connection.execute(
                    "SELECT id FROM documents WHERE course_id=(SELECT course_id FROM "
                    "learning_workspaces WHERE id=?) ORDER BY id",
                    (WORKSPACE,),
                )
            ]
        manifest_hash = hashlib.sha256(
            json.dumps(source_refs, separators=(",", ":")).encode()
        ).hexdigest()
        pack_id = "pack-course-question-engine-r1"
        connection.execute(
            "INSERT INTO learning_loop_pack_revisions("
            "id,course_id,offering_id,revision,source_manifest_hash,source_refs_json,"
            "rights_status,review_status,status,created_by_user_id) "
            "VALUES(?,(SELECT course_id FROM learning_workspaces WHERE id=?),?,1,?,?,"
            "'OWNER_PRIVATE','AI_ORGANIZED','ACTIVE',?)",
            (pack_id, WORKSPACE, "course-question-engine", manifest_hash, json.dumps(source_refs), OWNER),
        )
        connection.execute(
            "INSERT INTO learning_loop_pack_targets("
            "pack_revision_id,node_id,spec_version,objective_id) VALUES(?,?,?,?)",
            (
                pack_id,
                provenance["node_id"],
                provenance["spec_version"],
                provenance["objective_id"],
            ),
        )
        connection.execute(
            "INSERT INTO learning_loop_course_flags("
            "course_id,enabled,enabled_by_user_id,enabled_at,history_complete_from) "
            "VALUES((SELECT course_id FROM learning_workspaces WHERE id=?),1,?,"
            "strftime('%Y-%m-%dT%H:%M:%fZ','now'),'1970-01-01T00:00:00.000Z')",
            (WORKSPACE, OWNER),
        )
    return pack_id


def _second_ready_question(database, first_id: str, suffix: str = "transfer") -> str:
    second = f"question-learning-loop-{suffix}"
    question_hash = hashlib.sha256(second.encode()).hexdigest()
    solution_hash = hashlib.sha256((second + ":solution").encode()).hexdigest()
    with database.connect() as connection:
        question = connection.execute(
            "SELECT * FROM assessment_question_revisions WHERE id=?", (first_id,)
        ).fetchone()
        provenance = connection.execute(
            "SELECT * FROM question_engine_provenance WHERE question_revision_id=?", (first_id,)
        ).fetchone()
        connection.execute(
            "INSERT INTO assessment_question_revisions("
            "id,course_id,owner_user_id,family_id,revision,source_kind,"
            "source_document_version_id,source_problem_revision_id,question_type,difficulty,"
            "prompt_text,options_json,answer_json,validation_status,verification_method,"
            "content_hash,created_by_user_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                second, question["course_id"], question["owner_user_id"],
                f"family-learning-loop-{suffix}", 1, question["source_kind"],
                question["source_document_version_id"], question["source_problem_revision_id"],
                question["question_type"], question["difficulty"],
                question["prompt_text"] + " Transfer variant.", question["options_json"],
                question["answer_json"], question["validation_status"],
                question["verification_method"], question_hash, question["created_by_user_id"],
            ),
        )
        for row in connection.execute(
            "SELECT * FROM assessment_rubric_criteria WHERE question_revision_id=?", (first_id,)
        ):
            connection.execute(
                "INSERT INTO assessment_rubric_criteria("
                "question_revision_id,criterion_id,node_id,spec_version,item_id,dimension,"
                "description,max_fraction) VALUES(?,?,?,?,?,?,?,?)",
                (second, row["criterion_id"], row["node_id"], row["spec_version"],
                 row["item_id"], row["dimension"], row["description"], row["max_fraction"]),
            )
        reference = connection.execute(
            "SELECT * FROM assessment_reference_solutions WHERE question_revision_id=? "
            "ORDER BY solution_revision DESC LIMIT 1", (first_id,)
        ).fetchone()
        connection.execute(
            "INSERT INTO assessment_reference_solutions("
            "id,question_revision_id,solution_revision,steps_json,answer_json,source_refs_json,"
            "prompt_version,content_hash) VALUES(?,?,?,?,?,?,?,?)",
            (f"solution-learning-loop-{suffix}", second, 1, reference["steps_json"],
             reference["answer_json"], reference["source_refs_json"],
             reference["prompt_version"], solution_hash),
        )
        connection.execute(
            "INSERT INTO question_engine_provenance("
            "question_revision_id,workspace_id,blueprint_id,blueprint_hash,evidence_pack_hash,"
            "question_revision_hash,node_id,spec_version,objective_id,blueprint_json,"
            "evidence_ids_json,author_run_json,blind_input_hash,blind_output_json,blind_run_json,"
            "validation_report_json,publication_status,readiness_reason) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (second, provenance["workspace_id"], f"blueprint-learning-loop-{suffix}", hashlib.sha256((second + ':blueprint').encode()).hexdigest(),
             provenance["evidence_pack_hash"], hashlib.sha256((second + ':revision').encode()).hexdigest(), provenance["node_id"],
             provenance["spec_version"], provenance["objective_id"],
             provenance["blueprint_json"], provenance["evidence_ids_json"],
             provenance["author_run_json"], provenance["blind_input_hash"],
             provenance["blind_output_json"], provenance["blind_run_json"],
             provenance["validation_report_json"], "READY", "OFFLINE_TEST_READY"),
        )
    return second


def test_learning_loop_schema_is_additive_and_reference_store_is_absent(tmp_path: Path) -> None:
    values = pipeline(tmp_path)
    database = values["database"]
    with database.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    assert version == 60
    assert {
        "learning_loop_cycles",
        "learning_loop_exposures",
        "practice_submission_revisions",
        "practice_evaluation_jobs",
        "learning_loop_followups",
    } <= tables
    assert not any(name.startswith("ref_") for name in tables)


def test_wrong_transfer_closes_only_after_initial_feedback_and_keeps_frozen_help_snapshot(
    tmp_path: Path,
) -> None:
    values = pipeline(tmp_path)
    first = persist(values).question_revision_id
    second = _second_ready_question(values["database"], first)
    _activate_pack(values["database"], first)
    loop = LearningLoopService(values["database"], test_environment=True)

    cycle = loop.start(
        owner_user_id=OWNER,
        operation_id="loop-start-0001",
        course_id="course-question-engine",
        pair_ref="pair-main",
        node_id=NODE,
        initial_question_revision_id=first,
    )
    initial_assignment = cycle["initial_assignment"]
    initial_submission = loop.record_submission(
        owner_user_id=OWNER,
        operation_id="loop-submit-initial-0001",
        assignment_id=initial_assignment["id"],
        answer="A substantive but incorrect initial answer.",
    )
    loop.record_evaluation(
        owner_user_id=OWNER,
        operation_id="loop-eval-initial-0001",
        canonical_submission_id=initial_submission["canonical_submission_id"],
        outcome="INCORRECT",
    )

    with pytest.raises(LearningLoopError, match="INITIAL_FEEDBACK_REQUIRED"):
        loop.assign(
            owner_user_id=OWNER,
            operation_id="loop-transfer-too-early",
            cycle_id=cycle["id"],
            question_revision_id=second,
            purpose="TRANSFER",
        )

    loop.deliver_feedback(
        owner_user_id=OWNER,
        operation_id="loop-feedback-initial-0001",
        cycle_id=cycle["id"],
        canonical_submission_id=initial_submission["canonical_submission_id"],
        strategy_version="contrast/1",
    )
    transfer = loop.assign(
        owner_user_id=OWNER,
        operation_id="loop-transfer-0001",
        cycle_id=cycle["id"],
        question_revision_id=second,
        purpose="TRANSFER",
    )
    transfer_submission = loop.record_submission(
        owner_user_id=OWNER,
        operation_id="loop-submit-transfer-0001",
        assignment_id=transfer["id"],
        answer="Wrong, but it is a real attempt made before help.",
    )
    loop.record_exposure(
        owner_user_id=OWNER,
        operation_id="loop-reveal-after-submit-0001",
        question_revision_id=second,
        kind="SOLUTION",
        channel="PROBLEM_PANE",
        receipt="reveal-after-submit-0001",
        assignment_id=transfer["id"],
    )
    loop.record_evaluation(
        owner_user_id=OWNER,
        operation_id="loop-eval-transfer-0001",
        canonical_submission_id=transfer_submission["canonical_submission_id"],
        outcome="INCORRECT",
    )

    card = loop.evidence_card(owner_user_id=OWNER, cycle_id=cycle["id"])
    assert card["historical_closure_exists"] is True
    assert card["currently_valid_closure"] is True
    assert card["attempts"][-1]["outcome"] == "INCORRECT"
    assert card["attempts"][-1]["original_within_platform_unassisted"] is True
    assert card["attempts"][-1]["currently_eligible"] is True
    assert card["formal_grade_written_by_this_module"] is False

    followup = loop.schedule_followup(
        owner_user_id=OWNER,
        operation_id="loop-followup-opt-in-0001",
        cycle_id=cycle["id"],
        explicit_opt_in=True,
        timezone="Asia/Hong_Kong",
        due_at="2099-01-08T00:00:00Z",
    )
    assert followup["status"] == "PENDING"
    claimed = loop.claim_followup(owner_user_id=OWNER, followup_id=followup["id"])
    assert claimed["claimed"] is True
    bound = loop.finish_followup(
        owner_user_id=OWNER, followup_id=followup["id"], task_ref="task-followup-0001"
    )
    assert bound["status"] == "BOUND"
    assert loop.evidence_card(owner_user_id=OWNER, cycle_id=cycle["id"])["followups"][0][
        "task_ref"
    ] == "task-followup-0001"
    dependencies = loop.dependency_scan(target_ref=second)
    assert dependencies["target_kind"] == "QUESTION"
    assert dependencies["dependent_counts"]["submission_count"] == 1
    metrics = current_observation(
        values["database"], as_of=datetime(2100, 1, 1, tzinfo=UTC)
    )
    assert metrics["weekly_cycles"]["unique_users"] == 0
    assert metrics["weekly_cycles"]["internal_cycles_excluded"] == 1
    assert metrics["cost"]["status"] == "UNKNOWN_NO_BILLING_AMOUNT_LEDGER"
    assert metrics["student_validation"]["claim"] is None

    loop.withdraw(
        actor_user_id=OWNER,
        operation_id="loop-withdraw-transfer-0001",
        target_ref=second,
        reason_ref="source-correction-0001",
        editor_authorized=True,
    )
    corrected = loop.evidence_card(owner_user_id=OWNER, cycle_id=cycle["id"])
    assert corrected["historical_closure_exists"] is True
    assert corrected["currently_valid_closure"] is False
    assert "CONTENT_WITHDRAWN" in corrected["attempts"][-1]["reasons"]


def test_help_in_another_pane_or_history_is_in_the_frozen_submission_snapshot(
    tmp_path: Path,
) -> None:
    values = pipeline(tmp_path)
    question = persist(values).question_revision_id
    _activate_pack(values["database"], question)
    loop = LearningLoopService(values["database"], test_environment=True)
    cycle = loop.start(
        owner_user_id=OWNER,
        operation_id="loop-start-cross-pane",
        course_id="course-question-engine",
        pair_ref="pair-main",
        node_id=NODE,
        initial_question_revision_id=question,
    )
    assignment = cycle["initial_assignment"]
    loop.record_exposure(
        owner_user_id=OWNER,
        operation_id="loop-teaching-help-0001",
        question_revision_id=question,
        kind="TARGETED_TEACHING",
        channel="TEACHING_PANE",
        receipt="teaching-pane-help-0001",
        assignment_id=assignment["id"],
    )
    loop.record_exposure(
        owner_user_id=OWNER,
        operation_id="loop-authorized-share-help-0001",
        question_revision_id=question,
        kind="SOLUTION",
        channel="AUTHORIZED_SHARE",
        receipt="authorized-share-help-0001",
        assignment_id=assignment["id"],
    )
    loop.record_exposure(
        owner_user_id=OWNER,
        operation_id="loop-history-help-0001",
        question_revision_id=question,
        kind="SOLUTION",
        channel="HISTORY",
        receipt="history-help-0001",
        assignment_id=assignment["id"],
    )
    submission = loop.record_submission(
        owner_user_id=OWNER,
        operation_id="loop-submit-assisted-0001",
        assignment_id=assignment["id"],
        answer="A substantive answer after help.",
    )
    assert submission["independent_at_submission"] is False
    assert set(submission["eligibility_reasons"]) == {"HELP_BEFORE_SUBMISSION"}


def test_optional_three_item_diagnostic_is_skippable_and_not_a_formal_assessment(
    tmp_path: Path,
) -> None:
    values = pipeline(tmp_path)
    first = persist(values).question_revision_id
    for suffix in ("diagnostic-a", "diagnostic-b", "diagnostic-c"):
        _second_ready_question(values["database"], first, suffix)
    _activate_pack(values["database"], first)
    loop = LearningLoopService(values["database"], test_environment=True)
    cycle = loop.start(
        owner_user_id=OWNER,
        operation_id="loop-start-diagnostic-0001",
        course_id="course-question-engine",
        pair_ref="pair-main",
        node_id=NODE,
        initial_question_revision_id=first,
    )
    configured = loop.configure_diagnostic(
        owner_user_id=OWNER,
        operation_id="loop-configure-diagnostic-0001",
        cycle_id=cycle["id"],
    )
    assert configured["purpose"] == "PRACTICE_NOT_FORMAL_ASSESSMENT"
    assert configured["skippable"] is True
    assert len(configured["items"]) == 3
    assert len({item["family_id"] for item in configured["items"]}) == 3
    assert all(item["unsure_is_not_scored_zero"] for item in configured["items"])
    skipped = loop.skip_diagnostic(
        owner_user_id=OWNER,
        operation_id="loop-skip-diagnostic-0001",
        cycle_id=cycle["id"],
    )
    assert skipped["status"] == "SKIPPED"
    with values["database"].connect() as connection:
        state = connection.execute(
            "SELECT state,diagnostic_status FROM learning_loop_cycles WHERE id=?",
            (cycle["id"],),
        ).fetchone()
        formal = connection.execute(
            "SELECT COUNT(*) FROM assessment_sessions WHERE owner_user_id=?", (OWNER,)
        ).fetchone()[0]
    assert dict(state) == {"state": "DIRECT_PRACTICE", "diagnostic_status": "SKIPPED"}
    assert formal == 0


def test_three_explicit_unsure_responses_complete_diagnostic_without_a_grade(
    tmp_path: Path,
) -> None:
    values = pipeline(tmp_path)
    first = persist(values).question_revision_id
    for suffix in ("diagnostic-a", "diagnostic-b", "diagnostic-c"):
        _second_ready_question(values["database"], first, suffix)
    _activate_pack(values["database"], first)
    loop = LearningLoopService(values["database"], test_environment=True)
    cycle = loop.start(
        owner_user_id=OWNER,
        operation_id="loop-start-diagnostic-unsure",
        course_id="course-question-engine",
        pair_ref="pair-main",
        node_id=NODE,
        initial_question_revision_id=first,
    )
    diagnostic = loop.configure_diagnostic(
        owner_user_id=OWNER,
        operation_id="loop-configure-diagnostic-unsure",
        cycle_id=cycle["id"],
    )
    result = None
    for index, item in enumerate(diagnostic["items"], start=1):
        result = loop.record_diagnostic_unsure(
            owner_user_id=OWNER,
            operation_id=f"loop-diagnostic-unsure-{index}",
            cycle_id=cycle["id"],
            assignment_id=item["id"],
        )
    assert result is not None
    assert result["status"] == "COMPLETED"
    assert set(result["responses"].values()) == {"UNSURE"}
    card = loop.evidence_card(owner_user_id=OWNER, cycle_id=cycle["id"])
    assert card["diagnostic"]["status"] == "COMPLETED"
    assert all(item["response"] == "UNSURE" for item in card["diagnostic"]["items"])
    with values["database"].connect() as connection:
        formal = connection.execute(
            "SELECT COUNT(*) FROM assessment_sessions WHERE owner_user_id=?", (OWNER,)
        ).fetchone()[0]
        diagnostic_attempts = connection.execute(
            "SELECT COUNT(*) FROM practice_submission_revisions WHERE owner_user_id=?", (OWNER,)
        ).fetchone()[0]
    assert formal == 0
    assert diagnostic_attempts == 0


def test_real_seed_planner_activates_only_published_authorities(tmp_path: Path) -> None:
    values = pipeline(tmp_path)
    first = persist(values).question_revision_id
    _second_ready_question(values["database"], first)
    with values["database"].connect() as connection:
        connection.execute(
            "UPDATE courses SET course_type='official',owner_user_id=NULL,visibility='public',"
            "publication_status='published',published_at='2026-09-28T00:00:00Z' "
            "WHERE id='course-question-engine'"
        )
        connection.execute(
            "UPDATE knowledge_nodes SET owner_user_id=NULL,status='PUBLISHED' WHERE id=?", (NODE,)
        )
        connection.execute(
            "INSERT INTO courses(id,name,description,course_type,visibility,preferred_language,"
            "publication_status,display_type,requires_student_verification) "
            "VALUES('course-waiting','CS4335','','official','private','auto','private','campus',1)"
        )
    with values["database"].connect() as connection:
        active = plan_seed(connection, "course-question-engine")
        waiting = plan_seed(connection, "course-waiting")
    assert active.status == "ACTIVE"
    assert active.reason == "READY"
    assert active.targets[0].distinct_families == 2
    assert waiting.status == "DRAFT"
    assert waiting.review_status == "WAITING_SOURCE"
    assert waiting.reason == "NO_READY_DOCUMENTS"
    with values["database"].connect() as connection:
        applied = apply_seed(
            connection,
            plan=active,
            actor_user_id="admin-owner",
            observed_at="2026-09-28T00:00:00.000Z",
        )
    assert applied["action"] == "ACTIVATED"
    with values["database"].connect() as connection:
        replay = apply_seed(
            connection,
            plan=active,
            actor_user_id="admin-owner",
            observed_at="2026-09-28T00:00:00.000Z",
        )
        flag = connection.execute(
            "SELECT enabled,history_complete_from FROM learning_loop_course_flags "
            "WHERE course_id='course-question-engine'"
        ).fetchone()
    assert replay["action"] == "UNCHANGED"
    assert dict(flag) == {
        "enabled": 1,
        "history_complete_from": "2026-09-28T00:00:00.000Z",
    }
