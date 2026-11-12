from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.config import Settings
from app.db import LATEST_V3_SCHEMA_VERSION, Database


def _database(tmp_path: Path) -> Database:
    return Database(
        Settings(
            app_name="coursejesus-test",
            app_env="test",
            database_path=tmp_path / "rag.sqlite3",
            upload_dir=tmp_path / "uploads",
            v3_enabled=True,
            rag_provider_mode="deterministic",
            ui_web_dir=tmp_path / "no-web-build",
        )
    )


def _simulate_schema_86_ledger_with_v63_receipt_table(database: Database) -> None:
    """Reproduce the deployed mismatch: ledger 86, pre-internal-workspace CHECK."""

    old_reasons = (
        "BACKGROUND_QUOTA_SCOPE_V1",
        "PER_SHARD_REPAIR_SCOPE_V1",
        "FINAL_DISPOSITION_NORMALIZATION_V1",
        "REPAIRED_ARTIFACT_REHYDRATION_V1",
        "LEGACY_REJECTION_FEEDBACK_REHYDRATION_V1",
        "STAGED_COURSE_WORKSPACE_V1",
        "REQUIRED_ITEM_REPAIR_V1",
        "BASE_PROMPT_HASH_RESTORE_V1",
        "UNIQUE_KEY_REPAIR_V1",
        "EVIDENCE_SCOPE_REPAIR_V1",
        "EVIDENCE_SCOPE_NORMALIZATION_V1",
        "EVIDENCE_SCOPE_NORMALIZATION_RETRY_V1",
        "EVIDENCE_SCOPE_RESUME_V1",
        "SPEC_SPLIT_RESUME_V1",
        "SPEC_SPLIT_SOURCE_REPLAY_V1",
    )
    reason_sql = ",".join(f"'{reason}'" for reason in old_reasons)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses("
            "id,name,course_type,visibility,publication_status"
            ") VALUES('legacy-course','Legacy Course','official','public','published')"
        )
        connection.execute(
            "INSERT INTO auto_knowledge_targets("
            "target_key,course_id,target_kind,status"
            ") VALUES('AUTO_COURSE:legacy-course','legacy-course','AUTO_COURSE','BLOCKED')"
        )
        connection.execute(
            "INSERT INTO auto_knowledge_jobs("
            "id,target_key,course_id,target_kind,corpus_fingerprint,builder_version,"
            "status,source_snapshot_json"
            ") VALUES('legacy-job','AUTO_COURSE:legacy-course','legacy-course',"
            "'AUTO_COURSE',?, 'legacy-builder','BLOCKED','{}')",
            ("a" * 64,),
        )
        connection.execute("DROP TRIGGER IF EXISTS immutable_auto_knowledge_recovery_update")
        connection.execute("DROP TRIGGER IF EXISTS immutable_auto_knowledge_recovery_delete")
        connection.execute(
            f"""
            CREATE TABLE auto_knowledge_job_recovery_receipts_legacy (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL
                    REFERENCES auto_knowledge_jobs(id) ON DELETE RESTRICT,
                reason TEXT NOT NULL CHECK(reason IN ({reason_sql})),
                prior_receipt_json TEXT NOT NULL CHECK(json_valid(prior_receipt_json)),
                prior_receipt_hash TEXT NOT NULL CHECK(
                    length(prior_receipt_hash)=64
                    AND prior_receipt_hash NOT GLOB '*[^0-9a-f]*'
                ),
                blocked_operation_ids_json TEXT NOT NULL
                    CHECK(json_valid(blocked_operation_ids_json)),
                created_at TEXT NOT NULL
                    DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE(job_id,reason,blocked_operation_ids_json)
            )
            """
        )
        connection.execute(
            "INSERT INTO auto_knowledge_job_recovery_receipts_legacy("
            "id,job_id,reason,prior_receipt_json,prior_receipt_hash,"
            "blocked_operation_ids_json,created_at"
            ") VALUES('legacy-receipt','legacy-job','STAGED_COURSE_WORKSPACE_V1',"
            "'{\"status\":\"BLOCKED\"}', ?, '[]', '2026-11-12T00:00:00.000Z')",
            ("b" * 64,),
        )
        connection.execute("DROP TABLE auto_knowledge_job_recovery_receipts")
        connection.execute(
            "ALTER TABLE auto_knowledge_job_recovery_receipts_legacy "
            "RENAME TO auto_knowledge_job_recovery_receipts"
        )
        connection.execute("DELETE FROM schema_migrations WHERE version=87")


def test_schema_87_repairs_legacy_receipt_check_without_losing_history(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    database.initialize()
    _simulate_schema_86_ledger_with_v63_receipt_table(database)

    database.initialize()

    assert LATEST_V3_SCHEMA_VERSION == 87
    with database.connect() as connection:
        versions = {
            row["version"]: row["name"]
            for row in connection.execute(
                "SELECT version,name FROM schema_migrations WHERE version>=86"
            )
        }
        legacy = connection.execute(
            "SELECT job_id,reason,prior_receipt_hash,blocked_operation_ids_json,created_at "
            "FROM auto_knowledge_job_recovery_receipts WHERE id='legacy-receipt'"
        ).fetchone()
        connection.execute(
            "INSERT INTO auto_knowledge_job_recovery_receipts("
            "id,job_id,reason,prior_receipt_json,prior_receipt_hash,"
            "blocked_operation_ids_json"
            ") VALUES('new-receipt','legacy-job','INTERNAL_METERING_WORKSPACE_V1',"
            "'{\"status\":\"BLOCKED\"}',?,'[]')",
            ("c" * 64,),
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="Automatic-map recovery receipts are immutable",
        ):
            connection.execute(
                "UPDATE auto_knowledge_job_recovery_receipts "
                "SET reason='STAGED_COURSE_WORKSPACE_V1' WHERE id='legacy-receipt'"
            )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="Automatic-map recovery receipts are immutable",
        ):
            connection.execute(
                "DELETE FROM auto_knowledge_job_recovery_receipts WHERE id='legacy-receipt'"
            )
        foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert versions[86] == "automatic knowledge-map internal metering workspace recovery"
    assert versions[87] == "automatic knowledge-map recovery receipt constraint repair"
    assert tuple(legacy) == (
        "legacy-job",
        "STAGED_COURSE_WORKSPACE_V1",
        "b" * 64,
        "[]",
        "2026-11-12T00:00:00.000Z",
    )
    assert foreign_key_violations == []

    database.initialize()
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM auto_knowledge_job_recovery_receipts"
            ).fetchone()[0]
            == 2
        )
