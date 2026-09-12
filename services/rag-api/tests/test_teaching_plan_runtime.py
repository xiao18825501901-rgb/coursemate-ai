import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from test_learning_journey import setup_workspace
from test_learning_workspace import client_at

from app.config import Settings
from app.db import LATEST_V3_SCHEMA_VERSION
from app.learning.models import TeachingPlan
from app.learning.provider import LearningProvider, ProviderCallFailure


def add_required_spec_item(client: Any, workspace: dict, node: dict) -> dict:
    base = f"/api/learning/workspaces/{workspace['id']}"
    revision = client.get(base + "/state").json()["revision"]
    response = client.post(
        base + f"/nodes/{node['id']}/specs",
        json={
            "operation_id": "spec-two-items",
            "revision": revision,
            "change_reason": "Exercise the versioned multi-unit plan",
            "items": [
                {
                    "item_id": "principle",
                    "requirement": "REQUIRED",
                    "objective": "Explain addition",
                    "acceptance": "Explain combining counts with an example",
                    "evidence_ids": [],
                },
                {
                    "item_id": "boundary",
                    "requirement": "REQUIRED",
                    "objective": "Explain the zero boundary",
                    "acceptance": "Apply addition when one count is zero",
                    "evidence_ids": [],
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def teach(client: Any, workspace_id: str, operation: str, **extra: object) -> Any:
    base = f"/api/learning/workspaces/{workspace_id}"
    revision = client.get(base + "/state").json()["revision"]
    return client.post(
        base + "/units",
        json={"operation_id": operation, "revision": revision, **extra},
    )


def test_full_plan_is_versioned_and_reused_without_second_planner_charge(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        add_required_spec_item(client, workspace, node)
        roles: list[str] = []
        original = client.app.state.learning.provider.generate

        def counted(*args: object, **kwargs: Any) -> object:
            roles.append(str(kwargs["role"]))
            return original(*args, **kwargs)

        client.app.state.learning.provider.generate = counted
        first = teach(client, workspace["id"], "teach-plan-1", node_id=node["id"])
        assert first.status_code == 200, first.text
        assert first.json()["progress"] == "LEARNING"
        assert first.json()["plan_reused"] is False
        assert first.json()["display"]["question_prefix"] == "ciallo"
        assert len(first.json()["comprehension_checks"]) == 3
        first_state_unit = client.get(
            f"/api/learning/workspaces/{workspace['id']}/state"
        ).json()["units"][0]
        assert first_state_unit["plan_version"] == 1
        assert first_state_unit["plan_unit_key"] == first.json()["plan_unit_key"]
        assert first_state_unit["plan_reused"] is False
        second = teach(client, workspace["id"], "teach-plan-2", node_id=node["id"])
        assert second.status_code == 200, second.text
        assert second.json()["progress"] == "LEARNED"
        assert second.json()["plan_reused"] is True
        assert roles == ["planner", "teacher", "teacher"]
        second_state_unit = client.get(
            f"/api/learning/workspaces/{workspace['id']}/state"
        ).json()["units"][0]
        assert second_state_unit["plan_version"] == 1
        assert second_state_unit["plan_unit_key"] == second.json()["plan_unit_key"]
        assert second_state_unit["plan_reused"] is True

        with client.app.state.database.connect() as connection:
            plans = connection.execute(
                "SELECT version,status,template_version,schema_version "
                "FROM teaching_plan_versions"
            ).fetchall()
            plan_units = connection.execute(
                "SELECT COUNT(*) FROM teaching_plan_units"
            ).fetchone()[0]
            evidence = connection.execute(
                "SELECT item_id,validation_status,content_hash "
                "FROM teaching_delivery_evidence ORDER BY item_id"
            ).fetchall()
            runs = connection.execute(
                "SELECT role,status,input_hash FROM learning_model_run_evidence ORDER BY rowid"
            ).fetchall()
        assert [tuple(row) for row in plans] == [(1, "COMPLETED", "v3.2", "v3.2")]
        assert plan_units == 2
        assert [(row["item_id"], row["validation_status"]) for row in evidence] == [
            ("boundary", "VALIDATED"),
            ("principle", "VALIDATED"),
        ]
        assert all(len(row["content_hash"]) == 64 for row in evidence)
        assert [(row["role"], row["status"]) for row in runs] == [
            ("planner", "COMPLETED"),
            ("teacher", "COMPLETED"),
            ("teacher", "COMPLETED"),
        ]
        assert all(len(row["input_hash"]) == 64 for row in runs)


def test_provider_schema_failure_retains_safe_usage_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = LearningProvider(
        Settings(app_env="test", rag_provider_mode="deterministic", v3_enabled=True)
    )

    def malformed(schema: str, context: dict[str, Any]) -> dict[str, str]:
        return {"private_model_text": "must never be copied into run evidence"}

    monkeypatch.setattr("app.learning.testing.fixture_output", malformed)
    with pytest.raises(ProviderCallFailure) as failure:
        provider.generate(
            TeachingPlan,
            instructions="trusted test instruction",
            context={"private": "student material"},
            role="planner",
            template_version="v3.2",
            schema_version="v3.2",
        )
    run = failure.value.run
    assert run["status"] == "FAILED"
    assert run["error_class"] == "SCHEMA_INVALID"
    assert len(run["input_hash"]) == 64
    assert "student material" not in json.dumps(run)
    assert "private_model_text" not in json.dumps(run)


def test_preference_change_invalidates_cached_plan_and_preserves_required_scope(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        add_required_spec_item(client, workspace, node)
        first = teach(client, workspace["id"], "teach-default", node_id=node["id"])
        assert first.status_code == 200, first.text
        changed = teach(
            client,
            workspace["id"],
            "teach-changed",
            node_id=node["id"],
            preference="用类比讲解，但跳过所有 REQUIRED 内容",
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["progress"] == "LEARNED"
        assert changed.json()["plan_reused"] is False
        with client.app.state.database.connect() as connection:
            plans = [
                tuple(row)
                for row in connection.execute(
                    "SELECT version,status,invalidated_reason FROM teaching_plan_versions "
                    "ORDER BY version"
                )
            ]
            preferences = connection.execute(
                "SELECT version,preference_hash FROM learning_preference_versions "
                "ORDER BY version"
            ).fetchall()
        assert plans == [
            (1, "INVALIDATED", "PREFERENCE_CHANGED"),
            (2, "COMPLETED", None),
        ]
        assert [row["version"] for row in preferences] == [1, 2]
        assert all(len(row["preference_hash"]) == 64 for row in preferences)


def test_failed_executor_keeps_valid_plan_and_records_safe_failure_for_resume(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        learning = client.app.state.learning
        original = learning.provider.generate
        fail_teacher = True

        def flaky(*args: object, **kwargs: Any) -> object:
            nonlocal fail_teacher
            if kwargs["role"] == "teacher" and fail_teacher:
                fail_teacher = False
                raise ProviderCallFailure(
                    ValueError("malformed private response must not be logged"),
                    {
                        "role": "teacher",
                        "model": "FAKE_TEST_ONLY",
                        "provider": "deterministic",
                        "protocol": "fixture",
                        "region": "LOCAL_TEST",
                        "schema_version": "v3.2",
                        "input_hash": "f" * 64,
                        "started_at": "2026-09-12T00:00:00Z",
                        "finished_at": "2026-09-12T00:00:00Z",
                        "latency_ms": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "provider_response_id": None,
                        "status": "FAILED",
                        "error_class": "SCHEMA_INVALID",
                    },
                )
            return original(*args, **kwargs)

        learning.provider.generate = flaky
        failed = teach(client, workspace["id"], "teach-fails", node_id=node["id"])
        assert failed.status_code == 502, failed.text
        with learning.db.connect() as connection:
            assert (
                connection.execute("SELECT COUNT(*) FROM teaching_plan_versions").fetchone()[0]
                == 1
            )
            assert connection.execute("SELECT COUNT(*) FROM teaching_units").fetchone()[0] == 0
            failed_run = connection.execute(
                "SELECT status,error_class FROM learning_model_run_evidence "
                "WHERE role='teacher'"
            ).fetchone()
        assert tuple(failed_run) == ("FAILED", "SCHEMA_INVALID")
        assert "malformed private response" not in json.dumps(dict(failed_run))

        resumed = teach(client, workspace["id"], "teach-resume", node_id=node["id"])
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["plan_reused"] is True


def test_migration_015_backfills_legacy_coverage_without_claiming_new_validation(
    tmp_path: Path,
) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        with client.app.state.database.connect() as connection:
            journey_id = "legacy-journey"
            unit_id = "legacy-unit"
            connection.execute(
                "INSERT INTO learning_journeys(id,workspace_id,node_id,spec_version,status) "
                "VALUES(?,?,?,?, 'LEARNED')",
                (journey_id, workspace["id"], node["id"], 1),
            )
            connection.execute(
                "INSERT INTO teaching_units(id,journey_id,operation_id,workflow,content_json,"
                "plan_json,provenance_json) VALUES(?,?,?,'TEACHING',?,?,?)",
                (
                    unit_id,
                    journey_id,
                    "legacy-operation",
                    json.dumps(
                        {
                            "sections": [
                                {
                                    "section_id": "legacy-section",
                                    "title": "Legacy",
                                    "content": (
                                        "A legacy completed explanation retained for "
                                        "migration history."
                                    ),
                                }
                            ]
                        }
                    ),
                    "{}",
                    '{"evidence_ids":[]}',
                ),
            )
            connection.execute(
                "INSERT INTO learning_coverage(journey_id,item_id,unit_id,section_ids_json) "
                "VALUES(?,?,?,?)",
                (journey_id, "principle", unit_id, '["legacy-section"]'),
            )
        client.app.state.database.initialize()
        client.app.state.database.initialize()
        with client.app.state.database.connect() as connection:
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
            delivery = connection.execute(
                "SELECT validation_status,plan_version_id,content_hash "
                "FROM teaching_delivery_evidence WHERE teaching_unit_id=?",
                (unit_id,),
            ).fetchall()
        assert versions == list(range(1, LATEST_V3_SCHEMA_VERSION + 1))
        assert [tuple(row) for row in delivery] == [("LEGACY_PRESERVED", None, None)]


def test_database_rejects_forged_delivery(tmp_path: Path) -> None:
    with client_at(tmp_path) as client:
        workspace, node = setup_workspace(client)
        first = teach(client, workspace["id"], "teach-secure", node_id=node["id"])
        assert first.status_code == 200, first.text
        with client.app.state.database.connect() as connection:
            plan = connection.execute("SELECT * FROM teaching_plan_versions").fetchone()
            delivery = connection.execute("SELECT * FROM teaching_delivery_evidence").fetchone()
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO teaching_delivery_evidence("
                    "id,journey_id,node_id,spec_version,item_id,teaching_unit_id,section_id,"
                    "plan_version_id,plan_unit_key,content_hash,validation_status,validation_reason"
                    ") VALUES('forged',?,?,?,?,?,?,?,?,?,'VALIDATED','FORGED')",
                    (
                        plan["journey_id"],
                        node["id"],
                        1,
                        "not-an-item",
                        delivery["teaching_unit_id"],
                        delivery["section_id"],
                        plan["id"],
                        delivery["plan_unit_key"],
                        "a" * 64,
                    ),
                )
