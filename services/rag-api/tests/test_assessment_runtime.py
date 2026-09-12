import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from test_learning_journey import setup_workspace
from test_learning_workspace import client_at


def seed_assessment_pool(
    client: Any,
    node: dict[str, Any],
    *,
    prefix: str = "",
    include_open: bool = False,
) -> dict[str, str]:
    model_question = (
        "EXPLANATION",
        "Explain why addition combines the two disjoint counts.",
        {"reference_answer": "Addition combines the sizes of disjoint groups."},
        "Addition combines the sizes of disjoint groups.",
    ) if include_open else (
        "SHORT_TEXT",
        "Write the result of one plus one.",
        {"accepted": ["2", "two"], "case_sensitive": False},
        "two",
    )
    questions = [
        (
            prefix + "aq_official_mcq",
            prefix + "family_official_mcq",
            "OFFICIAL",
            None,
            "MCQ_SINGLE",
            1,
            "Choose the result of 2 + 3.",
            ["4", "5", "6"],
            {"correct_option": "1"},
            "OFFICIAL",
            "1",
        ),
        (
            prefix + "aq_private_numeric",
            prefix + "family_private_numeric",
            "WORKSPACE_PRIVATE",
            "a",
            "NUMERIC",
            2,
            "Calculate 4 + 3.",
            [],
            {"value": 7, "tolerance": 0},
            "OWNER_AUTHORED",
            "7",
        ),
        (
            prefix + "aq_model_short",
            prefix + "family_model_short",
            "MODEL_GENERATED",
            "a",
            model_question[0],
            3,
            model_question[1],
            [],
            model_question[2],
            "DETERMINISTIC",
            model_question[3],
        ),
        (
            prefix + "aq_external_numeric",
            prefix + "family_external_numeric",
            "EXTERNAL_INSPIRED",
            "a",
            "NUMERIC",
            4,
            "Calculate 5 + 4.",
            [],
            {"value": 9, "tolerance": 0},
            "HUMAN_REVIEWED",
            "9",
        ),
        (
            prefix + "aq_official_second",
            prefix + "family_official_second",
            "OFFICIAL",
            None,
            "MCQ_SINGLE",
            5,
            "Choose the result of 1 + 2.",
            ["3", "4", "5"],
            {"correct_option": "0"},
            "OFFICIAL",
            "0",
        ),
    ]
    answers: dict[str, str] = {}
    with client.app.state.database.connect() as connection:
        for (
            question_id,
            family_id,
            source_kind,
            owner,
            question_type,
            difficulty,
            prompt,
            options,
            answer,
            verification,
            submitted_answer,
        ) in questions:
            content = json.dumps(
                {"prompt": prompt, "options": options, "answer": answer},
                sort_keys=True,
            )
            connection.execute(
                "INSERT INTO assessment_question_revisions("
                "id,course_id,owner_user_id,family_id,revision,source_kind,"
                "question_type,difficulty,prompt_text,options_json,answer_json,"
                "validation_status,verification_method,content_hash,created_by_user_id) "
                "VALUES(?,?,?,?,1,?,?,?,?,?,?,'VALIDATED',?,?,?)",
                (
                    question_id,
                    "cs3481",
                    owner,
                    family_id,
                    source_kind,
                    question_type,
                    difficulty,
                    prompt,
                    json.dumps(options),
                    json.dumps(answer),
                    verification,
                    hashlib.sha256(content.encode()).hexdigest(),
                    owner or "admin",
                ),
            )
            connection.execute(
                "INSERT INTO assessment_rubric_criteria("
                "question_revision_id,criterion_id,node_id,spec_version,item_id,"
                "dimension,max_fraction,description,deterministic_rule_json) "
                "VALUES(?, 'correctness', ?, 1, 'principle', 'CALCULATION', 100, "
                "'Produces the correct result.', '{}')",
                (question_id, node["id"]),
            )
            answers[question_id] = submitted_answer
    return answers


def current_revision(client: Any, workspace_id: str) -> int:
    return client.get(f"/api/learning/workspaces/{workspace_id}/state").json()[
        "revision"
    ]


