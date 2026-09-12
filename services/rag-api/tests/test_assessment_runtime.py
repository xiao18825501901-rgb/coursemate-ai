import hashlib
import json
from pathlib import Path
from typing import Any

from test_learning_journey import setup_workspace
from test_learning_workspace import client_at


def seed_assessment_pool(client: Any, node: dict[str, Any]) -> dict[str, str]:
    questions = [
        (
            "aq_official_mcq",
            "family_official_mcq",
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
            "aq_private_numeric",
            "family_private_numeric",
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
            "aq_model_short",
            "family_model_short",
            "MODEL_GENERATED",
            "a",
            "SHORT_TEXT",
            3,
            "Write the result of one plus one.",
            [],
            {"accepted": ["2", "two"], "case_sensitive": False},
            "DETERMINISTIC",
            "two",
        ),
        (
            "aq_external_numeric",
            "family_external_numeric",
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
            "aq_official_second",
            "family_official_second",
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
