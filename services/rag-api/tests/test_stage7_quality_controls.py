import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_learning_workspace import Identity

from app.config import Settings
from app.db import LATEST_V3_SCHEMA_VERSION
from app.main import create_app

MAJOR_EXPECTATIONS = {
    "CS": "数据与表示",
    "SMART_MANUFACTURING": "物料、能量与信息流",
    "MATERIALS": "结构与微观组织",
    "ENERGY": "质量/能量守恒",
}


def configured_client(path: Path, **overrides: object) -> TestClient:
    values: dict[str, object] = {
        "database_path": path / "rag.db",
        "upload_dir": path / "uploads",
        "app_env": "test",
        "rag_provider_mode": "deterministic",
        "admin_user_ids": "admin",
        "v3_enabled": True,
    }
    values.update(overrides)
    return TestClient(
        create_app(
            settings=Settings.model_validate(values),
            auth_verifier=Identity(),
        )
    )


def create_workspace_node(
    client: TestClient,
    *,
    owner: str,
    course_id: str,
    major: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    client.headers["Authorization"] = "Bearer admin"
    created = client.post(
        "/api/courses",
        json={"id": course_id, "name": f"Stage 7 {major}"},
    )
    assert created.status_code == 201, created.text
    client.headers["Authorization"] = "Bearer " + owner
    workspace_response = client.post(
        "/api/learning/workspaces",
        json={"course_id": course_id},
    )
    assert workspace_response.status_code == 200, workspace_response.text
    workspace = workspace_response.json()
    node_response = client.post(
        f"/api/learning/workspaces/{workspace['id']}/nodes",
        json={
            "title": f"{major} bounded concept",
            "description": "A synthetic, non-course Stage 7 teaching contract fixture.",
            "major": major,
            "kind": "ATOMIC",
            "items": [
                {
                    "item_id": "required_concept",
                    "requirement": "REQUIRED",
                    "objective": "Explain the bounded concept",
                    "acceptance": "Give an accurate explanation and a checkable example",
                    "evidence_ids": [],
                }
            ],
        },
    )
    assert node_response.status_code == 200, node_response.text
    return workspace, node_response.json()


@pytest.mark.parametrize("major", list(MAJOR_EXPECTATIONS))
@pytest.mark.parametrize(
    ("preference", "expected_case", "language"),
    [
        ("", "CASE_A", "zh-CN"),
        ("STAGE7_USER_PREFERENCE_NONCE: use one analogy", "CASE_B", "bilingual"),
    ],
)
def test_four_major_case_matrix_reaches_persisted_learning_state(
    tmp_path: Path,
    major: str,
    preference: str,
    expected_case: str,
    language: str,
) -> None:
    case_path = tmp_path / f"{major.lower()}-{expected_case.lower()}"
    captured: list[dict[str, Any]] = []
    with configured_client(case_path) as client:
        course_id = (
            f"stage7-{major.lower().replace('_', '-')}-{expected_case.lower().replace('_', '-')}"
        )
        workspace, node = create_workspace_node(
            client,
            owner="a",
            course_id=course_id,
            major=major,
        )
        learning = client.app.state.learning
        original_generate = learning.provider.generate

        def capture(*args: object, **kwargs: Any) -> object:
            captured.append(
                {
                    "schema": args[0].__name__,
                    "role": kwargs["role"],
                    "instructions": kwargs["instructions"],
                    "context": kwargs["context"],
                }
            )
            return original_generate(*args, **kwargs)

        learning.provider.generate = capture
        base = f"/api/learning/workspaces/{workspace['id']}"
        revision = client.get(base + "/state").json()["revision"]
        response = client.post(
            base + "/units",
            json={
                "operation_id": f"teach-{major.lower()}-{expected_case.lower()}",
                "revision": revision,
                "node_id": node["id"],
                "preference": preference,
                "language": language,
            },
        )
        assert response.status_code == 200, response.text
        unit = response.json()
        assert unit["progress"] == "LEARNED"
        assert unit["grade"] == "NOT_ASSESSED"
        assert unit["plan_reused"] is False
        assert len(unit["comprehension_checks"]) in range(3, 6)

        assert [(call["schema"], call["role"]) for call in captured] == [
            ("TeachingPlan", "planner"),
            ("TeachingUnitOutput", "teacher"),
        ]
        planner = captured[0]
        teacher = captured[1]
        assert planner["context"]["major_policy"] == major
        assert planner["context"]["language"] == language
        assert planner["context"]["preference"] == preference
        assert f"MAJOR_POLICY_{major}" in teacher["instructions"]
        assert MAJOR_EXPECTATIONS[major] in teacher["instructions"]
        assert "STAGE7_USER_PREFERENCE_NONCE" not in teacher["instructions"]

        with learning.db.connect() as connection:
            plan = connection.execute(
                "SELECT case_type,plan_json,status FROM teaching_plan_versions"
            ).fetchone()
            runs = connection.execute(
                "SELECT role,status,model_id,protocol FROM learning_model_run_evidence "
                "ORDER BY rowid"
            ).fetchall()
            delivery_count = connection.execute(
                "SELECT COUNT(*) FROM teaching_delivery_evidence "
                "WHERE validation_status='VALIDATED'"
            ).fetchone()[0]
        assert plan["case_type"] == expected_case
        assert json.loads(plan["plan_json"])["case_type"] == expected_case
        assert plan["status"] == "COMPLETED"
        assert delivery_count == 1
        assert [tuple(run) for run in runs] == [
            ("planner", "COMPLETED", "FAKE_TEST_ONLY", "fixture"),
            ("teacher", "COMPLETED", "FAKE_TEST_ONLY", "fixture"),
        ]

    with configured_client(case_path) as restarted:
        restarted.headers["Authorization"] = "Bearer a"
        state = restarted.get(base + "/state")
        assert state.status_code == 200, state.text
        assert state.json()["nodes"][0]["progress"] == "LEARNED"
        assert state.json()["nodes"][0]["assessment"]["status"] == "NOT_ASSESSED"


def test_model_call_quota_is_reserved_before_a_second_provider_call(tmp_path: Path) -> None:
    with configured_client(
        tmp_path,
        v3_daily_model_calls_per_user=1,
        v3_daily_model_calls_per_user_course=1,
    ) as client:
        workspace, node = create_workspace_node(
            client,
            owner="a",
            course_id="stage7-quota",
            major="CS",
        )
        base = f"/api/learning/workspaces/{workspace['id']}"
        learning = client.app.state.learning
        roles: list[str] = []
        original_generate = learning.provider.generate

        def counted(*args: object, **kwargs: Any) -> object:
            roles.append(str(kwargs["role"]))
            return original_generate(*args, **kwargs)

        learning.provider.generate = counted
        first_revision = client.get(base + "/state").json()["revision"]
        first = client.post(
            base + "/solutions",
            json={
                "operation_id": "quota-first",
                "revision": first_revision,
                "question": "2 + 3",
                "node_ids": [node["id"]],
            },
        )
        assert first.status_code == 200, first.text
        second_revision = client.get(base + "/state").json()["revision"]
        blocked = client.post(
            base + "/solutions",
            json={
                "operation_id": "quota-blocked",
                "revision": second_revision,
                "question": "2 + 3",
                "node_ids": [node["id"]],
            },
        )
        assert blocked.status_code == 429, blocked.text
        assert blocked.json()["error"]["code"] == "DAILY_MODEL_CALL_QUOTA"
        assert roles == ["problem"]

        with learning.db.connect() as connection:
            reservations = connection.execute(
                "SELECT owner_user_id,course_id,role,status,input_tokens,output_tokens "
                "FROM learning_model_call_reservations"
            ).fetchall()
            operations = connection.execute(
                "SELECT id,status FROM learning_operations ORDER BY created_at,id"
            ).fetchall()
        assert [tuple(row) for row in reservations] == [
            ("a", "stage7-quota", "problem", "COMPLETED", 0, 0)
        ]
        assert {tuple(row) for row in operations} >= {
            ("quota-first", "COMPLETED"),
            ("quota-blocked", "FAILED"),
        }


def test_model_call_quotas_are_separate_per_owner_course_and_global_per_owner(
    tmp_path: Path,
) -> None:
    with configured_client(
        tmp_path,
        v3_daily_model_calls_per_user=2,
        v3_daily_model_calls_per_user_course=1,
    ) as client:
        workspaces = [
            create_workspace_node(
                client,
                owner="a",
                course_id=f"stage7-budget-{suffix}",
                major="CS",
            )
            for suffix in ("one", "two", "three")
        ]
        provider_calls = 0
        original_generate = client.app.state.learning.provider.generate

        def counted(*args: object, **kwargs: Any) -> object:
            nonlocal provider_calls
            provider_calls += 1
            return original_generate(*args, **kwargs)

        client.app.state.learning.provider.generate = counted

        def solve(index: int, operation: str) -> Any:
            workspace, node = workspaces[index]
            base = f"/api/learning/workspaces/{workspace['id']}"
            revision = client.get(base + "/state").json()["revision"]
            return client.post(
                base + "/solutions",
                json={
                    "operation_id": operation,
                    "revision": revision,
                    "question": "2 + 3",
                    "node_ids": [node["id"]],
                },
            )

        assert solve(0, "course-one-first").status_code == 200
        same_course = solve(0, "course-one-second")
        assert same_course.status_code == 429
        assert same_course.json()["error"]["code"] == "DAILY_MODEL_CALL_QUOTA"
        assert solve(1, "course-two-first").status_code == 200
        owner_total = solve(2, "course-three-first")
        assert owner_total.status_code == 429
        assert owner_total.json()["error"]["code"] == "DAILY_MODEL_CALL_QUOTA"
        assert provider_calls == 2

        with client.app.state.learning.db.connect() as connection:
            rows = connection.execute(
                "SELECT course_id,status FROM learning_model_call_reservations "
                "ORDER BY course_id"
            ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("stage7-budget-one", "COMPLETED"),
            ("stage7-budget-two", "COMPLETED"),
        ]


def test_pre_provider_configuration_failures_do_not_consume_the_model_call_quota(
    tmp_path: Path,
) -> None:
    with configured_client(
        tmp_path,
        app_env="development",
        rag_provider_mode="openai",
        v3_daily_model_calls_per_user=1,
        v3_daily_model_calls_per_user_course=1,
    ) as client:
        workspace, node = create_workspace_node(
            client,
            owner="a",
            course_id="stage7-blocked-provider",
            major="CS",
        )
        base = f"/api/learning/workspaces/{workspace['id']}"
        # Keep this test on the V3 provider gate: legacy RAG retrieval has its own
        # independently configured model adapter and is covered elsewhere.
        client.app.state.learning.evidence = lambda *_args, **_kwargs: []

        for operation in ("blocked-provider-one", "blocked-provider-two"):
            response = client.post(
                base + "/solutions",
                json={
                    "operation_id": operation,
                    "revision": client.get(base + "/state").json()["revision"],
                    "question": "2 + 3",
                    "node_ids": [node["id"]],
                },
            )
            assert response.status_code == 503, response.text
            assert response.json()["error"]["code"] == "MODEL_LIVE_BLOCKED"

        with client.app.state.learning.db.connect() as connection:
            statuses = [
                row[0]
                for row in connection.execute(
                    "SELECT status FROM learning_model_call_reservations ORDER BY created_at"
                )
            ]
        assert statuses == ["BLOCKED", "BLOCKED"]


def test_migration_021_backfills_existing_safe_model_run_evidence(tmp_path: Path) -> None:
    with configured_client(tmp_path) as client:
        workspace, node = create_workspace_node(
            client,
            owner="a",
            course_id="stage7-backfill",
            major="CS",
        )
        base = f"/api/learning/workspaces/{workspace['id']}"
        solved = client.post(
            base + "/solutions",
            json={
                "operation_id": "backfill-source-run",
                "revision": client.get(base + "/state").json()["revision"],
                "question": "2 + 3",
                "node_ids": [node["id"]],
            },
        )
        assert solved.status_code == 200, solved.text
        with client.app.state.learning.db.connect() as connection:
            connection.execute("DROP TABLE learning_model_call_reservations")
            connection.execute("DELETE FROM schema_migrations WHERE version=21")

        client.app.state.learning.db.initialize()
        client.app.state.learning.db.initialize()
        with client.app.state.learning.db.connect() as connection:
            reservation = connection.execute(
                "SELECT owner_user_id,course_id,role,status,input_tokens,output_tokens "
                "FROM learning_model_call_reservations"
            ).fetchone()
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
        assert tuple(reservation) == (
            "a",
            "stage7-backfill",
            "problem",
            "COMPLETED",
            0,
            0,
        )
        assert versions == list(range(1, LATEST_V3_SCHEMA_VERSION + 1))
