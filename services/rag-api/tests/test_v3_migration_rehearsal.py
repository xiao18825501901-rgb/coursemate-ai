from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path
from types import ModuleType

import pytest

from app.config import Settings
from app.db import Database

REPOSITORY_ROOT = Path(__file__).parents[3]
REHEARSAL_SCRIPT = REPOSITORY_ROOT / "scripts" / "rehearse_v3_migration.py"


def _load_rehearsal_module() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "rehearse_v3_migration", REHEARSAL_SCRIPT
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _initialized_v3_database(path: Path, upload_dir: Path) -> None:
    Database(
        Settings(
            app_env="test",
            database_path=path,
            upload_dir=upload_dir,
            v3_enabled=True,
        )
    ).initialize()


def _seed_model_evidence_before_migration_21(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO courses(id,name,course_type,visibility,publication_status) "
            "VALUES('course','Course','official','public','published')"
        )
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,"
            "publication_status) VALUES('private','Private','owner','user','private','private')"
        )
        connection.execute(
            "INSERT INTO learning_workspaces(id,owner_user_id,course_id,private_course_id) "
            "VALUES('workspace','owner','course','private')"
        )
        connection.execute(
            "INSERT INTO learning_operations(workspace_id,id,request_hash,kind,status) "
            "VALUES('workspace','operation','request-hash','TEACHING','COMPLETED')"
        )
        connection.execute(
            "INSERT INTO learning_model_run_evidence("
            "id,workspace_id,operation_id,role,model_id,provider_label,protocol,"
            "region_label,template_version,schema_version,input_hash,started_at,"
            "finished_at,latency_ms,input_tokens,output_tokens,status) "
            "VALUES('evidence','workspace','operation','teacher','qwen3.8-max',"
            "'MODEL_STUDIO','responses','INTL','v3.2','v3.2',NULL,"
            "'2026-09-12T00:00:00Z','2026-09-12T00:00:01Z',1000,20,40,'COMPLETED')"
        )
        connection.execute("DROP TABLE learning_model_call_reservations")
        connection.execute("DELETE FROM schema_migrations WHERE version=21")


def test_rehearsal_proves_model_budget_backfill_and_governance_objects(
    tmp_path: Path,
) -> None:
    module = _load_rehearsal_module()
    module.WORK_ROOT = tmp_path / "work"
    source = tmp_path / "source.sqlite3"
    target = module.WORK_ROOT / "rehearsal"
    _initialized_v3_database(source, tmp_path / "uploads")
    _seed_model_evidence_before_migration_21(source)

    result = module.rehearse(source, target)

    invariants = result["v3_invariants"]
    assert result["v3_invariants_ok"] is True
    assert invariants["learning_model_run_evidence"] == 1
    assert invariants["learning_model_call_reservations"] == 1
    assert invariants["model_runs_without_budget_reservations"] == 0
    assert invariants["model_reservation_scope_mismatches"] == 0
    assert invariants["model_reservation_evidence_mismatches"] == 0
    assert invariants["missing_governance_schema_objects"] == []


def test_rehearsal_rejects_a_missing_required_governance_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_rehearsal_module()
    module.WORK_ROOT = tmp_path / "work"
    source = tmp_path / "source.sqlite3"
    target = module.WORK_ROOT / "rehearsal"
    _initialized_v3_database(source, tmp_path / "uploads")
    expected = module.expected_governance_schema_objects()
    monkeypatch.setattr(
        module,
        "expected_governance_schema_objects",
        lambda: expected | {("trigger", "required_missing_trigger")},
    )

    with pytest.raises(RuntimeError, match="Migration rehearsal failed"):
        module.rehearse(source, target)

    evidence = json.loads(
        target.joinpath("migration-evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["v3_invariants_ok"] is False
    assert (
        "trigger:required_missing_trigger"
        in evidence["v3_invariants"]["missing_governance_schema_objects"]
    )