def start_assessment(
    client: Any,
    workspace_id: str,
    node_id: str,
    operation_id: str,
) -> dict[str, Any]:
    response = client.post(
        f"/api/learning/workspaces/{workspace_id}/assessments",
        json={
            "operation_id": operation_id,
            "revision": current_revision(client, workspace_id),
            "node_id": node_id,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def submit_assessment(
    client: Any,
    workspace_id: str,
    assessment: dict[str, Any],
    answers: dict[str, str],
    operation_id: str,
) -> Any:
    return client.post(
        f"/api/learning/workspaces/{workspace_id}/assessments/"
        f"{assessment['id']}/submit",
        json={
            "operation_id": operation_id,
            "revision": current_revision(client, workspace_id),
            "answers": [
                {
                    "blueprint_item_id": question["id"],
                    "answer": answers[question["question_revision_id"]],
                }
                for question in assessment["questions"]
            ],
        },
    )


def test_assessment_migrations_are_additive_and_seed_an_unconfigured_policy(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        database = client.app.state.database
        database.initialize()
        with database.connect() as connection:
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                )
            }
            policy = connection.execute(
                "SELECT * FROM grade_policy_versions WHERE id='gp_requirements_draft_v1'"
            ).fetchone()
            plan_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(teaching_plan_versions)")
            }

        assert versions == list(range(1, 19))
        assert {
            "assessment_question_revisions",
            "assessment_rubric_criteria",
            "assessment_blueprint_versions",
            "assessment_blueprint_items",
            "assessment_sessions",
            "assessment_question_attempts",
            "assessment_exposure_events",
            "performance_evidence",
            "learning_replan_triggers",
            "teaching_unit_remediations",
            "teaching_plan_performance_triggers",
            "grade_policy_versions",
            "assessment_blueprint_grade_policies",
            "grade_snapshots",
        } <= tables
        assert "performance_trigger_ids_json" not in plan_columns
        assert policy["status"] == "DRAFT_UNCONFIGURED"
        assert policy["display_name"] == "User-supplied learning grade draft"
        assert "official" not in policy["provenance_label"].lower()
        scale = {
            item["letter"]: item["numeric_value"]
            for item in json.loads(policy["numeric_scale_json"])
        }
        assert scale["A+"] == 4.3
        assert scale["A-"] is None
        assert json.loads(policy["raw_score_bands_json"]) == []


def test_assessment_freezes_five_unequal_questions_without_leaking_answers(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        seed_assessment_pool(client, node)
        base = f"/api/learning/workspaces/{workspace['id']}"
        response = client.post(
            base + "/assessments",
            json={
                "operation_id": "assessment-start-1",
                "revision": current_revision(client, workspace["id"]),
                "node_id": node["id"],
            },
        )
        assert response.status_code == 200, response.text
        assessment = response.json()
        assert assessment["status"] == "IN_PROGRESS"
        assert assessment["mode"] == "INDEPENDENT"
        assert len(assessment["questions"]) == 5
        marks = [question["marks"] for question in assessment["questions"]]
        assert sum(marks) == 100
        assert len(set(marks)) > 1
        assert {question["source_kind"] for question in assessment["questions"]} == {
            "OFFICIAL",
            "WORKSPACE_PRIVATE",
            "MODEL_GENERATED",
            "EXTERNAL_INSPIRED",
        }
        wire = json.dumps(assessment).lower()
        for forbidden in (
            "correct_option",
            '"accepted"',
            '"tolerance"',
            "produces the correct result",
            "deterministic_rule",
        ):
            assert forbidden not in wire
        with client.app.state.database.connect() as connection:
            blueprint = connection.execute(
                "SELECT status,selection_policy_json FROM assessment_blueprint_versions"
            ).fetchone()
            policy = connection.execute(
                "SELECT mapping_status FROM assessment_blueprint_grade_policies"
            ).fetchone()
        assert blueprint["status"] == "FROZEN"
        assert json.loads(blueprint["selection_policy_json"])["question_count"] == 5
        assert policy["mapping_status"] == "UNCONFIGURED"

        client.headers["Authorization"] = "Bearer b"
        assert client.get(base + f"/assessments/{assessment['id']}").status_code == 404
        client.headers["Authorization"] = "Bearer a"
        restored = client.get(base + f"/assessments/{assessment['id']}")
        assert restored.status_code == 200, restored.text
        assert restored.json()["questions"] == assessment["questions"]


def test_deterministic_submission_records_raw_score_without_inventing_grade(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        answers = seed_assessment_pool(client, node)
        base = f"/api/learning/workspaces/{workspace['id']}"
        started = client.post(
            base + "/assessments",
            json={
                "operation_id": "assessment-start-grade",
                "revision": current_revision(client, workspace["id"]),
                "node_id": node["id"],
            },
        ).json()
        calls: list[str] = []
        original = client.app.state.learning.provider.generate

        def counted(*args: object, **kwargs: Any) -> object:
            calls.append(str(kwargs["role"]))
            return original(*args, **kwargs)

        client.app.state.learning.provider.generate = counted
        response = client.post(
            base + f"/assessments/{started['id']}/submit",
            json={
                "operation_id": "assessment-submit-grade",
                "revision": current_revision(client, workspace["id"]),
                "answers": [
                    {
                        "blueprint_item_id": question["id"],
                        "answer": answers[question["question_revision_id"]],
                    }
                    for question in started["questions"]
                ],
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "GRADED"
        assert result["raw_score"] == 100
        assert result["independent_eligible"] is True
        assert result["grade"] == {
            "mapping_status": "UNCONFIGURED",
            "label": None,
            "numeric_value": None,
            "message": "评分映射待配置",
        }
        assert calls == []
        state = client.get(base + "/knowledge").json()
        projected = next(item for item in state["registry"] if item["id"] == node["id"])
        assert projected["state"]["learning"]["status"] == "NOT_STARTED"
        assert projected["state"]["assessment"]["raw_score"] == 100
        assert projected["state"]["assessment"]["status"] == "GRADED"


def test_revealing_one_answer_turns_the_whole_session_into_practice(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        answers = seed_assessment_pool(client, node)
        assessment = start_assessment(
            client,
            workspace["id"],
            node["id"],
            "assessment-start-assisted",
        )
        selected = assessment["questions"][0]
        response = client.post(
            f"/api/learning/workspaces/{workspace['id']}/assessments/"
            f"{assessment['id']}/assist",
            json={
                "operation_id": "assessment-reveal-answer",
                "revision": current_revision(client, workspace["id"]),
                "blueprint_item_id": selected["id"],
                "action": "ANSWER_REVEALED",
            },
        )
        assert response.status_code == 200, response.text
        assisted = response.json()
        assert assisted["mode"] == "PRACTICE"
        assert assisted["assistance_status"] == "ANSWER_EXPOSED"
        revealed = next(
            question for question in assisted["questions"] if question["id"] == selected["id"]
        )
        assert revealed["review"]["answer"]
        assert revealed["review"]["rubric"]
        assert all(
            "review" not in question
            for question in assisted["questions"]
            if question["id"] != selected["id"]
        )

        submitted = submit_assessment(
            client,
            workspace["id"],
            assessment,
            answers,
            "assessment-submit-assisted",
        )
        assert submitted.status_code == 200, submitted.text
        result = submitted.json()
        assert result["raw_score"] == 100
        assert result["mode"] == "PRACTICE"
        assert result["independent_eligible"] is False
        assert all(
            evidence["independent_eligible"] is False
            for evidence in result["performance_evidence"]
        )


def test_abandoned_or_unsubmitted_assessment_is_not_zero_or_failure(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        seed_assessment_pool(client, node)
        assessment = start_assessment(
            client,
            workspace["id"],
            node["id"],
            "assessment-start-abandon",
        )
        in_progress = client.get(
            f"/api/learning/workspaces/{workspace['id']}/knowledge"
        ).json()
        projected = next(
            item for item in in_progress["registry"] if item["id"] == node["id"]
        )
        assert projected["state"]["assessment"]["status"] == "IN_PROGRESS"
        assert projected["state"]["assessment"]["raw_score"] is None

        response = client.post(
            f"/api/learning/workspaces/{workspace['id']}/assessments/"
            f"{assessment['id']}/abandon",
            json={
                "operation_id": "assessment-abandon",
                "revision": current_revision(client, workspace["id"]),
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "ABANDONED"
        assert response.json()["raw_score"] is None
        projected = next(
            item
            for item in client.get(
                f"/api/learning/workspaces/{workspace['id']}/knowledge"
            ).json()["registry"]
            if item["id"] == node["id"]
        )
        assert projected["state"]["assessment"] == {
            "status": "NOT_ASSESSED",
            "raw_score": None,
            "grade_label": None,
        }
        with client.app.state.database.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM grade_snapshots").fetchone()[0] == 0


def test_weak_submission_creates_pending_replan_without_automatic_model_call(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        answers = seed_assessment_pool(client, node)
        assessment = start_assessment(
            client,
            workspace["id"],
            node["id"],
            "assessment-start-weak",
        )
        wrong = {question_id: "definitely wrong" for question_id in answers}
        calls: list[str] = []
        original = client.app.state.learning.provider.generate

        def counted(*args: object, **kwargs: Any) -> object:
            calls.append(str(kwargs["role"]))
            return original(*args, **kwargs)

        client.app.state.learning.provider.generate = counted
        response = submit_assessment(
            client,
            workspace["id"],
            assessment,
            wrong,
            "assessment-submit-weak",
        )
        assert response.status_code == 200, response.text
        assert response.json()["raw_score"] == 0
        assert calls == []
        with client.app.state.database.connect() as connection:
            trigger = connection.execute(
                "SELECT status,trigger_kind,performance_evidence_ids_json "
                "FROM learning_replan_triggers"
            ).fetchone()
        assert trigger["status"] == "PENDING"
        assert trigger["trigger_kind"] == "ASSESSMENT_WEAKNESS"
        assert len(json.loads(trigger["performance_evidence_ids_json"])) == 5


def test_pending_weakness_replans_only_on_next_explicit_teaching_action(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        answers = seed_assessment_pool(client, node)
        base = f"/api/learning/workspaces/{workspace['id']}"
        learned = client.post(
            base + "/units",
            json={
                "operation_id": "teach-before-assessment",
                "revision": current_revision(client, workspace["id"]),
                "node_id": node["id"],
            },
        )
        assert learned.status_code == 200, learned.text
        assert learned.json()["progress"] == "LEARNED"
        assessment = start_assessment(
            client,
            workspace["id"],
            node["id"],
            "assessment-start-remediation",
        )
        wrong = {question_id: "wrong" for question_id in answers}
        calls: list[str] = []
        original = client.app.state.learning.provider.generate

        def counted(*args: object, **kwargs: Any) -> object:
            calls.append(str(kwargs["role"]))
            return original(*args, **kwargs)

        client.app.state.learning.provider.generate = counted
        graded = submit_assessment(
            client,
            workspace["id"],
            assessment,
            wrong,
            "assessment-submit-remediation",
        )
        assert graded.status_code == 200, graded.text
        assert calls == []
        remediated = client.post(
            base + "/units",
            json={
                "operation_id": "teach-triggered-remediation",
                "revision": current_revision(client, workspace["id"]),
                "node_id": node["id"],
            },
        )
        assert remediated.status_code == 200, remediated.text
        assert remediated.json()["progress"] == "LEARNED"
        assert len(remediated.json()["remediation_trigger_ids"]) == 1
        assert calls == ["planner", "teacher"]
        with client.app.state.database.connect() as connection:
            trigger = connection.execute(
                "SELECT id,status,applied_at FROM learning_replan_triggers"
            ).fetchone()
            plan_link = connection.execute(
                "SELECT plan_version_id,trigger_id "
                "FROM teaching_plan_performance_triggers"
            ).fetchone()
            remediation = connection.execute(
                "SELECT trigger_id,teaching_unit_id FROM teaching_unit_remediations"
            ).fetchone()
        assert trigger["status"] == "APPLIED"
        assert trigger["applied_at"] is not None
        assert plan_link["trigger_id"] == trigger["id"]
        assert remediation["trigger_id"] == trigger["id"]


def test_open_response_uses_versioned_grader_and_backend_recomputes_marks(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        answers = seed_assessment_pool(client, node, include_open=True)
        assessment = start_assessment(
            client,
            workspace["id"],
            node["id"],
            "assessment-start-open",
        )
        response = submit_assessment(
            client,
            workspace["id"],
            assessment,
            answers,
            "assessment-submit-open",
        )
        assert response.status_code == 200, response.text
        assert response.json()["raw_score"] == 100
        with client.app.state.database.connect() as connection:
            run = connection.execute(
                "SELECT role,template_version,schema_version,status "
                "FROM learning_model_run_evidence WHERE role='grader'"
            ).fetchone()
        assert tuple(run) == ("grader", "assessment-v3.2", "v3.2", "COMPLETED")


def test_pool_excludes_foreign_private_questions_and_problem_answers_already_seen(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        base = f"/api/learning/workspaces/{workspace['id']}"
        solved = client.post(
            base + "/solutions",
            json={
                "operation_id": "solve-before-assessment-pool",
                "revision": current_revision(client, workspace["id"]),
                "question": "What is 2 + 3?",
                "node_ids": [node["id"]],
            },
        )
        assert solved.status_code == 200, solved.text
        seed_assessment_pool(client, node)
        with client.app.state.database.connect() as connection:
            problem_revision_id = connection.execute(
                "SELECT id FROM problem_revisions WHERE workspace_id=?",
                (workspace["id"],),
            ).fetchone()[0]
            for question_id, owner, source_problem_revision_id in (
                ("aq_answer_exposed", "a", problem_revision_id),
                ("aq_foreign_private", "b", None),
            ):
                answer = {"value": 5, "tolerance": 0}
                connection.execute(
                    "INSERT INTO assessment_question_revisions("
                    "id,course_id,owner_user_id,family_id,revision,source_kind,"
                    "source_problem_revision_id,question_type,difficulty,prompt_text,"
                    "options_json,answer_json,validation_status,verification_method,"
                    "content_hash,created_by_user_id) "
                    "VALUES(?,?,?,?,1,'MODEL_GENERATED',?,'NUMERIC',1,?, '[]',?,"
                    "'VALIDATED','DETERMINISTIC',?,?)",
                    (
                        question_id,
                        "cs3481",
                        owner,
                        "aaa_" + question_id,
                        source_problem_revision_id,
                        "Calculate the already exposed result.",
                        json.dumps(answer),
                        hashlib.sha256(question_id.encode()).hexdigest(),
                        owner,
                    ),
                )
                connection.execute(
                    "INSERT INTO assessment_rubric_criteria("
                    "question_revision_id,criterion_id,node_id,spec_version,item_id,"
                    "dimension,max_fraction,description,deterministic_rule_json) "
                    "VALUES(?,'correctness',?,1,'principle','CALCULATION',100,?, '{}')",
                    (question_id, node["id"], "Checks the result."),
                )
        assessment = start_assessment(
            client,
            workspace["id"],
            node["id"],
            "assessment-start-private-pool",
        )
        selected = {
            question["question_revision_id"] for question in assessment["questions"]
        }
        assert "aq_answer_exposed" not in selected
        assert "aq_foreign_private" not in selected


def test_grade_policy_requires_complete_admin_configuration_and_stays_versioned(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        seed_assessment_pool(client, node)
        pinned_before_publish = start_assessment(
            client,
            workspace["id"],
            node["id"],
            "assessment-start-before-policy",
        )
        incomplete = {
            "scope_type": "COURSE",
            "scope_id": "cs3481",
            "display_name": "Owner draft with source gaps",
            "provenance_label": "User supplied mapping draft",
            "numeric_scale": [
                {"letter": "A+", "numeric_value": 4.3},
                {"letter": "A-", "numeric_value": None},
            ],
            "raw_score_bands": [],
            "rounding_rule": None,
            "pass_rule": None,
            "retake_rule": None,
        }
        forbidden = client.post("/api/learning/grade-policies", json=incomplete)
        assert forbidden.status_code == 403
        client.headers["Authorization"] = "Bearer admin"
        created = client.post("/api/learning/grade-policies", json=incomplete)
        assert created.status_code == 200, created.text
        draft = created.json()
        assert draft["status"] == "DRAFT_UNCONFIGURED"
        assert next(
            item for item in draft["numeric_scale"] if item["letter"] == "A-"
        )["numeric_value"] is None
        preview = client.post(
            f"/api/learning/grade-policies/{draft['id']}/preview",
            json={"raw_score": 88},
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["mapping_status"] == "UNCONFIGURED"
        assert preview.json()["label"] is None
        assert (
            client.post(f"/api/learning/grade-policies/{draft['id']}/publish").status_code
            == 409
        )
        misleading = {**incomplete, "provenance_label": "CityU official policy"}
        assert client.post("/api/learning/grade-policies", json=misleading).status_code == 422

        configured = {
            **incomplete,
            "display_name": "Course owner configured learning scale",
            "provenance_label": "Owner supplied learning scale; not institutional",
            "numeric_scale": [
                {"letter": "A", "numeric_value": 4.0},
                {"letter": "B", "numeric_value": 3.0},
                {"letter": "F", "numeric_value": 0.0},
            ],
            "raw_score_bands": [
                {"minimum": 80, "maximum": 100, "letter": "A"},
                {"minimum": 50, "maximum": 79, "letter": "B"},
                {"minimum": 0, "maximum": 49, "letter": "F"},
            ],
            "rounding_rule": "NEAREST_INTEGER",
        }
        valid = client.post("/api/learning/grade-policies", json=configured)
        assert valid.status_code == 200, valid.text
        assert valid.json()["version"] == 2
        assert valid.json()["status"] == "DRAFT_VALID"
        preview = client.post(
            f"/api/learning/grade-policies/{valid.json()['id']}/preview",
            json={"raw_score": 85},
        ).json()
        assert (preview["label"], preview["numeric_value"]) == ("A", 4.0)
        published = client.post(
            f"/api/learning/grade-policies/{valid.json()['id']}/publish"
        )
        assert published.status_code == 200, published.text
        assert published.json()["status"] == "PUBLISHED"

        client.headers["Authorization"] = "Bearer a"
        pinned_result = submit_assessment(
            client,
            workspace["id"],
            pinned_before_publish,
            seed_assessment_pool_answers_only(),
            "assessment-submit-before-policy",
        )
        assert pinned_result.status_code == 200, pinned_result.text
        assert pinned_result.json()["grade"]["mapping_status"] == "UNCONFIGURED"
        assessment = start_assessment(
            client,
            workspace["id"],
            node["id"],
            "assessment-start-policy",
        )
        result = submit_assessment(
            client,
            workspace["id"],
            assessment,
            seed_assessment_pool_answers_only(),
            "assessment-submit-policy",
        )
        assert result.status_code == 200, result.text
        assert result.json()["grade"]["mapping_status"] == "CONFIGURED"
        assert result.json()["grade"]["label"] == "A"
        assert result.json()["grade"]["numeric_value"] == 4.0


def test_uncertain_open_response_stays_needs_review_and_is_not_scored_as_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        answers = seed_assessment_pool(client, node, include_open=True)
        assessment = start_assessment(
            client,
            workspace["id"],
            node["id"],
            "assessment-start-needs-review",
        )

        def uncertain_fixture(schema: str, context: dict[str, Any]) -> dict[str, Any]:
            assert schema == "AssessmentGradeProposal"
            return {
                "schema_version": "v3.2",
                "questions": [
                    {
                        "blueprint_item_id": question["blueprint_item_id"],
                        "criteria": [
                            {
                                "criterion_id": criterion["criterion_id"],
                                "score_fraction": 0.5,
                                "answer_evidence": "submitted_answer",
                                "feedback": "Manual review is required for this response.",
                                "confidence": 0.2,
                                "needs_review": True,
                            }
                            for criterion in question["rubric"]
                        ],
                    }
                    for question in context["questions"]
                ],
                "uncertainties": ["Synthetic uncertainty fixture"],
            }

        monkeypatch.setattr("app.learning.testing.fixture_output", uncertain_fixture)
        response = submit_assessment(
            client,
            workspace["id"],
            assessment,
            answers,
            "assessment-submit-needs-review",
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "SUBMITTED"
        assert response.json()["raw_score"] is None
        projected = next(
            item
            for item in client.get(
                f"/api/learning/workspaces/{workspace['id']}/knowledge"
            ).json()["registry"]
            if item["id"] == node["id"]
        )
        assert projected["state"]["assessment"]["status"] == "NEEDS_REVIEW"
        assert projected["state"]["assessment"]["raw_score"] is None
        with client.app.state.database.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM grade_snapshots").fetchone()[0] == 0


def seed_assessment_pool_answers_only(prefix: str = "") -> dict[str, str]:
    return {
        prefix + "aq_official_mcq": "1",
        prefix + "aq_private_numeric": "7",
        prefix + "aq_model_short": "two",
        prefix + "aq_external_numeric": "9",
        prefix + "aq_official_second": "0",
    }


def test_composite_assessment_aggregates_only_unique_independent_atomic_results(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, first = setup_workspace(client)
        base = f"/api/learning/workspaces/{workspace['id']}"
        second_response = client.post(
            base + "/nodes",
            json={
                "title": "Second atomic topic",
                "description": "Another bounded addition topic",
                "major": "CS",
                "kind": "ATOMIC",
                "items": [
                    {
                        "item_id": "principle",
                        "requirement": "REQUIRED",
                        "objective": "Explain another addition case",
                        "acceptance": "Calculate and explain the result",
                        "evidence_ids": [],
                    }
                ],
            },
        )
        assert second_response.status_code == 200, second_response.text
        second = second_response.json()
        composite_response = client.post(
            base + "/nodes",
            json={
                "title": "Addition chapter",
                "description": "Composite of two atomic topics",
                "major": "CS",
                "kind": "COMPOSITE",
                "items": [],
            },
        )
        assert composite_response.status_code == 200, composite_response.text
        composite = composite_response.json()
        plan = client.post(
            base + "/plans",
            json={
                "operation_id": "personal-plan-assessment-aggregate",
                "revision": current_revision(client, workspace["id"]),
                "title": "Assessment aggregate plan",
                "change_reason": "Verify unique atomic aggregation",
                "memberships": [
                    {
                        "node_id": composite["id"],
                        "parent_node_id": None,
                        "ordinal": 0,
                        "spec_version": None,
                    },
                    {
                        "node_id": first["id"],
                        "parent_node_id": composite["id"],
                        "ordinal": 0,
                        "spec_version": 1,
                    },
                    {
                        "node_id": second["id"],
                        "parent_node_id": composite["id"],
                        "ordinal": 1,
                        "spec_version": 1,
                    },
                ],
                "prerequisites": [],
            },
        )
        assert plan.status_code == 200, plan.text
        first_answers = seed_assessment_pool(client, first, prefix="first_")
        second_answers = seed_assessment_pool(client, second, prefix="second_")

        first_assessment = start_assessment(
            client,
            workspace["id"],
            first["id"],
            "assessment-start-first-aggregate",
        )
        first_result = submit_assessment(
            client,
            workspace["id"],
            first_assessment,
            first_answers,
            "assessment-submit-first-aggregate",
        )
        assert first_result.status_code == 200, first_result.text
        knowledge = client.get(base + "/knowledge").json()
        members = {
            member["node_id"]: member
            for member in knowledge["personalized_tree"]["members"]
        }
        aggregate = members[composite["id"]]["state"]["assessment"]
        assert aggregate["status"] == "PARTIALLY_ASSESSED"
        assert aggregate["raw_score"] == 100
        assert aggregate["assessed_atomic_count"] == 1
        assert aggregate["atomic_descendant_count"] == 2

        second_assessment = start_assessment(
            client,
            workspace["id"],
            second["id"],
            "assessment-start-second-aggregate",
        )
        wrong = {question_id: "wrong" for question_id in second_answers}
        second_result = submit_assessment(
            client,
            workspace["id"],
            second_assessment,
            wrong,
            "assessment-submit-second-aggregate",
        )
        assert second_result.status_code == 200, second_result.text
        knowledge = client.get(base + "/knowledge").json()
        members = {
            member["node_id"]: member
            for member in knowledge["personalized_tree"]["members"]
        }
        aggregate = members[composite["id"]]["state"]["assessment"]
        assert aggregate["status"] == "GRADED"
        assert aggregate["raw_score"] == 50
        assert aggregate["assessed_atomic_count"] == 2
